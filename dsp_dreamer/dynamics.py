"""Action-conditioned, causal latent dynamics with x-space shortcut forcing."""
from dataclasses import dataclass
import math

import torch
from torch import nn
from torch.utils.checkpoint import checkpoint

from .actions import ACTION_CODEC, forbidden_buttons
from .contract import require


@dataclass(frozen=True)
class DynamicsConfig:
    width: int = 512
    heads: int = 8
    blocks: int = 8
    registers: int = 8
    temporal_every: int = 4
    context: int = 64
    latent_tokens: int = 64
    bottleneck: int = 32
    activation_checkpointing: bool = True

    def __post_init__(self):
        require(self.blocks == 8 and self.registers == 8 and self.temporal_every == 4
                and self.context == 64 and self.latent_tokens == 64 and self.bottleneck == 32,
                '不相容的 dynamics 架構')
        require(self.width > 0 and self.width % 2 == 0 and self.heads > 0
                and self.width % self.heads == 0, '無效 attention 寬度')


def validate_actions(actions, shape):
    require(set(actions) == {'binary', 'mouse', 'wheel'}, '不相容的動作欄位')
    for name, classes in [('binary', 2), ('mouse', 121), ('wheel', 3)]:
        value = actions[name]
        expected = (*shape, ACTION_CODEC['binary_width']) if name == 'binary' else tuple(shape)
        require(tuple(value.shape) == expected and value.dtype == torch.int64
                and ((value >= 0) & (value < classes)).all().item(), '不相容的動作 shape、dtype 或類別')
    require(not any(forbidden_buttons(row) for row in actions['binary'].flatten(0, 1).tolist()), '禁止的動作組合')


class Dynamics(nn.Module):
    def __init__(self, config=DynamicsConfig()):
        super().__init__()
        self.config = config
        d = config.width
        self.latent_in = nn.Linear(32, d)
        self.position = nn.Parameter(torch.randn(config.latent_tokens, d) * .02)
        self.registers = nn.Parameter(torch.randn(config.registers, d) * .02)
        # One summed token: each binary component has its own off/on embedding.
        self.binary = nn.Embedding(ACTION_CODEC['binary_width'] * 2, d)
        self.mouse = nn.Embedding(121, d)
        self.wheel = nn.Embedding(3, d)
        self.action_token = nn.Parameter(torch.randn(d) * .02)
        self.signal = nn.Embedding(5, d // 2)  # 0, .1, .25, .5, .75
        self.step_size = nn.Embedding(2, d // 2)  # .25, .5
        self.spatial = nn.ModuleList([self._layer() for _ in range(config.blocks)])
        self.temporal = nn.ModuleList([self._layer() for _ in range(config.blocks // config.temporal_every)])
        self.norm = nn.LayerNorm(d)
        self.latent_out = nn.Linear(d, 32)

    def _layer(self):
        return nn.TransformerEncoderLayer(self.config.width, self.config.heads, self.config.width * 4,
            dropout=0., activation='gelu', batch_first=True, norm_first=True)

    def _checkpoint(self, function, value):
        if self.training and self.config.activation_checkpointing and torch.is_grad_enabled():
            return checkpoint(function, value, use_reentrant=False)
        return function(value)

    def forward(self, noisy, actions, levels, step_size):
        return self.latent_out(self.hidden(noisy, actions, levels, step_size)[:, :, :64])

    def hidden(self, noisy, actions, levels, step_size):
        require(noisy.ndim == 4 and tuple(noisy.shape[2:]) == (64, 32)
                and noisy.shape[0] > 0 and noisy.shape[1] > 0 and torch.isfinite(noisy).all().item(),
                '不相容的 dynamics latent')
        batch, steps = noisy.shape[:2]
        validate_actions(actions, (batch, steps))
        allowed = levels.new_tensor([0., .1, .25, .5, .75])
        matches = levels[..., None] == allowed
        require(tuple(levels.shape) == (batch, steps) and matches.any(-1).all().item()
                and step_size in (.25, .5), '不合法 shortcut signal 或 step')
        signal = torch.cat((self.signal(matches.long().argmax(-1)),
                            self.step_size(torch.full_like(levels, int(step_size == .5), dtype=torch.long))), -1)
        offsets = torch.arange(ACTION_CODEC['binary_width'], device=noisy.device) * 2
        action = (self.binary(actions['binary'] + offsets).sum(-2) + self.mouse(actions['mouse'])
                  + self.wheel(actions['wheel']) + self.action_token)
        tokens = torch.cat((self.latent_in(noisy) + self.position, action[:, :, None], signal[:, :, None],
                           self.registers.expand(batch, steps, -1, -1)), dim=2)
        # Sinusoidal time positions distinguish histories with the same set of frames.
        positions = torch.arange(steps, device=noisy.device)
        angles = positions[:, None] * torch.exp(torch.arange(0, self.config.width, 2, device=noisy.device)
                                               * (-math.log(10000.) / self.config.width))
        tokens = tokens + torch.stack((angles.sin(), angles.cos()), -1).flatten(-2)[None, :, None]
        distance = positions[:, None] - positions[None, :]
        mask = (distance < 0) | (distance >= self.config.context)
        count = tokens.shape[2]
        for i, spatial in enumerate(self.spatial):
            tokens = self._checkpoint(spatial, tokens.flatten(0, 1)).reshape(batch, steps, count, -1)
            if (i + 1) % self.config.temporal_every == 0:
                temporal = self.temporal[i // self.config.temporal_every]
                value = tokens.permute(0, 2, 1, 3).flatten(0, 1)
                value = self._checkpoint(lambda x, layer=temporal: layer(x, src_mask=mask), value)
                tokens = value.reshape(batch, count, steps, -1).permute(0, 2, 1, 3)
        return self.norm(tokens)

    @torch.no_grad()
    def rollout(self, history, history_actions, future_actions, *, seed):
        """Incoming actions align with latents; no future RGB or target is accepted."""
        require(not self.training, '自由預測需 eval 模式')
        validate_actions(history_actions, history.shape[:2])
        batch, horizon = future_actions['mouse'].shape
        require(batch == history.shape[0] and 1 <= horizon <= 15 and history.shape[1] > 0, '無效預測長度')
        validate_actions(future_actions, (batch, horizon))
        generator = torch.Generator(device=history.device).manual_seed(seed)
        generated = []
        for t in range(horizon):
            # Keep at most 64 past frames plus the frame being generated.
            history = history[:, -self.config.context:]
            actions = {k: torch.cat((v[:, -history.shape[1]:], future_actions[k][:, t:t+1]), 1)
                       for k, v in history_actions.items()}
            context = .1 * history + .9 * torch.randn(history.shape, device=history.device, generator=generator)
            current = torch.randn(history[:, :1].shape, device=history.device, generator=generator)
            levels = torch.full((batch, history.shape[1] + 1), .1, device=history.device)
            for step in range(4):
                tau = step / 4
                levels[:, -1] = tau
                prediction = self(torch.cat((context, current), 1), actions, levels, .25)[:, -1:]
                current = current + .25 * (prediction.float() - current) / (1 - tau)
            require(torch.isfinite(current).all().item(), '非有限自由預測')
            generated.append(current)
            history = torch.cat((history, current), 1)
            history_actions = actions
        return torch.cat(generated, 1)


def shortcut_loss(model, clean, actions):
    """Equation 7 in x-space, with the equation 8 ramp on both terms."""
    shape, device = clean.shape[:2], clean.device
    levels = torch.tensor([0., .1, .25, .5, .75], device=device)[torch.randint(5, shape, device=device)]
    tau = levels[..., None, None]
    noisy = (1 - tau) * torch.randn_like(clean) + tau * clean
    prediction = model(noisy, actions, levels, .25).float()
    # The initial frame has no observed incoming action and supplies context only.
    flow = ((.9 * tau + .1) * (prediction - clean).square())[:, 1:].mean()

    levels = torch.randint(3, shape, device=device).float() / 4
    tau = levels[..., None, None]
    noisy = (1 - tau) * torch.randn_like(clean) + tau * clean
    with torch.no_grad():
        first = (model(noisy, actions, levels, .25).float() - noisy) / (1 - tau)
        midpoint = noisy + .25 * first
        second = (model(midpoint, actions, levels + .25, .25).float() - midpoint) / (.75 - tau)
        target = noisy + (1 - tau) * (first + second) / 2
    prediction = model(noisy, actions, levels, .5).float()
    bootstrap = ((.9 * tau + .1) * (prediction - target).square())[:, 1:].mean()
    return flow + bootstrap, flow, bootstrap
