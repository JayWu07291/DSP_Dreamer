"""Native RGB causal tokenizer. The small DSP architecture is not a full Dreamer 4 replica."""
from dataclasses import dataclass

import torch
from torch import nn
from torch.utils.checkpoint import checkpoint

from .contract import require


@dataclass(frozen=True)
class TokenizerConfig:
    latent_tokens: int = 64
    bottleneck: int = 32
    width: int = 512
    heads: int = 8
    temporal_layers: int = 4
    patch_size: int = 20
    context: int = 64
    activation_checkpointing: bool = True

    def __post_init__(self):
        require(self.latent_tokens in (64, 96) and self.bottleneck == 32
                and self.patch_size == 20 and self.temporal_layers == 4 and self.context == 64,
                "不相容的 tokenizer 架構")
        require(self.width > 0 and self.heads > 0 and self.width % self.heads == 0, "無效 attention 寬度")


class CausalTokenizer(nn.Module):
    def __init__(self, config=TokenizerConfig()):
        super().__init__()
        self.config = config
        d, n = config.width, config.latent_tokens
        self.patch_embed = nn.Conv2d(3, d, 20, 20)
        self.patch_position = nn.Parameter(torch.randn(576, d) * .02)
        self.mask_token = nn.Parameter(torch.zeros(1, 1, d))
        self.latent_queries = nn.Parameter(torch.randn(n, d) * .02)
        self.encoder_cross = nn.MultiheadAttention(d, config.heads, batch_first=True)
        self.encoder_norm = nn.LayerNorm(d)
        self.temporal = nn.ModuleList([
            nn.TransformerEncoderLayer(d, config.heads, d * 4, dropout=0.,
                                       activation="gelu", batch_first=True, norm_first=True)
            for _ in range(config.temporal_layers)])
        self.to_bottleneck = nn.Linear(d, config.bottleneck)
        self.from_bottleneck = nn.Linear(config.bottleneck, d)
        self.patch_queries = nn.Parameter(torch.randn(576, d) * .02)
        self.decoder_cross = nn.MultiheadAttention(d, config.heads, batch_first=True)
        self.decoder_norm = nn.LayerNorm(d)
        self.to_pixels = nn.Linear(d, 3 * 20 * 20)

    def _checkpoint(self, function, *args):
        if self.training and self.config.activation_checkpointing and torch.is_grad_enabled():
            return checkpoint(function, *args, use_reentrant=False)
        return function(*args)

    def _encode_frames(self, frames, mask):
        patches = self.patch_embed(frames).flatten(2).transpose(1, 2)
        patches = torch.where(mask, self.mask_token, patches) + self.patch_position
        queries = self.latent_queries.unsqueeze(0).expand(len(frames), -1, -1)
        latents, _ = self.encoder_cross(queries, patches, patches, need_weights=False)
        return self.encoder_norm(latents + queries)

    def encode(self, frames, *, generator=None):
        require(frames.ndim == 5 and tuple(frames.shape[2:]) == (3, 360, 640),
                "觀測必須為 B,T,3,360,640，不裁切、縮放或補邊")
        require(frames.is_floating_point() and torch.isfinite(frames).all().item()
                and frames.min().item() >= 0 and frames.max().item() <= 1, "觀測需為有限 [0,1] RGB")
        batch, steps = frames.shape[:2]
        mask = torch.zeros((batch * steps, 576, 1), device=frames.device, dtype=torch.bool)
        if self.training:
            # Dreamer 4 §3.1: per-image U(0,.9), replace patches, do not drop positions.
            probability = .9 * torch.rand((batch * steps, 1, 1), device=frames.device, generator=generator)
            mask = torch.rand(mask.shape, device=frames.device, generator=generator) < probability
        latents = self._checkpoint(self._encode_frames, frames.flatten(0, 1), mask)
        n = self.config.latent_tokens
        temporal = latents.reshape(batch, steps, n, -1).permute(0, 2, 1, 3).flatten(0, 1)
        positions = torch.arange(steps, device=frames.device)
        distances = positions[:, None] - positions[None, :]
        causal = (distances < 0) | (distances >= self.config.context)
        for layer in self.temporal:
            # Bind the layer now so checkpoint recomputation uses the same block.
            temporal = self._checkpoint(lambda x, layer=layer: layer(x, src_mask=causal), temporal)
        latents = temporal.reshape(batch, n, steps, -1).permute(0, 2, 1, 3)
        return torch.tanh(self.to_bottleneck(latents))

    def _decode_frames(self, latents):
        memory = self.from_bottleneck(latents)
        queries = self.patch_queries.unsqueeze(0).expand(len(latents), -1, -1)
        patches, _ = self.decoder_cross(queries, memory, memory, need_weights=False)
        pixels = self.to_pixels(self.decoder_norm(patches + queries)).sigmoid()
        return pixels.reshape(-1, 18, 32, 3, 20, 20).permute(0, 3, 1, 4, 2, 5).reshape(-1, 3, 360, 640)

    def decode(self, latents):
        require(latents.ndim == 4 and tuple(latents.shape[2:]) == (self.config.latent_tokens, 32),
                "不相容的 latent shape")
        pixels = self._checkpoint(self._decode_frames, latents.flatten(0, 1))
        return pixels.reshape(*latents.shape[:2], 3, 360, 640)

    def forward(self, frames, *, generator=None):
        latents = self.encode(frames, generator=generator)
        return latents, self.decode(latents)
