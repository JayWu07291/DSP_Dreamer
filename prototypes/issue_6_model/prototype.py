"""PROTOTYPE ONLY: a measured shape test for DSP Dreamer's three stages.

The code is deliberately compact and disposable. It checks the causal masks,
conditioning paths, losses, freezing rules, and peak CUDA memory. It is not a
training implementation and does not read the real transition dataset.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import subprocess
import threading
import time
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint

from config import PrototypeConfig


def nvidia_smi_memory() -> dict[str, float]:
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    total_mib, used_mib, free_mib = [float(value.strip()) for value in output.splitlines()[0].split(",")]
    return {
        "total_gib": round(total_mib / 1024, 3),
        "used_gib": round(used_mib / 1024, 3),
        "free_gib": round(free_mib / 1024, 3),
    }


class NvidiaSmiMonitor:
    """Samples whole-device VRAM, including other processes, every 100 ms."""

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.samples: list[dict[str, float]] = []
        self.thread = threading.Thread(target=self._sample_until_stopped, daemon=True)

    def _sample_until_stopped(self) -> None:
        while not self.stop_event.is_set():
            self.samples.append(nvidia_smi_memory())
            self.stop_event.wait(0.1)

    def start(self) -> None:
        self.samples.append(nvidia_smi_memory())
        self.thread.start()

    def stop(self) -> dict[str, float]:
        self.stop_event.set()
        self.thread.join()
        self.samples.append(nvidia_smi_memory())
        return {
            "used_before_gib": self.samples[0]["used_gib"],
            "peak_used_gib": max(sample["used_gib"] for sample in self.samples),
            "sample_count": len(self.samples),
        }


def causal_mask(length: int, device: torch.device) -> torch.Tensor:
    return torch.triu(
        torch.full((length, length), float("-inf"), device=device), diagonal=1
    )


def transformer_layer(dim: int, heads: int) -> nn.TransformerEncoderLayer:
    return nn.TransformerEncoderLayer(
        dim,
        heads,
        dim_feedforward=dim * 4,
        dropout=0.0,
        activation="gelu",
        batch_first=True,
        norm_first=True,
    )


class CausalTokenizer(nn.Module):
    """Per-frame spatial compression followed by causal temporal mixing."""

    def __init__(self, cfg: PrototypeConfig):
        super().__init__()
        self.cfg = cfg
        dim = cfg.model_dim
        self.patch_embed = nn.Conv2d(3, dim, cfg.patch_size, cfg.patch_size)
        self.latent_queries = nn.Parameter(torch.randn(cfg.latent_tokens, dim) * 0.02)
        self.encoder_cross = nn.MultiheadAttention(dim, cfg.attention_heads, batch_first=True)
        self.encoder_norm = nn.LayerNorm(dim)
        self.temporal = nn.ModuleList(
            [
                transformer_layer(dim, cfg.attention_heads)
                for _ in range(cfg.tokenizer_temporal_layers)
            ]
        )
        self.to_bottleneck = nn.Linear(dim, cfg.latent_dim)

        self.from_bottleneck = nn.Linear(cfg.latent_dim, dim)
        self.patch_queries = nn.Parameter(torch.randn(cfg.patch_count, dim) * 0.02)
        self.decoder_cross = nn.MultiheadAttention(dim, cfg.attention_heads, batch_first=True)
        self.to_pixels = nn.Linear(dim, 3 * cfg.patch_size * cfg.patch_size)

    def preprocess(self, frames: torch.Tensor) -> torch.Tensor:
        if frames.shape[-2:] == (self.cfg.model_height, self.cfg.model_width):
            return frames
        batch, steps, channels, height, width = frames.shape
        resized = F.interpolate(
            frames.reshape(batch * steps, channels, height, width),
            size=(self.cfg.model_height, self.cfg.model_width),
            mode="area",
        )
        return resized.reshape(
            batch, steps, channels, self.cfg.model_height, self.cfg.model_width
        )

    def encode(self, frames: torch.Tensor) -> torch.Tensor:
        frames = self.preprocess(frames)
        batch, steps = frames.shape[:2]
        patches = self.patch_embed(frames.flatten(0, 1)).flatten(2).transpose(1, 2)
        queries = self.latent_queries.unsqueeze(0).expand(batch * steps, -1, -1)
        latents, _ = self.encoder_cross(queries, patches, patches, need_weights=False)
        latents = self.encoder_norm(latents + queries)
        latents = latents.reshape(batch, steps, self.cfg.latent_tokens, -1)

        temporal = latents.permute(0, 2, 1, 3).flatten(0, 1)
        mask = causal_mask(steps, frames.device)
        for layer in self.temporal:
            temporal = layer(temporal, src_mask=mask)
        temporal = temporal.reshape(batch, self.cfg.latent_tokens, steps, -1)
        temporal = temporal.permute(0, 2, 1, 3)
        return torch.tanh(self.to_bottleneck(temporal))

    def decode(self, latents: torch.Tensor) -> torch.Tensor:
        batch, steps = latents.shape[:2]
        memory = self.from_bottleneck(latents).flatten(0, 1)
        queries = self.patch_queries.unsqueeze(0).expand(batch * steps, -1, -1)
        patches, _ = self.decoder_cross(queries, memory, memory, need_weights=False)
        pixels = self.to_pixels(patches)
        patch = self.cfg.patch_size
        grid_h = self.cfg.model_height // patch
        grid_w = self.cfg.model_width // patch
        pixels = pixels.reshape(batch, steps, grid_h, grid_w, 3, patch, patch)
        return pixels.permute(0, 1, 4, 2, 5, 3, 6).reshape(
            batch, steps, 3, self.cfg.model_height, self.cfg.model_width
        )

    def forward(self, frames: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        latents = self.encode(frames)
        return latents, self.decode(latents)


class SpaceTimeBlock(nn.Module):
    def __init__(self, cfg: PrototypeConfig, has_time_layer: bool):
        super().__init__()
        self.space = transformer_layer(cfg.model_dim, cfg.attention_heads)
        self.time = (
            transformer_layer(cfg.model_dim, cfg.attention_heads)
            if has_time_layer
            else None
        )

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        batch, steps, spatial, dim = tokens.shape
        tokens = self.space(tokens.flatten(0, 1)).reshape(batch, steps, spatial, dim)
        if self.time is not None:
            temporal = tokens.permute(0, 2, 1, 3).flatten(0, 1)
            temporal = self.time(temporal, src_mask=causal_mask(steps, tokens.device))
            tokens = temporal.reshape(batch, spatial, steps, dim).permute(0, 2, 1, 3)
        return tokens


class InteractiveDynamics(nn.Module):
    """Action-conditioned x-prediction with task-blind world tokens."""

    def __init__(self, cfg: PrototypeConfig):
        super().__init__()
        self.cfg = cfg
        dim = cfg.model_dim
        self.latent_in = nn.Linear(cfg.latent_dim, dim)
        self.keyboard_in = nn.Linear(cfg.keyboard_buttons, dim, bias=False)
        self.mouse_in = nn.Embedding(cfg.mouse_classes, dim)
        self.wheel_in = nn.Embedding(cfg.wheel_classes, dim)
        self.tau_in = nn.Embedding(cfg.shortcut_steps + 1, dim // 2)
        self.step_in = nn.Embedding(cfg.shortcut_steps, dim // 2)
        self.signal_in = nn.Linear(dim, dim)
        self.registers = nn.Parameter(torch.randn(cfg.register_tokens, dim) * 0.02)
        self.blocks = nn.ModuleList(
            [
                SpaceTimeBlock(cfg, has_time_layer=((index + 1) % 4 == 0))
                for index in range(cfg.dynamics_layers)
            ]
        )
        self.norm = nn.LayerNorm(dim)
        self.latent_out = nn.Linear(dim, cfg.latent_dim)

    def _action_embedding(self, actions: dict[str, torch.Tensor]) -> torch.Tensor:
        return (
            self.keyboard_in(actions["keyboard"])
            + self.mouse_in(actions["mouse"])
            + self.wheel_in(actions["wheel"])
        )

    def hidden(
        self,
        noisy_latents: torch.Tensor,
        actions: dict[str, torch.Tensor],
        tau_index: torch.Tensor,
        step_index: torch.Tensor,
    ) -> torch.Tensor:
        batch, steps, spatial = noisy_latents.shape[:3]
        action = self._action_embedding(actions).unsqueeze(2)
        signal = self.signal_in(
            torch.cat([self.tau_in(tau_index), self.step_in(step_index)], dim=-1)
        ).unsqueeze(2)
        tokens = self.latent_in(noisy_latents) + action + signal
        registers = self.registers.view(1, 1, self.cfg.register_tokens, -1)
        registers = registers.expand(batch, steps, -1, -1)
        tokens = torch.cat([tokens, registers], dim=2)
        for block in self.blocks:
            if self.training and torch.is_grad_enabled():
                tokens = checkpoint(block, tokens, use_reentrant=False)
            else:
                tokens = block(tokens)
        return self.norm(tokens)

    def forward(
        self,
        noisy_latents: torch.Tensor,
        actions: dict[str, torch.Tensor],
        tau_index: torch.Tensor,
        step_index: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        hidden = self.hidden(noisy_latents, actions, tau_index, step_index)
        world = hidden[:, :, : self.cfg.latent_tokens]
        return self.latent_out(world), hidden


class AgentHeads(nn.Module):
    """Task-conditioned agent token; world tokens never attend back to it."""

    def __init__(self, cfg: PrototypeConfig):
        super().__init__()
        self.cfg = cfg
        dim = cfg.model_dim
        distances = cfg.mtp_distance + 1
        self.task_in = nn.Embedding(cfg.task_count, dim)
        self.agent_query = nn.Parameter(torch.randn(1, 1, dim) * 0.02)
        self.cross = nn.MultiheadAttention(dim, cfg.attention_heads, batch_first=True)
        self.norm = nn.LayerNorm(dim)
        self.keyboard = nn.Linear(dim, distances * cfg.keyboard_buttons)
        self.mouse = nn.Linear(dim, distances * cfg.mouse_classes)
        self.wheel = nn.Linear(dim, distances * cfg.wheel_classes)
        self.reward = nn.Linear(dim, distances * cfg.twohot_bins)
        self.value = nn.Linear(dim, cfg.twohot_bins)

    def features(self, world_hidden: torch.Tensor, tasks: torch.Tensor) -> torch.Tensor:
        batch, steps, spatial, dim = world_hidden.shape
        memory = world_hidden.flatten(0, 1)
        query = self.agent_query.expand(batch * steps, -1, -1)
        query = query + self.task_in(tasks).reshape(batch * steps, 1, dim)
        attended, _ = self.cross(query, memory, memory, need_weights=False)
        return self.norm(attended + query).reshape(batch, steps, dim)

    def forward(self, features: torch.Tensor) -> dict[str, torch.Tensor]:
        batch, steps = features.shape[:2]
        distances = self.cfg.mtp_distance + 1
        return {
            "keyboard": self.keyboard(features).reshape(
                batch, steps, distances, self.cfg.keyboard_buttons
            ),
            "mouse": self.mouse(features).reshape(
                batch, steps, distances, self.cfg.mouse_classes
            ),
            "wheel": self.wheel(features).reshape(
                batch, steps, distances, self.cfg.wheel_classes
            ),
            "reward": self.reward(features).reshape(
                batch, steps, distances, self.cfg.twohot_bins
            ),
            "value": self.value(features),
        }


class DreamerPrototype(nn.Module):
    def __init__(self, cfg: PrototypeConfig):
        super().__init__()
        self.cfg = cfg
        self.tokenizer = CausalTokenizer(cfg)
        self.dynamics = InteractiveDynamics(cfg)
        self.agent = AgentHeads(cfg)


def synthetic_batch(
    cfg: PrototypeConfig, device: torch.device, steps: int | None = None
) -> dict[str, torch.Tensor | dict[str, torch.Tensor]]:
    steps = steps or cfg.train_steps
    batch = cfg.batch_size
    return {
        "frames": torch.rand(
            batch,
            steps,
            3,
            cfg.observation_height,
            cfg.observation_width,
            device=device,
        ),
        "actions": {
            "keyboard": torch.randint(
                0, 2, (batch, steps, cfg.keyboard_buttons), device=device
            ).float(),
            "mouse": torch.randint(0, cfg.mouse_classes, (batch, steps), device=device),
            "wheel": torch.randint(0, cfg.wheel_classes, (batch, steps), device=device),
        },
        "tasks": torch.randint(0, cfg.task_count, (batch, steps), device=device),
        "rewards": torch.randint(0, 2, (batch, steps), device=device).float(),
    }


def zero_actions(
    cfg: PrototypeConfig, batch: int, steps: int, device: torch.device
) -> dict[str, torch.Tensor]:
    return {
        "keyboard": torch.zeros(batch, steps, cfg.keyboard_buttons, device=device),
        "mouse": torch.full((batch, steps), cfg.mouse_classes // 2, device=device),
        "wheel": torch.full((batch, steps), 1, device=device),
    }


def corrupt(latents: torch.Tensor, cfg: PrototypeConfig) -> tuple[torch.Tensor, torch.Tensor]:
    batch, steps = latents.shape[:2]
    tau_index = torch.randint(1, cfg.shortcut_steps, (batch, steps), device=latents.device)
    tau = tau_index.float() / cfg.shortcut_steps
    noise = torch.randn_like(latents)
    noisy = (1.0 - tau[..., None, None]) * noise + tau[..., None, None] * latents
    return noisy, tau_index


def twohot_targets(values: torch.Tensor, bins: int) -> torch.Tensor:
    transformed = torch.sign(values) * torch.log1p(values.abs())
    scaled = ((transformed.clamp(-20, 20) + 20) / 40) * (bins - 1)
    lower = scaled.floor().long()
    upper = scaled.ceil().long()
    upper_weight = scaled - lower.float()
    target = torch.zeros(*values.shape, bins, device=values.device)
    target.scatter_add_(-1, lower.unsqueeze(-1), (1 - upper_weight).unsqueeze(-1))
    target.scatter_add_(-1, upper.unsqueeze(-1), upper_weight.unsqueeze(-1))
    return target


def twohot_loss(logits: torch.Tensor, values: torch.Tensor) -> torch.Tensor:
    targets = twohot_targets(values, logits.shape[-1])
    return -(targets * logits.log_softmax(-1)).sum(-1).mean()


def dynamics_loss(
    model: DreamerPrototype,
    latents: torch.Tensor,
    actions: dict[str, torch.Tensor],
) -> tuple[torch.Tensor, torch.Tensor]:
    noisy, tau_index = corrupt(latents, model.cfg)
    minimum_step_index = torch.full_like(tau_index, 2)
    predicted, hidden = model.dynamics(noisy, actions, tau_index, minimum_step_index)
    tau = tau_index.float() / model.cfg.shortcut_steps
    weight = 0.9 * tau + 0.1
    flow_loss = (weight[..., None, None] * (predicted - latents).square()).mean()

    bootstrap_tau_index = torch.randint(
        0, model.cfg.shortcut_steps - 1, tau_index.shape, device=latents.device
    )
    bootstrap_tau = bootstrap_tau_index.float() / model.cfg.shortcut_steps
    bootstrap_noise = torch.randn_like(latents)
    bootstrap_input = (
        (1.0 - bootstrap_tau[..., None, None]) * bootstrap_noise
        + bootstrap_tau[..., None, None] * latents
    )
    half_step_index = torch.full_like(bootstrap_tau_index, 2)
    full_step_index = torch.full_like(bootstrap_tau_index, 1)
    bootstrap_prediction, _ = model.dynamics(
        bootstrap_input, actions, bootstrap_tau_index, full_step_index
    )
    with torch.no_grad():
        first_half, _ = model.dynamics(
            bootstrap_input, actions, bootstrap_tau_index, half_step_index
        )
        first_velocity = (first_half - bootstrap_input) / (
            1.0 - bootstrap_tau[..., None, None]
        )
        midpoint = bootstrap_input + first_velocity * 0.25
        second_half, _ = model.dynamics(
            midpoint, actions, bootstrap_tau_index + 1, half_step_index
        )
        second_velocity = (second_half - midpoint) / (
            0.75 - bootstrap_tau[..., None, None]
        ).clamp_min(0.25)
        target_velocity = 0.5 * (first_velocity + second_velocity)
    predicted_velocity = (bootstrap_prediction - bootstrap_input) / (
        1.0 - bootstrap_tau[..., None, None]
    )
    bootstrap_loss = (
        (1.0 - bootstrap_tau[..., None, None]).square()
        * (predicted_velocity - target_velocity).square()
    ).mean()
    return flow_loss + bootstrap_loss, hidden


def shifted_targets(source: torch.Tensor, distance: int) -> tuple[torch.Tensor, torch.Tensor]:
    usable = source.shape[1] - distance
    return source[:, :usable], source[:, distance:]


def mtp_loss(
    outputs: dict[str, torch.Tensor],
    actions: dict[str, torch.Tensor],
    rewards: torch.Tensor,
) -> torch.Tensor:
    total = torch.zeros((), device=rewards.device)
    for distance in range(outputs["keyboard"].shape[2]):
        predicted_keyboard, target_keyboard = shifted_targets(
            outputs["keyboard"][:, :, distance], distance
        )
        predicted_mouse, target_mouse = shifted_targets(
            outputs["mouse"][:, :, distance], distance
        )
        predicted_wheel, target_wheel = shifted_targets(
            outputs["wheel"][:, :, distance], distance
        )
        predicted_reward, target_reward = shifted_targets(
            outputs["reward"][:, :, distance], distance
        )
        _, target_keys = shifted_targets(actions["keyboard"], distance)
        _, target_mouse_values = shifted_targets(actions["mouse"], distance)
        _, target_wheel_values = shifted_targets(actions["wheel"], distance)
        _, target_reward_values = shifted_targets(rewards, distance)
        total = total + F.binary_cross_entropy_with_logits(
            predicted_keyboard, target_keys
        )
        total = total + F.cross_entropy(
            predicted_mouse.flatten(0, 1), target_mouse_values.flatten()
        )
        total = total + F.cross_entropy(
            predicted_wheel.flatten(0, 1), target_wheel_values.flatten()
        )
        total = total + twohot_loss(predicted_reward, target_reward_values)
    return total / outputs["keyboard"].shape[2]


def freeze(module: nn.Module, frozen: bool) -> None:
    for parameter in module.parameters():
        parameter.requires_grad_(not frozen)


def stage_one(model: DreamerPrototype, cfg: PrototypeConfig, device: torch.device) -> torch.Tensor:
    freeze(model.tokenizer, False)
    freeze(model.dynamics, False)
    freeze(model.agent, True)
    batch = synthetic_batch(cfg, device)
    frames = batch["frames"]
    latents, reconstruction = model.tokenizer(frames)
    tokenizer_loss = F.mse_loss(reconstruction, model.tokenizer.preprocess(frames))
    world_loss, _ = dynamics_loss(model, latents.detach(), batch["actions"])
    return tokenizer_loss + world_loss


def stage_two(model: DreamerPrototype, cfg: PrototypeConfig, device: torch.device) -> torch.Tensor:
    freeze(model.tokenizer, True)
    freeze(model.dynamics, False)
    freeze(model.agent, False)
    batch = synthetic_batch(cfg, device)
    with torch.no_grad():
        latents = model.tokenizer.encode(batch["frames"])
    uniform = slice(1, None)
    relevant = slice(0, 1)
    uniform_actions = {key: value[uniform] for key, value in batch["actions"].items()}
    world_loss, _ = dynamics_loss(model, latents[uniform], uniform_actions)

    relevant_latents = latents[relevant]
    relevant_actions = {key: value[relevant] for key, value in batch["actions"].items()}
    noisy, tau_index = corrupt(relevant_latents, cfg)
    step_index = torch.full_like(tau_index, 2)
    _, hidden = model.dynamics(noisy, relevant_actions, tau_index, step_index)
    agent_features = model.agent.features(hidden, batch["tasks"][relevant])
    outputs = model.agent(agent_features)
    return world_loss + mtp_loss(
        outputs, relevant_actions, batch["rewards"][relevant]
    )


def sample_action(
    outputs: dict[str, torch.Tensor], cfg: PrototypeConfig
) -> tuple[dict[str, torch.Tensor], torch.Tensor]:
    keyboard_dist = torch.distributions.Bernoulli(logits=outputs["keyboard"][:, -1, 0])
    mouse_dist = torch.distributions.Categorical(logits=outputs["mouse"][:, -1, 0])
    wheel_dist = torch.distributions.Categorical(logits=outputs["wheel"][:, -1, 0])
    keyboard = keyboard_dist.sample()
    mouse = mouse_dist.sample()
    wheel = wheel_dist.sample()
    log_prob = (
        keyboard_dist.log_prob(keyboard).sum(-1)
        + mouse_dist.log_prob(mouse)
        + wheel_dist.log_prob(wheel)
    )
    return {
        "keyboard": keyboard[:, None],
        "mouse": mouse[:, None],
        "wheel": wheel[:, None],
    }, log_prob


def stage_three(
    model: DreamerPrototype, cfg: PrototypeConfig, device: torch.device
) -> torch.Tensor:
    freeze(model.tokenizer, True)
    freeze(model.dynamics, True)
    freeze(model.agent, False)
    prior = copy.deepcopy(model.agent).eval()
    freeze(prior, True)
    batch = synthetic_batch(cfg, device, steps=cfg.context_steps)
    with torch.no_grad():
        latents = model.tokenizer.encode(batch["frames"])

    log_probs = []
    prior_log_probs = []
    reward_logits = []
    value_logits = []
    tasks = batch["tasks"][:, -1:]
    action_history = batch["actions"]

    for _ in range(cfg.imagination_horizon):
        context = latents[:, -cfg.context_steps :]
        context_actions = {
            key: value[:, -context.shape[1] :] for key, value in action_history.items()
        }
        tau = torch.full(
            context.shape[:2], cfg.shortcut_steps, device=device, dtype=torch.long
        )
        step = torch.full_like(tau, cfg.shortcut_steps - 1)
        with torch.no_grad():
            _, hidden = model.dynamics(context, context_actions, tau, step)
        task_context = tasks.expand(-1, context.shape[1])
        features = model.agent.features(hidden.detach(), task_context)
        outputs = model.agent(features)
        action, log_prob = sample_action(outputs, cfg)
        log_probs.append(log_prob)
        reward_logits.append(outputs["reward"][:, -1, 0])
        value_logits.append(outputs["value"][:, -1])

        with torch.no_grad():
            prior_features = prior.features(hidden, task_context)
            prior_outputs = prior(prior_features)
            prior_action_log_prob = torch.zeros_like(log_prob)
            prior_action_log_prob += torch.distributions.Bernoulli(
                logits=prior_outputs["keyboard"][:, -1, 0]
            ).log_prob(action["keyboard"][:, 0]).sum(-1)
            prior_action_log_prob += torch.distributions.Categorical(
                logits=prior_outputs["mouse"][:, -1, 0]
            ).log_prob(action["mouse"][:, 0])
            prior_action_log_prob += torch.distributions.Categorical(
                logits=prior_outputs["wheel"][:, -1, 0]
            ).log_prob(action["wheel"][:, 0])
            prior_log_probs.append(prior_action_log_prob)

            noise = torch.randn_like(context[:, -1:])
            next_latent = noise
            extended_actions = {
                key: torch.cat([value, action[key]], dim=1)
                for key, value in context_actions.items()
            }
            for denoise_index in range(cfg.shortcut_steps):
                tau_value = denoise_index
                tau_step = torch.full(
                    (context.shape[0], context.shape[1] + 1),
                    tau_value,
                    device=device,
                    dtype=torch.long,
                )
                step_value = torch.full_like(tau_step, 2)
                candidate = torch.cat([context, next_latent], dim=1)
                predicted, _ = model.dynamics(
                    candidate, extended_actions, tau_step, step_value
                )
                tau_scalar = denoise_index / cfg.shortcut_steps
                velocity = (predicted[:, -1:] - next_latent) / (1.0 - tau_scalar)
                next_latent = next_latent + velocity / cfg.shortcut_steps
            latents = torch.cat([latents, next_latent], dim=1)
            action_history = {
                key: torch.cat([value, action[key]], dim=1)
                for key, value in action_history.items()
            }

    rewards = torch.stack(
        [twohot_expectation(item) for item in reward_logits], dim=1
    )
    values = torch.stack([twohot_expectation(item) for item in value_logits], dim=1)
    returns = lambda_returns(rewards.detach(), values.detach(), gamma=0.997, lam=0.95)
    advantage = returns - values.detach()
    policy_log_prob = torch.stack(log_probs, dim=1)
    prior_log_prob = torch.stack(prior_log_probs, dim=1)
    positive = advantage >= 0
    negative = ~positive
    positive_loss = -policy_log_prob[positive].mean() if positive.any() else 0.0
    negative_loss = policy_log_prob[negative].mean() if negative.any() else 0.0
    reverse_kl_sample = policy_log_prob - prior_log_prob
    policy_loss = 0.5 * positive_loss + 0.5 * negative_loss + 0.3 * reverse_kl_sample.mean()
    value_loss = torch.stack(
        [twohot_loss(logits, target) for logits, target in zip(value_logits, returns.unbind(1))]
    ).mean()
    return policy_loss + value_loss


def twohot_expectation(logits: torch.Tensor) -> torch.Tensor:
    support = torch.linspace(-20, 20, logits.shape[-1], device=logits.device)
    symlog_value = (logits.softmax(-1) * support).sum(-1)
    return torch.sign(symlog_value) * torch.expm1(symlog_value.abs())


def lambda_returns(
    rewards: torch.Tensor, values: torch.Tensor, gamma: float, lam: float
) -> torch.Tensor:
    result = torch.empty_like(rewards)
    carry = values[:, -1]
    for index in reversed(range(rewards.shape[1])):
        next_value = values[:, index + 1] if index + 1 < values.shape[1] else values[:, -1]
        carry = rewards[:, index] + gamma * ((1 - lam) * next_value + lam * carry)
        result[:, index] = carry
    return result


STAGES: dict[str, Callable[[DreamerPrototype, PrototypeConfig, torch.device], torch.Tensor]] = {
    "world_model": stage_one,
    "agent_finetune": stage_two,
    "imagination": stage_three,
}


def trainable_parameters(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


def measure_stage(
    name: str,
    function: Callable[[DreamerPrototype, PrototypeConfig, torch.device], torch.Tensor],
    cfg: PrototypeConfig,
    device: torch.device,
) -> dict[str, float | int | str]:
    torch.manual_seed(7)
    device_monitor = NvidiaSmiMonitor() if device.type == "cuda" else None
    if device_monitor:
        device_monitor.start()
    model = DreamerPrototype(cfg).to(device)
    model.train()
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    started = time.perf_counter()
    autocast = (
        torch.autocast(device_type="cuda", dtype=torch.bfloat16)
        if device.type == "cuda"
        else nullcontext()
    )
    with autocast:
        loss = function(model, cfg, device)
    loss.backward()
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=3e-4,
    )
    optimizer.step()
    if device.type == "cuda":
        torch.cuda.synchronize(device)
        allocated = torch.cuda.max_memory_allocated(device) / 1024**3
        reserved = torch.cuda.max_memory_reserved(device) / 1024**3
    else:
        allocated = reserved = 0.0
    whole_device = device_monitor.stop() if device_monitor else None
    elapsed = time.perf_counter() - started
    result = {
        "stage": name,
        "loss": float(loss.detach()),
        "seconds": round(elapsed, 3),
        "peak_allocated_gib": round(allocated, 3),
        "peak_reserved_gib": round(reserved, 3),
        "whole_device_vram": whole_device,
        "trainable_parameters": trainable_parameters(model),
    }
    del loss, optimizer, model
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["all", *STAGES], default="all")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    cfg = PrototypeConfig()
    device = torch.device("cpu" if args.cpu or not torch.cuda.is_available() else "cuda")
    if device.type == "cuda":
        free_bytes, total_bytes = torch.cuda.mem_get_info(device)
        cuda_memory_before = {
            "total_gib": round(total_bytes / 1024**3, 3),
            "used_gib": round((total_bytes - free_bytes) / 1024**3, 3),
            "free_gib": round(free_bytes / 1024**3, 3),
        }
        nvidia_smi_memory_before = nvidia_smi_memory()
    else:
        cuda_memory_before = None
        nvidia_smi_memory_before = None
    selected = STAGES if args.stage == "all" else {args.stage: STAGES[args.stage]}
    results = [measure_stage(name, function, cfg, device) for name, function in selected.items()]
    report = {
        "prototype": True,
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "torch": torch.__version__,
        "cuda_memory_before": cuda_memory_before,
        "nvidia_smi_memory_before": nvidia_smi_memory_before,
        "config": asdict(cfg),
        "results": results,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
