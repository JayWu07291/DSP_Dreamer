import copy

import numpy as np
import pytest

torch = pytest.importorskip('torch')

from dsp_dreamer.actions import ACTION_CODEC, decode_action
from dsp_dreamer.contract import InvalidRecording
from dsp_dreamer.dynamics import Dynamics, DynamicsConfig
from dsp_dreamer.agent import Agent, incoming_actions, mtp_loss, twohot, reward_expectation, policy_action


def actions(steps):
    return {k: torch.tensor(v).expand(1, steps, *(() if k != 'binary' else (21,))).clone()
            for k, v in ACTION_CODEC['noop'].items()}


def test_agent_causality_masks_twohot_and_legal_actions():
    torch.set_num_threads(2)
    torch.manual_seed(26)
    world = Dynamics(DynamicsConfig(width=32, heads=4)).eval()
    agent = Agent(world).eval()
    clean = torch.rand(1, 5, 64, 32)
    actual = actions(5)
    tasks = torch.nn.functional.one_hot(torch.tensor([[0, 0, 16, 0, 0]]), 17).float()
    levels = torch.full((1, 5), .1)
    past = incoming_actions(actual)
    with torch.no_grad():
        expected_world = world(clean, past, levels, .25)
        expected = agent(clean, past, tasks, levels)
        changed_tasks = tasks.roll(1, -1)
        changed = agent(clean, past, changed_tasks, levels)
        assert not torch.equal(expected['binary'], changed['binary'])
        torch.testing.assert_close(world(clean, past, levels, .25), expected_world, rtol=0, atol=0)
        actual['binary'][:, 3, 1] = 1
        changed = agent(clean, incoming_actions(actual), tasks, levels)
        torch.testing.assert_close(expected['binary'][:, :4], changed['binary'][:, :4], rtol=0, atol=0)
        assert not torch.equal(expected['binary'][:, 4], changed['binary'][:, 4])
        history = clean.clone()
        history[:, 0] = 0
        assert not torch.equal(expected['binary'][:, 2], agent(history, past, tasks, levels)['binary'][:, 2])
    valid = torch.tensor([[True, True, True, True, False]])
    actual['mouse'][:, 3] = 121  # Illegal targets are excluded before cross entropy.
    rewards = torch.tensor([[0., 1., 0., 0., float('nan')]])
    loss = mtp_loss(expected, actual, rewards, tasks, valid, valid)
    assert loss['counts'] == [3, 1, 0, 0, 0, 0, 0, 0, 0]
    assert torch.isfinite(loss['total'])
    empty = mtp_loss(expected, actual, rewards, tasks, valid, torch.zeros_like(valid))
    assert empty['total'].item() == 0 and empty['counts'] == [0] * 9
    values = torch.tensor([-1., 0., .5, 1., 10.])
    distribution = twohot(values)
    torch.testing.assert_close(distribution.sum(-1), torch.ones(5))
    torch.testing.assert_close(reward_expectation(distribution.log()), values, rtol=1e-5, atol=1e-6)
    assert reward_expectation(torch.zeros(255)).item() == 0
    logits = {k: v[0, 0, 0] for k, v in expected.items()}
    logits['binary'] = torch.ones(21)
    assert policy_action(logits, legal=False)['binary'] == [1] * 21
    decode_action(policy_action(logits))
    outputs = {k: torch.zeros(1, 10, 9, n, requires_grad=True) for k, n in
               dict(binary=21, mouse=121, wheel=3, reward=255).items()}
    same_task = torch.nn.functional.one_hot(torch.zeros(1, 10, dtype=torch.long), 17).float()
    mask = torch.ones(1, 10, dtype=torch.bool)
    losses = mtp_loss(outputs, actions(10), torch.zeros(1, 10), same_task, mask, mask)
    assert losses['counts'] == [10, 9, 8, 7, 6, 5, 4, 3, 2]
    losses['total'].backward()
    assert outputs['binary'].grad[0, 0, 8].abs().sum() > 0
    assert outputs['binary'].grad[0, 2, 8].abs().sum() == 0


def test_stage_one_loader_finetuning_resume_and_gate_rejection(tmp_path):
    from test_training_index import fixture, registry
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.tokenizer import TokenizerConfig
    from dsp_dreamer.tokenizer_training import ReconstructionLoss, TokenizerTrainer, TrainingConfig
    from dsp_dreamer.dynamics_training import DynamicsTrainer, DynamicsTrainingConfig, read_dynamics_checkpoint
    from dsp_dreamer.agent_training import AgentTrainer, AgentTrainingConfig, read_agent_checkpoint
    from dsp_dreamer.agent_evaluation import evaluate_agent, combine_gates, evaluation_rows, score_agent
    from dsp_dreamer.evaluation_protocol import seal
    from dsp_dreamer.contract import atomic_save, file_info, load

    index = TrainingIndex([fixture(tmp_path / 'train', group='train'), fixture(tmp_path / 'val', group='9')],
                          registry(('train', 'demonstration'), ('9', 'demonstration')), length=2)
    inputs = seal(dict(index_id=index.report['artifact_id'], prediction=dict(selected=[])))
    provenance = dict(evaluation_inputs_id=inputs['artifact_id'])
    token = TokenizerTrainer(index, ReconstructionLoss('data/torch-cache'), TokenizerConfig(width=32, heads=4),
        TrainingConfig(updates=1, microbatch=1, accumulation=1, short_length=2, long_length=2), device='cpu')
    token.update()
    token.save(tmp_path / 'token.pt')
    stage_one = DynamicsTrainer(tmp_path / 'token.pt', index, DynamicsTrainingConfig(updates=1, microbatch=1,
        accumulation=1, short_length=2, long_length=2), model_config=DynamicsConfig(width=32, heads=4), device='cpu')
    stage_one.update()
    source = tmp_path / 'world.pt'
    stage_one.save(source)
    cfg = AgentTrainingConfig(updates=4, microbatch=1, accumulation=2, short_length=2, long_length=3)
    trainer = AgentTrainer(source, index, cfg, device='cpu', provenance=provenance)
    for key, value in stage_one.model.state_dict().items():
        torch.testing.assert_close(value, trainer.model.dynamics.state_dict()[key], rtol=0, atol=0)
    assert trainer.samples(3)[0] == 3
    result = trainer.update()
    assert [s['pool'] for s in result['samples']] == ['uniform', 'relevant']
    assert result['dynamics'] > 0 and result['policy'] > 0 and result['reward'] > 0
    assert any(not torch.equal(v, trainer.model.dynamics.state_dict()[k]) for k, v in stage_one.model.state_dict().items())
    checkpoint = tmp_path / 'agent.pt'
    trainer.save(checkpoint)
    expected = trainer.update()
    restored = AgentTrainer.restore(checkpoint, index, device='cpu')
    assert restored.update() == expected
    for key, value in trainer.model.state_dict().items():
        torch.testing.assert_close(value, restored.model.state_dict()[key], rtol=0, atol=0)
    for key, value in token.model.state_dict().items():
        torch.testing.assert_close(value, restored.tokenizer.state_dict()[key], rtol=0, atol=0)
    assert all(p.grad is None and not p.requires_grad for p in restored.tokenizer.parameters())
    payload = read_agent_checkpoint(checkpoint)
    assert payload['status'] == 'engineering_only' and payload['stage_one_source']['checkpoint'] == file_info(source)
    assert read_dynamics_checkpoint(checkpoint)['model'].keys() == stage_one.model.state_dict().keys()
    with pytest.raises(InvalidRecording, match='第一階段|工程'):
        AgentTrainer(source, index, cfg, formal=True, device='cpu')
    with pytest.raises(InvalidRecording, match='第一階段|工程'):
        AgentTrainer(source, index, cfg, formal=True, device='cpu', prediction=dict(gate=dict(status='passed')))
    with pytest.raises(InvalidRecording, match='第一階段'):
        AgentTrainer(checkpoint, index, cfg, device='cpu')
    for field, value in [('controls', list(reversed(ACTION_CODEC['controls']))), ('mu', 6), ('binary_width', 20)]:
        invalid = copy.deepcopy(payload)
        invalid['action_codec'][field] = value
        invalid['model'] = {}  # Codec rejection must precede loading weights.
        path = tmp_path / f'bad-{field}.pt'
        torch.save(invalid, path)
        atomic_save(str(path) + '.json', dict(checkpoint=file_info(path)))
        with pytest.raises(InvalidRecording, match='codec/catalog'):
            AgentTrainer.restore(path, index, device='cpu')
    invalid = copy.deepcopy(payload)
    invalid.update(formal=True, status='passed')
    path = tmp_path / 'forged.pt'
    torch.save(invalid, path)
    atomic_save(str(path) + '.json', dict(checkpoint=file_info(path)))
    with pytest.raises(InvalidRecording, match='第一階段|工程'):
        read_agent_checkpoint(path)
    output = tmp_path / 'evaluation'
    gate = evaluate_agent(checkpoint, index, inputs, output, device='cpu')
    assert gate['status'] == 'engineering_only' and not gate['qualified']
    assert gate['reward']['n'] == 6 and gate['policy']['n'] == 0
    assert gate['dynamics']['status'] == 'pending'
    metrics, recipe = load(output / 'metrics.json'), load(output / 'recipe.json')
    assert len(evaluation_rows(index)) == 6
    predictions = metrics['transitions']
    with pytest.raises(InvalidRecording, match='transition'):
        score_agent(index, predictions + predictions[:1])
    with pytest.raises(InvalidRecording, match='transition'):
        score_agent(index, predictions[:-1])
    forged = seal({**{k: v for k, v in metrics.items() if k != 'artifact_id'}, 'formal': True})
    with pytest.raises(InvalidRecording, match='checkpoint 或 recipe'):
        combine_gates(forged, index, inputs, checkpoint_path=checkpoint, recipe=recipe)


def test_reward_and_policy_metrics_use_exact_paired_denominators():
    from dsp_dreamer.agent_evaluation import reward_metrics, policy_metrics
    rows = []
    for task in range(16):
        for i in range(10):
            # 4 TP, 1 FP, 1 FN: both precision and recall exactly .8.
            rows.append(dict(artifact_id='fixture', episode_id=str(task), model_index=i, segment=task,
                task_id=task, reward=int(i < 5), score=float(i < 4 or i == 5), non_active=i == 6))
    result = reward_metrics(rows)
    assert result['status'] == 'passed'
    task = result['per_task']['0']
    assert (task['tp'], task['fp'], task['fn'], task['tn'], task['n']) == (4, 1, 1, 4, 10)
    assert task['precision'] == task['recall'] == .8 and task['base_rate'] == .5
    assert task['pr_auc'] == pytest.approx(.74)  # .8*.8 + .2*.5; tied scores share a threshold.
    assert result['delay_diagnostic']['tp'] == 80
    rows[0]['score'] = 0.
    assert reward_metrics(rows)['status'] == 'failed'
    for row in rows[:10]:
        row['score'] = 0.
    assert reward_metrics(rows)['status'] == 'insufficient_evidence'
    for row in rows[:10]:
        row['reward'] = 0
    assert reward_metrics(rows)['per_task']['0']['pr_auc'] is None
    waiting = dict(rows[-1], task_id=16, model_index=100, reward=0, score=1., non_active=True)
    result = reward_metrics([*rows, waiting])
    assert result['waiting'] == dict(n=1, fp=1)
    assert result['non_active']['fp'] == 1

    baseline = dict(source_split='train', source_ids=['train'], tasks=[dict(task_id=t,
        mouse=dict(n=10, counts={'60': 10}, mode=60), wheel=dict(n=10, counts={'1': 10}, mode=1)) for t in range(17)])
    policy_rows = []
    for i in range(10):
        target = copy.deepcopy(ACTION_CODEC['noop'])
        target.update(mouse=61, wheel=2)
        target['binary'][1] = 1  # Digit1 participates in macro F1.
        predicted = copy.deepcopy(target)
        if i >= 5:
            predicted.update(mouse=60, wheel=1)
        probabilities = dict(binary=[.99 if b else .01 for b in predicted['binary']],
            mouse=[.99 if c == predicted['mouse'] else .01 / 120 for c in range(121)],
            wheel=[.99 if c == predicted['wheel'] else .005 for c in range(3)])
        policy_rows.append(dict(task_id=0, action=target, probabilities=probabilities))
    result = policy_metrics(policy_rows, baseline)
    assert result['status'] == 'passed' and result['binary_macro_f1'] == 1
    assert result['per_control']['Digit1']['n'] == 10
    assert result['per_control']['B']['status'] == 'missing_positives'
    assert result['mouse']['n'] == 10 and result['mouse']['correct'] == 5 and result['mouse']['baseline_correct'] == 0
    # Same paired subset; one baseline-positive class changes the comparison by exactly .1.
    baseline['tasks'][0]['mouse'].update(mode=61, counts={'61': 10})
    assert policy_metrics(policy_rows, baseline)['status'] == 'failed'
    baseline['tasks'][0]['mouse'].update(mode=None, n=0, counts={})
    assert policy_metrics(policy_rows, baseline)['status'] == 'insufficient_evidence'
    assert policy_metrics([], baseline)['status'] == 'insufficient_evidence'
    policy_rows[0]['probabilities']['binary'][1] = 0.
    result = policy_metrics(policy_rows, baseline)
    assert result['joint_nll'] == 'infinity' and result['nonfinite_nll'] == 1

    boundary = copy.deepcopy(policy_rows)
    baseline['tasks'][0]['mouse'].update(mode=61, n=10, counts={'61': 10})
    for i, row in enumerate(boundary):
        row['action']['binary'][1] = int(i < 5)
        row['probabilities']['binary'][1] = .9 if i < 3 or i >= 8 else .1
        row['action']['mouse'] = 61 if i < 5 else 62
        predicted = row['action']['mouse'] if i in (0, 1, 2, 5, 6, 7) else 60
        row['probabilities']['mouse'] = [.99 if c == predicted else .01/120 for c in range(121)]
    result = policy_metrics(boundary, baseline)
    assert result['status'] == 'passed' and result['binary_macro_f1'] == .6
    assert result['mouse']['correct'] == 6 and result['mouse']['baseline_correct'] == 5
    assert result['mouse']['improvement_pp'] == 10
    boundary[0]['probabilities']['binary'][1] = .1
    assert policy_metrics(boundary, baseline)['status'] == 'failed'


def test_continuous_validation_relevant_union_and_stage_two_dynamics(tmp_path):
    from test_training_index import fixture, registry, FFMPEG
    from dsp_dreamer import Recording, compile_recording
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.tokenizer import TokenizerConfig
    from dsp_dreamer.tokenizer_training import ReconstructionLoss, TokenizerTrainer, TrainingConfig
    from dsp_dreamer.dynamics_training import DynamicsTrainer, DynamicsTrainingConfig
    from dsp_dreamer.agent_training import AgentTrainer, AgentTrainingConfig, sequence_pools
    from dsp_dreamer.agent_evaluation import evaluation_rows, score_agent, train_baseline, combine_gates
    from dsp_dreamer.dynamics_evaluation import evaluate_prediction
    from dsp_dreamer.evaluation_protocol import seal
    from dsp_dreamer.contract import load, file_info

    with Recording.synthetic(tmp_path / 'source', FFMPEG) as recording:
        recording.metadata.update(progress_version=1, progress_tech_ids=[1001, 1002, 1003, 1004, 1005])
        recording.begin_attempt(dict(manifest_id='9', split_group_id='9', mecha_seed=1, camera_seed=2, policy_seed=3))
        recording.event(3260, 'progress_fact', episode_id=recording.episode['episode_id'], kind='research_queue',
                        tech_ids=[1001, 1002, 1003, 1004, 1005])  # Non-active only, scalar stays zero.
        for ticks in range(0, 8001, 50):
            active = ticks < 7000
            recording.input(ticks, held=['Digit1'] if active else [], down=['Digit1'] if ticks == 0 else [],
                up=['Digit1'] if ticks == 7000 else [], delta=[.2, 0] if active else [0, 0], wheel=1 if active else 0)
            if ticks == 8000:
                recording.end_episode(7999, 'timeout')
            recording.complete(recording.request(ticks, ticks, ticks), np.zeros((360, 640, 4), dtype=np.uint8))
    validation = compile_recording(recording.publish(tmp_path / 'evidence'), tmp_path / 'validation', FFMPEG)
    index = TrainingIndex([fixture(tmp_path / 'train', group='train'), validation, fixture(tmp_path / 'fault', group='9', fault=True)],
        registry(('train', 'demonstration'), ('9', 'demonstration')), length=2)
    artifact = next(s['artifact_id'] for s in index.report['sources'] if s['manifest_id'] == '9'
                    and s['episodes'][0]['validity_status'] == 'valid')
    selected = evaluation_rows(index)
    assert len(selected) == 80 and all(r['reward_eligible'] and r['policy_eligible'] for r in selected)
    assert sum(r['reward'] for r in selected) == 0 and sum(r['non_active'] for r in selected) == 1
    assert len(sequence_pools(index, 64, 'validation')['relevant']) == 17
    probabilities = dict(binary=[.9 if i == 1 else .1 for i in range(21)],
                         mouse=[1/121]*121, wheel=[1/3]*3)
    predictions = [dict(artifact_id=r['artifact_id'], model_index=r['model_index'], score=0., probabilities=probabilities)
                   for r in selected]
    scores = score_agent(index, predictions)
    assert scores['policy']['n'] == 80 and scores['policy']['per_control']['Digit1']['positives'] == 70
    assert scores['policy']['mouse']['n'] == scores['policy']['wheel']['n'] == 70
    assert scores['policy']['mouse']['baseline_correct'] == 0
    assert scores['reward']['status'] == 'insufficient_evidence'
    assert train_baseline(index)['tasks'][0]['mouse']['mode'] == 60
    wrong_baseline = train_baseline(index)
    wrong_baseline['tasks'][0]['mouse']['mode'] = 61
    with pytest.raises(InvalidRecording, match='baseline'):
        score_agent(index, predictions, baseline=wrong_baseline)

    sample = dict(artifact_id=artifact, start=0, category='ui', task_id=0, generation_seed=2203,
        shuffle_donor=dict(artifact_id=artifact, start=0), regions=[[0, 0, 64, 64]],
        key_states=[dict(type='cursor', expected='fixture')], action_difference=dict(noop=True, shuffled=False, copy_last=True))
    inputs = seal(dict(index_id=index.report['artifact_id'], prediction=dict(selected=[sample])))
    provenance = dict(evaluation_inputs_id=inputs['artifact_id'])
    metric = ReconstructionLoss('data/torch-cache')
    tokenizer = TokenizerTrainer(index, metric, TokenizerConfig(width=32, heads=4),
        TrainingConfig(updates=1, microbatch=1, accumulation=1, short_length=2, long_length=2), device='cpu')
    tokenizer.save(tmp_path / 'token.pt')
    world = DynamicsTrainer(tmp_path / 'token.pt', index, DynamicsTrainingConfig(updates=1, microbatch=1,
        accumulation=1, short_length=2, long_length=2), model_config=DynamicsConfig(width=32, heads=4), device='cpu', provenance=provenance)
    world.update()
    world.save(tmp_path / 'world.pt')
    trainer = AgentTrainer(tmp_path / 'world.pt', index, AgentTrainingConfig(updates=1, microbatch=1,
        accumulation=2, short_length=2, long_length=2), device='cpu', provenance=provenance)
    trainer.update()
    path = tmp_path / 'agent.pt'
    trainer.save(path)
    output = tmp_path / 'prediction'
    dynamics_gate = evaluate_prediction(path, index, metric, inputs, output, device='cpu')
    assert dynamics_gate['status'] == 'engineering_only' and dynamics_gate['sequences'] == 1
    proof = dict(metrics=load(output / 'metrics.json'), recipe=load(output / 'recipe.json'), gate=dynamics_gate)
    recipe = seal(dict(checkpoint_sha256=file_info(path)['sha256'], formal=False, **provenance))
    metrics = seal(dict(checkpoint_sha256=recipe['checkpoint_sha256'], recipe_id=recipe['artifact_id'],
                        index_id=index.report['artifact_id'], formal=False, **provenance, **scores))
    gate = combine_gates(metrics, index, inputs, checkpoint_path=path, recipe=recipe, prediction=proof)
    assert set(('reward', 'policy', 'dynamics')) <= gate.keys() and not gate['qualified']
    assert gate['dynamics'] == dynamics_gate
    proof['metrics'] = dict(proof['metrics'], checkpoint_sha256='different')
    with pytest.raises(InvalidRecording, match='不是此第二階段'):
        combine_gates(metrics, index, inputs, checkpoint_path=path, recipe=recipe, prediction=proof)
