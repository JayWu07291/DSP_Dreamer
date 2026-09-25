"""Action-conditioned, causal latent dynamics with x-space shortcut forcing."""
from dataclasses import dataclass
import math

import torch
from torch import nn

from .actions import ACTION_CODEC, forbidden_buttons
from .contract import require
from .transformer import ARCHITECTURE, BlockCausalTransformer


@dataclass(frozen=True)
class DynamicsConfig:
    architecture: str = ARCHITECTURE
    width: int = 1280
    heads: int = 20
    kv_heads: int = 4
    blocks: int = 16
    registers: int = 8
    temporal_every: int = 4
    context: int = 64
    latent_tokens: int = 64
    bottleneck: int = 32
    attention_softcap: float = 30.
    attention_chunk_size: int = 16
    activation_checkpointing: bool = True

    def __post_init__(self):
        require(self.architecture == ARCHITECTURE, '舊 dynamics 架構不能續訓，請重新訓練')
        require(self.latent_tokens == 64 and self.bottleneck == 32, '不相容的 dynamics 表徵')
        require(all(type(v) is int and v > 0 for v in (self.width, self.heads, self.kv_heads,
            self.blocks, self.registers, self.temporal_every, self.context, self.attention_chunk_size))
            and self.width % self.heads == 0 and (self.width // self.heads) % 2 == 0
            and self.heads % self.kv_heads == 0 and self.temporal_every >= 2
            and self.blocks % self.temporal_every == 0, '無效 dynamics Transformer 配置')
        require(math.isfinite(self.attention_softcap) and self.attention_softcap > 0
                and type(self.activation_checkpointing) is bool, '無效 attention 設定')


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
        self.transformer = BlockCausalTransformer(d, config.heads, config.blocks, config.context,
            kv_heads=config.kv_heads, temporal_every=config.temporal_every, softcap=config.attention_softcap,
            chunk_size=config.attention_chunk_size, activation_checkpointing=config.activation_checkpointing)
        self.latent_out = nn.Linear(d, 32)

    def forward(self, noisy, actions, levels, step_size):
        return self.latent_out(self.hidden(noisy, actions, levels, step_size)[:, :, :64])

    def hidden(self, noisy, actions, levels, step_size, *, agent_tokens=None):
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
        mask = None
        if agent_tokens is not None:
            require(tuple(agent_tokens.shape) == (batch, steps, 1, self.config.width), '不相容的 agent tokens')
            world_count = tokens.shape[2]
            tokens = torch.cat((tokens, agent_tokens), 2)
            mask = torch.zeros(tokens.shape[2], tokens.shape[2], device=tokens.device, dtype=torch.bool)
            mask[:world_count, world_count:] = True
        return self.transformer(tokens, mask)

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
