"""Full-loss training and verified, resumable tokenizer checkpoints."""
from dataclasses import asdict, dataclass
import importlib.metadata
import math
from pathlib import Path
import random
import platform
import time

import numpy as np
import torch
from torch.utils.checkpoint import checkpoint

from .actions import ACTION_CODEC, validate_action_contract
from .contract import atomic_save, file_info, load, require
from .tokenizer import CausalTokenizer, TokenizerConfig


class ReconstructionLoss:
    def __init__(self, cache_dir, device="cpu"):
        import lpips
        require(importlib.metadata.version("lpips") == "0.1.4", "需要 lpips 0.1.4")
        torch.hub.set_dir(str(Path(cache_dir).resolve()))
        self.metric = lpips.LPIPS(net="alex", version="0.1", spatial=False, verbose=False).eval().to(device)
        self.metric.requires_grad_(False)
        self.identity = dict(lpips_version="0.1.4", net="alex", version="0.1", spatial=False,
            alexnet=file_info(Path(torch.hub.get_dir()) / "checkpoints/alexnet-owt-7be5be79.pth"),
            lpips=file_info(Path(lpips.__file__).parent / "weights/v0.1/alex.pth"),
            torch=str(torch.__version__), torchvision=importlib.metadata.version("torchvision"))
        self.identity['environment'] = dict(python=platform.python_version(), platform=platform.platform(),
            numpy=np.__version__, cuda=torch.version.cuda, cudnn=torch.backends.cudnn.version())

    def per_frame(self, prediction, target):
        # LPIPS and MSE stay float32 even inside the model's BF16 autocast context.
        with torch.autocast(prediction.device.type, enabled=False):
            prediction, target = prediction.float(), target.float()
            mse = (prediction - target).square().mean(dim=(1, 2, 3))
            perceptual = self.metric(prediction * 2 - 1, target * 2 - 1).flatten()
        return torch.stack((mse, perceptual), dim=-1)

    def __call__(self, prediction, target):
        prediction, target = prediction.flatten(0, 1), target.flatten(0, 1)
        # Keep the full native-resolution loss, recomputing AlexNet one frame at a time.
        values = [checkpoint(self.per_frame, p[None], t[None], use_reentrant=False)
                  if torch.is_grad_enabled() else self.per_frame(p[None], t[None])
                  for p, t in zip(prediction, target)]
        mse, perceptual = torch.cat(values).mean(0).unbind()
        return mse + .2 * perceptual, mse, perceptual


@dataclass(frozen=True)
class TrainingConfig:
    updates: int
    seed: int = 2202
    microbatch: int = 2
    accumulation: int = 8
    short_length: int = 32
    long_length: int = 80
    learning_rate: float = 1e-4
    max_seconds: float = 14400

    def __post_init__(self):
        require(all(type(v) is int and v > 0 for v in (self.updates, self.microbatch,
            self.accumulation, self.short_length, self.long_length)), "無效訓練步數或 batch")
        require(math.isfinite(self.max_seconds) and 0 < self.max_seconds <= 14400
                and self.learning_rate == 1e-4 and type(self.seed) is int, "無效訓練預算或配方")

    def validate_formal(self):
        require((self.microbatch, self.accumulation) in ((2, 8), (1, 16))
                and (self.short_length, self.long_length) == (32, 80), "正式配方需 batch 16 及 32/80 steps")


def read_checkpoint(path):
    require(file_info(path) == load(str(path) + ".json")["checkpoint"], "Checkpoint checksum mismatch")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    require(payload.get("schema") == "dsp-tokenizer-checkpoint/1", "不支援的 checkpoint schema")
    validate_action_contract(payload["action_codec"])
    return payload


class TokenizerTrainer:
    def __init__(self, index, loss, model_config, config, *, device="cuda", provenance=None):
        self.index, self.loss, self.config = index, loss, config
        self.device = torch.device(device)
        require(self.device.type in ("cpu", "cuda"), "不支援的訓練 device")
        if self.device.type == "cuda":
            require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), "需要支援 BF16 的 CUDA")
        random.seed(config.seed)
        np.random.seed(config.seed)
        torch.manual_seed(config.seed)
        self.model = CausalTokenizer(model_config).to(self.device)
        decay: list[torch.nn.Parameter] = []
        no_decay: list[torch.nn.Parameter] = []
        for name, parameter in self.model.named_parameters():
            (no_decay if parameter.ndim < 2 or name.endswith("bias") else decay).append(parameter)
        self.optimizer = torch.optim.AdamW([dict(params=decay, weight_decay=.01),
            dict(params=no_decay, weight_decay=0.)], lr=config.learning_rate, betas=(.9, .999), eps=1e-8)
        self.step, self.elapsed_seconds = 0, 0.
        self.provenance = provenance or {}
        self.history = []
        self.pools = {length: [(s['artifact_id'], start) for s in index.report['sources']
            if s['split'] == 'train' for start in index.views[s['artifact_id']].sequence_starts(length)]
            for length in {config.short_length, config.long_length}}
        require(all(self.pools.values()), "Train 缺少合法 sequence")

    def samples(self, step):
        length = self.config.long_length if step % 4 == 3 else self.config.short_length
        rng = random.Random(self.config.seed + step)
        return length, [rng.choice(self.pools[length])
                        for _ in range(self.config.microbatch * self.config.accumulation)]

    def update(self, *, deadline=None):
        cfg = self.config
        require(self.step < cfg.updates and self.elapsed_seconds < cfg.max_seconds, "已達訓練預算")
        started = time.monotonic()
        deadline = min(deadline or float('inf'), started + cfg.max_seconds - self.elapsed_seconds)
        self.model.train()
        self.optimizer.zero_grad(set_to_none=True)
        warmup = max(1, math.ceil(cfg.updates * .05))
        factor = ((self.step + 1) / warmup if self.step < warmup else
                  .1 + .9 * (1 + math.cos(math.pi * (self.step - warmup + 1) /
                            max(1, cfg.updates - warmup))) / 2)
        for group in self.optimizer.param_groups:
            group['lr'] = cfg.learning_rate * factor
        length, samples = self.samples(self.step)
        totals = np.zeros(3)
        for offset in range(0, len(samples), cfg.microbatch):
            if time.monotonic() >= deadline:
                raise TimeoutError('已達訓練時數，未完成的 accumulation 不更新權重')
            frames = []
            for artifact, start in samples[offset:offset + cfg.microbatch]:
                batch = self.index.views[artifact].sequence(start, length)
                require(batch['valid_mask'].all() and batch['loss_mask'].all(), "訓練 sequence 含非法區間")
                frames.append(torch.from_numpy(batch['inputs']['observation']))
            inputs = torch.stack(frames).to(self.device)
            del frames, batch
            # Mask RNG is independent of parameter count: the 64/96 runs see identical masks.
            generator = torch.Generator(device=self.device).manual_seed(cfg.seed + self.step * 16 + offset)
            with torch.autocast(self.device.type, dtype=torch.bfloat16, enabled=self.device.type == 'cuda'):
                _, prediction = self.model(inputs, generator=generator)
                total, mse, perceptual = self.loss(prediction, inputs)
            require(torch.isfinite(total).item(), "非有限 loss，停止訓練")
            (total / cfg.accumulation).backward()
            totals += [value.detach().item() / cfg.accumulation for value in (total, mse, perceptual)]
            del inputs, prediction, total, mse, perceptual
        norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1., error_if_nonfinite=True)
        if time.monotonic() >= deadline:
            raise TimeoutError('已達訓練時數，未完成的 accumulation 不更新權重')
        self.optimizer.step()
        self.step += 1
        self.elapsed_seconds += time.monotonic() - started
        result = dict(step=self.step, length=length, samples=samples, loss=float(totals[0]),
                      mse=float(totals[1]), lpips=float(totals[2]), grad_norm=norm.item(),
                      learning_rate=self.optimizer.param_groups[0]['lr'])
        self.history.append(result)
        return result

    def save(self, path):
        path = Path(path)
        require(not path.exists(), f"Refusing overwrite: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        numpy_state = np.random.get_state(legacy=True)
        assert isinstance(numpy_state, tuple)
        payload = dict(schema="dsp-tokenizer-checkpoint/1", action_codec=ACTION_CODEC,
            model_config=asdict(self.model.config), training_config=asdict(self.config),
            index_id=self.index.report['artifact_id'], sources=self.index.report['sources'],
            provenance=self.provenance, metric=self.loss.identity,
            model=self.model.state_dict(), optimizer=self.optimizer.state_dict(), step=self.step,
            elapsed_seconds=self.elapsed_seconds, history=self.history,
            python_rng=random.getstate(), numpy_rng=(numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]),
            torch_rng=torch.get_rng_state(), cuda_rng=torch.cuda.get_rng_state_all() if self.device.type == 'cuda' else [],
            device_type=self.device.type)
        partial = path.with_name(path.name + '.partial')
        with partial.open('xb') as stream:
            torch.save(payload, stream)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        partial.rename(path)
        atomic_save(str(path) + '.json', dict(checkpoint=file_info(path), step=self.step,
                    index_id=payload['index_id'], model_config=payload['model_config'], provenance=self.provenance))

    @classmethod
    def restore(cls, path, index, loss, *, device="cuda", provenance=None):
        value = read_checkpoint(path)
        require(value['index_id'] == index.report['artifact_id'] and value['sources'] == index.report['sources'],
                "Checkpoint 資料身分不同")
        require(value['metric'] == loss.identity and value['device_type'] == torch.device(device).type,
                "Checkpoint metric 或 device 不同")
        require(provenance is None or provenance == value['provenance'], "Checkpoint 凍結資料不同")
        trainer = cls(index, loss, TokenizerConfig(**value['model_config']),
                      TrainingConfig(**value['training_config']), device=device, provenance=value['provenance'])
        trainer.model.load_state_dict(value['model'])
        trainer.optimizer.load_state_dict(value['optimizer'])
        trainer.step, trainer.elapsed_seconds = value['step'], value['elapsed_seconds']
        trainer.history = value['history']
        random.setstate(value['python_rng'])
        state = value['numpy_rng']
        np.random.set_state((state[0], np.array(state[1], dtype=np.uint32), *state[2:]))
        torch.set_rng_state(value['torch_rng'])
        if value['cuda_rng']:
            torch.cuda.set_rng_state_all(value['cuda_rng'])
        return trainer
