import copy
import math
import subprocess
import sys

import numpy as np
import pytest

torch = pytest.importorskip('torch')

from dsp_dreamer.actions import ACTION_CODEC, decode_action, encode_action
from dsp_dreamer.contract import InvalidRecording, atomic_save, file_info, load
from dsp_dreamer.imagination import (ImaginationTrainer, ImaginationConfig, lambda_returns,
                                    imagination_loss, sample_action, policy_distributions)


def test_imagination_objective_and_action_contract():
    # Two rewards followed by a bootstrap value: 1 + .5*(.5*4 + .5*4.5), 2 + .5*5.
    rewards = torch.tensor([[1., 2.]])
    values = torch.tensor([[3., 4., 5.]])
    torch.testing.assert_close(lambda_returns(rewards, values, gamma=.5, lambda_=.5), torch.tensor([[3.125, 4.5]]))
    logits = dict(binary=torch.zeros(1, 3, 21, requires_grad=True),
                  mouse=torch.zeros(1, 3, 121, requires_grad=True), wheel=torch.zeros(1, 3, 3, requires_grad=True))
    actions = sample_action(logits)
    for t in range(3):
        action = {k: v[0, t].item() if k != 'binary' else v[0, t].tolist() for k, v in actions.items()}
        decoded = decode_action(action)
        assert encode_action(dict(binary=action['binary'], delta=decoded['observed_delta'], wheel=decoded['wheel'],
                                  ambiguous=False, unsupported=False, forbidden=False)) == action
    # Unequal positive/negative counts must still receive equal total PMPO weight.
    prior = {k: v.detach().clone() for k, v in logits.items()}
    value_logits = torch.zeros(1, 3, 255, requires_grad=True)
    result = imagination_loss(logits, prior, actions, value_logits, torch.tensor([[1., 2., -1.]]), torch.zeros(1, 3))
    assert result['positive'] == 2 and result['negative'] == 1
    assert result['kl'].item() == pytest.approx(0., abs=1e-6)
    assert result['policy'].item() == pytest.approx(0., abs=1e-6)
    result['total'].backward()
    assert value_logits.grad.abs().sum() > 0 and logits['mouse'].grad.abs().sum() > 0
    assert all(torch.isfinite(p.logits).all() for p in policy_distributions(prior).values() if hasattr(p, 'logits'))
    shifted = {k: v.detach().clone() for k, v in logits.items()}
    shifted['binary'][..., 0] = math.log(4)  # Escape: current p=.8, frozen prior p=.5.
    result = imagination_loss(shifted, prior, actions, value_logits, torch.ones(1, 3), torch.zeros(1, 3))
    assert result['kl'].item() == pytest.approx(.8 * math.log(1.6) + .2 * math.log(.4), abs=1e-6)
    assert result['negative'] == 0 and torch.isfinite(result['total'])


def test_stage_two_imagination_resume_export_and_rejections(tmp_path):
    from test_training_index import fixture, registry
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.tokenizer import TokenizerConfig
    from dsp_dreamer.tokenizer_training import ReconstructionLoss, TokenizerTrainer, TrainingConfig
    from dsp_dreamer.dynamics import DynamicsConfig
    from dsp_dreamer.dynamics_training import DynamicsTrainer, DynamicsTrainingConfig, read_dynamics_checkpoint
    from dsp_dreamer.agent_training import AgentTrainer, AgentTrainingConfig, read_agent_checkpoint
    from dsp_dreamer.agent_evaluation import evaluate_agent
    from dsp_dreamer.evaluation_protocol import seal
    from dsp_dreamer.imagination import export_candidate

    torch.set_num_threads(2)
    index = TrainingIndex([fixture(tmp_path / 'train', group='train'), fixture(tmp_path / 'val', group='9')],
                          registry(('train', 'demonstration'), ('9', 'demonstration')), length=2)
    inputs = seal(dict(index_id=index.report['artifact_id'], prediction=dict(selected=[])))
    provenance = dict(evaluation_inputs_id=inputs['artifact_id'])
    token = TokenizerTrainer(index, ReconstructionLoss('data/torch-cache'), TokenizerConfig(width=32, heads=4),
        TrainingConfig(updates=1, microbatch=1, accumulation=1, short_length=2, long_length=2), device='cpu')
    token.update()
    token.save(tmp_path / 'token.pt')
    world = DynamicsTrainer(tmp_path / 'token.pt', index, DynamicsTrainingConfig(updates=1, microbatch=1,
        accumulation=1, short_length=2, long_length=2), model_config=DynamicsConfig(width=32, heads=4), device='cpu')
    world.update()
    world.save(tmp_path / 'world.pt')
    agent = AgentTrainer(tmp_path / 'world.pt', index, AgentTrainingConfig(updates=1, microbatch=1,
        accumulation=2, short_length=2, long_length=2), device='cpu', provenance=provenance)
    agent.update()
    source = tmp_path / 'agent.pt'
    agent.save(source)
    cfg = ImaginationConfig(updates=3, microbatch=1, accumulation=2, short_length=2, long_length=3)
    trainer = ImaginationTrainer(source, index, cfg, device='cpu', provenance=provenance)
    for key, value in agent.model.state_dict().items():
        assert torch.equal(value, trainer.model.state_dict()[key])
    before = copy.deepcopy(trainer.model.state_dict())
    before_value = copy.deepcopy(trainer.value.state_dict())
    frozen = trainer.frozen_hashes()
    sample = next(iter(trainer.pools[2]))
    rollout = trainer.imagine([index.views[sample[0]].sequence(sample[1], 2)])
    assert rollout['features'].shape == (1, 16, 32)
    assert (rollout['tasks'] == rollout['tasks'][:, :1]).all()
    assert rollout['tasks'][0, 0] == index.views[sample[0]].rows[sample[1] + 1]['task_id']
    result = trainer.update()
    assert result['horizon'] == 15 and result['positive'] + result['negative'] == 30
    assert result['frozen'] == frozen == trainer.frozen_hashes()
    assert any(not torch.equal(v, trainer.value.state_dict()[k]) for k, v in before_value.items())
    assert all(p.grad is None for p in trainer.model.parameters() if not p.requires_grad)
    assert all(not p.requires_grad and p.grad is None for p in trainer.prior.parameters())
    assert any(not torch.equal(v, trainer.model.state_dict()[k]) for k, v in before.items() if k.startswith('heads.binary.'))
    assert all(torch.equal(v, trainer.model.state_dict()[k]) for k, v in before.items()
               if not k.startswith(('heads.binary.', 'heads.mouse.', 'heads.wheel.')))
    checkpoint = tmp_path / 'imagination.pt'
    trainer.save(checkpoint)
    expected = trainer.update()
    restored = ImaginationTrainer.restore(checkpoint, index, device='cpu')
    assert restored.update() == expected
    for key, value in trainer.model.state_dict().items():
        assert torch.equal(value, restored.model.state_dict()[key])
    for key, value in trainer.value.state_dict().items():
        assert torch.equal(value, restored.value.state_dict()[key])
    saved = read_agent_checkpoint(checkpoint)
    assert saved['schema'] == 'dsp-imagination-checkpoint/1'
    assert read_dynamics_checkpoint(checkpoint)['model'].keys() == world.model.state_dict().keys()
    gate = evaluate_agent(checkpoint, index, inputs, tmp_path / 'evaluation', device='cpu')
    assert gate['status'] == 'engineering_only' and not gate['qualified']
    assert gate['reward']['n'] == 6 and gate['dynamics']['status'] == 'pending'
    candidate = export_candidate(checkpoint, index, inputs, tmp_path / 'candidate',
        metrics=load(tmp_path / 'evaluation/metrics.json'), recipe=load(tmp_path / 'evaluation/recipe.json'))
    assert not candidate['qualified'] and candidate['status'] == 'engineering_only'
    assert candidate['action_codec'] == ACTION_CODEC and candidate['stage_two_source']['checkpoint'] == file_info(source)
    assert candidate['gate']['dynamics']['status'] == 'pending'
    read_agent_checkpoint(tmp_path / 'candidate/model.pt')
    with pytest.raises(InvalidRecording, match='第二階段|工程'):
        ImaginationTrainer(source, index, cfg, formal=True, device='cpu')
    with pytest.raises(InvalidRecording, match='第二階段'):
        ImaginationTrainer(checkpoint, index, cfg, device='cpu')
    with pytest.raises(InvalidRecording, match='第二階段'):
        AgentTrainer.restore(checkpoint, index, device='cpu')
    # CLI rejects engineering sources and recovery before opening the formal corpus or creating output.
    for arguments in (['--stage-two', str(source)], ['--checkpoint', str(checkpoint)]):
        output = tmp_path / 'forbidden-cli'
        process = subprocess.run([sys.executable, 'tools/train-agent.py', 'imagine', *arguments,
                                  '--output', str(output)], capture_output=True, text=True, encoding='utf-8')
        assert process.returncode != 0 and '工程 checkpoint' in process.stderr and not output.exists()
    for field, value in [('binary_width', 17), ('controls', list(reversed(ACTION_CODEC['controls']))), ('mu', 6)]:
        bad = copy.deepcopy(saved)
        bad['action_codec'][field] = value
        bad['model'] = {}
        path = tmp_path / f'bad-{field}.pt'
        torch.save(bad, path)
        atomic_save(str(path) + '.json', dict(checkpoint=file_info(path)))
        with pytest.raises(InvalidRecording, match='codec/catalog'):
            ImaginationTrainer.restore(path, index, device='cpu')
    bad = copy.deepcopy(saved)
    bad['imagination_config']['horizon'] = 14
    path = tmp_path / 'bad-recipe.pt'
    torch.save(bad, path)
    atomic_save(str(path) + '.json', dict(checkpoint=file_info(path)))
    with pytest.raises(InvalidRecording, match='配方'):
        ImaginationTrainer.restore(path, index, device='cpu')
    bad = copy.deepcopy(saved)
    next(iter(bad['prior'].values())).add_(1)
    path = tmp_path / 'bad-prior.pt'
    torch.save(bad, path)
    atomic_save(str(path) + '.json', dict(checkpoint=file_info(path)))
    with pytest.raises(InvalidRecording, match='凍結'):
        read_agent_checkpoint(path)
    before = copy.deepcopy(restored.model.state_dict())
    with pytest.raises(TimeoutError):
        restored.update(deadline=0.001)
    assert restored.step == 2 and all(torch.equal(v, restored.model.state_dict()[k]) for k, v in before.items())
    with torch.no_grad():
        next(restored.model.heads['reward'].parameters()).add_(1)
    with pytest.raises(InvalidRecording, match='凍結'):
        restored.save(tmp_path / 'corrupted.pt')
