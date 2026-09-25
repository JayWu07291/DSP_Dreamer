"""Shared, checkpointed AdamW and warmup/cosine settings."""
from dataclasses import dataclass
import math

from .contract import require


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
