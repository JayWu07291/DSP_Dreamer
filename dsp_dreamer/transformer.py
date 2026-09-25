"""Dreamer 4 space/time blocks shared by the tokenizer, world model and agent."""
import math

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint

from .contract import require


ARCHITECTURE = 'dsp-block-causal/2'


def rotary(value):
    """RoPE along the active axis: patch/token order or frame order."""
    size = value.shape[-1]
    frequencies = torch.exp(torch.arange(0, size, 2, device=value.device, dtype=torch.float32)
                            * (-math.log(10000.) / size))
    angles = torch.arange(value.shape[-2], device=value.device)[:, None] * frequencies
    cosine, sine = angles.cos().to(value.dtype), angles.sin().to(value.dtype)
    even, odd = value[..., 0::2], value[..., 1::2]
    return torch.stack((even * cosine - odd * sine, even * sine + odd * cosine), -1).flatten(-2)


class Attention(nn.Module):
    def __init__(self, width, heads, kv_heads, softcap):
        super().__init__()
        self.heads, self.kv_heads, self.head_dim = heads, kv_heads, width // heads
        self.softcap = softcap
        self.query = nn.Linear(width, width, bias=False)
        self.key = nn.Linear(width, kv_heads * self.head_dim, bias=False)
        self.value = nn.Linear(width, kv_heads * self.head_dim, bias=False)
        self.query_norm = nn.RMSNorm(self.head_dim, eps=1e-6)
        self.key_norm = nn.RMSNorm(self.head_dim, eps=1e-6)
        self.output = nn.Linear(width, width, bias=False)

    def forward(self, inputs, blocked):
        batch, length, width = inputs.shape
        query = self.query(inputs).reshape(batch, length, self.heads, self.head_dim).transpose(1, 2)
        key = self.key(inputs).reshape(batch, length, self.kv_heads, self.head_dim).transpose(1, 2)
        value = self.value(inputs).reshape(batch, length, self.kv_heads, self.head_dim).transpose(1, 2)
        query, key = rotary(self.query_norm(query)), rotary(self.key_norm(key))
        if self.kv_heads != self.heads:
            key = key.repeat_interleave(self.heads // self.kv_heads, dim=1)
            value = value.repeat_interleave(self.heads // self.kv_heads, dim=1)
        scores = (query @ key.transpose(-1, -2)) * self.head_dim ** -.5
        scores = self.softcap * torch.tanh(scores / self.softcap)
        if blocked is not None:
            scores = scores.masked_fill(blocked, float('-inf'))
        weights = scores.softmax(-1, dtype=torch.float32).to(value.dtype)
        result = (weights @ value).transpose(1, 2).reshape(batch, length, width)
        return self.output(result)


class TransformerBlock(nn.Module):
    def __init__(self, width, heads, kv_heads, softcap):
        super().__init__()
        hidden = 64 * math.ceil((8 * width / 3) / 64)
        self.attention_norm = nn.RMSNorm(width, eps=1e-6)
        self.attention = Attention(width, heads, kv_heads, softcap)
        self.mlp_norm = nn.RMSNorm(width, eps=1e-6)
        self.gate = nn.Linear(width, hidden, bias=False)
        self.up = nn.Linear(width, hidden, bias=False)
        self.down = nn.Linear(hidden, width, bias=False)

    def forward(self, inputs, blocked):
        value = inputs + self.attention(self.attention_norm(inputs), blocked)
        normalized = self.mlp_norm(value)
        return value + self.down(F.silu(self.gate(normalized)) * self.up(normalized))


class BlockCausalTransformer(nn.Module):
    def __init__(self, width, heads, blocks, context, *, kv_heads=None, temporal_every=4,
                 softcap=30., chunk_size=4, activation_checkpointing=True):
        super().__init__()
        kv_heads = heads if kv_heads is None else kv_heads
        require(all(type(v) is int and v > 0 for v in
                    (width, heads, kv_heads, blocks, context, temporal_every, chunk_size))
                and width % heads == 0 and (width // heads) % 2 == 0
                and heads % kv_heads == 0 and temporal_every >= 2
                and blocks % temporal_every == 0, '無效時空 Transformer 配置')
        require(math.isfinite(softcap) and softcap > 0, '無效 attention soft cap')
        self.context, self.temporal_every = context, temporal_every
        self.chunk_size, self.activation_checkpointing = chunk_size, activation_checkpointing
        self.layers = nn.ModuleList([TransformerBlock(width, heads, kv_heads, softcap) for _ in range(blocks)])
        self.norm = nn.RMSNorm(width, eps=1e-6)

    def forward(self, tokens, spatial_mask=None):
        batch, steps, count, width = tokens.shape
        positions = torch.arange(steps, device=tokens.device)
        distance = positions[:, None] - positions[None, :]
        temporal_mask = (distance < 0) | (distance >= self.context)
        for index, layer in enumerate(self.layers):
            temporal = (index + 1) % self.temporal_every == 0
            inputs = (tokens.permute(0, 2, 1, 3).reshape(batch * count, steps, width)
                      if temporal else tokens.reshape(batch * steps, count, width))
            blocked = temporal_mask if temporal else spatial_mask
            # Chunk independent frames/slots, never an attention sequence. Checkpoint each
            # chunk so backward also fits without materializing all video attention matrices.
            outputs = []
            # Temporal matrices are much smaller than native-image spatial matrices.
            chunk_size = max(self.chunk_size, 128) if temporal else self.chunk_size
            for chunk in inputs.split(chunk_size):
                if self.activation_checkpointing and self.training and torch.is_grad_enabled():
                    outputs.append(checkpoint(layer, chunk, blocked, use_reentrant=False))
                else:
                    outputs.append(layer(chunk, blocked))
            value = torch.cat(outputs)
            tokens = (value.reshape(batch, count, steps, width).permute(0, 2, 1, 3)
                      if temporal else value.reshape(batch, steps, count, width))
        return self.norm(tokens)
