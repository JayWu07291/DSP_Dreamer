"""Shared, checkpointed AdamW and warmup/cosine settings."""
from dataclasses import dataclass
import math

import torch
from torch import nn

from .contract import require


class LossRMS(nn.Module):
    """Bias-corrected EMA of squared microbatch losses, committed once per update.

    The first update uses unit scales. Failed/interrupted accumulation cannot change
    these statistics; raw evaluation metrics never pass through this normalizer.
    """
    mean_square: torch.Tensor
    weight: torch.Tensor

    def __init__(self, size, decay=.99, epsilon=1e-8):
        super().__init__()
        require(math.isfinite(decay) and 0 <= decay < 1 and math.isfinite(epsilon) and epsilon > 0,
                '無效 loss RMS 設定')
        self.decay, self.epsilon = decay, epsilon
        self.register_buffer('mean_square', torch.zeros(size))
        self.register_buffer('weight', torch.zeros(()))

    def scales(self):
        variance = self.mean_square / self.weight.clamp_min(self.epsilon)
        return torch.where(self.weight > 0, variance.clamp_min(self.epsilon ** 2).sqrt(), torch.ones_like(variance))

    @torch.no_grad()
    def update(self, mean_square):
        value = torch.as_tensor(mean_square, dtype=self.mean_square.dtype, device=self.mean_square.device)
        require(value.shape == self.mean_square.shape and torch.isfinite(value).all().item()
                and (value >= 0).all().item(), '非有限 loss RMS 統計')
        self.mean_square.mul_(self.decay).add_(value, alpha=1 - self.decay)
        self.weight.mul_(self.decay).add_(1 - self.decay)


@dataclass(frozen=True, kw_only=True)
class OptimizerConfig:
    updates: int
    weight_decay: float = .01
    beta1: float = .9
    beta2: float = .999
    epsilon: float = 1e-8
    grad_clip: float = 1.
    warmup_fraction: float = .05
    min_lr_fraction: float = .1
    long_every: int = 4

    def __post_init__(self):
        require(all(math.isfinite(v) and v >= 0 for v in (self.weight_decay, self.beta1, self.beta2,
            self.epsilon, self.grad_clip, self.warmup_fraction, self.min_lr_fraction)), 'Invalid optimizer setting')
        require(self.beta1 < 1 and self.beta2 < 1 and self.epsilon > 0 and self.grad_clip > 0
                and self.warmup_fraction <= 1 and self.min_lr_fraction <= 1
                and type(self.long_every) is int and self.long_every > 0, 'Invalid optimizer setting')

    def lr_factor(self, step):
        warmup = max(1, math.ceil(self.updates * self.warmup_fraction))
        return ((step + 1) / warmup if step < warmup else self.min_lr_fraction +
                (1 - self.min_lr_fraction) * (1 + math.cos(math.pi * (step - warmup + 1) /
                 max(1, self.updates - warmup))) / 2)
