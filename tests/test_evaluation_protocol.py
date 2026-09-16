import copy
import json
from pathlib import Path
import subprocess

import pytest

from dsp_dreamer import InvalidRecording
from dsp_dreamer.contract import load
from dsp_dreamer.evaluation_protocol import (
    authorize_test_disclosure, prepare_evaluation, read_protocol, seal, validate_trials,
)
from dsp_dreamer.training_index import TrainingIndex
from test_training_index import fixture, registry


PROTOCOL = Path('protocols/evaluation-v2.json')


def test_build_control_revision_preserves_frozen_v1_contract():
    old = load('protocols/evaluation-v1.json')
    from dsp_dreamer.contract import file_info
    from dsp_dreamer.evaluation_protocol import verify_seal
    verify_seal(old)
    for name, info in old['files'].items():
        assert file_info(Path('protocols') / name) == info
    current = read_protocol(PROTOCOL)
    assert current['supersedes'] == old['artifact_id']
    assert current['action_codec']['controls'] == old['action_codec']['controls'] + ['B']
    assert current['action_codec']['binary_width'] == 21
    for key in ('thresholds', 'seeds', 'trials_id', 'trial_counts', 'episode_seconds'):
        assert current[key] == old[key]
    with pytest.raises(InvalidRecording, match='action catalog'):
        read_protocol('protocols/evaluation-v1.json')


def test_protocol_preparation_keeps_missing_evidence_pending(tmp_path):
    path = fixture(tmp_path, group='trial')
    index = TrainingIndex([path], registry(('trial', 'demonstration')), length=64)
    protocol = read_protocol(PROTOCOL)
    packet = prepare_evaluation(index, protocol)
    assert packet['status'] == 'pending'
    assert packet['training_authorized'] is False
    assert packet['annotations_status'] == 'pending'
    assert packet['prediction']['selected'] == []
    assert packet['prediction']['deficits'] == dict(movement=50, ui=50, interaction=50, waiting=50)
    assert packet['baseline']['status'] == 'insufficient_evidence'
    assert packet == prepare_evaluation(index, protocol)
    changed = copy.deepcopy(protocol)
    changed['thresholds']['reconstruction']['overall'] = 0.1
    with pytest.raises(InvalidRecording, match='checksum'):
        prepare_evaluation(index, changed)
    candidates = dict(schema='dsp-prediction-candidates/1', index_id=index.report['artifact_id'],
                      protocol_id=protocol['artifact_id'], samples=[dict(artifact_id=index.report['sources'][0]['artifact_id'],
                      start=0, task_id=0, category='movement', reviewed=True, evidence='capture:0',
                      regions=[[0, 0, 640, 360]], key_states=[dict(type='cursor', expected='center')])])
    with pytest.raises(InvalidRecording, match='illegal validation'):
        prepare_evaluation(index, protocol, seal(candidates))


def test_frozen_trials_match_recorder_and_reject_split_or_seed_reuse(tmp_path):
    trials = load('protocols/evaluation-trials-v1.json')
    reg = load('protocols/evaluation-registry-v1.json')
    expected_id = read_protocol(PROTOCOL)['trials_id']
    validate_trials(trials, reg, expected_id=expected_id)
    baseline = trials['manifests'][0]['trial_manifest']
    source = tmp_path / 'metadata.json'
    source.write_text(json.dumps(dict(trial_manifest=baseline)), encoding='utf-8')
    output = tmp_path / 'trials.json'
    subprocess.run(['powershell.exe', '-NoProfile', '-File', 'tools/freeze-evaluation-trials.ps1',
                    '-DatasetMetadata', str(source), '-Out', str(output)], check=True)
    assert load(output) == trials
    bad_registry = copy.deepcopy(reg)
    bad_registry['manifests'][0]['split_group_id'] = baseline['split_group_id']
    with pytest.raises(InvalidRecording, match='reserved group'):
        validate_trials(trials, bad_registry, expected_id=expected_id)
    reused = dict(baseline, manifest_id='demonstration', split_group_id='demonstration')
    with pytest.raises(InvalidRecording, match='seed'):
        validate_trials(trials, reg, [reused], expected_id=expected_id)
    changed = copy.deepcopy(trials)
    changed['manifests'][-1]['purpose'] = 'development'
    changed = seal({k: v for k, v in changed.items() if k != 'artifact_id'})
    with pytest.raises(InvalidRecording, match='frozen protocol'):
        validate_trials(changed, reg, expected_id=expected_id)
    changed = copy.deepcopy(trials)
    changed['manifests'][0]['trial_manifest']['mecha_yaw'] += 0.01
    changed = seal({k: v for k, v in changed.items() if k != 'artifact_id'})
    with pytest.raises(InvalidRecording, match='frozen protocol'):
        validate_trials(changed, reg, expected_id=expected_id)


def test_offline_test_requires_ordered_blind_recipe_freeze():
    protocol = read_protocol(PROTOCOL)
    data = dict(schema='dsp-evaluation-data-freeze/1', protocol_id=protocol['artifact_id'],
                index_id='a'*64, evaluation_inputs_id='b'*64, annotations_id='c'*64,
                supplementation_complete=True, frozen_at='2026-10-01T00:00:00+08:00')
    frozen_data = seal(data)
    recipe = dict(schema='dsp-evaluation-recipe-freeze/1', data_freeze_id=frozen_data['artifact_id'],
                  checkpoint_sha256='d'*64, recipe_sha256='e'*64, selection_split='validation+development',
                  offline_test_seen=False, final_seen=False, frozen_at='2026-10-02T00:00:00+08:00')
    result = authorize_test_disclosure(protocol, frozen_data, seal(recipe))
    assert result['offline_test_disclosure_authorized'] is True
    assert result['training_authorized'] is False
    for field, value in [('offline_test_seen', True), ('final_seen', True), ('selection_split', 'final'),
                         ('checkpoint_sha256', ''), ('frozen_at', '2026-09-01T00:00:00+08:00')]:
        with pytest.raises(InvalidRecording):
            authorize_test_disclosure(protocol, frozen_data, seal(dict(recipe, **{field: value})))
