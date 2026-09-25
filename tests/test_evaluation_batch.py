import copy
import json

import numpy as np
import pytest

from dsp_dreamer import Recording
from dsp_dreamer.actions import ACTION_CODEC
from dsp_dreamer.contract import file_info, load, sha
from dsp_dreamer.evaluation_protocol import seal
from test_control import FFMPEG


def batch_plan(tmp_path, stages=(2,)):
    candidates = []
    for stage in stages:
        checkpoint = tmp_path / f'stage-{stage}.fixture'
        checkpoint.write_text('隔離的候選資格 fixture，不是模型 checkpoint', encoding='utf-8')
        candidates.append(dict(stage=stage, checkpoint=str(checkpoint), file=file_info(checkpoint),
                               fixture_eligible=True))
    manifests = []
    for i in range(40):
        manifests.append(dict(purpose='development' if i < 10 else 'final', trial_manifest=dict(
            manifest_id=f'fixture-{i}', split_group_id=f'fixture-{i}',
            mecha_seed=1000000 + i * 3, camera_seed=1000001 + i * 3, policy_seed=1000002 + i * 3,
            mecha_yaw=-14 + i / 100, camera_yaw=14 - i / 100)))
    trials = seal(dict(schema='dsp-evaluation-trials/1', manifests=manifests))
    registry = dict(schema='dsp-split-registry/1', manifests=[dict(
        manifest_id=e['trial_manifest']['manifest_id'], split_group_id=e['trial_manifest']['split_group_id'],
        purpose=e['purpose']) for e in manifests])
    return seal(dict(schema='dsp-evaluation-batch-plan/1', engineering_only=True,
                     trials=trials, registry=registry, candidates=candidates))


def record_attempt(request, directory, *, invalid=False, facts=(), outcome='timeout'):
    with Recording.synthetic(directory / 'source', FFMPEG) as recording:
        recording.begin_attempt(request['trial_manifest'])
        recording.metadata.update(diagnostic_mode=True, progress_version=4,
            progress_tech_ids=[1001, 1002, 1003, 1004, 1005], control_mode='policy',
            runner=dict(status='engineering_only', qualified=False,
                checkpoint_sha256=request['candidate']['file']['sha256'],
                action_codec_sha256=sha(json.dumps(ACTION_CODEC, sort_keys=True).encode())))
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks, fact in facts:
            recording.event(ticks, 'progress_fact', episode_id=recording.episode['episode_id'], **fact)
        recording.events.append(dict(recording.identity(70), type='control_request', operation='model_action',
            request_id=1, catalog=ACTION_CODEC['catalog'], **copy.deepcopy(ACTION_CODEC['noop']),
            capture_ticks=50, inference_ticks=60, requested_ticks=70,
            sent_count=0, requested_count=0, succeeded=True))
        recording.events.append(dict(recording.identity(70), type='control_request', operation='runner_step',
            step=0, capture_ticks=50, inference_started_ticks=55, inference_ticks=60,
            requested_ticks=70, request_id=1, missed=False))
        recording.input(80, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(355), type='control_request', operation='release_all',
            requested_ticks=355, sent_count=21, requested_count=21, succeeded=True))
        recording.input(365, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks in range(50, 401, 50):
            if ticks == 400:
                recording.end_episode(380, outcome=outcome, reason='human_intervention' if invalid else None)
            recording.complete(recording.request(ticks, 1, 1), np.zeros((360, 640, 4), np.uint8))
    return dict(evidence=str(recording.publish(directory / 'evidence')))


def test_batch_retries_same_manifest_and_exports_zero_success(tmp_path):
    from dsp_dreamer.evaluation_batch import run_batch

    plan = batch_plan(tmp_path)
    requests = []

    def execute(request, directory):
        requests.append(copy.deepcopy(request))
        # queue_research completes without activation, start_dismantle completes while active.
        return record_attempt(request, directory, invalid=len(requests) == 1, facts=[
            (60, dict(kind='research_queue', tech_ids=[1001, 1002, 1003, 1004, 1005])),
            (160 if int(request['trial_manifest']['manifest_id'].split('-')[-1]) < 25 else 260,
             dict(kind='lander_work', work_ticks=1)),
        ])

    report = run_batch(plan, tmp_path / 'batch', execute, ffmpeg=FFMPEG)
    assert report['status'] == 'completed' and report['engineering_only']
    assert report['formal_valid_episodes'] == 0 and report['selected_stage'] == 2
    assert report['counts'] == dict(total=31, invalid=1, retries=1, valid=30,
                                    invalid_fraction=1 / 31, reasons={'human_intervention': 1})
    assert requests[0]['trial_manifest'] == requests[1]['trial_manifest']
    assert all(r['purpose'] == 'final' for r in requests)
    stats = report['final']
    assert stats['success']['n'] == 0 and stats['success']['N'] == 30
    assert stats['success']['wilson95'] == pytest.approx([0, .11351339317396876])
    assert stats['nodes'][0]['arrival']['rate'] == 1
    assert stats['nodes'][0]['time']['median_seconds'] == pytest.approx(.2)
    assert stats['nodes'][0]['time']['iqr_seconds'] == pytest.approx(.1)
    assert stats['nodes'][0]['time']['q1_seconds'] == pytest.approx(.15)
    assert stats['nodes'][0]['time']['q3_seconds'] == pytest.approx(.25)
    assert stats['nodes'][1]['arrival']['n'] == 30
    assert stats['nodes'][1]['active_completion']['N'] == 0
    assert stats['nodes'][1]['time']['median_seconds'] is None
    assert stats['nodes'][1]['reached_without_activation'] == 30
    assert stats['nodes'][2]['unreached'] == 30
    assert stats['nodes'][2]['arrival']['rate'] == 0
    assert load(tmp_path / 'batch' / 'report.json') == report
    assert len(list((tmp_path / 'batch' / 'attempts').glob('*/result.json'))) == 31
    assert (tmp_path / 'batch' / 'nodes.csv').exists()


def success_facts(offset=0):
    from test_progress import production_batches

    batches = production_batches()
    links = [(1, [10], [1001], [1]), (2, [10], [1001], [1]), (3, [11], [1002], [1]),
             (4, [2, 3], [1102, 1104], [0, 0]), (5, [1, 3], [1101, 1104], [0, 0]),
             (6, [4, 5], [1202, 1301], [0, 0])]
    batches[2][0:0] = [dict(kind='line_state', target=f'm:0:{entity}', sources=[f'm:0:{i}' for i in sources],
        items=items, belts=belts, powered=True) for entity, sources, items, belts in links] + [
        dict(kind='miner_stock', target='m:0:11', item_id=1002, count=2, vein_item_id=1002,
             power=1., network_id=1, proto_id=2301)]
    for batch in batches:
        for fact in batch:
            if fact['kind'] == 'miner_stock' and fact['item_id'] == 1002:
                fact['target'] = 'm:0:11'
    facts = [(60 + offset + i * 10, fact) for i, batch in enumerate(batches) for fact in batch]
    facts += [(55 + offset, dict(kind='tech_state', tech_id=i, unlocked=True)) for i in range(1001, 1006)]
    facts.append((55 + offset, dict(kind='lander_removed')))
    return sorted(facts, key=lambda f: f[0])


def test_two_candidates_tie_ignores_speed_and_final_all_success(tmp_path):
    from dsp_dreamer.evaluation_batch import run_batch

    plan = batch_plan(tmp_path, stages=(3, 2))

    def execute(request, directory):
        return record_attempt(request, directory, facts=success_facts(100 if request['candidate']['stage'] == 2 else 0),
                              outcome='success')

    report = run_batch(plan, tmp_path / 'batch', execute, ffmpeg=FFMPEG)
    assert report['selected_stage'] == 2 and report['counts']['total'] == 50
    assert report['final']['success']['wilson95'] == pytest.approx([.8864866068260312, 1])
    assert report['final']['nodes'][22]['time']['median_seconds'] == pytest.approx(.25)
    assert report['final']['nodes'][22]['time']['iqr_seconds'] == 0
    assert report['final']['nodes'][22]['unreached'] == 0
    assert report['development']['2']['nodes'][22]['time']['median_seconds'] > report['development']['3']['nodes'][22]['time']['median_seconds']
    development = [a for a in report['attempts'] if a['purpose'] == 'development']
    assert [a['manifest_id'] for a in development[:10]] == [a['manifest_id'] for a in development[10:]]
    assert load(tmp_path / 'batch' / 'selection.json')['speed_used'] is False


def test_three_invalid_stop_preserves_attempts_and_no_candidates_do_not_execute(tmp_path):
    from dsp_dreamer.evaluation_batch import run_batch

    plan = batch_plan(tmp_path, stages=(3,))
    report = run_batch(plan, tmp_path / 'invalid',
        lambda request, directory: record_attempt(request, directory, invalid=True), ffmpeg=FFMPEG)
    assert report['status'] == 'stopped' and report['stop_reason'] == 'three_consecutive_invalid'
    assert report['counts']['total'] == report['counts']['invalid'] == 3
    assert report['counts']['retries'] == 2
    assert len({a['manifest_id'] for a in report['attempts']}) == 1
    assert report['final']['success'] == dict(n=0, N=0, rate=None, wilson95=None)
    empty = dict(plan, candidates=[])
    empty.pop('artifact_id')
    report = run_batch(seal(empty), tmp_path / 'empty', lambda *args: pytest.fail('不應執行試驗'), ffmpeg=FFMPEG)
    assert report['stop_reason'] == 'no_qualified_candidate' and report['attempts'] == []
    assert report['selected_stage'] is None
    rejected = copy.deepcopy(plan)
    rejected.pop('artifact_id')
    rejected['candidates'][0]['fixture_eligible'] = False
    report = run_batch(seal(rejected), tmp_path / 'rejected', lambda *args: pytest.fail('不應執行試驗'), ffmpeg=FFMPEG)
    assert report['stop_reason'] == 'no_qualified_candidate'


def test_batch_rejects_formal_manifests_checkpoint_changes_and_wrong_retry(tmp_path):
    from dsp_dreamer import InvalidRecording
    from dsp_dreamer.evaluation_batch import run_batch

    plan = batch_plan(tmp_path)
    formal = dict(plan, engineering_only=False)
    formal.pop('artifact_id')
    with pytest.raises(InvalidRecording, match='正式候選'):
        run_batch(seal(formal), tmp_path / 'formal', None, ffmpeg=FFMPEG)
    reserved = dict(plan, trials=load('protocols/evaluation-trials-v1.json'),
                    registry=load('protocols/evaluation-registry-v1.json'))
    reserved.pop('artifact_id')
    with pytest.raises(InvalidRecording, match='正式保留'):
        run_batch(seal(reserved), tmp_path / 'reserved', None, ffmpeg=FFMPEG)

    def execute(request, directory):
        request['trial_manifest']['policy_seed'] += 1
        return record_attempt(request, directory)

    report = run_batch(plan, tmp_path / 'wrong-retry', execute, ffmpeg=FFMPEG)
    assert report['counts']['valid'] == 0 and report['counts']['total'] == 3
    assert all('manifest' in a['error']['message'] for a in report['attempts'])
    from pathlib import Path
    Path(plan['candidates'][0]['checkpoint']).write_text('changed')
    with pytest.raises(InvalidRecording, match='checkpoint'):
        run_batch(plan, tmp_path / 'changed', None, ffmpeg=FFMPEG)


@pytest.mark.parametrize('priority', range(7))
def test_selection_compares_each_priority_before_lower_progress(tmp_path, priority):
    from dsp_dreamer.evaluation_batch import run_batch

    plan = batch_plan(tmp_path, stages=(2, 3))
    # Stage three reaches the priority node; stage two reaches every lower priority node.
    ordered = ['matrix_done', 1005, 1004, 1003, 1002, 1001, 'lander_done']

    def execute(request, directory):
        if request['purpose'] == 'final':
            return record_attempt(request, directory, invalid=True)
        nodes = ordered[priority:priority + 1] if request['candidate']['stage'] == 3 else ordered[priority + 1:]
        facts = []
        if 'matrix_done' in nodes:
            facts = success_facts()
        else:
            for node in nodes:
                facts.append((60, dict(kind='lander_removed') if node == 'lander_done' else
                                   dict(kind='tech_state', tech_id=node, unlocked=True)))
        return record_attempt(request, directory, facts=facts, outcome='success' if 'matrix_done' in nodes else 'timeout')

    report = run_batch(plan, tmp_path / 'batch', execute, ffmpeg=FFMPEG)
    assert report['selected_stage'] == 3
    assert report['counts']['valid'] == 20 and report['counts']['invalid'] == 3
    assert report['stop_reason'] == 'three_consecutive_invalid'


@pytest.mark.parametrize('count', [19, 20])
def test_train_only_stagnation_calibration_and_evidence_labels(tmp_path, count):
    from dsp_dreamer import compile_recording
    from dsp_dreamer.evaluation_batch import run_batch
    from dsp_dreamer.training_index import TrainingIndex
    from test_training_index import registry

    paths = []
    for group, size, completion in [('0', count, 160), ('9', 20, 260)]:
        with Recording.synthetic(tmp_path / f'train-{group}', FFMPEG) as recording:
            recording.metadata.update(progress_version=4, progress_tech_ids=[1001, 1002, 1003, 1004, 1005])
            for episode in range(size):
                offset = 1000 * episode
                recording.begin_attempt(dict(manifest_id=group, split_group_id=group,
                                             mecha_seed=1, camera_seed=2, policy_seed=3))
                recording.input(offset, held=[], down=[], up=[], delta=[0, 0], wheel=0)
                recording.event(offset + completion, 'progress_fact', episode_id=recording.episode['episode_id'],
                                kind='lander_work', work_ticks=1)
                for ticks in range(50, 401, 50):
                    if ticks == 400:
                        recording.end_episode(offset + 380, outcome='timeout')
                    recording.complete(recording.request(offset + ticks, 1, 1), np.zeros((360, 640, 4), np.uint8))
        evidence = recording.publish(tmp_path / f'evidence-{group}')
        paths.append(compile_recording(evidence, tmp_path / f'dataset-{group}', FFMPEG))
    index = TrainingIndex(paths, registry(('0', 'demonstration'), ('9', 'demonstration')), length=2)
    plan = batch_plan(tmp_path)

    def execute(request, directory):
        response = record_attempt(request, directory, invalid=True)
        response['failure_labels'] = [dict(label=label, capture_ids=[0], event_refs=[]) for label in
                                      ('observation_reconstruction', 'wrong_action')]
        return response

    report = run_batch(plan, tmp_path / 'batch', execute, ffmpeg=FFMPEG, training_index=index)
    calibration = load(tmp_path / 'batch' / 'calibration.json')
    task = calibration['tasks'][0]
    assert task['n'] == count
    assert task['threshold_seconds'] == (pytest.approx(.3) if count == 20 else None)
    labels = report['attempts'][0]['failure_labels']
    assert [l['label'] for l in labels] == ['observation_reconstruction', 'wrong_action'] + (['stagnation'] if count == 20 else [])
    assert report['attempts'][0]['episode_outcome'] == 'timeout'
    assert all(l['capture_ids'] for l in labels)


def test_cli_preserves_executor_failures_and_stops(tmp_path):
    import subprocess
    import sys
    from dsp_dreamer.contract import atomic_save

    plan = batch_plan(tmp_path)
    atomic_save(tmp_path / 'plan.json', plan)
    subprocess.run([sys.executable, '-m', 'dsp_dreamer.evaluation_batch', '--plan', str(tmp_path / 'plan.json'),
                    '--out', str(tmp_path / 'batch'), '--ffmpeg', str(FFMPEG), '--execute', sys.executable,
                    '-c', 'raise RuntimeError("controlled fixture failure")'], check=True)
    report = load(tmp_path / 'batch' / 'report.json')
    assert report['counts']['total'] == 3 and report['stop_reason'] == 'three_consecutive_invalid'
    assert all(a['error']['type'] == 'CalledProcessError' for a in report['attempts'])
    assert len(list((tmp_path / 'batch' / 'attempts').glob('*/executor.log'))) == 3
