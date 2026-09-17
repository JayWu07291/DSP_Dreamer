"""只讀已封存來源的事件與轉移表，解釋任務正例缺口；不重驗 RGB、不授權 gate。"""
import argparse
from bisect import bisect_right
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import seal, verify_seal
from dsp_dreamer.model_view import ModelView
from dsp_dreamer.progress import TASKS


def diagnose(path, index):
    verify_seal(index)
    require(index.get('schema') == 'dsp-training-index/1', 'Expected sealed training index')
    completed_info = file_info(path / 'COMPLETED')
    matches = [s for s in index['sources'] if s['model_view']['source_completed'] == completed_info]
    require(len(matches) == 1, 'Source is missing or duplicated in index')
    source = matches[0]
    require(source['split'] is not None, 'Reserved evaluation source cannot be diagnosed')
    completed = load(path / 'COMPLETED')
    verified = {}
    for name in ('dataset.json', 'transitions.parquet', 'events.parquet'):
        verified[name] = file_info(path / name)
        require(verified[name] == completed['files'][name], f'Table checksum mismatch: {name}')
    metadata = load(path / 'dataset.json')
    rows = pq.read_table(path / 'transitions.parquet').to_pylist()
    events = [json.loads(e['payload_json']) for e in pq.read_table(path / 'events.parquet').to_pylist()]
    # Only the already verified metadata is supplied. No Dataset or RGB array is opened.
    view = ModelView(SimpleNamespace(path=path, metadata=metadata, rows=rows, events=events))
    require(view.metadata == source['model_view'], 'Model view identity mismatch')
    length = index['sequence_length']
    starts = view.sequence_starts(length)
    require(starts == source['uniform'], 'Legal sequence starts differ from sealed index')
    input_changes = [e for e in events if e['type'] == 'gap' or e.get('operation') == 'game_input_reset'
                     or e['type'] == 'input' and (e['down'] or e['up'])]

    def describe(window, episode):
        row = view.rows[window]
        first, last = rows[row['start']], rows[row['stop'] - 1]
        return dict(model_index=window, capture_ids=[first['capture_id'], last['next_capture_id']],
                    seconds=(first['requested_ticks'] - episode['start_ticks']) / metadata['ticks_frequency'],
                    task_id=row['task_id'], valid=row['valid'], reward=row['reward'],
                    gap=any(p['gap'] for p in rows[row['start']:row['stop']]),
                    action_flags={k: row['action'][k] for k in ('ambiguous', 'unsupported', 'forbidden')},
                    incomplete_window=row['stop'] - row['start'] != 2)

    episodes = []
    positives: list[set[str]] = [set() for _ in range(16)]
    for episode in metadata['episodes']:
        eid = episode['episode_id']
        windows = [i for i, r in enumerate(view.rows) if rows[r['start']]['episode_id'] == eid]
        tasks = []
        for task, name in enumerate(TASKS[:16]):
            completions = [i for i in windows if task in view.rows[i]['node_completions']]
            require(len(completions) <= 1, 'Repeated node completion')
            result: dict[str, Any] = dict(task_id=task, task=name, reason='not_completed')
            if completions:
                i = completions[0]
                row = view.rows[i]
                before = bisect_right(starts, i) - 1
                covered = before >= 0 and i < starts[before] + length
                reason = ('non_active_completion' if row['task_id'] != task else
                          'invalid_window' if not row['valid'] else
                          'short_valid_run' if not covered else 'usable_positive')
                result.update(describe(i, episode), reason=reason, task_id=task, active_task_id=row['task_id'],
                              covered=covered,
                              transition_tasks=[r['task_id'] for r in rows[row['start']:row['stop']]])
                if reason == 'usable_positive':
                    positives[task].add(eid)
                if reason in ('invalid_window', 'short_valid_run'):
                    left = right = i
                    if row['valid']:
                        while left > windows[0] and view.rows[left - 1]['valid']:
                            left -= 1
                        while right < windows[-1] and view.rows[right + 1]['valid']:
                            right += 1
                    barriers = [i] if not row['valid'] else [j for j in (left - 1, right + 1) if j in windows]
                    result.update(valid_run_steps=right - left + 1 if row['valid'] else 0,
                                  valid_run_bounds=[left, right] if row['valid'] else None, barriers=[])
                    for j in barriers:
                        barrier = describe(j, episode)
                        first, last = rows[view.rows[j]['start']], rows[view.rows[j]['stop'] - 1]
                        barrier['events'] = [{k: e[k] for k in ('sequence_number', 'ticks', 'unity_frame', 'type',
                            'operation', 'source', 'reason', 'gap_start_ticks', 'gap_end_ticks', 'missed', 'down', 'up', 'held')
                            if k in e} for e in input_changes
                            if first['requested_ticks'] <= e['ticks'] < last['next_requested_ticks']]
                        result['barriers'].append(barrier)
            tasks.append(result)
        episodes.append(dict(episode_id=eid, tasks=tasks))
    counts = [len(ids) for ids in positives]
    if len(index['sources']) == 1:
        require(counts == [t['active_reward_episodes'] for t in index['splits'][source['split']]['tasks']],
                'Diagnostic positive counts differ from sealed index')
    require(file_info(path / 'COMPLETED') == completed_info and
            all(file_info(path / name) == info for name, info in verified.items()), 'Source changed during diagnosis')
    return seal(dict(schema='dsp-task-coverage-diagnosis/1', index_id=index['artifact_id'],
                     source_artifact_id=metadata['artifact_id'], source_completed=completed_info,
                     checked_files=verified, sequence_length=length, split=source['split'],
                     episodes=episodes, positive_episode_counts=counts, rgb_opened=False,
                     scope='sealed source metadata only; not a dataset revalidation or corpus coverage gate',
                     training_authorized=False, tool=file_info(Path(__file__))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(args.source, load(args.index))
    atomic_save(args.report, report)
    print(json.dumps(dict(report_id=report['artifact_id'], positive_episode_counts=report['positive_episode_counts'],
                          rgb_opened=False)))


if __name__ == '__main__':
    main()
