"""Issue #24: 正式 tokenizer 訓練、恢復、短程對照與 validation 重建。"""
import argparse
from dataclasses import asdict
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import torch

from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import seal
from dsp_dreamer.tokenizer import TokenizerConfig
from dsp_dreamer.tokenizer_training import ReconstructionLoss, TokenizerTrainer, TrainingConfig
from dsp_dreamer.tokenizer_evaluation import (open_frozen_corpus, read_frozen_evaluation,
                                             evaluate_reconstruction, score_reconstruction)


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def train(trainer, output, inputs, annotations, *, verify_resume=False, deadline=None):
    output.mkdir(parents=True, exist_ok=False)
    atomic_save(output / 'recipe.json', seal(dict(model=asdict(trainer.model.config), training=asdict(trainer.config),
        metric=trainer.loss.identity, provenance=trainer.provenance, index_id=trainer.index.report['artifact_id'])))
    torch.cuda.reset_peak_memory_stats()
    started, last_validation = time.monotonic(), time.monotonic()
    initial_elapsed = trainer.elapsed_seconds
    restored_equal = None
    while trainer.step < trainer.config.updates and trainer.elapsed_seconds < trainer.config.max_seconds:
        before = time.monotonic()
        resume_path = output / f'resume-{trainer.step}.pt'
        if verify_resume and trainer.step == trainer.config.updates - 1:
            trainer.save(resume_path)
        try:
            result = trainer.update(deadline=deadline)
        except TimeoutError:
            break
        emit(dict(tokens=trainer.model.config.latent_tokens, step=trainer.step, length=result['length'],
                  loss=result['loss'], seconds=time.monotonic()-before))
        if resume_path.exists():
            # Compare the next long update through the actual save/load path, including AdamW and RNG.
            completed_path = output / f'completed-{trainer.step}.pt'
            trainer.save(completed_path)
            expected = {k: v.detach().cpu().clone() for k, v in trainer.model.state_dict().items()}
            index, loss, provenance = trainer.index, trainer.loss, trainer.provenance
            del trainer
            gc.collect()
            torch.cuda.empty_cache()
            trainer = TokenizerTrainer.restore(resume_path, index, loss, device='cuda', provenance=provenance)
            try:
                actual = trainer.update(deadline=deadline)
            except TimeoutError:
                trainer = TokenizerTrainer.restore(completed_path, index, loss, device='cuda', provenance=provenance)
                restored_equal = False
                break
            require(result == actual, '恢復後下一次更新紀錄不同')
            require(all(torch.equal(v, trainer.model.state_dict()[k].cpu()) for k, v in expected.items()),
                    '恢復後模型權重不同')
            restored_equal = True
            del expected
        if time.monotonic() - last_validation >= 1800:
            path = output / f'step-{trainer.step}.pt'
            trainer.save(path)
            try:
                evaluate_reconstruction(path, trainer.index, trainer.loss, inputs, annotations,
                                        output / f'validation-{trainer.step}', limit=8, deadline=deadline)
            except TimeoutError:
                break
            last_validation = time.monotonic()
        trainer.elapsed_seconds = initial_elapsed + time.monotonic() - started
    trainer.elapsed_seconds = initial_elapsed + time.monotonic() - started
    path = output / f'final-{trainer.step}.pt'
    trainer.save(path)
    report = seal(dict(schema='dsp-tokenizer-run/1', checkpoint=str(path), checkpoint_sha256=file_info(path)['sha256'],
        updates=trainer.step, planned_updates=trainer.config.updates, seconds=time.monotonic()-started,
        peak_allocated_gib=torch.cuda.max_memory_allocated()/2**30,
        peak_reserved_gib=torch.cuda.max_memory_reserved()/2**30,
        resumed_next_update_identical=restored_equal, history=trainer.history,
        model=asdict(trainer.model.config), training=asdict(trainer.config), metric=trainer.loss.identity,
        provenance=trainer.provenance, index_id=trainer.index.report['artifact_id']))
    atomic_save(output / 'run.json', report)
    return report


def run_budgeted(args):
    # One mutable ledger for stage A, including probes, failures, resumes and evaluation.
    path = Path('runs/tokenizer-budget.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    state = load(path) if path.exists() else dict(schema='dsp-tokenizer-budget/1', attempts=[])
    require(state['schema'] == 'dsp-tokenizer-budget/1', '不相容的訓練預算紀錄')
    now = time.time()
    for attempt in state['attempts']:
        if attempt['seconds'] is None:
            attempt.update(seconds=max(0., now-attempt['started']), status='interrupted')
    remaining = 14400 - sum(a['seconds'] for a in state['attempts'])
    require(remaining > 0, '第一階段 A 已用完四小時，停止執行')
    require(args.microbatch != 1 or any(a['status'] == 'cuda_oom' and a['microbatch'] == 2
                                      for a in state['attempts']), '1/16 需先有 2/8 顯存不足紀錄')
    attempt = dict(command=args.command, output=str(args.output), microbatch=args.microbatch,
                   started=now, seconds=None, status='running')
    state['attempts'].append(attempt)

    def save_budget():
        temporary = path.with_suffix('.partial')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(state, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    save_budget()
    started = time.monotonic()
    try:
        run_gpu(args, started + remaining)
        attempt['status'] = 'completed'
    except torch.cuda.OutOfMemoryError:
        attempt['status'] = 'cuda_oom'
        raise
    except BaseException:
        attempt['status'] = 'failed'
        raise
    finally:
        attempt['seconds'] = time.monotonic() - started
        save_budget()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['verify', 'train', 'evaluate', 'score'])
    parser.add_argument('--catalog', default='docs/data-catalog.json')
    parser.add_argument('--protocol', default='protocols/evaluation-v2.json')
    parser.add_argument('--cache', default='data/torch-cache')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--updates', type=int, default=4)
    parser.add_argument('--microbatch', type=int, choices=[1, 2], default=2)
    parser.add_argument('--tokens', type=int, choices=[64, 96], default=64)
    parser.add_argument('--max-seconds', type=float, default=14400)
    parser.add_argument('--metrics', type=Path)
    parser.add_argument('--judgments', type=Path)
    args = parser.parse_args()
    if args.command == 'score':
        _, inputs, annotations, _ = read_frozen_evaluation(args.catalog, args.protocol)
        require(args.metrics is not None, '需要 --metrics')
        result = score_reconstruction(load(args.metrics), inputs, annotations,
                                      load(args.judgments) if args.judgments else None)
        atomic_save(args.output, result)
        emit(result)
        return
    require(args.command != 'train' or args.tokens == 64, '正式 v1 固定 64 tokens；96 僅限 verify 對照')
    run_budgeted(args)


def run_gpu(args, deadline):
    require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), '正式執行需要 BF16 CUDA')
    tasks = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq DSPGAME.exe', '/FO', 'CSV'], text=True)
    require('DSPGAME.exe' not in tasks, '訓練前請關閉 DSP')
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    emit(dict(status='核對正式資料與完整 checksum'))
    index, inputs, annotations, provenance = open_frozen_corpus(args.catalog, args.protocol)
    provenance['implementation'] = {str(p): file_info(p) for p in [Path(__file__),
        Path('dsp_dreamer/tokenizer.py'), Path('dsp_dreamer/tokenizer_training.py'), Path('dsp_dreamer/tokenizer_evaluation.py')]}
    loss = ReconstructionLoss(args.cache, 'cuda')
    emit(dict(status='資料核對通過', device=torch.cuda.get_device_name(), index_id=index.report['artifact_id']))
    if args.command == 'evaluate':
        require(args.checkpoint is not None, '需要 --checkpoint')
        emit(evaluate_reconstruction(args.checkpoint, index, loss, inputs, annotations, args.output, deadline=deadline))
        return
    config = TrainingConfig(updates=args.updates, microbatch=args.microbatch,
                            accumulation=16//args.microbatch, max_seconds=args.max_seconds)
    config.validate_formal()
    if args.command == 'train':
        trainer = (TokenizerTrainer.restore(args.checkpoint, index, loss, provenance=provenance)
                   if args.checkpoint else TokenizerTrainer(index, loss, TokenizerConfig(latent_tokens=args.tokens),
                                                           config, provenance=provenance))
        require(trainer.model.config.latent_tokens == 64, '正式 v1 不接受 96-token checkpoint')
        trainer.config.validate_formal()
        require(trainer.model.config == TokenizerConfig(), '正式訓練不接受測試架構')
        emit(train(trainer, args.output, inputs, annotations, deadline=deadline))
        return
    require(args.updates >= 4, 'verify 至少四次更新，以涵蓋 80-step batch')
    args.output.mkdir(parents=True, exist_ok=False)
    benchmark = []
    for tokens in (64, 96):
        benchmark.append(train(TokenizerTrainer(index, loss, TokenizerConfig(latent_tokens=tokens),
            TrainingConfig(updates=4, microbatch=args.microbatch, accumulation=16//args.microbatch,
                           max_seconds=3600), provenance=provenance),
            args.output/f'probe-{tokens}', inputs, annotations, verify_resume=True, deadline=deadline))
        gc.collect()
        torch.cuda.empty_cache()
    require(all(r['updates'] == 4 and r['resumed_next_update_identical'] for r in benchmark), '探測未完成，停止對照')
    # Freeze a common count only after both full-loss, real-loader probes have been measured.
    seconds_per_update = max(r['seconds']/4 for r in benchmark)
    updates = min(args.updates, int(1620 / seconds_per_update))
    require(updates >= 1, '30 分鐘內無法完成共同 updates，停止對照')
    plan = seal(dict(schema='dsp-tokenizer-comparison-plan/1', updates=updates, seed=2202,
        tokens=[64, 96], official_v1_tokens=64, max_seconds_each=1800,
        benchmark_ids=[r['artifact_id'] for r in benchmark], seconds_per_update=seconds_per_update,
        metric=loss.identity, index_id=index.report['artifact_id'], **provenance))
    atomic_save(args.output/'comparison-plan.json', plan)
    results = []
    for tokens in (64, 96):
        comparison_deadline = min(deadline, time.monotonic() + 1800)
        trainer = TokenizerTrainer(index, loss, TokenizerConfig(latent_tokens=tokens),
            TrainingConfig(updates=updates, microbatch=args.microbatch, accumulation=16//args.microbatch,
                           max_seconds=1800), provenance=provenance)
        result = train(trainer, args.output/f'compare-{tokens}', inputs, annotations, deadline=comparison_deadline)
        del trainer
        gc.collect()
        torch.cuda.empty_cache()
        gate = evaluate_reconstruction(result['checkpoint'], index, loss, inputs, annotations,
                                       args.output/f'reconstruction-{tokens}', deadline=comparison_deadline)
        results.append(dict(run=result, gate=gate))
    require(results[0]['run']['updates'] == results[1]['run']['updates'] == updates, '對照未完成相同步數')
    require([r['samples'] for r in results[0]['run']['history']] == [r['samples'] for r in results[1]['run']['history']],
            '對照資料順序不同')
    summary = seal(dict(schema='dsp-tokenizer-verification/1', plan_id=plan['artifact_id'], benchmark=benchmark,
        comparisons=results, official_v1_tokens=64, engineering_status='passed', model_quality_status='pending',
        gpu=torch.cuda.get_device_name(), precision='bf16', activation_checkpointing=True,
        limits='少量更新與完整 loss/loader 驗證，不代表收斂、品質 gate 或長程訓練已通過'))
    atomic_save(args.output/'verification.json', summary)
    emit(dict(status='工程驗證完成', report=str(args.output/'verification.json'), model_quality_status='pending'))


if __name__ == '__main__':
    main()
