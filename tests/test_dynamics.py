import copy
import random

import numpy as np
import pytest

torch = pytest.importorskip('torch')

from dsp_dreamer.actions import ACTION_CODEC
from dsp_dreamer.contract import InvalidRecording
from dsp_dreamer.dynamics import Dynamics, DynamicsConfig, shortcut_loss


def test_causal_action_conditioning_and_free_prediction():
    torch.set_num_threads(2)
    torch.manual_seed(25)
    model = Dynamics(DynamicsConfig(width=32, heads=4)).eval()
    latents = torch.rand(1, 3, 64, 32)
    actions = dict(binary=torch.zeros(1, 3, 21, dtype=torch.long),
                   mouse=torch.full((1, 3), 60), wheel=torch.ones(1, 3, dtype=torch.long))
    levels = torch.full((1, 3), .25)
    with torch.no_grad():
        expected = model(latents, actions, levels, .25)
        changed = {k: v.clone() for k, v in actions.items()}
        changed['binary'][:, -1, 20] = 1
        actual = model(latents, changed, levels, .25)
        torch.testing.assert_close(expected[:, :2], actual[:, :2], rtol=0, atol=0)
        assert not torch.equal(expected[:, -1], actual[:, -1])
        future = latents.clone()
        future[:, -1] = 0
        torch.testing.assert_close(expected[:, :2], model(future, actions, levels, .25)[:, :2], rtol=0, atol=0)
        future_actions = {k: v[:, :1].expand(-1, 15, *v.shape[2:]).clone() for k, v in actions.items()}
        generated = model.rollout(latents, actions, future_actions, seed=2203)
        future_actions['binary'][:, 4, 20] = 1
        altered = model.rollout(latents, actions, future_actions, seed=2203)
        assert generated.shape == (1, 15, 64, 32) and torch.isfinite(generated).all()
        torch.testing.assert_close(generated[:, :4], altered[:, :4], rtol=0, atol=0)
        assert not torch.equal(generated[:, 4], altered[:, 4])
        assert not torch.equal(generated[:, 14], altered[:, 14])
    model.train()
    loss, flow, bootstrap = shortcut_loss(model, latents, actions)
    loss.backward()
    assert flow > 0 and bootstrap > 0
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())
    with pytest.raises(InvalidRecording, match='動作'):
        model(latents, {**actions, 'binary': actions['binary'][..., :20]}, levels, .25)


def test_loader_training_resume_and_checkpoint_contract(tmp_path):
    from test_training_index import fixture, registry
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.tokenizer import TokenizerConfig
    from dsp_dreamer.tokenizer_training import ReconstructionLoss, TokenizerTrainer, TrainingConfig
    from dsp_dreamer.dynamics_training import DynamicsTrainer, DynamicsTrainingConfig, read_dynamics_checkpoint
    from dsp_dreamer.contract import atomic_save, file_info

    torch.set_num_threads(2)
    index = TrainingIndex([fixture(tmp_path / 'source', group='train')],
                          registry(('train', 'demonstration')), length=2)
    tokenizer = TokenizerTrainer(index, ReconstructionLoss('data/torch-cache'),
        TokenizerConfig(width=32, heads=4), TrainingConfig(updates=1, microbatch=1,
        accumulation=1, short_length=2, long_length=2), device='cpu')
    tokenizer.update()
    initial = tmp_path / 'tokenizer.pt'
    tokenizer.save(initial)
    frozen = copy.deepcopy(tokenizer.model.state_dict())
    config = DynamicsTrainingConfig(updates=4, microbatch=1, accumulation=1, short_length=2, long_length=3)
    trainer = DynamicsTrainer(initial, index, config, model_config=DynamicsConfig(width=32, heads=4), device='cpu')
    first = trainer.update()
    assert first['loss'] > 0 and first['flow'] > 0 and first['bootstrap'] > 0 and first['samples']
    checkpoint = tmp_path / 'step1.pt'
    trainer.save(checkpoint)
    expected_rng = random.random(), np.random.random(), torch.rand(3).tolist()
    expected = trainer.update()
    restored = DynamicsTrainer.restore(checkpoint, index, device='cpu')
    assert (random.random(), np.random.random(), torch.rand(3).tolist()) == expected_rng
    assert restored.update() == expected
    for key, value in trainer.model.state_dict().items():
        torch.testing.assert_close(value, restored.model.state_dict()[key], rtol=0, atol=0)
    for key, value in frozen.items():
        torch.testing.assert_close(value, restored.tokenizer.state_dict()[key], rtol=0, atol=0)
    assert all(p.grad is None and not p.requires_grad for p in restored.tokenizer.parameters())
    assert restored.samples(3)[0] == 3
    for width in (17, 18, 20):
        payload = torch.load(checkpoint, weights_only=True)
        payload['action_codec']['binary_width'] = width
        bad = tmp_path / f'legacy-{width}.pt'
        torch.save(payload, bad)
        atomic_save(str(bad) + '.json', dict(checkpoint=file_info(bad)))
        with pytest.raises(InvalidRecording, match='codec/catalog'):
            read_dynamics_checkpoint(bad)
    for field, value in [('controls', list(reversed(ACTION_CODEC['controls']))), ('mu', 6)]:
        payload = torch.load(checkpoint, weights_only=True)
        payload['action_codec'][field] = value
        bad = tmp_path / f'bad-{field}.pt'
        torch.save(payload, bad)
        atomic_save(str(bad) + '.json', dict(checkpoint=file_info(bad)))
        with pytest.raises(InvalidRecording, match='codec/catalog'):
            DynamicsTrainer.restore(bad, index, device='cpu')
    with pytest.raises(InvalidRecording, match='重建 gate'):
        DynamicsTrainer(initial, index, config, device='cpu', formal=True)


def test_prediction_gate_uses_paired_denominators_and_requires_reviews():
    from dsp_dreamer.evaluation_protocol import seal, CATEGORIES
    from dsp_dreamer.dynamics_evaluation import score_prediction

    selected = [dict(artifact_id='fixture', start=i, category=kind, task_id=i % 17,
        action_difference=dict(noop=True, shuffled=True, copy_last=True),
        key_states=[dict(type='cursor', expected='原位置')])
        for i, kind in enumerate(kind for kind in CATEGORIES for _ in range(50))]
    inputs = seal(dict(prediction=dict(selected=selected)))

    def report(samples):
        return seal(dict(evaluation_inputs_id=inputs['artifact_id'], checkpoint_sha256='abc',
            formal=True, samples=[dict(sample=s, conditions={c: {str(step): dict(mse=.1, lpips=.2,
                region_lpips=.8 if c == 'correct' else 1.) for step in (1, 5, 15)}
                for c in ('correct', 'noop', 'shuffled', 'copy_last')}) for s in samples]))

    metrics = report(selected)
    result = score_prediction(metrics, inputs)
    assert result['status'] == 'pending' and result['recognition']['total'] == 200
    judgments = dict(report_id=metrics['artifact_id'], checkpoint_sha256='abc',
        evaluation_inputs_id=inputs['artifact_id'], items=[dict(sample_id=f'P{i+1:03d}-K001',
            correct=True, reviewer='測試', evidence='fixture') for i in range(200)])
    assert score_prediction(metrics, inputs, judgments)['status'] == 'passed'
    # One excluded pair must exclude BOTH errors from that baseline's means.
    rows = copy.deepcopy(metrics['samples'])
    rows[0]['conditions']['noop']['5']['region_lpips'] = 0.
    rows[0]['conditions']['correct']['5']['region_lpips'] = 100.
    paired = seal({**{k: v for k, v in metrics.items() if k != 'artifact_id'}, 'samples': rows})
    counts = score_prediction(paired, inputs)['comparisons']['movement']['noop']
    assert counts['denominator'] == 49 and counts['zero_error'] == 1
    assert counts['correct_mean'] == pytest.approx(.8) and counts['relative_improvement'] == pytest.approx(.2)
    for row in rows[:50]:
        row['conditions']['noop']['5']['region_lpips'] = 0.
    zero = seal({**{k: v for k, v in metrics.items() if k != 'artifact_id'}, 'samples': rows})
    assert score_prediction(zero, inputs)['status'] == 'insufficient_evidence'
    judgments['items'][0]['correct'] = None
    assert score_prediction(metrics, inputs, judgments)['status'] == 'pending'
    judgments['items'] = judgments['items'][:130]
    assert score_prediction(metrics, inputs, judgments)['recognition']['pending'] == 71
    for item in judgments['items'][:20]:
        item['correct'] = False
    judgments['items'] += [dict(sample_id=f'P{i+1:03d}-K001', correct=True, reviewer='測試', evidence='fixture')
                           for i in range(130, 200)]
    assert score_prediction(metrics, inputs, judgments)['status'] == 'failed'
    smoke = seal({**{k: v for k, v in metrics.items() if k != 'artifact_id'}, 'formal': False})
    assert score_prediction(smoke, inputs)['status'] == 'engineering_only'
    assert score_prediction(report(selected[:4]), inputs)['status'] == 'pending'


def test_recording_to_free_prediction_exports_aligned_targets(tmp_path):
    from test_training_index import fixture, registry, FFMPEG
    from dsp_dreamer import Recording, compile_recording
    from dsp_dreamer.contract import load
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.evaluation_protocol import seal
    from dsp_dreamer.tokenizer import TokenizerConfig
    from dsp_dreamer.tokenizer_training import ReconstructionLoss, TokenizerTrainer, TrainingConfig
    from dsp_dreamer.dynamics_training import DynamicsTrainer, DynamicsTrainingConfig
    from dsp_dreamer.dynamics_evaluation import evaluate_prediction

    torch.set_num_threads(2)
    with Recording.synthetic(tmp_path / 'validation-source', FFMPEG) as recording:
        recording.metadata.update(progress_version=1, progress_tech_ids=[1001, 1002, 1003, 1004, 1005])
        recording.begin_attempt(dict(manifest_id='9', split_group_id='9', mecha_seed=1, camera_seed=2, policy_seed=3))
        for ticks in range(0, 8001, 50):
            recording.input(ticks, held=['B'] if 6400 <= ticks < 6700 else [],
                down=['B'] if ticks == 6400 else [], up=['B'] if ticks == 6700 else [], delta=[0, 0], wheel=0)
            if ticks == 8000:
                recording.end_episode(7999, 'timeout')
            rgba = np.zeros((360, 640, 4), dtype=np.uint8)
            rgba[..., 0] = ticks // 50
            recording.complete(recording.request(ticks, ticks, ticks), rgba)
    evidence = recording.publish(tmp_path / 'validation-evidence')
    validation = compile_recording(evidence, tmp_path / 'validation-dataset', FFMPEG)
    index = TrainingIndex([fixture(tmp_path / 'train-source', group='train'), validation],
                          registry(('train', 'demonstration'), ('9', 'demonstration')), length=64)
    artifact = next(s['artifact_id'] for s in index.report['sources'] if s['split'] == 'validation')
    sample = dict(artifact_id=artifact, start=0, category='ui', task_id=0, generation_seed=2203,
        shuffle_donor=dict(artifact_id=artifact, start=0), regions=[[0, 0, 64, 64]],
        key_states=[dict(type='cursor', expected='fixture')], action_difference=dict(noop=True, shuffled=False, copy_last=True))
    inputs = seal(dict(index_id=index.report['artifact_id'], prediction=dict(selected=[sample])))
    metric = ReconstructionLoss('data/torch-cache')
    tokenizer = TokenizerTrainer(index, metric, TokenizerConfig(width=32, heads=4),
        TrainingConfig(updates=1, microbatch=1, accumulation=1, short_length=2, long_length=2), device='cpu')
    initial = tmp_path / 'tokenizer.pt'
    tokenizer.save(initial)
    trainer = DynamicsTrainer(initial, index,
        DynamicsTrainingConfig(updates=1, microbatch=1, accumulation=1, short_length=2, long_length=2),
        model_config=DynamicsConfig(width=32, heads=4), device='cpu', provenance=dict(evaluation_inputs_id=inputs['artifact_id']))
    trainer.update()
    checkpoint = tmp_path / 'dynamics.pt'
    trainer.save(checkpoint)
    output = tmp_path / 'prediction'
    gate = evaluate_prediction(checkpoint, index, metric, inputs, output, device='cpu')
    assert gate['status'] == 'engineering_only' and gate['sequences'] == 1
    report = load(output / 'metrics.json')
    row = report['samples'][0]
    assert [s['next_observation_index'] for s in row['target_sources']] == [130, 138, 158]
    assert row['conditions']['correct'] == row['conditions']['shuffled']
    assert row['conditions']['correct']['5'] != row['conditions']['noop']['5']
    assert row['conditions']['copy_last']['1']['mse'] == pytest.approx((2 / 255)**2 / 3)
    assert len(list(output.glob('*.png'))) == 15
    assert load(output / 'judgments-template.json')['items'][0]['correct'] is None
