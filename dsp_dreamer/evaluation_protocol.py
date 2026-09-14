"""Frozen evaluation inputs; preparation never grants a model quality gate."""
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
from typing import Any

from .actions import ACTION_CODEC
from .contract import file_info, load, require, sha


CATEGORIES = ('movement', 'ui', 'interaction', 'waiting')
ITEM_TYPES = ('cursor', 'recipe', 'item_number', 'connection')


def seal(payload):
    result = copy.deepcopy(payload)
    result['artifact_id'] = sha(json.dumps(payload, sort_keys=True, allow_nan=False).encode())
    return result


def verify_seal(value):
    require(isinstance(value, dict) and value.get('artifact_id') ==
            seal({k: v for k, v in value.items() if k != 'artifact_id'})['artifact_id'],
            'Evaluation artifact checksum mismatch')


def read_protocol(path):
    protocol = load(path)
    verify_seal(protocol)
    require(protocol.get('schema') == 'dsp-evaluation-protocol/1', 'Unknown evaluation protocol')
    require(protocol['action_codec'] == ACTION_CODEC, 'Evaluation action catalog mismatch')
    for name, expected in protocol['files'].items():
        require(file_info(Path(path).parent / name) == expected, f'Protocol file checksum mismatch: {name}')
    return protocol


def validate_trials(trials, registry, recorded_trials=(), *, expected_id):
    """Reject reservations that share identities, yaw or RNG seeds with demonstrations."""
    verify_seal(trials)
    require(trials['artifact_id'] == expected_id, 'Trial artifact differs from frozen protocol')
    require(trials.get('schema') == 'dsp-evaluation-trials/1', 'Unknown trial schema')
    entries = trials['manifests']
    require(Counter(e['purpose'] for e in entries) == {'development': 10, 'final': 30}, 'Expected 10/30 trials')
    registrations = {e['manifest_id']: e for e in registry['manifests']}
    require(len(registrations) == len(registry['manifests']), 'Duplicate registry identity')
    ids, groups, seeds, yaws = set(), set(), set(), set()
    for entry in entries:
        trial = entry['trial_manifest']
        mid, group = trial['manifest_id'], trial['split_group_id']
        require(mid not in ids and group not in groups, 'Overlapping trial identity/group')
        ids.add(mid)
        groups.add(group)
        require(registrations.get(mid) == dict(manifest_id=mid, split_group_id=group, purpose=entry['purpose']),
                'Missing or changed reserved manifest registration')
        for key in ('mecha_seed', 'camera_seed', 'policy_seed'):
            value = trial[key]
            require(type(value) is int and 0 <= value < 2147483647 and value not in seeds, 'Reused trial seed')
            seeds.add(value)
        for key in ('mecha_yaw', 'camera_yaw'):
            value = trial[key]
            require(type(value) in (int, float) and -15 <= value <= 15 and value not in yaws, 'Reused trial yaw')
            yaws.add(value)
    require(all(e['manifest_id'] in ids or e['split_group_id'] not in groups for e in registry['manifests']),
            'Demonstration shares a reserved group')
    for trial in recorded_trials:
        if trial['manifest_id'] in ids:
            expected = next(e['trial_manifest'] for e in entries if e['trial_manifest']['manifest_id'] == trial['manifest_id'])
            require(trial == expected, 'Recorded evaluation manifest changed')
        else:
            require(trial['split_group_id'] not in groups, 'Recording shares reserved group')
            require(all(trial[k] not in seeds for k in ('mecha_seed', 'camera_seed', 'policy_seed')),
                    'Demonstration reuses reserved seed')
            require(all(trial.get(k) not in yaws for k in ('mecha_yaw', 'camera_yaw')), 'Demonstration reuses reserved yaw')


def _seeded_hash(seed, value):
    return sha(json.dumps([seed, value], sort_keys=True, allow_nan=False).encode())


def prepare_evaluation(index, protocol, candidates=None):
    """Select only source-verified validation inputs. Human labels remain pending."""
    verify_seal(protocol)
    require(protocol['action_codec'] == ACTION_CODEC and index.report['sequence_length'] == 64,
            'Protocol requires current catalog and 64-step training index')
    frames = []
    legal_predictions: set[tuple[str, int]] = set()
    counts: dict[int, dict[str, Counter]] = {task: dict(mouse=Counter(), wheel=Counter()) for task in range(17)}
    train_sources = []
    for source in index.report['sources']:
        view = index.views[source['artifact_id']]
        if source['split'] == 'train' and source['source_kind'] == 'live':
            train_sources.append(source['artifact_id'])
            for row in view.rows:
                if row['valid']:
                    for head in ('mouse', 'wheel'):
                        counts[row['task_id']][head][row['model_action'][head]] += 1
        if source['split'] != 'validation' or source['source_kind'] != 'live':
            continue
        for i, row in enumerate(view.rows):
            if row['valid']:
                first = view.dataset.rows[row['start']]
                frames.append(dict(artifact_id=source['artifact_id'], model_index=i, task_id=row['task_id'],
                                   observation_index=first['observation_index'], capture_id=first['capture_id']))
        legal_predictions.update((source['artifact_id'], start) for start in view.sequence_starts(79))
    seed = protocol['seeds']['sampling']
    frames.sort(key=lambda row: _seeded_hash(seed, row))
    selected = []
    deficits = {}
    for task in range(17):
        pool = [row for row in frames if row['task_id'] == task]
        selected.extend(pool[:10])
        deficits[str(task)] = max(0, 10 - len(pool))
    keys = {(row['artifact_id'], row['model_index']) for row in selected}
    selected.extend([row for row in frames if (row['artifact_id'], row['model_index']) not in keys][:200-len(selected)])
    # A missing quota is kept visible; neither duplicate frames nor another task can fill it.
    reconstruction = dict(selected=selected, task_deficits=deficits, total_deficit=max(0, 200-len(selected)))
    pools: dict[str, list] = {category: [] for category in CATEGORIES}
    candidates_id = None
    if candidates is not None:
        verify_seal(candidates)
        require(candidates.get('schema') == 'dsp-prediction-candidates/1' and
                candidates.get('index_id') == index.report['artifact_id'] and
                candidates.get('protocol_id') == protocol['artifact_id'] and
                isinstance(candidates.get('samples'), list), 'Candidate provenance mismatch')
        candidates_id = candidates['artifact_id']
        seen = set()
        for row in candidates['samples']:
            require(isinstance(row, dict) and set(row) == {'artifact_id', 'start', 'task_id', 'category',
                    'reviewed', 'evidence', 'regions', 'key_states'}, 'Invalid prediction candidate fields')
            key = (row['artifact_id'], row['start'])
            require(type(row['start']) is int and key in legal_predictions and key not in seen,
                    'Duplicate or illegal validation prediction sequence')
            seen.add(key)
            require(row['category'] in CATEGORIES and row.get('reviewed') is True and
                    isinstance(row.get('evidence'), str) and bool(row['evidence'].strip()), 'Unreviewed prediction category')
            view = index.views[row['artifact_id']]
            future = view.rows[row['start'] + 64:row['start'] + 79]
            task = future[0]['task_id']
            require(row['task_id'] == task, 'Prediction task mismatch')
            _validate_regions(row['regions'])
            require(len(row['regions']) == 1 and row['regions'][0][2]-row['regions'][0][0] >= 64
                    and row['regions'][0][3]-row['regions'][0][1] >= 64, 'Expected one affected region of at least 64x64')
            require(isinstance(row.get('key_states'), list) and row['key_states'], 'Missing prediction key states')
            for item in row['key_states']:
                require(item.get('type') in ITEM_TYPES and isinstance(item.get('expected'), str)
                        and bool(item['expected'].strip()), 'Invalid prediction key state')
            pools[row['category']].append(copy.deepcopy(row))
    prediction_selected = []
    prediction_deficits = {}
    for category, pool in pools.items():
        pool.sort(key=lambda row: _seeded_hash(seed, row))
        picked = pool[:50]
        prediction_deficits[category] = max(0, 50-len(picked))
        # Cycle within the selected same-task/category stratum. Singleton strata cannot be compared.
        groups = defaultdict(list)
        for row in picked:
            groups[row['task_id']].append(row)
        for group in groups.values():
            for i, row in enumerate(group):
                donor = group[(i+1) % len(group)]
                actions = _future_actions(index, row)
                shuffled = _future_actions(index, donor)
                row['shuffle_donor'] = dict(artifact_id=donor['artifact_id'], start=donor['start'])
                has_non_noop = any(a != ACTION_CODEC['noop'] for a in actions[:5])
                row['action_difference'] = dict(noop=has_non_noop, shuffled=actions[:5] != shuffled[:5], copy_last=has_non_noop)
                row['generation_seed'] = int(_seeded_hash(protocol['seeds']['generation'], [row['artifact_id'], row['start']])[:8], 16)
                prediction_selected.append(row)
    baseline_tasks: list[dict[str, Any]] = []
    for task, heads in counts.items():
        baseline_tasks.append(dict(task_id=task, **{head: dict(n=sum(counter.values()), counts={str(k): v for k, v in sorted(counter.items())},
            mode=min(counter, key=lambda value: (-counter[value], value)) if counter else None)
            for head, counter in heads.items()}))
    return seal(dict(schema='dsp-evaluation-inputs/1', protocol_id=protocol['artifact_id'],
        index_id=index.report['artifact_id'], sources=[dict(artifact_id=s['artifact_id'], split=s['split'],
        model_view=s['model_view']) for s in index.report['sources']], status='pending',
        annotations_status='pending', training_authorized=False, coverage_gate_passed=index.report['coverage_gate_passed'],
        reconstruction=reconstruction, prediction=dict(selected=prediction_selected, deficits=prediction_deficits,
        candidates_id=candidates_id), baseline=dict(status='ready' if all(t[head]['n'] for t in baseline_tasks for head in ('mouse', 'wheel'))
        else 'insufficient_evidence', source_split='train', source_ids=train_sources, tasks=baseline_tasks)))


def _future_actions(index, row):
    view = index.views[row['artifact_id']]
    return [r['model_action'] for r in view.rows[row['start']+64:row['start']+79]]


def _validate_regions(regions):
    require(isinstance(regions, list), 'Invalid regions')
    for box in regions:
        require(isinstance(box, list) and len(box) == 4 and all(type(v) is int for v in box), 'Invalid region box')
        x0, y0, x1, y1 = box
        require(0 <= x0 < x1 <= 640 and 0 <= y0 < y1 <= 360, 'Region outside RGB')


def authorize_test_disclosure(protocol, data_freeze, recipe_freeze):
    """Only an ordered, content-bound recipe freeze permits offline-test scores."""
    from datetime import datetime

    for artifact in (protocol, data_freeze, recipe_freeze):
        verify_seal(artifact)
    require(data_freeze.get('schema') == 'dsp-evaluation-data-freeze/1' and
            recipe_freeze.get('schema') == 'dsp-evaluation-recipe-freeze/1', 'Invalid freeze schema')
    require(data_freeze.get('protocol_id') == protocol['artifact_id'] and
            recipe_freeze.get('data_freeze_id') == data_freeze['artifact_id'], 'Freeze provenance mismatch')
    for artifact, fields in ((data_freeze, ('index_id', 'evaluation_inputs_id', 'annotations_id')),
                             (recipe_freeze, ('checkpoint_sha256', 'recipe_sha256'))):
        require(all(isinstance(artifact.get(k), str) and len(artifact[k]) == 64 and
                    all(c in '0123456789abcdef' for c in artifact[k]) for k in fields), 'Missing frozen artifact hash')
    dates = [datetime.fromisoformat(a['frozen_at']) for a in (protocol, data_freeze, recipe_freeze)]
    require(all(d.tzinfo is not None for d in dates) and dates[0] <= dates[1] <= dates[2], 'Invalid freeze order')
    require(data_freeze.get('supplementation_complete') is True and recipe_freeze.get('selection_split') == 'validation+development'
            and recipe_freeze.get('offline_test_seen') is False and recipe_freeze.get('final_seen') is False,
            'Test disclosure requires supplementation and blind recipe selection')
    return dict(offline_test_disclosure_authorized=True, recipe_freeze_id=recipe_freeze['artifact_id'],
                training_authorized=False)
