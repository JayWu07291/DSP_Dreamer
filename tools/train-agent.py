"""第二／三階段訓練、恢復、候選匯出與共用離線 gate。"""
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

from dsp_dreamer.agent_training import AgentTrainer, AgentTrainingConfig, read_agent_checkpoint, require_stage_one
from dsp_dreamer.agent_evaluation import evaluate_agent, combine_gates
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.dynamics_evaluation import evaluate_prediction, score_prediction
from dsp_dreamer.evaluation_protocol import seal
from dsp_dreamer.imagination import ImaginationTrainer, ImaginationConfig, export_candidate
from dsp_dreamer.tokenizer_evaluation import open_frozen_corpus, read_frozen_evaluation
from dsp_dreamer.tokenizer_training import ReconstructionLoss


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def prediction_proof(directory, gate_path, inputs):
    require(directory is not None and gate_path is not None, '需要 --prediction-dir 與 --prediction-gate')
    return dict(metrics=load(directory / 'metrics.json'), recipe=load(directory / 'recipe.json'),
                gate=load(gate_path), inputs=inputs)


def train(trainer, output, inputs, metric):
    output.mkdir(parents=True, exist_ok=False)
    source = (dict(stage_two_source=trainer.stage_two_source) if isinstance(trainer, ImaginationTrainer)
              else dict(stage_one_source=trainer.stage_one_source))
    atomic_save(output / 'recipe.json', seal(dict(model=asdict(trainer.model.dynamics.config),
        training=asdict(trainer.config), **source,
        provenance=trainer.provenance, index_id=trainer.index.report['artifact_id'])))
    initial_elapsed = trainer.elapsed_seconds
    started = last_validation = time.monotonic()
    deadline = started + trainer.config.max_seconds - initial_elapsed
    status = 'completed'
    try:
        while trainer.step < trainer.config.updates:
            if time.monotonic() >= deadline:
                raise TimeoutError('已達本階段時數上限')
            trainer.update(deadline=deadline)
            emit(trainer.history[-1])
            trainer.elapsed_seconds = initial_elapsed + time.monotonic() - started
            if time.monotonic() - last_validation >= 1800:
                path = output / f'step-{trainer.step}.pt'
                trainer.save(path)
                with torch.random.fork_rng(devices=[torch.cuda.current_device()]):
                    evaluate_prediction(path, trainer.index, metric, inputs, output / f'validation-{trainer.step}',
                                        limit=4, deadline=deadline)
                last_validation = time.monotonic()
    except TimeoutError:
        status = 'budget_exhausted'
    except BaseException:
        status = 'failed'
        raise
    finally:
        trainer.elapsed_seconds = initial_elapsed + time.monotonic() - started
        checkpoint = output / f'final-{trainer.step}.pt'
        trainer.save(checkpoint)
        atomic_save(output / 'run.json', seal(dict(schema='dsp-agent-run/1', status=status,
            quality_status='pending', checkpoint=str(checkpoint), checkpoint_sha256=file_info(checkpoint)['sha256'],
            updates=trainer.step, seconds=trainer.elapsed_seconds, **source,
            provenance=trainer.provenance, history=trainer.history)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['train', 'imagine', 'evaluate', 'predict', 'score-prediction', 'score', 'export'])
    parser.add_argument('--catalog', default='docs/data-catalog.json')
    parser.add_argument('--protocol', default='protocols/evaluation-v2.json')
    parser.add_argument('--cache', default='data/torch-cache')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage-one', type=Path)
    parser.add_argument('--stage-two', type=Path)
    parser.add_argument('--agent-gate', type=Path)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--prediction-dir', type=Path)
    parser.add_argument('--prediction-gate', type=Path)
    parser.add_argument('--metrics', type=Path)
    parser.add_argument('--judgments', type=Path)
    parser.add_argument('--updates', type=int)
    parser.add_argument('--microbatch', type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    # Reject engineering artifacts before reading the formal corpus or allocating CUDA models.
    if args.checkpoint:
        saved = read_agent_checkpoint(args.checkpoint)
        require(saved['formal'], '工程 checkpoint 不可用於正式執行')
    else:
        require(args.command == 'train' and args.stage_one is not None
                or args.command == 'imagine' and args.stage_two is not None, '需提供 --checkpoint 或對應的來源階段')
        if args.stage_two:
            require(read_agent_checkpoint(args.stage_two)['formal'], '工程 checkpoint 不可用於正式執行')
    _, inputs, _, freeze = read_frozen_evaluation(args.catalog, args.protocol)
    provenance = dict(protocol_id=freeze['protocol_id'], data_freeze_id=freeze['artifact_id'],
                      evaluation_inputs_id=inputs['artifact_id'], annotations_id=freeze['annotations_id'])
    if not args.checkpoint and args.command == 'train':
        proof = prediction_proof(args.prediction_dir, args.prediction_gate, inputs)
        require_stage_one(args.stage_one, proof, provenance)
    index, inputs, _, provenance = open_frozen_corpus(args.catalog, args.protocol)
    provenance['implementation'] = {str(p): file_info(p) for p in [Path(__file__), *[
        Path('dsp_dreamer') / name for name in ('agent.py', 'agent_training.py', 'agent_evaluation.py',
        'imagination.py', 'actions.py', 'dynamics.py', 'dynamics_training.py', 'dynamics_evaluation.py')]]}
    if args.command == 'score-prediction':
        require(args.metrics is not None, '需要 --metrics')
        gate = score_prediction(load(args.metrics), inputs, load(args.judgments) if args.judgments else None,
                                checkpoint_path=args.checkpoint, recipe=load(args.metrics.parent / 'recipe.json'))
        atomic_save(args.output, gate)
        emit(gate)
        return
    if args.command in ('score', 'export'):
        require(args.metrics is not None, '需要 --metrics')
        proof = prediction_proof(args.prediction_dir, args.prediction_gate, inputs)
        if args.command == 'export':
            gate = export_candidate(args.checkpoint, index, inputs, args.output, metrics=load(args.metrics),
                                    recipe=load(args.metrics.parent / 'recipe.json'), prediction=proof)
        else:
            gate = combine_gates(load(args.metrics), index, inputs, checkpoint_path=args.checkpoint,
                                 recipe=load(args.metrics.parent / 'recipe.json'), prediction=proof)
            atomic_save(args.output, gate)
        emit(gate)
        return
    require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), '正式執行需要 BF16 CUDA')
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    if args.command == 'evaluate':
        emit(evaluate_agent(args.checkpoint, index, inputs, args.output))
    elif args.command == 'predict':
        emit(evaluate_prediction(args.checkpoint, index, ReconstructionLoss(args.cache, 'cuda'), inputs, args.output))
    else:
        tasks = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq DSPGAME.exe', '/FO', 'CSV'], text=True)
        require('DSPGAME.exe' not in tasks, '訓練前請關閉 DSP')
        if args.checkpoint:
            trainer = (ImaginationTrainer.restore(args.checkpoint, index, provenance=provenance) if args.command == 'imagine'
                       else AgentTrainer.restore(args.checkpoint, index, provenance=provenance))
        elif args.command == 'imagine':
            require(args.updates is not None and args.metrics is not None and args.agent_gate is not None,
                    '需要固定 --updates、第二階段 --metrics 與 --agent-gate')
            proof = dict(metrics=load(args.metrics), recipe=load(args.metrics.parent / 'recipe.json'),
                         prediction=prediction_proof(args.prediction_dir, args.prediction_gate, inputs), gate=load(args.agent_gate))
            trainer = ImaginationTrainer(args.stage_two, index, ImaginationConfig(updates=args.updates,
                microbatch=args.microbatch, accumulation=16//args.microbatch), formal=True,
                inputs=inputs, proof=proof, provenance=provenance)
        else:
            require(args.updates is not None, '需要依完整 loader/loss 測速固定 --updates')
            trainer = AgentTrainer(args.stage_one, index, AgentTrainingConfig(updates=args.updates,
                microbatch=args.microbatch, accumulation=16//args.microbatch), formal=True,
                prediction=proof, provenance=provenance)
        train(trainer, args.output, inputs, ReconstructionLoss(args.cache, 'cuda'))


if __name__ == '__main__':
    main()
