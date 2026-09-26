import copy
import json
from pathlib import Path

import pytest

from dsp_dreamer.contract import InvalidRecording, load
from dsp_dreamer.training_settings import DEFAULT_CONFIG, read_settings


def test_editable_recipe_reaches_optimizer_and_checkpoint(tmp_path):
    import torch
    from test_training_index import fixture, registry
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.tokenizer import TokenizerConfig
    from dsp_dreamer.tokenizer_training import TrainingConfig, TokenizerTrainer, ReconstructionLoss

    settings = read_settings()
    assert set(settings['stages']) == {'A', 'B', 'second', 'third'}
    custom = tmp_path / 'config.py'
    custom.write_text(DEFAULT_CONFIG.read_text(encoding='utf-8') + "\nSTAGES['A'].update(learning_rate=0.0003, weight_decay=0.02, mask_max_probability=0., warmup_fraction=0.5, mse_weight=0.5, lpips_weight=0.1)\n", encoding='utf-8')
    values = read_settings(custom)['stages']['A']
    values.update(updates=4, microbatch=1, accumulation=1, short_length=2, long_length=2)
    torch.set_num_threads(2)
    path = fixture(tmp_path / 'source', group='train')
    index = TrainingIndex([path], registry(('train', 'demonstration')), length=2)
    metric = ReconstructionLoss('data/torch-cache')
    trainer = TokenizerTrainer(index, metric, TokenizerConfig(width=32, heads=4, encoder_blocks=4, decoder_blocks=4), TrainingConfig(**values), device='cpu')
    result = trainer.update()
    assert result['learning_rate'] == .00015
    assert result['loss'] == pytest.approx(.5 * result['mse'] + .1 * result['lpips'])
    assert trainer.optimizer.param_groups[0]['weight_decay'] == .02
    checkpoint = tmp_path / 'saved.pt'
    trainer.save(checkpoint)
    expected = trainer.update()
    restored = TokenizerTrainer.restore(checkpoint, index, metric, device='cpu')
    assert restored.config == trainer.config
    assert restored.update() == expected
    # Architecture knobs are accepted for a NEW run, with the 64x32 interface intact.
    with custom.open('a', encoding='utf-8') as stream:
        stream.write("\nTOKENIZER.update(width=128, heads=4, encoder_blocks=4, decoder_blocks=4)\n")
    adjusted = read_settings(custom)
    assert adjusted['tokenizer']['width'] == 128 and adjusted['tokenizer']['encoder_blocks'] == 4
    with custom.open('a', encoding='utf-8') as stream:
        stream.write(f"\nTOKENIZER.update(context={settings['stages']['A']['long_length']})\n")
    with pytest.raises(InvalidRecording, match='長片段'):
        read_settings(custom)


def test_update_limited_A_requires_a_target_and_accepts_no_deadline(tmp_path):
    custom = tmp_path / 'updates.py'
    original = DEFAULT_CONFIG.read_text(encoding='utf-8')
    custom.write_text(original + "\nSTAGES['A'].update(max_seconds=None, updates=2000)\n", encoding='utf-8')
    values = read_settings(custom)['stages']['A']
    assert values['updates'] == 2000 and values['max_seconds'] is None
    custom.write_text(original + "\nSTAGES['A'].update(max_seconds=None, updates=None)\n", encoding='utf-8')
    with pytest.raises(InvalidRecording, match='更新次數'):
        read_settings(custom)


def test_immutable_loader_skips_rgb_but_rejects_metadata_changes(tmp_path):
    from test_training_index import fixture, registry
    from dsp_dreamer.training_index import TrainingIndex
    path = fixture(tmp_path / 'source', group='train', pixel_value=1)
    index = TrainingIndex([path], registry(('train', 'demonstration')), length=2)
    report = tmp_path / 'index.json'
    index.save(report)
    fast = TrainingIndex.open(report, [path], verify_rgb=False)
    assert fast.report == index.report
    chunk = next(p for p in (path / 'observations.zarr/rgb/c').rglob('*') if p.is_file())
    chunk.write_bytes(b'changed RGB')
    assert TrainingIndex.open(report, [path], verify_rgb=False).report == index.report
    with pytest.raises(InvalidRecording, match='checksum'):
        TrainingIndex.open(report, [path])
    with (path / 'dataset.json').open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(InvalidRecording, match='checksum'):
        TrainingIndex.open(report, [path], verify_rgb=False)


def test_restart_archives_budget_and_never_overwrites_history(tmp_path):
    from dsp_dreamer.training_control import TrainingBudget, STAGE_SECONDS
    now = [0.]
    with TrainingBudget(tmp_path / 'budget.json', formal=False, clock=lambda: now[0]) as budget:
        with budget.attempt('A', 'train'):
            now[0] = 100.
        with budget.attempt('preflight', 'benchmark', target='A'):
            now[0] = 150.
        budget.progress('A')['updates'] = 20
        old = copy.deepcopy(budget.state)
        archive = tmp_path / 'old.json'
        budget.restart_stage('A', archive)
        assert load(archive) == old
        assert budget.remaining('A') == 14400 and budget.remaining('preflight') == 7200
        assert budget.progress('A')['updates'] == 0 and budget.progress('A')['plan'] is None
        budget.configure_limits(dict(STAGE_SECONDS, A=28800))
        assert budget.remaining('A') == 28800
        with pytest.raises(InvalidRecording):
            budget.restart_stage('A', archive)
        assert load(archive) == old
        with budget.attempt('B', 'train'):
            pass
        with pytest.raises(InvalidRecording, match='下游'):
            budget.restart_stage('A', tmp_path / 'new.json')


def test_append_log_captures_progress_and_traceback(tmp_path):
    from dsp_dreamer.training_log import TrainingLog
    directory = tmp_path / 'log'
    with pytest.raises(RuntimeError):
        with TrainingLog(directory, {'stage': 'A'}) as log:
            log.emit('update', step=1, loss=.5, learning_rate=.0001)
            log.emit('checkpoint', path='saved.pt', step=1)
            print('visible progress', flush=True)
            raise RuntimeError('training failed')
    rows = [json.loads(row) for row in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [r['event'] for r in rows] == ['started', 'update', 'checkpoint', 'failed']
    assert rows[1]['loss'] == .5 and rows[1]['learning_rate'] == .0001
    assert 'Traceback' in (directory / 'console.log').read_text(encoding='utf-8')
    assert load(directory / 'status.json')['status'] == 'failed'
