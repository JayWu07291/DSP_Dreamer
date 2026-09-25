"""Evidence-backed batch execution; fixture results never admit a formal candidate."""
from collections import Counter
import copy
import csv
import json
import math
from pathlib import Path
import subprocess
from typing import Any

import numpy as np

from .contract import atomic_save, file_info, load, require, sha
from .dataset import compile_recording, open_dataset
from .evaluation_protocol import read_protocol, seal, validate_trials, verify_seal
from .progress import TASKS, MILESTONES
from .runner import episode_result


NODES = TASKS[:16] + MILESTONES
SELECTION_ORDER = ['matrix_done', 'matrix_tech_done', 'manufacturing_done', 'logistics_done',
                   'metallurgy_done', 'electromagnetism_done', 'lander_done']
FAILURE_LABELS = {'observation_reconstruction', 'injection', 'wrong_action', 'task_reward', 'stagnation', 'unknown'}
PROTOCOL = Path(__file__).resolve().parents[1] / 'protocols' / 'evaluation-v2.json'


def proportion(n, total):
    if not total:
        return dict(n=n, N=total, rate=None, wilson95=None)
    p, z = n / total, 1.959963984540054
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return dict(n=n, N=total, rate=p, wilson95=[max(0., center - radius), min(1., center + radius)])


def node_records(dataset, episode):
    """Times use the first confirming observation, the same boundary as prompt changes."""
    activated: dict[int, int] = {}
    completed: dict[int, int] = {}
    references: dict[int, dict] = {}
    for row in dataset.rows:
        if row['episode_id'] != episode['episode_id']:
            continue
        if row['task_id'] < 16 and row['requested_ticks'] < episode['end_ticks']:
            activated.setdefault(row['task_id'], row['requested_ticks'])
        for node in row['node_completions']:
            completed.setdefault(node, row['next_requested_ticks'])
            references.setdefault(node, dict(capture_id=row['next_capture_id'], event_refs=row['event_refs']))
    frequency = dataset.metadata['ticks_frequency']
    result = []
    for node, name in enumerate(NODES):
        start = activated.get(node) if node < 16 else episode['start_ticks']
        end = completed.get(node)
        result.append(dict(node=name, reached=end is not None, activated=node in activated,
            activated_ticks=activated.get(node), completed_ticks=end,
            seconds=(end - start) / frequency if start is not None and end is not None else None,
            active_seconds=(min(end, episode['end_ticks']) if end is not None else episode['end_ticks']) / frequency
                - start / frequency if node < 16 and start is not None else None,
            evidence=references.get(node)))
    return result


def summarize(attempts):
    valid = [a for a in attempts if a['validity_status'] == 'valid']
    nodes = []
    for i, name in enumerate(NODES):
        rows = [a['nodes'][i] for a in valid]
        reached = sum(r['reached'] for r in rows)
        times = [r['seconds'] for r in rows if r['seconds'] is not None]
        q1, median, q3 = np.percentile(times, [25, 50, 75]).tolist() if times else (None, None, None)
        nodes.append(dict(node=name, arrival=proportion(reached, len(valid)), unreached=len(valid) - reached,
            active_completion=proportion(sum(r['reached'] and r['activated'] for r in rows),
                                         sum(r['activated'] for r in rows)) if i < 16 else None,
            reached_without_activation=sum(r['reached'] and not r['activated'] for r in rows) if i < 16 else None,
            time=dict(n=len(times), median_seconds=median, q1_seconds=q1, q3_seconds=q3,
                      iqr_seconds=q3 - q1 if q1 is not None else None)))
    return dict(valid_episodes=len(valid), success=proportion(sum(a['episode_outcome'] == 'success' for a in valid), len(valid)),
                nodes=nodes)


def calibrate_stagnation(index=None, *, engineering_only=False):
    samples: list[list[dict]] = [[] for _ in range(16)]
    seen = set()
    if index is not None:
        for source in index.report['sources']:
            if (source['split'] != 'train' or source['progress_version'] != 4
                    or source['source_kind'] != ('synthetic' if engineering_only else 'live')):
                continue
            dataset = index.views[source['artifact_id']].dataset
            for episode in dataset.metadata['episodes']:
                if episode['validity_status'] != 'valid' or episode['episode_id'] in seen:
                    continue
                seen.add(episode['episode_id'])
                records = node_records(dataset, episode)
                for task, row in enumerate(records[:16]):
                    interval = [r for r in dataset.rows if r['episode_id'] == episode['episode_id']
                                and row['activated_ticks'] is not None and row['completed_ticks'] is not None
                                and row['activated_ticks'] <= r['requested_ticks'] < row['completed_ticks']]
                    if row['seconds'] is not None and interval and all(r['valid'] for r in interval):
                        samples[task].append(dict(episode_id=episode['episode_id'], dataset_id=source['artifact_id'],
                                                 seconds=row['seconds']))
    return seal(dict(schema='dsp-stagnation-calibration/1', engineering_only=engineering_only,
        index_id=index.report['artifact_id'] if index is not None else None, source_split='train', minimum_episodes=20,
        tasks=[dict(task=name, n=len(rows), status='calibrated' if len(rows) >= 20 else 'insufficient_evidence',
                    threshold_seconds=2 * float(np.percentile([r['seconds'] for r in rows], 95)) if len(rows) >= 20 else None,
                    samples=rows) for name, rows in zip(TASKS[:16], samples)]))


def score_attempt(dataset, response, calibration):
    result = episode_result(dataset)
    episode = dataset.metadata['episodes'][0]
    result['nodes'] = node_records(dataset, episode)
    require((result['episode_outcome'] == 'success') == result['nodes'][22]['reached'],
            '回合成功與 matrix_done 證據不符')
    labels = copy.deepcopy(response.get('failure_labels', []))
    require(isinstance(labels, list), '失敗分類必須為清單')
    captures = {r['capture_id'] for r in dataset.rows} | {r['next_capture_id'] for r in dataset.rows}
    events = {e['sequence_number'] for e in dataset.events}
    for label in labels:
        require(label.get('label') in FAILURE_LABELS and isinstance(label.get('capture_ids'), list)
                and isinstance(label.get('event_refs'), list)
                and (label['capture_ids'] or label['event_refs'])
                and set(label['capture_ids']) <= captures and set(label['event_refs']) <= events,
                '失敗分類缺少有效影片／事件引用')
    for node, threshold in zip(result['nodes'][:16], calibration['tasks']):
        seconds, limit = node['active_seconds'], threshold['threshold_seconds']
        if seconds is not None and limit is not None and seconds > limit:
            labels.append(dict(label='stagnation', task=node['node'], seconds=seconds, threshold_seconds=limit,
                               capture_ids=[result['final_capture_id']] if result['final_capture_id'] is not None else [],
                               event_refs=[], calibration_id=calibration['artifact_id']))
    failed = result['episode_outcome'] != 'success' or result['validity_status'] != 'valid'
    if failed and not labels:
        labels.append(dict(label='unknown', capture_ids=sorted(captures)[-1:], event_refs=[]))
    result.update(failure_labels=labels, classification_status='reviewed' if response.get('failure_labels') else
                  'pending' if failed else 'not_applicable')
    return result


def validate_plan(plan, protocol):
    verify_seal(plan)
    require(plan.get('schema') == 'dsp-evaluation-batch-plan/1' and plan.get('engineering_only') is True,
            '本入口只執行隔離工程批次；正式候選須由 #32／#33／#34／#35 核准')
    trials = plan['trials']
    validate_trials(trials, plan['registry'], expected_id=trials['artifact_id'])
    reserved = load(PROTOCOL.parent / 'evaluation-trials-v1.json')
    # The fixture namespace cannot consume any formal manifest, group, seed or yaw.
    validate_trials(reserved, load(PROTOCOL.parent / 'evaluation-registry-v1.json'),
                    [e['trial_manifest'] for e in trials['manifests']], expected_id=protocol['trials_id'])
    reserved_ids = {e['trial_manifest']['manifest_id'] for e in reserved['manifests']}
    require(not reserved_ids.intersection(e['trial_manifest']['manifest_id'] for e in trials['manifests']),
            '工程批次不能使用正式保留 manifest')
    candidates = plan['candidates']
    require(isinstance(candidates, list) and len(candidates) <= 2, '最多兩個候選')
    require(len({c['stage'] for c in candidates}) == len(candidates), '階段候選重複')
    for candidate in candidates:
        require(type(candidate['stage']) is int and candidate['stage'] in (2, 3)
                and type(candidate.get('fixture_eligible')) is bool, '缺少工程候選身分')
        require(file_info(candidate['checkpoint']) == candidate['file'], '候選 checkpoint 已改變')


def run_batch(plan, output, execute, *, ffmpeg, training_index=None):
    """execute(request, attempt_dir) publishes evidence and returns its path, never scores.

    #29 currently admits engineering checkpoints only. Admission of real candidates stays
    closed until #32/#33 offline gates and #34 runtime evidence are connected by #35.
    """
    protocol = read_protocol(PROTOCOL)
    validate_plan(plan, protocol)
    if training_index is not None:
        groups = {e['trial_manifest']['split_group_id'] for e in plan['trials']['manifests']}
        require(not groups.intersection(s['split_group_id'] for s in training_index.report['sources']),
                '批次 manifest 不得出現在訓練索引')
        validate_trials(plan['trials'], plan['registry'],
            [v.dataset.metadata['trial_manifest'] for v in training_index.views.values()],
            expected_id=plan['trials']['artifact_id'])
    plan = copy.deepcopy(plan)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    atomic_save(output / 'plan.json', plan)
    calibration = calibrate_stagnation(training_index, engineering_only=True)
    atomic_save(output / 'calibration.json', calibration)
    attempts: list[dict] = []
    development = {}
    candidates = sorted([c for c in plan['candidates'] if c['fixture_eligible']], key=lambda c: c['stage'])
    seen_attempts, seen_episodes, seen_sources = set(), set(), set()
    consecutive = 0
    stop_reason = 'no_qualified_candidate' if not candidates else None
    selected = None

    def run_phase(candidate, purpose):
        nonlocal consecutive, stop_reason
        phase = []
        for entry in plan['trials']['manifests']:
            if entry['purpose'] != purpose:
                continue
            retry = 0
            while True:
                directory = output / 'attempts' / f'{len(attempts) + 1:04}'
                directory.mkdir(parents=True)
                request = seal(dict(schema='dsp-batch-attempt/1', engineering_only=True, plan_id=plan['artifact_id'],
                    candidate=candidate, purpose=purpose, trial_manifest=entry['trial_manifest'], retry=retry))
                atomic_save(directory / 'request.json', request)
                result: dict[str, Any] = dict(validity_status='invalid', validity_reasons=[], episode_outcome=None)
                try:
                    require(file_info(candidate['checkpoint']) == candidate['file'], '候選 checkpoint 已改變')
                    response = execute(copy.deepcopy(request), directory)
                    atomic_save(directory / 'response.json', response)
                    require(file_info(candidate['checkpoint']) == candidate['file'], '執行期間候選 checkpoint 已改變')
                    evidence = Path(response['evidence']).resolve()
                    dataset = open_dataset(compile_recording(evidence, directory / 'dataset', ffmpeg))
                    require(dataset.metadata['source_kind'] == 'synthetic' and dataset.metadata['diagnostic_mode'],
                            '工程 fixtures 必須隔離且禁止進入訓練')
                    require(dataset.metadata['trial_manifest'] == entry['trial_manifest'], '重試 manifest 不符')
                    require(dataset.metadata['progress_version'] == 4, '批次需要 v4 任務排程')
                    require(dataset.metadata['runner']['checkpoint_sha256'] == candidate['file']['sha256'], '候選 checksum 不符')
                    result = score_attempt(dataset, response, calibration)
                    require(result['attempt_id'] not in seen_attempts and result['episode_id'] not in seen_episodes
                            and dataset.metadata['source_artifact_id'] not in seen_sources, '重複的試驗證據')
                    seen_attempts.add(result['attempt_id'])
                    seen_episodes.add(result['episode_id'])
                    seen_sources.add(dataset.metadata['source_artifact_id'])
                    result['evidence'] = dict(path=str(evidence), manifest=file_info(evidence / 'manifest.json'),
                                              dataset=str(directory / 'dataset'))
                except (Exception, KeyboardInterrupt) as error:
                    result.update(validity_status='invalid',
                                  validity_reasons=sorted(set(result['validity_reasons'] + ['execution_error'])),
                                  error=dict(type=type(error).__name__, message=str(error)))
                    if isinstance(error, KeyboardInterrupt):
                        stop_reason = 'interrupted'
                result.update(schema='dsp-batch-attempt-result/1', attempt_directory=str(directory),
                              request_id=request['artifact_id'], stage=candidate['stage'], purpose=purpose,
                              manifest_id=entry['trial_manifest']['manifest_id'], retry=retry, engineering_only=True)
                result = seal(result)
                atomic_save(directory / 'result.json', result)
                attempts.append(result)
                phase.append(result)
                if stop_reason:
                    return phase
                if result['validity_status'] == 'valid':
                    consecutive = 0
                    break
                consecutive += 1
                if consecutive == 3:
                    stop_reason = 'three_consecutive_invalid'
                    return phase
                retry += 1
        return phase

    if len(candidates) == 2:
        scores = {}
        for candidate in candidates:
            phase = run_phase(candidate, 'development')
            summary = summarize(phase)
            development[str(candidate['stage'])] = summary
            scores[candidate['stage']] = [summary['nodes'][NODES.index(name)]['arrival']['n'] for name in SELECTION_ORDER]
            if stop_reason:
                break
        if not stop_reason:
            selected = max(candidates, key=lambda c: (scores[c['stage']], -c['stage']))
    elif candidates:
        selected = candidates[0]
    if selected is not None:
        # Persist selection before touching a final manifest. Final results cannot select a model.
        atomic_save(output / 'selection.json', seal(dict(engineering_only=True, selected=selected,
            order=SELECTION_ORDER, development=development, tie_rule='stage_two', speed_used=False)))
        run_phase(selected, 'final')
    invalid = [a for a in attempts if a['validity_status'] != 'valid']
    report = seal(dict(schema='dsp-evaluation-batch/1', engineering_only=True, qualified=False,
        formal_valid_episodes=0, status='stopped' if stop_reason else 'completed', stop_reason=stop_reason,
        plan_id=plan['artifact_id'], protocol_id=protocol['artifact_id'], scorer=file_info(__file__),
        action_codec_sha256=sha(json.dumps(protocol['action_codec'], sort_keys=True).encode()),
        calibration_id=calibration['artifact_id'], selected_stage=selected['stage'] if selected else None,
        counts=dict(total=len(attempts), invalid=len(invalid), retries=sum(a['retry'] > 0 for a in attempts),
            valid=len(attempts) - len(invalid), invalid_fraction=len(invalid) / len(attempts) if attempts else None,
            reasons=dict(Counter(r for a in invalid for r in a['validity_reasons']))),
        development=development, final=summarize([a for a in attempts if a['purpose'] == 'final']), attempts=attempts))
    atomic_save(output / 'report.json', report)
    with (output / 'nodes.csv').open('x', newline='', encoding='utf-8-sig') as stream:
        writer = csv.writer(stream)
        writer.writerow(['purpose', 'stage', 'node', 'n', 'N', 'rate', 'wilson95_low', 'wilson95_high',
                         'active_n', 'active_N', 'median_seconds', 'q1_seconds', 'q3_seconds', 'unreached'])
        for purpose, stage, summary in [('development', stage, s) for stage, s in development.items()] + [
                ('final', report['selected_stage'], report['final'])]:
            for node in summary['nodes']:
                rate, active, times = node['arrival'], node['active_completion'], node['time']
                writer.writerow([purpose, stage, node['node'], rate['n'], rate['N'], rate['rate'],
                    *(rate['wilson95'] or [None, None]), active['n'] if active else None, active['N'] if active else None,
                    times['median_seconds'], times['q1_seconds'], times['q3_seconds'], node['unreached']])
    return report


def main():
    import argparse
    from .training_index import TrainingIndex

    parser = argparse.ArgumentParser(description='隔離工程批次：固定 manifests、重試、選模與統計')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--training-index', type=Path)
    parser.add_argument('--training-source', type=Path, nargs='+')
    parser.add_argument('--execute', nargs=argparse.REMAINDER, required=True,
                        help='單回合命令；尾端自動附加 request.json 與 response.json 路徑')
    args = parser.parse_args()
    require(bool(args.execute), '缺少單回合命令')
    require(bool(args.training_index) == bool(args.training_source), '校準需同時提供索引與來源')
    index = TrainingIndex.open(args.training_index, args.training_source) if args.training_index else None

    def execute(request, directory):
        response = directory / 'executor-response.json'
        with (directory / 'executor.log').open('xb') as log:
            subprocess.run([*args.execute, str(directory / 'request.json'), str(response)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        return load(response)

    report = run_batch(load(args.plan), args.out, execute, ffmpeg=args.ffmpeg, training_index=index)
    print(json.dumps(dict(status=report['status'], counts=report['counts'], report=str(args.out / 'report.json'))))


if __name__ == '__main__':
    main()
