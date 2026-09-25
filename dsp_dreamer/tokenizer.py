"""Small Dreamer 4 causal video tokenizer with native 640x360 RGB input/output."""
from dataclasses import dataclass
import math

import torch
from torch import nn

from .contract import require
from .transformer import ARCHITECTURE, BlockCausalTransformer


@dataclass(frozen=True)
class TokenizerConfig:
    architecture: str = ARCHITECTURE
    latent_tokens: int = 64
    bottleneck: int = 32
    width: int = 640
    heads: int = 10
    encoder_blocks: int = 12
    decoder_blocks: int = 12
    temporal_every: int = 4
    patch_size: int = 20
    context: int = 32
    attention_softcap: float = 30.
    attention_chunk_size: int = 8
    activation_checkpointing: bool = True

    def __post_init__(self):
        require(self.architecture == ARCHITECTURE, '舊 tokenizer 架構不能續訓，請重新執行 A')
        require(self.latent_tokens in (64, 96) and self.bottleneck == 32 and self.patch_size == 20,
                '不相容的 tokenizer 表徵或影像契約')
        require(all(type(v) is int and v > 0 for v in (self.width, self.heads, self.encoder_blocks,
            self.decoder_blocks, self.temporal_every, self.context, self.attention_chunk_size))
            and self.width % self.heads == 0 and (self.width // self.heads) % 2 == 0
            and self.temporal_every >= 2 and self.encoder_blocks % self.temporal_every == 0
            and self.decoder_blocks % self.temporal_every == 0, '無效 tokenizer Transformer 配置')
        require(math.isfinite(self.attention_softcap) and self.attention_softcap > 0
                and type(self.activation_checkpointing) is bool, '無效 attention 設定')


class CausalTokenizer(nn.Module):
    def __init__(self, config=TokenizerConfig()):
        super().__init__()
        self.config = config
        d, n = config.width, config.latent_tokens
        self.patch_embed = nn.Conv2d(3, d, 20, 20)
        self.patch_position = nn.Parameter(torch.randn(576, d) * .02)
        self.mask_token = nn.Parameter(torch.zeros(1, 1, d))
        self.latent_queries = nn.Parameter(torch.randn(n, d) * .02)
        options = dict(temporal_every=config.temporal_every, softcap=config.attention_softcap,
                       chunk_size=config.attention_chunk_size, activation_checkpointing=config.activation_checkpointing)
        self.encoder = BlockCausalTransformer(d, config.heads, config.encoder_blocks, config.context, **options)
        self.decoder = BlockCausalTransformer(d, config.heads, config.decoder_blocks, config.context, **options)
        self.to_bottleneck = nn.Linear(d, config.bottleneck)
        self.from_bottleneck = nn.Linear(config.bottleneck, d)
        self.patch_queries = nn.Parameter(torch.randn(576, d) * .02)
        self.to_pixels = nn.Linear(d, 3 * 20 * 20)
        nn.init.normal_(self.to_bottleneck.weight, std=.02)
        nn.init.zeros_(self.to_bottleneck.bias)
        nn.init.normal_(self.to_pixels.weight, std=.02)
        nn.init.zeros_(self.to_pixels.bias)
        # Patches precede latents. Encoder patches cannot see latents; decoder
        # latents cannot see readout patches. Both streams have self-attention.
        encoder_mask = torch.zeros(576 + n, 576 + n, dtype=torch.bool)
        encoder_mask[:576, 576:] = True
        self.register_buffer('encoder_mask', encoder_mask, persistent=False)
        self.register_buffer('decoder_mask', encoder_mask.T.contiguous(), persistent=False)

    def encode(self, frames, *, generator=None, mask_max_probability=.9):
        require(frames.ndim == 5 and tuple(frames.shape[2:]) == (3, 360, 640)
                and frames.shape[0] > 0 and frames.shape[1] > 0,
                '觀測必須為 B,T,3,360,640，不裁切、縮放或補邊')
        require(frames.is_floating_point() and torch.isfinite(frames).all().item()
                and frames.min().item() >= 0 and frames.max().item() <= 1, '觀測需為有限 [0,1] RGB')
        batch, steps = frames.shape[:2]
        patches = self.patch_embed(frames.flatten(0, 1)).flatten(2).transpose(1, 2)
        if self.training:
            require(math.isfinite(mask_max_probability) and 0 <= mask_max_probability <= 1, 'Invalid mask probability')
            probability = mask_max_probability * torch.rand((batch * steps, 1, 1), device=frames.device, generator=generator)
            mask = torch.rand((batch * steps, 576, 1), device=frames.device, generator=generator) < probability
            patches = torch.where(mask, self.mask_token.to(patches.dtype), patches)
        patches = patches + self.patch_position
        queries = self.latent_queries.expand(batch * steps, -1, -1)
        tokens = torch.cat((patches, queries), 1).reshape(batch, steps, 576 + self.config.latent_tokens, -1)
        encoded = self.encoder(tokens, self.encoder_mask)[:, :, 576:]
        return torch.tanh(self.to_bottleneck(encoded))

    def decode(self, latents):
        require(latents.ndim == 4 and tuple(latents.shape[2:]) == (self.config.latent_tokens, 32)
                and latents.shape[0] > 0 and latents.shape[1] > 0, '不相容的 latent shape')
        batch, steps = latents.shape[:2]
        memory = self.from_bottleneck(latents)
        queries = self.patch_queries.expand(batch, steps, -1, -1)
        tokens = self.decoder(torch.cat((queries, memory), 2), self.decoder_mask)
        pixels = self.to_pixels(tokens[:, :, :576]).sigmoid()
        return pixels.reshape(batch, steps, 18, 32, 3, 20, 20).permute(0, 1, 4, 2, 5, 3, 6).reshape(batch, steps, 3, 360, 640)

    def forward(self, frames, *, generator=None, mask_max_probability=.9):
        latents = self.encode(frames, generator=generator, mask_max_probability=mask_max_probability)
        return latents, self.decode(latents)
