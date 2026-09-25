import pytest
import copy
import random
import time

import numpy as np
torch = pytest.importorskip('torch')

from dsp_dreamer.contract import InvalidRecording, atomic_save, file_info, load


def test_budget_failure_retry_and_throughput_plan(tmp_path):
    from dsp_dreamer.training_control import TrainingBudget, plan_updates

    now = [100.]
    clock = lambda: now[0]
    path = tmp_path / 'budget.json'
    with TrainingBudget(path, formal=False, clock=clock, wall_clock=clock) as budget:
        assert budget.remaining('A') == 14400
        with pytest.raises(RuntimeError):
            with budget.attempt('A', 'train', microbatch=2):
                now[0] += 100
                raise RuntimeError('中斷')
        assert budget.remaining('A') == 14300
    with TrainingBudget(path, formal=False, clock=clock, wall_clock=clock) as budget:
        assert budget.remaining('A') == 14300
        assert budget.state['attempts'][0]['status'] == 'failed'
        assert plan_updates(14300, [10., 10., 10., 30.]) == 858
        with pytest.raises(InvalidRecording):
            plan_updates(100, [1., float('nan'), 1., 3.])
        with budget.attempt('A', 'train', microbatch=2):
            now[0] += 14300
        with pytest.raises(InvalidRecording, match='預算'):
            with budget.attempt('A', 'train', microbatch=2):
                pass


def test_budget_import_crash_oom_gates_and_fallback(tmp_path):
    from dsp_dreamer.training_control import TrainingBudget, STAGE_SECONDS, select_candidate
    assert sum(STAGE_SECONDS.values()) == 115200
    now = [100.]
    clock = lambda: now[0]
    history = tmp_path / 'history.json'
    atomic_save(history, dict(attempts=[dict(seconds=300., status='failed')]))
    path = tmp_path / 'budget.json'
    with TrainingBudget(path, clock=clock, wall_clock=clock) as budget:
        for _ in range(2):
            budget.import_history(history, 'A', load(history)['attempts'])
        assert budget.remaining('A') == 14100
        with pytest.raises(InvalidRecording, match='OOM'):
            with budget.attempt('preflight', 'benchmark', microbatch=1, target='A'):
                pass
        with pytest.raises(torch.cuda.OutOfMemoryError):
            with budget.attempt('preflight', 'benchmark', microbatch=2, target='A'):
                now[0] += 7
                raise torch.cuda.OutOfMemoryError('2/8')
        assert budget.remaining('preflight') == 7193
        with pytest.raises(InvalidRecording, match='OOM'):
            with budget.attempt('preflight', 'benchmark', microbatch=2, target='A'):
                pass
        with pytest.raises(torch.cuda.OutOfMemoryError):
            with budget.attempt('preflight', 'benchmark', microbatch=1, target='A'):
                now[0] += 3
                raise torch.cuda.OutOfMemoryError('1/16')
        with pytest.raises(InvalidRecording, match='停止'):
            with budget.attempt('preflight', 'benchmark', microbatch=1, target='A'):
                pass
        for status in ('failed', 'pending', 'insufficient_evidence', 'engineering_only'):
            budget.progress('second')['gate'] = dict(status=status, qualified=False)
            with pytest.raises(InvalidRecording, match='前階段 gate'):
                budget.require_upstream('third', history)
            assert select_candidate(budget, third_improved=True) is None
        second = budget.progress('second')
        second['candidate'] = dict(path=str(history), file=file_info(history))
        second['gate'] = dict(status='passed', qualified=True, checkpoint_sha256=file_info(history)['sha256'])
        budget.require_upstream('third', history)
        for status in ('pending', 'failed'):
            budget.progress('third')['gate'] = dict(status=status, qualified=False)
            assert select_candidate(budget, third_improved=True) == second['candidate']
        assert select_candidate(budget) == second['candidate']
        with budget.attempt('second', 'predict'):
            now[0] += 1
        assert select_candidate(budget) == second['candidate']
        directory = tmp_path / 'evaluation'
        directory.mkdir()
        metrics = directory / 'metrics.json'
        atomic_save(metrics, dict(status='fixture'))
        budget.record_evaluation('second', history, directory, second['gate'])
        control = dict(budget_id=budget.state['id'], stage='second')
        budget.require_evaluation('second', history, control, metrics)
        for wrong in (None, dict(control, budget_id='another-budget'), dict(control, stage='third')):
            with pytest.raises(InvalidRecording, match='本帳本'):
                budget.require_evaluation('second', history, wrong, metrics)
        with pytest.raises(InvalidRecording, match='metrics'):
            budget.require_evaluation('second', history, control, metrics, prediction_metrics=tmp_path / 'untracked.json')
        gate = dict(second['gate'])
        with budget.attempt('second', 'evaluate'):
            now[0] += budget.remaining('second')
            budget.record_evaluation('second', history, directory, gate)
        # 純評分仍可登錄，沒有新增 GPU 額度。
        budget.require_evaluation('second', history, control, metrics)
        assert budget.remaining('second') == 0
        budget.invalidate('second', 'failed')
        with pytest.raises(InvalidRecording, match='本帳本'):
            budget.require_evaluation('second', history, control, metrics)
    # 模擬程序強制終止留下的 durable running 記錄，重啟保守計費且只計一次。
    state = load(path)
    state['attempts'].append(dict(stage='B', target='B', command='train', microbatch=2,
        started=100., seconds=10., reserved=57600., status='running'))
    path.write_text(__import__('json').dumps(state), encoding='utf-8')
    now[0] = 150.
    for _ in range(2):
        with TrainingBudget(path, clock=clock, wall_clock=clock) as budget:
            assert budget.remaining('B') == 57550
            assert budget.state['attempts'][-1]['status'] == 'interrupted'


def test_controlled_pipeline_uses_real_trainers_and_recovers(tmp_path):
    from test_training_index import fixture, registry, FFMPEG
    from dsp_dreamer import Recording, compile_recording
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.tokenizer import TokenizerConfig
    from dsp_dreamer.tokenizer_training import ReconstructionLoss, TokenizerTrainer, TrainingConfig, read_checkpoint
    from dsp_dreamer.dynamics import DynamicsConfig
    from dsp_dreamer.dynamics_training import DynamicsTrainer, DynamicsTrainingConfig
    from dsp_dreamer.agent_training import AgentTrainer, AgentTrainingConfig
    from dsp_dreamer.imagination import ImaginationTrainer, ImaginationConfig
    from dsp_dreamer.evaluation_protocol import seal
    from dsp_dreamer.training_control import TrainingBudget, benchmark, run_training, select_candidate
    from dsp_dreamer.training_cli import evaluate_stage

    torch.set_num_threads(2)
    with Recording.synthetic(tmp_path / 'val-source', FFMPEG) as recording:
        recording.metadata.update(progress_version=1, progress_tech_ids=[1001, 1002, 1003, 1004, 1005])
        recording.begin_attempt(dict(manifest_id='9', split_group_id='9', mecha_seed=1, camera_seed=2, policy_seed=3))
        recording.event(3260, 'progress_fact', episode_id=recording.episode['episode_id'], kind='research_queue',
                        tech_ids=[1001, 1002, 1003, 1004, 1005])
        for ticks in range(0, 8001, 50):
            recording.input(ticks, held=['Digit1'], down=['Digit1'] if ticks == 0 else [], up=[], delta=[.2, 0], wheel=1)
            if ticks == 8000:
                recording.end_episode(7999, 'timeout')
            recording.complete(recording.request(ticks, ticks, ticks), np.zeros((360, 640, 4), dtype=np.uint8))
    val = compile_recording(recording.publish(tmp_path / 'evidence'), tmp_path / 'validation', FFMPEG)
    index = TrainingIndex([fixture(tmp_path / 'train', group='train'), val],
                          registry(('train', 'demonstration'), ('9', 'demonstration')), length=2)
    artifact = next(s['artifact_id'] for s in index.report['sources'] if s['split'] == 'validation')
    row = index.views[artifact].rows[0]
    sample = dict(artifact_id=artifact, start=0, category='ui', task_id=0, generation_seed=2203,
        shuffle_donor=dict(artifact_id=artifact, start=0), regions=[[0, 0, 64, 64]],
        key_states=[dict(type='cursor', expected='fixture')], action_difference=dict(noop=True, shuffled=False, copy_last=True))
    inputs = seal(dict(index_id=index.report['artifact_id'], prediction=dict(selected=[sample]),
        reconstruction=dict(selected=[dict(artifact_id=artifact, model_index=0,
                                           observation_index=row['start'], task_id=0)])))
    annotations = seal(dict(items=[], ui_regions=[]))
    provenance = dict(evaluation_inputs_id=inputs['artifact_id'], annotations_id=annotations['artifact_id'])
    metric = ReconstructionLoss('data/torch-cache')
    cfg = dict(updates=4, microbatch=1, accumulation=2, short_length=2, long_length=3)
    paths = {}

    def create(stage):
        if stage == 'A':
            return TokenizerTrainer(index, metric, TokenizerConfig(width=32, heads=4), TrainingConfig(**cfg),
                                    device='cpu', provenance=provenance)
        if stage == 'B':
            return DynamicsTrainer(paths['A'], index, DynamicsTrainingConfig(**cfg),
                model_config=DynamicsConfig(width=32, heads=4), device='cpu', provenance=provenance)
        if stage == 'second':
            return AgentTrainer(paths['B'], index, AgentTrainingConfig(**cfg), device='cpu', provenance=provenance)
        return ImaginationTrainer(paths['second'], index, ImaginationConfig(**cfg), device='cpu', provenance=provenance)

    offset = [0.]
    clock = lambda: time.monotonic() + offset[0]
    with TrainingBudget(tmp_path / 'budget.json', formal=False, clock=clock) as budget:
        for stage in ('A', 'B', 'second', 'third'):
            with budget.attempt('preflight', 'benchmark', target=stage):
                plan = benchmark(create(stage), budget, stage, tmp_path / f'{stage}-plan.json', update_limit=2)
            assert plan['status'] == 'engineering_only' and plan['updates'] == 2
            assert plan['lengths'] == [2, 2, 2, 3]
            trainer = create(stage)
            periodic = []

            def evaluate(path, output, full, deadline):
                random.random()
                np.random.random()
                torch.rand(3)
                periodic.append(full)
                result = evaluate_stage(stage, path, index, metric, inputs, annotations, output,
                                        full=full, deadline=deadline, device='cpu')
                if stage == 'A' and not full and len(periodic) == 1:
                    raise KeyboardInterrupt('validation 後中斷')
                return result

            if stage == 'A':
                with pytest.raises(KeyboardInterrupt):
                    with budget.attempt(stage, 'train'):
                        offset[0] += 1801
                        run_training(trainer, budget, stage, tmp_path / 'interrupted', evaluate)
                saved = budget.progress(stage)['latest']['path']
                payload = read_checkpoint(saved)
                assert payload['control']['budget_id'] == budget.state['id']
                assert payload['control']['budget']['attempts'][-1]['seconds'] >= 1801
                expected_rng = (random.random(), np.random.random(), torch.rand(3).tolist())
                trainer = TokenizerTrainer.restore(saved, index, metric, device='cpu')
                assert (random.random(), np.random.random(), torch.rand(3).tolist()) == expected_rng
                assert budget.remaining(stage) < 12599
            with budget.attempt(stage, 'train'):
                if stage != 'A':
                    offset[0] += 1801
                report = run_training(trainer, budget, stage, tmp_path / stage, evaluate)
            assert report['updates'] == report['charged_updates'] == 2
            assert report['quality_status'] == 'engineering_only' and not report['gate']['qualified']
            assert periodic[-1] is True and False in periodic
            assert (tmp_path / stage / 'gate').exists()
            assert len(trainer.optimizer.state) > 0
            if stage in ('second', 'third'):
                partial_recipe = load(tmp_path / stage / 'validation-0/agent/recipe.json')
                from dsp_dreamer.agent_evaluation import combine_gates
                with pytest.raises(InvalidRecording, match='小樣本'):
                    combine_gates({}, index, inputs, checkpoint_path=report['checkpoint'], recipe=partial_recipe)
            assert trainer.optimizer.defaults['betas'] == (.9, .999) and trainer.optimizer.defaults['eps'] == 1e-8
            for group in trainer.optimizer.param_groups:
                assert group['lr'] == pytest.approx(group.get('peak_lr', 1e-4) * .1)
            paths[stage] = report['checkpoint']
            restore = type(trainer).restore
            extra = dict(loss=metric) if stage == 'A' else {}
            restored = restore(paths[stage], index, device='cpu', **extra)
            assert restored.control['plan'] == plan and restored.step == 2
            for key, value in trainer.model.state_dict().items():
                assert torch.equal(value, restored.model.state_dict()[key])
            if stage == 'third':
                assert all(torch.equal(value, restored.value.state_dict()[key]) for key, value in trainer.value.state_dict().items())
        assert select_candidate(budget, third_improved=True) is None
    # v4 正常恢復；所有舊寬度及完整 codec 錯配在模型權重讀入前拒絕。
    original = torch.load(paths['A'], weights_only=True)
    for change in (dict(binary_width=17), dict(binary_width=18), dict(binary_width=20),
                   dict(controls=original['action_codec']['controls'][::-1]), dict(mu=999)):
        value = copy.deepcopy(original)
        value['action_codec'].update(change)
        value['model'] = {}  # 不能先嘗試載入這份權重。
        path = tmp_path / f'bad-{len(list(tmp_path.glob("bad-*.pt")))}.pt'
        torch.save(value, path)
        atomic_save(str(path) + '.json', dict(checkpoint=file_info(path)))
        with pytest.raises(InvalidRecording, match='[Cc]odec|[Aa]ction|動作'):
            TokenizerTrainer.restore(path, index, metric, device='cpu')


def test_real_update_failures_keep_last_complete_checkpoint_and_time_cap(tmp_path):
    from test_training_index import fixture, registry
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.tokenizer import TokenizerConfig
    from dsp_dreamer.tokenizer_training import ReconstructionLoss, TokenizerTrainer, TrainingConfig, read_checkpoint
    from dsp_dreamer.training_control import TrainingBudget, benchmark, run_training
    torch.set_num_threads(2)
    index = TrainingIndex([fixture(tmp_path / 'train', group='train')], registry(('train', 'demonstration')), length=2)
    metric = ReconstructionLoss('data/torch-cache')
    config = TrainingConfig(updates=4, microbatch=1, accumulation=1, short_length=2, long_length=3)

    def create():
        return TokenizerTrainer(index, metric, TokenizerConfig(width=32, heads=4), config, device='cpu')

    offset = [0.]
    clock = lambda: time.monotonic() + offset[0]
    with TrainingBudget(tmp_path / 'budget.json', formal=False, clock=clock) as budget:
        with budget.attempt('preflight', 'benchmark', target='A'):
            benchmark(create(), budget, 'A', tmp_path / 'plan.json', update_limit=3)
        trainer = create()
        parameter = next(metric.metric.parameters())
        before = parameter.detach().clone()
        parameter.data.fill_(float('nan'))
        with pytest.raises(InvalidRecording, match='非有限 loss'):
            with budget.attempt('A', 'train'):
                run_training(trainer, budget, 'A', tmp_path / 'nan', None)
        parameter.data.copy_(before)
        saved = budget.progress('A')['latest']['path']
        assert saved.endswith('start-0.pt') and read_checkpoint(saved)['step'] == 0
        assert budget.progress('A')['updates'] == 1 and budget.progress('A')['gate']['status'] == 'failed'
        trainer = TokenizerTrainer.restore(saved, index, metric, device='cpu')
        for view in index.views.values():
            for row in view.rows:
                row['valid'] = False
        with pytest.raises(InvalidRecording):
            with budget.attempt('A', 'train'):
                run_training(trainer, budget, 'A', tmp_path / 'bad-data', None)
        assert budget.progress('A')['updates'] == 2
        saved = budget.progress('A')['latest']['path']
        for view in index.views.values():
            for row in view.rows:
                row['valid'] = True
        trainer = TokenizerTrainer.restore(saved, index, metric, device='cpu')
        with budget.attempt('A', 'train'):
            offset[0] += budget.remaining('A') + 1
            report = run_training(trainer, budget, 'A', tmp_path / 'timeout', None)
        assert report['status'] == 'budget_exhausted' and report['updates'] == 0
        assert report['charged_updates'] == 2 and report['gate'] == dict(status='pending', qualified=False)
        assert read_checkpoint(report['checkpoint'])['step'] == 0
        assert load(tmp_path / 'timeout/run.json')['status'] == 'budget_exhausted'
        assert budget.remaining('A') == 0 and budget.state['attempts'][-1]['status'] == 'budget_exhausted'
