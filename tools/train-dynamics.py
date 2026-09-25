"""Issue #25：通過重建 gate 後訓練 dynamics，或評估與人工判讀評分。"""
import argparse
from dataclasses import asdict
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
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import torch

from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.dynamics_training import (DynamicsTrainer, DynamicsTrainingConfig,
    read_dynamics_checkpoint, require_reconstruction)
from dsp_dreamer.dynamics_evaluation import evaluate_prediction, score_prediction
from dsp_dreamer.evaluation_protocol import seal
from dsp_dreamer.tokenizer_evaluation import read_frozen_evaluation, open_frozen_corpus
from dsp_dreamer.tokenizer_training import ReconstructionLoss


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def train(trainer, output, loss, inputs, *, deadline):
    output.mkdir(parents=True, exist_ok=False)
    atomic_save(output / 'recipe.json', seal(dict(model=asdict(trainer.model.config), training=asdict(trainer.config),
        tokenizer_source=trainer.tokenizer_source, provenance=trainer.provenance, index_id=trainer.index.report['artifact_id'])))
    torch.cuda.reset_peak_memory_stats()
    started = last_validation = time.monotonic()
    initial_elapsed = trainer.elapsed_seconds
    status = 'completed'
    try:
        while (trainer.step < trainer.config.updates and trainer.elapsed_seconds < trainer.config.max_seconds
               and time.monotonic() < deadline):
            trainer.update(deadline=deadline)
            emit(trainer.history[-1])
            trainer.elapsed_seconds = initial_elapsed + time.monotonic() - started
            if time.monotonic() - last_validation >= 1800:
                path = output / f'step-{trainer.step}.pt'
                trainer.save(path)
                # Evaluation initialization must not change the training RNG stream.
                with torch.random.fork_rng(devices=[torch.cuda.current_device()]):
                    evaluate_prediction(path, trainer.index, loss, inputs, output / f'validation-{trainer.step}',
                                        limit=4, deadline=deadline)
                last_validation = time.monotonic()
        if trainer.step < trainer.config.updates:
            status = 'budget_exhausted'
    except TimeoutError:
        status = 'budget_exhausted'
    except BaseException:
        status = 'failed'
        raise
    finally:
        trainer.elapsed_seconds = initial_elapsed + time.monotonic() - started
        path = output / f'final-{trainer.step}.pt'
        trainer.save(path)
        report = seal(dict(schema='dsp-dynamics-run/1', status=status, formal=True,
            checkpoint=str(path), checkpoint_sha256=file_info(path)['sha256'], updates=trainer.step,
            planned_updates=trainer.config.updates, seconds=time.monotonic()-started,
            peak_allocated_gib=torch.cuda.max_memory_allocated()/2**30,
            peak_reserved_gib=torch.cuda.max_memory_reserved()/2**30, history=trainer.history,
            tokenizer_source=trainer.tokenizer_source, provenance=trainer.provenance,
            quality_status='pending', limits='更新完成不代表已通過 200 序列及人工判讀 gate'))
        atomic_save(output / 'run.json', report)
    emit(report)


def run_gpu(args, deadline):
    require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), '正式執行需要 BF16 CUDA')
    tasks = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq DSPGAME.exe', '/FO', 'CSV'], text=True)
    require('DSPGAME.exe' not in tasks, '訓練前請關閉 DSP')
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    index, inputs, _, provenance = open_frozen_corpus(args.catalog, args.protocol)
    provenance['implementation'] = {str(p): file_info(p) for p in [Path(__file__), Path('dsp_dreamer/dynamics.py'),
        Path('dsp_dreamer/dynamics_training.py'), Path('dsp_dreamer/dynamics_evaluation.py')]}
    loss = ReconstructionLoss(args.cache, 'cuda')
    if args.command == 'evaluate':
        emit(evaluate_prediction(args.checkpoint, index, loss, inputs, args.output, deadline=deadline))
        return
    if args.checkpoint:
        trainer = DynamicsTrainer.restore(args.checkpoint, index, provenance=provenance)
        require(trainer.formal, '工程 smoke checkpoint 不可升級為正式訓練')
    else:
        require(args.updates is not None, '需要依實測 throughput 固定 --updates')
        trainer = DynamicsTrainer(args.tokenizer, index, DynamicsTrainingConfig(updates=args.updates,
            microbatch=args.microbatch, accumulation=16//args.microbatch), formal=True,
            reconstruction=args.proof, provenance=provenance)
    deadline = min(deadline, time.monotonic() + trainer.config.max_seconds - trainer.elapsed_seconds)
    train(trainer, args.output, loss, inputs, deadline=deadline)


def run_budgeted(args):
    # ponytail: single-process ledger; use a file lock before allowing concurrent runs.
    path = Path('runs/dynamics-budget.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    state = load(path) if path.exists() else dict(schema='dsp-dynamics-budget/1', attempts=[])
    require(state['schema'] == 'dsp-dynamics-budget/1', '不相容的預算紀錄')
    now = time.time()
    for attempt in state['attempts']:
        if attempt['seconds'] is None:
            attempt.update(seconds=max(0., now-attempt['started']), status='interrupted')
    remaining = 57600 - sum(a['seconds'] for a in state['attempts'])
    require(remaining > 0, '第一階段 B 已用完 16 小時')
    if args.command == 'train':
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
    parser.add_argument('command', choices=['train', 'evaluate', 'score'])
    parser.add_argument('--catalog', default='docs/data-catalog.json')
    parser.add_argument('--protocol', default='protocols/evaluation-v2.json')
    parser.add_argument('--cache', default='data/torch-cache')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--updates', type=int)
    parser.add_argument('--microbatch', type=int, choices=[1, 2], default=2)
    parser.add_argument('--reconstruction-metrics', type=Path)
    parser.add_argument('--reconstruction-gate', type=Path)
    parser.add_argument('--metrics', type=Path)
    parser.add_argument('--judgments', type=Path)
    args = parser.parse_args()
    _, inputs, annotations, freeze = read_frozen_evaluation(args.catalog, args.protocol)
    if args.command == 'score':
        require(args.metrics is not None, '需要 --metrics')
        result = score_prediction(load(args.metrics), inputs, load(args.judgments) if args.judgments else None)
        atomic_save(args.output, result)
        emit(result)
        return
    provenance = dict(protocol_id=freeze['protocol_id'], data_freeze_id=freeze['artifact_id'],
                      evaluation_inputs_id=inputs['artifact_id'], annotations_id=annotations['artifact_id'])
    # Check the quality gate before allocating models or opening the full corpus.
    if args.checkpoint:
        value = read_dynamics_checkpoint(args.checkpoint)
        require(value['formal'], '工程 smoke checkpoint 不可用於正式執行')
        args.proof = value['reconstruction']
        tokenizer_hash = value['tokenizer_source']['checkpoint']['sha256']
        if args.command == 'train':
            args.microbatch = value['training_config']['microbatch']
    else:
        require(args.command == 'train' and args.tokenizer and args.reconstruction_metrics and args.reconstruction_gate,
                '需要 --tokenizer、--reconstruction-metrics 與 --reconstruction-gate；evaluate 需要 --checkpoint')
        args.proof = dict(metrics=load(args.reconstruction_metrics), inputs=inputs, annotations=annotations,
                          gate=load(args.reconstruction_gate))
        tokenizer_hash = file_info(args.tokenizer)['sha256']
    require_reconstruction(args.proof, tokenizer_hash, provenance)
    run_budgeted(args)


if __name__ == '__main__':
    main()
