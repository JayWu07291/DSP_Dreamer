"""Stage B loader, frozen tokenizer, full shortcut loss and resumable checkpoints."""
from dataclasses import asdict, dataclass
import math
import os
from pathlib import Path
import random
import time

import numpy as np
import torch

from .actions import ACTION_CODEC, validate_action_contract
from .contract import atomic_save, file_info, load, require
from .dynamics import Dynamics, DynamicsConfig, shortcut_loss
from .tokenizer import CausalTokenizer, TokenizerConfig
from .tokenizer_training import read_checkpoint
from .tokenizer_evaluation import score_reconstruction


@dataclass(frozen=True)
class DynamicsTrainingConfig:
    updates: int
    seed: int = 2203
    microbatch: int = 2
    accumulation: int = 8
    short_length: int = 32
    long_length: int = 80
    learning_rate: float = 1e-4
    max_seconds: float = 57600

    def __post_init__(self):
        require(all(type(v) is int and v > 0 for v in (self.updates, self.microbatch,
                self.accumulation, self.short_length, self.long_length)), '無效訓練步數或 batch')
        require(type(self.seed) is int and self.learning_rate == 1e-4
                and math.isfinite(self.max_seconds) and 0 < self.max_seconds <= 57600, '無效訓練預算或配方')

    def validate_formal(self):
        require((self.microbatch, self.accumulation) in ((2, 8), (1, 16))
                and (self.short_length, self.long_length) == (32, 80), '正式配方需 batch 16 及 32/80 steps')


def require_reconstruction(proof, tokenizer_sha256, provenance):
    require(isinstance(proof, dict) and set(proof) == {'metrics', 'inputs', 'annotations', 'gate'},
            '正式第一階段 B 需要完整重建 gate 證據')
    gate = score_reconstruction(proof['metrics'], proof['inputs'], proof['annotations'], proof['gate']['judgments'])
    require(gate == proof['gate'] and gate['status'] == 'passed', '重建 gate 未通過')
    require(proof['metrics']['checkpoint_sha256'] == tokenizer_sha256
            and all(proof['metrics'].get(k) == provenance.get(k) for k in
                    ('protocol_id', 'data_freeze_id', 'evaluation_inputs_id', 'annotations_id')),
            '重建 gate 不屬於此 tokenizer 或凍結資料')
    return gate['artifact_id']


def read_dynamics_checkpoint(path):
    require(file_info(path) == load(str(path) + '.json')['checkpoint'], 'Checkpoint checksum mismatch')
    value = torch.load(path, map_location='cpu', weights_only=True)
    require(value.get('schema') == 'dsp-dynamics-checkpoint/1', '不支援的 dynamics checkpoint')
    # Validate the entire codec before constructing or loading any model weights.
    validate_action_contract(value['action_codec'])
    return value


def load_tokenizer(path, *, device='cpu'):
    payload = read_checkpoint(path)
    model = CausalTokenizer(TokenizerConfig(**payload['model_config'])).to(device).eval()
    model.load_state_dict(payload['model'])
    model.requires_grad_(False)
    return model, payload


class DynamicsTrainer:
    def __init__(self, tokenizer_path, index, config, *, model_config=DynamicsConfig(), device='cuda',
                 formal=False, reconstruction=None, provenance=None):
        self.tokenizer_source = dict(path=str(Path(tokenizer_path).resolve()), checkpoint=file_info(tokenizer_path))
        self.index, self.config, self.formal = index, config, formal
        self.reconstruction, self.provenance = reconstruction, provenance or {}
        if formal:
            require_reconstruction(reconstruction, self.tokenizer_source['checkpoint']['sha256'], self.provenance)
            config.validate_formal()
            require(model_config == DynamicsConfig() and index.report['coverage_gate_passed'], '正式架構或資料覆蓋不符')
            require(torch.device(device).type == 'cuda', '正式訓練需要 CUDA')
        else:
            require(all(s['source_kind'] == 'synthetic' for s in index.report['sources']),
                    '工程 smoke 僅接受合成 fixtures；真實資料需要通過重建 gate')
        self.device = torch.device(device)
        require(self.device.type in ('cpu', 'cuda'), '不支援的 device')
        if self.device.type == 'cuda':
            require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), '需要 BF16 CUDA')
        random.seed(config.seed)
        np.random.seed(config.seed)
        torch.manual_seed(config.seed)
        self.tokenizer, payload = load_tokenizer(tokenizer_path, device=self.device)
        require(payload['index_id'] == index.report['artifact_id'] and payload['sources'] == index.report['sources'],
                'Tokenizer 資料身分不同')
        require(self.tokenizer.config.latent_tokens == 64, '正式 v1 dynamics 固定 64 tokens')
        if formal:
            require(self.tokenizer.config == TokenizerConfig() and payload['step'] > 0, '正式 tokenizer 架構或進度不符')
            require(all(payload['provenance'].get(k) == self.provenance.get(k) for k in
                    ('protocol_id', 'data_freeze_id', 'evaluation_inputs_id', 'annotations_id')), 'Tokenizer 凍結資料不符')
        self.metric_identity = payload['metric']
        self.model = Dynamics(model_config).to(self.device)
        decay: list[torch.nn.Parameter] = []
        no_decay: list[torch.nn.Parameter] = []
        for name, parameter in self.model.named_parameters():
            (no_decay if parameter.ndim < 2 or name.endswith('bias') else decay).append(parameter)
        self.optimizer = torch.optim.AdamW([dict(params=decay, weight_decay=.01),
            dict(params=no_decay, weight_decay=0.)], lr=config.learning_rate, betas=(.9, .999), eps=1e-8)
        self.step, self.elapsed_seconds = 0, 0.
        self.history = []
        self.pools = {length: [(s['artifact_id'], start) for s in index.report['sources']
            if s['split'] == 'train' for start in index.views[s['artifact_id']].sequence_starts(length)]
            for length in {config.short_length, config.long_length}}
        require(all(self.pools.values()), 'Train 缺少合法 sequence')

    def samples(self, step):
        length = self.config.long_length if step % 4 == 3 else self.config.short_length
        rng = random.Random(self.config.seed + step)
        return length, [rng.choice(self.pools[length]) for _ in range(self.config.microbatch * self.config.accumulation)]

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
            group['lr'] = cfg.learning_rate * factor
        length, samples = self.samples(self.step)
        totals = np.zeros(3)
        for offset in range(0, len(samples), cfg.microbatch):
            if time.monotonic() >= deadline:
                raise TimeoutError('已達預算，未完成的 accumulation 不更新權重')
            frames = []
            action_rows: dict[str, list] = {k: [] for k in ('binary', 'mouse', 'wheel')}
            for artifact, start in samples[offset:offset + cfg.microbatch]:
                batch = self.index.views[artifact].sequence(start, length)
                require(batch['valid_mask'].all() and batch['loss_mask'].all(), '訓練含非法區間')
                # z_0,...,z_T with incoming actions no-op,a_0,...,a_(T-1).
                frames.append(torch.from_numpy(np.concatenate((batch['inputs']['observation'],
                                                               batch['targets']['next_observation'][-1:]))))
                for k in action_rows:
                    values = torch.from_numpy(batch['inputs'][k])
                    action_rows[k].append(torch.cat((torch.tensor(ACTION_CODEC['noop'][k]).reshape(1, *values.shape[1:]), values)))
            rgb = torch.stack(frames).to(self.device)
            actions = {k: torch.stack(v).to(self.device) for k, v in action_rows.items()}
            del frames, action_rows, batch
            with torch.autocast(self.device.type, dtype=torch.bfloat16, enabled=self.device.type == 'cuda'):
                with torch.no_grad():
                    clean = self.tokenizer.encode(rgb).float()
                del rgb
                total, flow, bootstrap = shortcut_loss(self.model, clean, actions)
            require(torch.isfinite(total).item(), '非有限 loss，停止訓練')
            (total / cfg.accumulation).backward()
            totals += [v.detach().item() / cfg.accumulation for v in (total, flow, bootstrap)]
        norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1., error_if_nonfinite=True)
        if time.monotonic() >= deadline:
            raise TimeoutError('已達預算，未完成的 accumulation 不更新權重')
        self.optimizer.step()
        self.step += 1
        self.elapsed_seconds += time.monotonic() - started
        result = dict(step=self.step, length=length, samples=samples, loss=float(totals[0]),
                      flow=float(totals[1]), bootstrap=float(totals[2]), grad_norm=norm.item(),
                      learning_rate=self.optimizer.param_groups[0]['lr'])
        self.history.append(result)
        return result

    def save(self, path):
        path = Path(path)
        require(not path.exists(), f'Refusing overwrite: {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        state = np.random.get_state(legacy=True)
        assert isinstance(state, tuple)
        payload = dict(schema='dsp-dynamics-checkpoint/1', action_codec=ACTION_CODEC,
            model_config=asdict(self.model.config), training_config=asdict(self.config),
            model=self.model.state_dict(), optimizer=self.optimizer.state_dict(),
            tokenizer_source=self.tokenizer_source, metric=self.metric_identity,
            formal=self.formal, reconstruction=self.reconstruction, provenance=self.provenance,
            index_id=self.index.report['artifact_id'], sources=self.index.report['sources'],
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
        atomic_save(str(path) + '.json', dict(checkpoint=file_info(path), step=self.step, formal=self.formal,
                    index_id=payload['index_id'], tokenizer_source=self.tokenizer_source))

    @classmethod
    def restore(cls, path, index, *, device='cuda', provenance=None):
        value = read_dynamics_checkpoint(path)
        require(value['index_id'] == index.report['artifact_id'] and value['sources'] == index.report['sources'],
                'Checkpoint 資料身分不同')
        require(value['device_type'] == torch.device(device).type, 'Checkpoint device 不同')
        require(provenance is None or provenance == value['provenance'], 'Checkpoint 凍結資料或實作不同')
        source = value['tokenizer_source']
        require(file_info(source['path']) == source['checkpoint'], 'Tokenizer checkpoint 已改變')
        trainer = cls(source['path'], index, DynamicsTrainingConfig(**value['training_config']),
            model_config=DynamicsConfig(**value['model_config']), device=device, formal=value['formal'],
            reconstruction=value['reconstruction'], provenance=value['provenance'])
        require(trainer.metric_identity == value['metric'], 'Tokenizer metric 不同')
        trainer.model.load_state_dict(value['model'])
        trainer.optimizer.load_state_dict(value['optimizer'])
        trainer.step, trainer.elapsed_seconds, trainer.history = value['step'], value['elapsed_seconds'], value['history']
        random.setstate(value['python_rng'])
        state = value['numpy_rng']
        np.random.set_state((state[0], np.array(state[1], dtype=np.uint32), *state[2:]))
        torch.set_rng_state(value['torch_rng'])
        if value['cuda_rng']:
            torch.cuda.set_rng_state_all(value['cuda_rng'])
        return trainer
