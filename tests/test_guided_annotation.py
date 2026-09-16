import copy
import json
import runpy
import shutil
import subprocess

import pytest

guided = runpy.run_path('tools/guided-annotation.py')


def test_human_answers_stay_partial_and_bound_to_original_sources(tmp_path):
    source = dict(id='R031', artifact_id='original', observation_index=474, image='images/original.png')
    batch = guided['seal'](dict(protocol_id='protocol', index_id='index', evaluation_inputs_id='inputs',
        questions=[dict(id=f'Q0{i}', source=source, box=[0, 224, 79, 245], target='左側提示') for i in range(1, 5)]))
    answer = dict(status='readable', item='磁鐵', count='001', reviewer='human', answered_at='2026-09-16T01:00:00Z')
    submission = dict(schema='dsp-guided-annotation-answers/1', batch_id=batch['artifact_id'],
        status='pending', training_authorized=False, answers={'Q01': answer,
        'Q02': dict(answer, status='unreadable', item=None, count=None),
        'Q03': dict(answer, status='wrong_target', item=None, count=None)})
    draft = guided['checked_answers'](batch, submission)
    row = draft['records']['reconstruction:R031']
    assert row['source'] == source and row['reviewed'] is False
    assert row['items'][0]['expected'].endswith('完整數字=001')
    assert row['items'][0]['reviewer'] == 'human' and row['items'][1]['eligible'] is False
    assert [q['question_id'] for q in draft['pending_questions']] == ['Q03', 'Q04']
    assert draft['whole_frames_reviewed'] == 0 and draft['training_authorized'] is False
    for field, value in [('count', '1e2'), ('count', 1), ('item', ''), ('reviewer', ''),
                         ('answered_at', '2026-09-16T01:00:00'), ('status', 'approved')]:
        bad = copy.deepcopy(submission)
        bad['answers']['Q01'][field] = value
        with pytest.raises(ValueError):
            guided['checked_answers'](batch, bad)
    bad = copy.deepcopy(submission)
    bad['answers']['Q02']['count'] = '0'
    with pytest.raises(ValueError):
        guided['checked_answers'](batch, bad)
    with pytest.raises(ValueError):
        guided['checked_answers'](dict(batch, index_id='other'), submission)
    with pytest.raises(ValueError):
        guided['checked_answers'](batch, dict(submission, batch_id='other'))
    with pytest.raises(ValueError):
        guided['checked_answers'](batch, dict(submission, answers={'Q99': answer}))
    # Import verifies the exported package before writing; tampering never produces a draft.
    folder = tmp_path / 'batch'
    folder.mkdir()
    guided['atomic_save'](folder / 'batch.json', batch)
    guided['atomic_save'](folder / 'export.json', guided['seal'](dict(batch_id=batch['artifact_id'],
        files={'batch.json': guided['file_info'](folder / 'batch.json')})))
    answers = tmp_path / 'answers.json'
    guided['atomic_save'](answers, submission)
    out = tmp_path / 'draft.json'
    assert guided['check_submission'](folder, answers, out) == draft
    # JSON field ordering changes on disk. The browser must accept the exact output bytes.
    node = shutil.which('node')
    if node:
        payload = tmp_path / 'browser-import.json'
        payload.write_text(json.dumps(dict(work=dict(protocol_id='protocol', index_id='index',
            evaluation_inputs_id='inputs', reconstruction=[source], prediction=[]), draft=guided['load'](out))), encoding='utf-8')
        subprocess.run([node, 'tests/check-annotation-draft.cjs', str(payload)], check=True, capture_output=True)
    with pytest.raises(ValueError, match='overwrite'):
        guided['check_submission'](folder, answers, out)
    (folder / 'batch.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='changed'):
        guided['check_submission'](folder, answers, tmp_path / 'tampered.json')
    assert not (tmp_path / 'tampered.json').exists()


def test_export_rejects_source_overlap_before_writing(tmp_path):
    for out in (tmp_path, tmp_path / 'child', tmp_path.parent):
        with pytest.raises(ValueError, match='overlap'):
            guided['export_batch'](tmp_path, out)
    assert not list(tmp_path.iterdir())
