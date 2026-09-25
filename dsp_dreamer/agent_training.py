"""Stage-two fine-tuning with source-bound gates and deterministic recovery."""
from dataclasses import asdict, dataclass
import math
import os
from pathlib import Path
import random
import time

import numpy as np
import torch

from .actions import ACTION_CODEC
from .agent import AGENT_CONFIG, Agent, incoming_actions, mtp_loss
from .contract import atomic_save, file_info, require
from .dynamics import Dynamics, DynamicsConfig, shortcut_loss
from .dynamics_training import (DynamicsTrainingConfig, load_tokenizer, read_dynamics_checkpoint,
                                require_reconstruction, verify_implementation)


@dataclass(frozen=True)
class AgentTrainingConfig(DynamicsTrainingConfig):
    max_seconds: float = 21600

    def __post_init__(self):
        super().__post_init__()
        require(self.max_seconds <= 21600 and self.microbatch * self.accumulation % 2 == 0,
                '第二階段需 50/50 batch，且最多 6 小時')


def require_stage_one(path, prediction, provenance):
    from .dynamics_evaluation import score_prediction
    value = read_dynamics_checkpoint(path)
    require(value['schema'] == 'dsp-dynamics-checkpoint/1' and value['formal'] and value['step'] > 0
            and all(s['source_kind'] == 'live' for s in value['sources']), '需要合格第一階段，工程 checkpoint 不可升級')
    require(all(value['provenance'].get(k) == provenance.get(k) and provenance.get(k) for k in
                ('protocol_id', 'data_freeze_id', 'evaluation_inputs_id', 'annotations_id')), '第一階段凍結來源不同')
    source = value['tokenizer_source']
    require(file_info(source['path']) == source['checkpoint'], 'Tokenizer checkpoint 已改變')
    require_reconstruction(value['reconstruction'], source['checkpoint']['sha256'], provenance)
    verify_implementation(value['provenance'])
    require(isinstance(prediction, dict) and set(prediction) == {'metrics', 'inputs', 'recipe', 'gate'},
            '正式第二階段需要第一階段預測 gate 證據')
    gate = score_prediction(prediction['metrics'], prediction['inputs'], prediction['gate']['judgments'],
                            checkpoint_path=path, recipe=prediction['recipe'])
    require(gate == prediction['gate'] and gate['status'] == 'passed', '第一階段預測 gate 未通過')
    return value


def validate_agent_checkpoint(value):
    require(value['agent_config'] == AGENT_CONFIG, '不相容 agent 配方')
    source = value['stage_one_source']
    require(file_info(source['path']) == source['checkpoint'], '第一階段 checkpoint 已改變')
    if value['formal']:
        original = require_stage_one(source['path'], value['prediction'], value['provenance'])
        require(value['index_id'] == original['index_id'] and value['sources'] == original['sources']
                and value['tokenizer_source'] == original['tokenizer_source']
                and value['model_config'] == original['model_config'], '第一階段 checkpoint 來源不符')
        verify_implementation(value['provenance'])


def read_agent_checkpoint(path):
    value = read_dynamics_checkpoint(path)
    require(value['schema'] == 'dsp-agent-checkpoint/1', '需要第二階段 checkpoint')
    return value


def sequence_pools(index, length, split='train'):
    pools: dict[str, list] = dict(uniform=[], relevant=[])
    for source in index.report['sources']:
        if source['split'] != split:
            continue
        artifact = source['artifact_id']
        view = index.views[artifact]
        completed = np.concatenate(([0], np.cumsum([bool(r['node_completions']) for r in view.rows])))
        for start in view.sequence_starts(length):
            pools['uniform'].append((artifact, start))
            if completed[start + length] > completed[start]:
                pools['relevant'].append((artifact, start))
    return pools


class AgentTrainer:
    def __init__(self, stage_one_path, index, config, *, device='cuda', formal=False, prediction=None, provenance=None):
        value = read_dynamics_checkpoint(stage_one_path)
        require(value['schema'] == 'dsp-dynamics-checkpoint/1' and value['step'] > 0, '需載入已更新的第一階段 checkpoint')
        self.provenance = provenance or {}
        if formal:
            require_stage_one(stage_one_path, prediction, self.provenance)
            verify_implementation(self.provenance)
            config.validate_formal()
            require(value['model_config'] == asdict(DynamicsConfig()) and index.report['coverage_gate_passed']
                    and torch.device(device).type == 'cuda', '正式架構、資料覆蓋或 CUDA 不符')
        else:
            require(not value['formal'] and all(s['source_kind'] == 'synthetic' for s in index.report['sources']),
                    '工程驗證只接受合成 fixtures')
        require(value['index_id'] == index.report['artifact_id'] and value['sources'] == index.report['sources'],
                '第一階段資料身分不同')
        if value['provenance'].get('implementation'):
            verify_implementation(value['provenance'])
        self.stage_one_source = dict(path=str(Path(stage_one_path).resolve()), checkpoint=file_info(stage_one_path))
        self.tokenizer_source = value['tokenizer_source']
        require(file_info(self.tokenizer_source['path']) == self.tokenizer_source['checkpoint'], 'Tokenizer checkpoint 已改變')
        self.device = torch.device(device)
        require(self.device.type in ('cpu', 'cuda'), '不支援的 device')
        if self.device.type == 'cuda':
            require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), '需要 BF16 CUDA')
        self.index, self.config, self.formal, self.prediction = index, config, formal, prediction
        self.reconstruction, self.metric_identity = value['reconstruction'], value['metric']
        random.seed(config.seed)
        np.random.seed(config.seed)
        torch.manual_seed(config.seed)
        self.tokenizer, token = load_tokenizer(self.tokenizer_source['path'], device=self.device)
        require(token['index_id'] == value['index_id'] and token['sources'] == value['sources']
                and token['metric'] == self.metric_identity, 'Tokenizer 資料或 metric 不符')
        world = Dynamics(DynamicsConfig(**value['model_config'])).to(self.device)
        world.load_state_dict(value['model'])
        self.model = Agent(world).to(self.device)
        groups = []
        for is_world in (True, False):
            for decay in (True, False):
                parameters = [p for n, p in self.model.named_parameters()
                              if n.startswith('dynamics.') == is_world and (p.ndim >= 2 and not n.endswith('bias')) == decay]
                groups.append(dict(params=parameters, lr=1e-5 if is_world else 1e-4,
                                   peak_lr=1e-5 if is_world else 1e-4, weight_decay=.01 if decay else 0.))
        self.optimizer = torch.optim.AdamW(groups, betas=(.9, .999), eps=1e-8)
        self.pools = {length: sequence_pools(index, length) for length in {config.short_length, config.long_length}}
        require(all(p for pools in self.pools.values() for p in pools.values()), 'Train 缺少 uniform/relevant 合法 sequence')
        self.step, self.elapsed_seconds = 0, 0.
        self.history = []

    def samples(self, step):
        length = self.config.long_length if step % 4 == 3 else self.config.short_length
        rng = random.Random(self.config.seed + step)
        samples = []
        for pool in ('uniform', 'relevant'):
            for _ in range(self.config.microbatch * self.config.accumulation // 2):
                artifact, start = rng.choice(self.pools[length][pool])
                samples.append(dict(artifact_id=artifact, start=start, pool=pool))
        return length, samples

    def update(self, *, deadline=None):
        cfg = self.config
        require(self.step < cfg.updates and self.elapsed_seconds < cfg.max_seconds, '已達訓練預算')
        started = time.monotonic()
        deadline = min(deadline or float('inf'), started + cfg.max_seconds - self.elapsed_seconds)
        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        warmup = max(1, math.ceil(cfg.updates * .05))
        factor = ((self.step + 1) / warmup if self.step < warmup else
                  .1 + .9 * (1 + math.cos(math.pi * (self.step - warmup + 1) / max(1, cfg.updates - warmup))) / 2)
        for group in self.optimizer.param_groups:
            group['lr'] = group['peak_lr'] * factor
        length, samples = self.samples(self.step)
        totals = dict(dynamics=0., policy=0., reward=0.)
        counts = [0] * 9
        # A microbatch never crosses the uniform/relevant boundary.
        half = len(samples) // 2
        for begin in (0, half):
            for offset in range(begin, begin + half, cfg.microbatch):
                if time.monotonic() >= deadline:
                    raise TimeoutError('已達預算，未完成的 accumulation 不更新權重')
                selected = samples[offset:min(offset + cfg.microbatch, begin + half)]
                batches = [self.index.views[s['artifact_id']].sequence(s['start'], length) for s in selected]
                require(all(b['valid_mask'].all() and b['loss_mask'].all() for b in batches), '訓練含非法區間')
                uniform = begin == 0
                frames = [np.concatenate((b['inputs']['observation'], b['targets']['next_observation'][-1:]))
                          if uniform else b['inputs']['observation'] for b in batches]
                rgb = torch.from_numpy(np.stack(frames)).to(self.device)
                actual = {k: torch.from_numpy(np.stack([b['inputs'][k] for b in batches])).to(self.device)
                          for k in ('binary', 'mouse', 'wheel')}
                past = incoming_actions(actual)
                if uniform:
                    past = {k: torch.cat((v, actual[k][:, -1:]), 1) for k, v in past.items()}
                weight = len(selected) / half
                with torch.autocast(self.device.type, dtype=torch.bfloat16, enabled=self.device.type == 'cuda'):
                    with torch.no_grad():
                        clean = self.tokenizer.encode(rgb).float()
                    if uniform:
                        total, _, _ = shortcut_loss(self.model.dynamics, clean, past)
                        totals['dynamics'] += total.detach().item() * weight
                    else:
                        tasks = torch.from_numpy(np.stack([b['inputs']['task_condition'] for b in batches])).to(self.device)
                        rewards = torch.from_numpy(np.stack([b['targets']['reward'] for b in batches])).to(self.device)
                        valid = torch.from_numpy(np.stack([b['valid_mask'] & b['loss_mask'] for b in batches])).to(self.device)
                        levels = torch.tensor([0., .1, .25, .5, .75], device=self.device)[torch.randint(5, clean.shape[:2], device=self.device)]
                        tau = levels[..., None, None]
                        outputs = self.model(tau * clean + (1 - tau) * torch.randn_like(clean), past, tasks, levels)
                        losses = mtp_loss(outputs, actual, rewards, tasks, valid, valid)
                        total = losses['total']
                        for key in ('policy', 'reward'):
                            totals[key] += losses[key].detach().item() * weight
                        counts = [a + b for a, b in zip(counts, losses['counts'])]
                require(torch.isfinite(total).item(), '非有限 loss，停止訓練')
                (total * weight).backward()
        norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1., error_if_nonfinite=True)
        if time.monotonic() >= deadline:
            raise TimeoutError('已達預算，未完成的 accumulation 不更新權重')
        self.optimizer.step()
        self.step += 1
        self.elapsed_seconds += time.monotonic() - started
        result = dict(step=self.step, length=length, samples=samples, loss=sum(totals.values()), **totals,
                      mtp_counts=counts, grad_norm=norm.item(), learning_rates=[g['lr'] for g in self.optimizer.param_groups])
        self.history.append(result)
        return result

    def save(self, path):
        path = Path(path)
        require(not path.exists(), f'Refusing overwrite: {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        state = np.random.get_state(legacy=True)
        assert isinstance(state, tuple)
        payload = dict(schema='dsp-agent-checkpoint/1', action_codec=ACTION_CODEC, agent_config=AGENT_CONFIG,
            model_config=asdict(self.model.dynamics.config), training_config=asdict(self.config),
            model=self.model.dynamics.state_dict(), agent={k: v for k, v in self.model.state_dict().items() if not k.startswith('dynamics.')},
            optimizer=self.optimizer.state_dict(), tokenizer_source=self.tokenizer_source, metric=self.metric_identity,
            formal=self.formal, status='pending' if self.formal else 'engineering_only',
            reconstruction=self.reconstruction, prediction=self.prediction, stage_one_source=self.stage_one_source,
            provenance=self.provenance, index_id=self.index.report['artifact_id'], sources=self.index.report['sources'],
            step=self.step, elapsed_seconds=self.elapsed_seconds, history=self.history,
            python_rng=random.getstate(), numpy_rng=(state[0], state[1].tolist(), *state[2:]),
            torch_rng=torch.get_rng_state(), cuda_rng=torch.cuda.get_rng_state_all() if self.device.type == 'cuda' else [],
            device_type=self.device.type)
        partial = path.with_name(path.name + '.partial')
        with partial.open('xb') as stream:
            torch.save(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        partial.rename(path)
        atomic_save(str(path) + '.json', dict(checkpoint=file_info(path), status=payload['status'], step=self.step))

    @classmethod
    def restore(cls, path, index, *, device='cuda', provenance=None):
        value = read_agent_checkpoint(path)
        require(value['index_id'] == index.report['artifact_id'] and value['sources'] == index.report['sources']
                and value['device_type'] == torch.device(device).type, 'Checkpoint 資料或 device 不同')
        require(provenance is None or provenance == value['provenance'], 'Checkpoint 凍結資料或實作不同')
        trainer = cls(value['stage_one_source']['path'], index, AgentTrainingConfig(**value['training_config']),
                      device=device, formal=value['formal'], prediction=value['prediction'], provenance=value['provenance'])
        trainer.model.load_state_dict({**{f'dynamics.{k}': v for k, v in value['model'].items()}, **value['agent']})
        trainer.optimizer.load_state_dict(value['optimizer'])
        trainer.step, trainer.elapsed_seconds, trainer.history = value['step'], value['elapsed_seconds'], value['history']
        random.setstate(value['python_rng'])
        state = value['numpy_rng']
        np.random.set_state((state[0], np.array(state[1], dtype=np.uint32), *state[2:]))
        torch.set_rng_state(value['torch_rng'])
        if value['cuda_rng']:
            torch.cuda.set_rng_state_all(value['cuda_rng'])
        return trainer
