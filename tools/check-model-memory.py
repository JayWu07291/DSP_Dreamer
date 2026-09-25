"""用合成影像檢查新版模型的 CUDA 前向／反向與顯存；不更新權重或正式帳本。"""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from dsp_dreamer.actions import ACTION_CODEC
from dsp_dreamer.agent import Agent, mtp_loss
from dsp_dreamer.contract import atomic_save, require
from dsp_dreamer.dynamics import Dynamics, DynamicsConfig, shortcut_loss
from dsp_dreamer.tokenizer import CausalTokenizer, TokenizerConfig
from dsp_dreamer.tokenizer_training import ReconstructionLoss
from dsp_dreamer.training_settings import DEFAULT_CONFIG, read_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=('A', 'B', 'second', 'both'), default='both')
    parser.add_argument('--cycles', type=int, default=1)
    args = parser.parse_args()
    require(not args.output.exists(), '顯存檢查紀錄不可覆寫')
    require(args.cycles > 0, 'cycles 必須大於零')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    settings = read_settings(args.config)
    torch.set_num_threads(settings['runtime']['num_threads'])
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(2202)
    require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), '需要 BF16 CUDA')
    torch.cuda.set_per_process_memory_fraction(settings['runtime']['cuda_memory_fraction'])
    metric = ReconstructionLoss('data/torch-cache', 'cuda')
    report = dict(kind='synthetic_forward_backward_only', optimizer_updates=0,
                  gpu=torch.cuda.get_device_name(), settings=settings, checks=[])
    for stage in (('A', 'B') if args.stage == 'both' else (args.stage,)):
        config = settings['stages'][stage]
        model: Any = (CausalTokenizer(TokenizerConfig(**settings['tokenizer'])) if stage == 'A'
                 else Dynamics(DynamicsConfig(**settings['dynamics']))).cuda().train()
        if stage == 'second':
            model = Agent(model).cuda().train()
        tokenizer = (CausalTokenizer(TokenizerConfig(**settings['tokenizer'])).cuda().eval().requires_grad_(False)
                     if stage != 'A' else None)
        # Allocate the two FP32 AdamW moments, without performing an optimizer step.
        moments = [torch.zeros_like(p) for p in model.parameters() for _ in range(2)]
        lengths = ((config['short_length'],) * (config['long_every'] - 1) + (config['long_length'],)
                   if stage == 'A' else (config['long_length'] + 1,)) * args.cycles
        for length in lengths:
            model.zero_grad(set_to_none=False)
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            started = time.monotonic()
            with torch.autocast('cuda', dtype=torch.bfloat16):
                if stage == 'A':
                    inputs = torch.rand(config['microbatch'], length, 3, 360, 640, device='cuda')
                    latents, prediction = model(inputs, mask_max_probability=config['mask_max_probability'])
                    terms = metric(prediction, inputs)
                else:
                    assert tokenizer is not None
                    rgb = torch.rand(config['microbatch'], length, 3, 360, 640, device='cuda')
                    with torch.no_grad():
                        inputs = tokenizer.encode(rgb).float()
                    del rgb
                    actions = {k: torch.tensor(v, device='cuda').expand(config['microbatch'], length,
                        *(() if k != 'binary' else (len(v),))) for k, v in ACTION_CODEC['noop'].items()}
                    terms = shortcut_loss(model.dynamics if stage == 'second' else model, inputs, actions)
                loss = terms[0]
            require(torch.isfinite(loss).item(), '非有限 synthetic loss')
            loss.backward()
            if stage == 'second':
                del loss, terms
                shape = (config['microbatch'], length - 1)
                tasks = torch.nn.functional.one_hot(torch.zeros(shape, device='cuda', dtype=torch.long), 17).float()
                relevant_actions = {k: v[:, :-1] for k, v in actions.items()}
                valid = torch.ones(shape, device='cuda', dtype=torch.bool)
                with torch.autocast('cuda', dtype=torch.bfloat16):
                    outputs = model(inputs[:, :-1], relevant_actions, tasks, torch.full(shape, .1, device='cuda'))
                    terms = mtp_loss(outputs, relevant_actions, torch.zeros(shape, device='cuda'), tasks, valid, valid)
                    loss = terms['total']
                loss.backward()
                del outputs, tasks, relevant_actions, valid
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), config['grad_clip'], error_if_nonfinite=True)
            torch.cuda.synchronize()
            row = dict(stage=stage, input_kind='native_rgb' if stage == 'A' else 'rgb_with_frozen_tokenizer',
                length=length, microbatch=config['microbatch'], loss=loss.item(),
                grad_norm=norm.item(), parameters=sum(p.numel() for p in model.parameters()),
                seconds=time.monotonic() - started,
                frames_per_second=config['microbatch'] * length / (time.monotonic() - started),
                peak_allocated_gib=torch.cuda.max_memory_allocated() / 2**30,
                peak_reserved_gib=torch.cuda.max_memory_reserved() / 2**30)
            report['checks'].append(row)
            print(json.dumps(row), flush=True)
            del inputs, loss, terms
            if stage == 'A':
                del latents, prediction
        del moments, model, tokenizer
        gc.collect()
        torch.cuda.empty_cache()
    report['status'] = 'passed'
    atomic_save(args.output, report)


if __name__ == '__main__':
    main()
