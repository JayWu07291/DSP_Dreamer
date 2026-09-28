"""Exploratory live-data B is explicit, resumable, and never a formal candidate."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest
import torch

from dsp_dreamer.contract import InvalidRecording, atomic_save, file_info, load
from dsp_dreamer.training_control import TrainingBudget, STAGE_SECONDS
from dsp_dreamer.training_settings import read_settings, DEFAULT_CONFIG


def test_exploratory_recipe_cli_and_shared_lock(tmp_path):
    from dsp_dreamer.agent_training import AgentTrainingConfig
    with pytest.raises(InvalidRecording, match='有限時間'):
        AgentTrainingConfig(updates=1, max_seconds=None)
    config = DEFAULT_CONFIG.parent / 'training_config_B_exploratory.py'
    with pytest.raises(InvalidRecording, match='B 超過'):
        read_settings(config)
    settings = read_settings(config, exploratory_b=True)
    assert settings['stages']['B']['updates'] == 100
    assert settings['stages']['B']['max_seconds'] is None
    command = [sys.executable, '-X', 'utf8', 'tools/train.py', 'B', 'show-config', '--config', str(config)]
    result = subprocess.run(command + ['--exploratory'], capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0 and 'B-unqualified-tokenizer/1' in result.stdout
    for args in (command, command + ['--prediction-limit', '8'], command + ['--exploratory', '--prediction-limit', '0']):
        assert subprocess.run(args, capture_output=True).returncode != 0
    with TrainingBudget(tmp_path / 'formal.json') as formal:
        before = file_info(formal.path)
        with pytest.raises(OSError):
            with TrainingBudget(tmp_path / 'explore.json', formal=False, lock_path=formal.lock_path):
                pass
        assert file_info(formal.path) == before
        with pytest.raises(InvalidRecording):
            formal.configure_limits(dict(STAGE_SECONDS, B=None))
    with TrainingBudget(tmp_path / 'explore.json', formal=False, lock_path=tmp_path / 'formal.lock') as budget:
        budget.configure_limits(dict(STAGE_SECONDS, B=None))
        assert budget.remaining('B') == float('inf')
    assert file_info(tmp_path / 'formal.json') == before


def test_exploratory_trainer_freezes_tokenizer_resumes_and_cannot_qualify(tmp_path):
    from test_training_index import fixture, registry
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.tokenizer import TokenizerConfig
    from dsp_dreamer.tokenizer_training import TokenizerTrainer, TrainingConfig, ReconstructionLoss
    from dsp_dreamer.dynamics import DynamicsConfig
    from dsp_dreamer.dynamics_training import DynamicsTrainer, DynamicsTrainingConfig, read_dynamics_checkpoint, load_tokenizer
    from dsp_dreamer.agent_training import require_stage_one

    torch.set_num_threads(2)
    index = TrainingIndex([fixture(tmp_path / 'source', group='train')], registry(('train', 'demonstration')), length=2)
    # Simulate the live-source boundary with isolated fixture data, never the real corpus.
    index.report['coverage_gate_passed'] = True
    index.report['sources'][0]['source_kind'] = 'live'
    implementation = {str(p): file_info(p) for p in Path('dsp_dreamer').glob('*.py')}
    provenance = dict(protocol_id='p', data_freeze_id='d', evaluation_inputs_id='e', annotations_id='a',
                      implementation=implementation)
    old_provenance = {**provenance, 'implementation': {**implementation, 'retired-training-helper.py': {'bytes': 1, 'sha256': 'old'}}}
    tokenizer = TokenizerTrainer(index, ReconstructionLoss('data/torch-cache'),
        TokenizerConfig(width=32, heads=4, encoder_blocks=4, decoder_blocks=4),
        TrainingConfig(updates=1, microbatch=1, accumulation=1, short_length=2, long_length=2),
        device='cpu', provenance=old_provenance)
    tokenizer.update()
    initial = tmp_path / 'tokenizer.pt'
    tokenizer.save(initial)
    with pytest.raises(InvalidRecording, match='實作 checksum'):
        load_tokenizer(initial)  # Formal/synthetic callers retain the full implementation check.
    model = DynamicsConfig(width=32, heads=4, blocks=4, kv_heads=2)
    config = DynamicsTrainingConfig(updates=2, microbatch=1, accumulation=16, short_length=2, long_length=2, max_seconds=None)
    provenance = {**provenance, 'experiment': 'B-unqualified-tokenizer/1', 'prediction_limit': 8}
    with pytest.raises(InvalidRecording, match='合成 fixtures'):
        DynamicsTrainer(initial, index, config, model_config=model, device='cpu')
    with pytest.raises(InvalidRecording, match='重建 gate'):
        DynamicsTrainer(initial, index, replace(config, max_seconds=57600), model_config=model, device='cpu', formal=True)
    trainer = DynamicsTrainer(initial, index, config, model_config=model, device='cpu', exploratory=True, provenance=provenance)
    trainer.elapsed_seconds = 100000
    assert trainer.update()['step'] == 1
    checkpoint = tmp_path / 'B.pt'
    trainer.save(checkpoint)
    expected = trainer.update()
    restored = DynamicsTrainer.restore(checkpoint, index, device='cpu', provenance=provenance)
    assert restored.exploratory and not restored.formal
    assert restored.update() == expected
    for key, value in tokenizer.model.state_dict().items():
        assert torch.equal(restored.tokenizer.state_dict()[key], value)
    assert all(not p.requires_grad and p.grad is None for p in restored.tokenizer.parameters())
    with pytest.raises(InvalidRecording, match='工程 checkpoint 不可升級'):
        require_stage_one(checkpoint, {}, provenance)
    forged = read_dynamics_checkpoint(checkpoint)
    forged['formal'] = True
    fake = tmp_path / 'forged.pt'
    torch.save(forged, fake)
    atomic_save(str(fake) + '.json', dict(checkpoint=file_info(fake)))
    with pytest.raises(InvalidRecording, match='不可宣告正式'):
        read_dynamics_checkpoint(fake)
    bad = torch.load(initial, weights_only=True)
    key = next(p for p in implementation if Path(p).name == 'tokenizer.py')
    bad['provenance']['implementation'][key] = {'bytes': 1, 'sha256': 'changed-model'}
    altered = tmp_path / 'changed-tokenizer.pt'
    torch.save(bad, altered)
    atomic_save(str(altered) + '.json', dict(checkpoint=file_info(altered)))
    with pytest.raises(InvalidRecording, match='模型實作 checksum'):
        load_tokenizer(altered, model_only=True)
