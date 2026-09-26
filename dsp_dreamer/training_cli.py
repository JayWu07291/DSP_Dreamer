"""正式訓練入口。工程測試直接呼叫共用控制器並使用隔離帳本。"""
import argparse
from contextlib import nullcontext
from dataclasses import asdict, replace
from datetime import datetime
import gc
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any

import torch

from .agent_training import AgentTrainer, AgentTrainingConfig, read_agent_checkpoint, require_stage_one
from .agent_evaluation import evaluate_agent, combine_gates
from .contract import atomic_save, file_info, load, require
from .dynamics_training import DynamicsTrainer, DynamicsTrainingConfig, read_dynamics_checkpoint, require_reconstruction
from .dynamics_evaluation import evaluate_prediction, score_prediction
from .imagination import ImaginationTrainer, ImaginationConfig, export_candidate
from .tokenizer import TokenizerConfig
from .tokenizer_training import TokenizerTrainer, TrainingConfig, ReconstructionLoss, read_checkpoint
from .tokenizer_evaluation import (open_frozen_corpus, read_frozen_evaluation,
                                    evaluate_reconstruction, score_reconstruction)
from .training_control import TrainingBudget, benchmark, import_existing_usage, run_training
from .frozen_sources import COMPATIBILITY
from .training_settings import CONFIG_TYPES, DEFAULT_CONFIG, read_settings
from .training_log import TrainingLog
from .dynamics import DynamicsConfig


def prediction_proof(directory, gate, inputs):
    require(directory is not None and gate is not None, '需要 --prediction-dir 與 --prediction-gate')
    return dict(metrics=load(directory / 'metrics.json'), recipe=load(directory / 'recipe.json'),
                gate=load(gate), inputs=inputs)


def checkpoint_stage(path):
    # 先核對完整 codec，再讀任何模型權重。
    value = read_dynamics_checkpoint(path)
    require(value['formal'], '工程 checkpoint 不可用於正式執行')
    return 'third' if value['schema'] == 'dsp-imagination-checkpoint/1' else 'second'


def evaluate_stage(stage, path, index, metric, inputs, annotations, output, *, full, deadline, device='cuda'):
    if stage == 'A':
        return evaluate_reconstruction(path, index, metric, inputs, annotations, output,
            device=device, limit=200 if full else 8, deadline=deadline)
    prediction = evaluate_prediction(path, index, metric, inputs, output / 'prediction',
        device=device, limit=200 if full else 4, deadline=deadline)
    if stage == 'B':
        return prediction
    agent = evaluate_agent(path, index, inputs, output / 'agent', device=device, deadline=deadline,
                           limit=None if full else 32)
    if not full:
        return dict(status='pending', qualified=False, dynamics=prediction, agent=agent)
    gate = combine_gates(load(output / 'agent/metrics.json'), index, inputs, checkpoint_path=path,
        recipe=load(output / 'agent/recipe.json'), prediction=dict(metrics=load(output / 'prediction/metrics.json'),
            recipe=load(output / 'prediction/recipe.json'), inputs=inputs, gate=prediction))
    atomic_save(output / 'gate.json', gate)
    return gate


def main(stage=None):
    parser = argparse.ArgumentParser(description=__doc__)
    if stage is None:
        parser.add_argument('stage', choices=['A', 'B', 'second', 'third'])
    parser.add_argument('command', choices=['run', 'show-config', 'benchmark', 'train', 'imagine', 'evaluate', 'predict',
                                           'score', 'score-prediction', 'export'])
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--restart', action='store_true', help='run only: archive ledger and reset this stage before fresh training')
    parser.add_argument('--verify-data', action='store_true', help='recheck all RGB bytes instead of trusting immutable corpus')
    parser.add_argument('--catalog', default='docs/data-catalog.json')
    parser.add_argument('--protocol', default='protocols/evaluation-v2.json')
    parser.add_argument('--cache', default='data/torch-cache')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--init-from', type=Path, help='A run/benchmark: initialize learned weights and loss RMS')
    parser.add_argument('--tokenizer', type=Path)
    parser.add_argument('--stage-one', type=Path)
    parser.add_argument('--stage-two', type=Path)
    parser.add_argument('--reconstruction-metrics', type=Path)
    parser.add_argument('--reconstruction-gate', type=Path)
    parser.add_argument('--prediction-dir', type=Path)
    parser.add_argument('--prediction-gate', type=Path)
    parser.add_argument('--agent-gate', type=Path)
    parser.add_argument('--metrics', type=Path)
    parser.add_argument('--judgments', type=Path)
    parser.add_argument('--updates', type=int, help='本輪更新目標；有時間上限時只能縮減測速換算值')
    parser.add_argument('--microbatch', type=int, choices=[1, 2])
    args = parser.parse_args()
    settings = read_settings(args.config)
    stage = stage or args.stage
    if stage == 'agent':
        stage = checkpoint_stage(args.checkpoint) if args.checkpoint else (
            'third' if args.command == 'imagine' or args.stage_two else 'second')
    if args.command == 'show-config':
        print(json.dumps(settings, ensure_ascii=False, indent=2, allow_nan=False))
        return
    args.output = args.output or Path('runs') / (stage + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    require(not args.output.exists(), f'Output already exists: {args.output}')
    require(not args.restart or args.command == 'run' and args.checkpoint is None, '--restart needs a fresh run')
    require(args.init_from is None or stage == 'A' and args.command in ('run', 'benchmark') and args.checkpoint is None,
            '--init-from 僅供 A run/benchmark，恢復中斷請用 train --checkpoint')
    require(args.updates is None or args.updates > 0, '更新次數必須大於零')
    if args.verify_data:
        settings['runtime']['verify_rgb'] = True
    with TrainingLog(str(args.output) + '.logs', settings) as log:
        log.emit('invocation', stage=stage, command=args.command, config_file=file_info(args.config), output=str(args.output))
        execute(args, stage, settings, log)


def execute(args, stage, settings, log):
    saved = {}
    if args.init_from:
        initial = read_checkpoint(args.init_from)
        require(initial['step'] > 0 and all(s['source_kind'] == 'live' for s in initial['sources'])
                and initial['model_config'] == settings['tokenizer'], '初始化需要相同架構的真實資料 checkpoint')
        del initial
    require(args.command != 'imagine' or stage == 'third', 'imagine 僅供第三階段')
    require(args.command != 'export' or stage == 'third', 'export 僅供第三階段')
    require(stage != 'A' or args.command not in ('predict', 'score-prediction'), 'A 階段沒有 dynamics prediction')
    if args.command == 'imagine':
        args.command = 'train'
    if args.checkpoint:
        saved = read_checkpoint(args.checkpoint) if stage == 'A' else read_dynamics_checkpoint(args.checkpoint)
        require(all(s['source_kind'] == 'live' for s in saved['sources']) and saved.get('formal', True),
                '工程 checkpoint 不可用於正式執行')
        expected = {'A': 'dsp-tokenizer-checkpoint/1', 'B': 'dsp-dynamics-checkpoint/1',
                    'second': 'dsp-agent-checkpoint/1', 'third': 'dsp-imagination-checkpoint/1'}
        require(saved['schema'] == expected[stage], 'Checkpoint 階段不同')
        args.microbatch = args.microbatch or saved['training_config']['microbatch']
    args.microbatch = args.microbatch or settings['stages'][stage]['microbatch']
    if args.stage_two:
        require(read_agent_checkpoint(args.stage_two)['formal'], '工程 checkpoint 不可用於正式執行')
    require(args.command != 'benchmark' or args.checkpoint is None, '測速不能恢復訓練 checkpoint')
    require(args.command in ('benchmark', 'run') or args.updates is None, '更新上限由 benchmark 固定，恢復時不能重設')
    # 所有 GPU 工作與失敗均在同一把鎖、同一份不可回退的累計帳本下。
    root = Path(__file__).resolve().parents[1]
    with TrainingBudget(root / 'runs/training-budget.json') as budget:
        import_existing_usage(budget, root)
        if args.restart:
            budget.restart_stage(stage, log.directory / 'previous-budget.json')
            log.emit('budget_restarted', stage=stage, path=str(log.directory / 'previous-budget.json'))
        budget.configure_limits(dict(preflight=settings['runtime']['preflight_seconds'],
            **{k: v['max_seconds'] for k, v in settings['stages'].items()}))
        if args.command == 'run':
            require(args.checkpoint is None, 'run starts fresh; use train --checkpoint to resume')
            require(budget.progress(stage)['plan'] is None, '已有訓練計畫；新實驗需 --restart，恢復用 train --checkpoint')
            output = args.output
            output.mkdir(parents=True, exist_ok=False)
            args.command, args.output = 'benchmark', output / 'plan.json'
            corpus = execute_phase(args, stage, settings, log, budget, saved)
            gc.collect()
            torch.cuda.empty_cache()
            args.command, args.output = 'train', output / 'training'
            execute_phase(args, stage, settings, log, budget, saved, corpus=corpus)
        else:
            execute_phase(args, stage, settings, log, budget, saved)


def execute_phase(args, stage, settings, log, budget, saved, *, corpus=None):
    root = Path(__file__).resolve().parents[1]
    if args.command in ('score', 'export'):
        require(args.metrics is not None and args.checkpoint is not None, '需要 --metrics 與 --checkpoint')
        require(stage in ('A', 'B') or args.prediction_dir is not None, '需要 --prediction-dir')
        budget.require_evaluation(stage, args.checkpoint, saved.get('control'), args.metrics,
            prediction_metrics=args.prediction_dir / 'metrics.json' if stage in ('second', 'third') else None)
    if args.command == 'evaluate':
        require(args.checkpoint is not None and saved.get('control') is not None
                and saved['control']['budget_id'] == budget.state['id'], '評估需要本帳本 checkpoint')
    if args.command in ('train', 'benchmark') and stage != 'A':
        source = (saved[dict(B='tokenizer_source', second='stage_one_source', third='stage_two_source')[stage]]['path']
                  if args.checkpoint else dict(B=args.tokenizer, second=args.stage_one, third=args.stage_two)[stage])
        budget.require_upstream(stage, source)
    scoring = args.command in ('score', 'score-prediction', 'export')
    # 已完成 GPU 評估後的人工判讀／CPU 重算另計，不解鎖任何額外 GPU 工作。
    with (nullcontext(budget) if scoring else budget.attempt(
            'preflight' if args.command == 'benchmark' else stage, args.command,
            microbatch=args.microbatch, target=stage)):
        _, inputs, annotations, freeze = read_frozen_evaluation(args.catalog, args.protocol)
        provenance = {k: freeze[k] for k in ('protocol_id', 'evaluation_inputs_id', 'annotations_id')}
        provenance['data_freeze_id'] = freeze['artifact_id']
        proof = None
        if stage == 'B' and not args.checkpoint:
            require(args.tokenizer and args.reconstruction_metrics and args.reconstruction_gate,
                    '需要 tokenizer 與完整重建 gate 證據')
            proof = dict(metrics=load(args.reconstruction_metrics), gate=load(args.reconstruction_gate),
                         inputs=inputs, annotations=annotations)
            require_reconstruction(proof, file_info(args.tokenizer)['sha256'], provenance)
        elif stage == 'second' and not args.checkpoint:
            require(args.stage_one is not None, '需要 --stage-one')
            proof = prediction_proof(args.prediction_dir, args.prediction_gate, inputs)
            require_stage_one(args.stage_one, proof, provenance)
        gpu = args.command in ('benchmark', 'train', 'evaluate', 'predict')
        if gpu:
            require(torch.cuda.is_available() and torch.cuda.is_bf16_supported(), '正式執行需要 BF16 CUDA')
            tasks = subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq DSPGAME.exe', '/FO', 'CSV'], text=True)
            require('DSPGAME.exe' not in tasks, 'GPU 訓練／評估前請關閉 DSP')
            torch.set_num_threads(settings['runtime']['num_threads'])
            torch.cuda.set_per_process_memory_fraction(settings['runtime']['cuda_memory_fraction'])
            torch.use_deterministic_algorithms(True)
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        if corpus is None:
            started = time.monotonic()
            log.emit('data_loading', verify_rgb=settings['runtime']['verify_rgb'])
            corpus = open_frozen_corpus(args.catalog, args.protocol, verify_rgb=settings['runtime']['verify_rgb'])
            log.emit('data_loaded', seconds=time.monotonic() - started, verify_rgb=settings['runtime']['verify_rgb'])
        index, inputs, annotations, provenance = corpus
        provenance = dict(provenance)
        recipe = dict(settings['stages'][stage])
        recipe['microbatch'] = args.microbatch
        recipe['accumulation'] = 16 // args.microbatch
        provenance['validation_schedule'] = dict(seconds=settings['runtime']['validation_seconds'],
                                                 updates=settings['runtime']['validation_updates'])
        provenance['implementation'] = {str(p): file_info(p) for p in sorted(Path('dsp_dreamer').glob('*.py'))}
        provenance['implementation'][str(COMPATIBILITY.relative_to(root))] = file_info(COMPATIBILITY)
        if args.command in ('score', 'score-prediction', 'export'):
            require(args.metrics is not None and args.checkpoint is not None, '需要 --metrics 與 --checkpoint')
            if stage == 'A':
                result = score_reconstruction(load(args.metrics), inputs, annotations,
                                              load(args.judgments) if args.judgments else None)
                require(load(args.metrics)['checkpoint_sha256'] == file_info(args.checkpoint)['sha256'],
                        '評分 checkpoint 不符')
            elif stage == 'B' or args.command == 'score-prediction':
                result = score_prediction(load(args.metrics), inputs, load(args.judgments) if args.judgments else None,
                    checkpoint_path=args.checkpoint, recipe=load(args.metrics.parent / 'recipe.json'))
            else:
                proof = prediction_proof(args.prediction_dir, args.prediction_gate, inputs)
                if args.command == 'export':
                    result = export_candidate(args.checkpoint, index, inputs, args.output,
                        metrics=load(args.metrics), recipe=load(args.metrics.parent / 'recipe.json'), prediction=proof)
                else:
                    result = combine_gates(load(args.metrics), index, inputs, checkpoint_path=args.checkpoint,
                        recipe=load(args.metrics.parent / 'recipe.json'), prediction=proof)
            if args.command != 'export':
                atomic_save(args.output, result)
            if args.command == 'score':
                progress = budget.progress(stage)
                progress['gate'] = dict(result, qualified=result['status'] == 'passed',
                    checkpoint_sha256=file_info(args.checkpoint)['sha256'])
                if progress['gate']['qualified']:
                    progress['candidate'] = dict(path=str(args.checkpoint.resolve()), file=file_info(args.checkpoint))
                budget.save()
        else:
            metric = ReconstructionLoss(args.cache, 'cuda')

            def evaluate(path, output, full, deadline):
                gate = evaluate_stage(stage, path, index, metric, inputs, annotations, output,
                                      full=full, deadline=deadline)
                if stage == 'A':
                    rows = load(output / 'metrics.json')['frames']
                    log.emit('reconstruction_diagnostics', step=load(str(path) + '.json')['step'],
                        images=len(rows), source_spatial_std=sum(r['source_spatial_std'] for r in rows) / len(rows),
                        reconstruction_spatial_std=sum(r['reconstruction_spatial_std'] for r in rows) / len(rows),
                        path=str(output / 'human-review.md'))
                return gate

            if args.command in ('evaluate', 'predict'):
                require(args.checkpoint is not None, '評估需要 --checkpoint')
                result = (evaluate_prediction(args.checkpoint, index, metric, inputs, args.output, deadline=budget.deadline)
                          if args.command == 'predict' else evaluate(args.checkpoint, args.output, True, budget.deadline))
                if args.command == 'evaluate':
                    budget.record_evaluation(stage, args.checkpoint, args.output, result)
            else:
                plan = budget.progress(stage)['plan']
                require(args.command == 'benchmark' or plan is not None, '需先執行 benchmark')
                config_type = CONFIG_TYPES[stage]
                config = config_type(**dict(recipe, updates=math.lcm(4, recipe['long_every']) if args.command == 'benchmark' else plan['updates']))
                log.emit('resolved_training_config', stage=stage, command=args.command, training=asdict(config),
                         model=settings['tokenizer'] if stage == 'A' else settings['dynamics'])
                if args.checkpoint:
                    trainer_type: Any = dict(A=TokenizerTrainer, B=DynamicsTrainer,
                                        second=AgentTrainer, third=ImaginationTrainer)[stage]
                    extra = dict(loss=metric) if stage == 'A' else {}
                    trainer = trainer_type.restore(args.checkpoint, index, provenance=provenance, **extra)
                    unchanged = set(asdict(config)) - {'updates', 'microbatch', 'accumulation'}
                    require(all(getattr(config, k) == getattr(trainer.config, k) for k in unchanged),
                            '恢復時設定已改變；新配方需 run --restart')
                    if args.microbatch != trainer.config.microbatch:
                        require(args.microbatch == 1 and plan['identity']['training']['microbatch'] == 1,
                                '只允許 OOM 後已重新測速的 1/16 配方')
                        trainer.config = replace(trainer.config, microbatch=1, accumulation=16)
                elif stage == 'A':
                    trainer = TokenizerTrainer(index, metric, TokenizerConfig(**settings['tokenizer']), config, provenance=provenance)
                    if args.init_from:
                        trainer.initialize_from(args.init_from)
                        log.emit('initialized_from', stage=stage, **trainer.initialization)
                elif stage == 'B':
                    trainer = DynamicsTrainer(args.tokenizer, index, config, model_config=DynamicsConfig(**settings['dynamics']), formal=True,
                                              reconstruction=proof, provenance=provenance)
                elif stage == 'second':
                    trainer = AgentTrainer(args.stage_one, index, config, formal=True,
                                           prediction=proof, provenance=provenance)
                else:
                    require(args.stage_two and args.metrics and args.agent_gate, '需要合格第二階段來源及 gate')
                    proof = dict(metrics=load(args.metrics), recipe=load(args.metrics.parent / 'recipe.json'),
                        prediction=prediction_proof(args.prediction_dir, args.prediction_gate, inputs), gate=load(args.agent_gate))
                    trainer = ImaginationTrainer(args.stage_two, index, config, formal=True,
                        inputs=inputs, proof=proof, provenance=provenance)
                expected_model = settings['tokenizer'] if stage == 'A' else settings['dynamics']
                actual_model = trainer.model.dynamics.config if hasattr(trainer.model, 'dynamics') else trainer.model.config
                require(asdict(actual_model) == expected_model, '模型設定與 checkpoint 不符；新架構需從 A 重新訓練')
                result = (benchmark(trainer, budget, stage, args.output, update_limit=args.updates or recipe['updates'],
                                    fraction=settings['runtime']['update_fraction'], event=log.emit)
                          if args.command == 'benchmark' else run_training(trainer, budget, stage, args.output, evaluate,
                            validation_seconds=settings['runtime']['validation_seconds'],
                            validation_updates=settings['runtime']['validation_updates'], event=log.emit))
        log.emit('command_completed', stage=stage, command=args.command, status=result.get('status'),
                 path=str(args.output), planned_updates=result.get('updates'))
    return corpus
