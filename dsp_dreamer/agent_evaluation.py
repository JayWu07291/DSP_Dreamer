"""Exact-transition reward and deduplicated relevant-policy validation gates."""
from collections import Counter, defaultdict
import math
from pathlib import Path
import time

import numpy as np
import torch

from .actions import ACTION_CODEC, forbidden_buttons
from .agent import Agent, incoming_actions, reward_expectation
from .agent_training import read_agent_checkpoint, sequence_pools
from .contract import atomic_save, file_info, require, sha
from .dynamics import Dynamics, DynamicsConfig
from .dynamics_training import load_tokenizer, verify_implementation
from .dynamics_evaluation import score_prediction
from .evaluation_protocol import seal, verify_seal


def classification(truth, predicted):
    tp = sum(a and b for a, b in zip(truth, predicted))
    fp = sum(not a and b for a, b in zip(truth, predicted))
    fn = sum(a and not b for a, b in zip(truth, predicted))
    n = len(truth)
    return dict(n=n, positives=tp+fn, predicted_positives=tp+fp, tp=tp, fp=fp, fn=fn, tn=n-tp-fp-fn,
                precision=tp/(tp+fp) if tp+fp else None, recall=tp/(tp+fn) if tp+fn else None,
                base_rate=(tp+fn)/n if n else None)


def average_precision(rows):
    positives = sum(r['reward'] for r in rows)
    if not positives:
        return None
    groups: dict[float, list] = defaultdict(list)
    for row in rows:
        groups[row['score']].append(row['reward'])
    tp = n = 0
    area = 0.
    for score in sorted(groups, reverse=True):
        increment = sum(groups[score])
        tp += increment
        n += len(groups[score])
        area += increment / positives * tp / n
    return area


def reward_metrics(rows):
    require(all(type(r['score']) in (int, float) and math.isfinite(r['score'])
                and r['reward'] in (0, 1) and 0 <= r['task_id'] <= 16 for r in rows), '非法 reward 評估值')
    tasks = {}
    for task in range(16):
        subset = [r for r in rows if r['task_id'] == task]
        counts = classification([bool(r['reward']) for r in subset], [r['score'] >= .5 for r in subset])
        status = ('insufficient_evidence' if counts['precision'] is None or counts['recall'] is None
                  else 'passed' if counts['precision'] >= .8 and counts['recall'] >= .8 else 'failed')
        tasks[str(task)] = dict(**counts, pr_auc=average_precision(subset), status=status)
    # Exact matches first, then adjacent pairs, ordered by prediction and target time.
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[(row['artifact_id'], row['episode_id'], row['segment'], row['task_id'])].append(row)
    matched = predicted = positives = 0
    for subset in groups.values():
        target = {r['model_index'] for r in subset if r['reward']}
        guesses = {r['model_index'] for r in subset if r['score'] >= .5}
        positives += len(target)
        predicted += len(guesses)
        pairs = sorted((abs(p-t), p, t) for p in guesses for t in (p-1, p, p+1) if t in target)
        used_p, used_t = set(), set()
        for _, p, t in pairs:
            if p not in used_p and t not in used_t:
                used_p.add(p)
                used_t.add(t)
        matched += len(used_p)

    def false_positives(subset):
        return dict(n=len(subset), fp=sum(r['score'] >= .5 for r in subset))

    return dict(status=gate_status([t['status'] for t in tasks.values()]), per_task=tasks,
        n=len(rows), alignment='exact_transition', threshold=.5,
        pr_auc_definition='non-interpolated average precision; tied scores share one threshold',
        waiting=false_positives([r for r in rows if r['task_id'] == 16]),
        non_active=false_positives([r for r in rows if r['non_active'] and r['reward'] == 0]),
        delay_diagnostic=dict(tp=matched, fp=predicted-matched, fn=positives-matched, tolerance_steps=1,
                              used_for_gate=False))


def gate_status(statuses):
    if 'insufficient_evidence' in statuses:
        return 'insufficient_evidence'
    if 'pending' in statuses:
        return 'pending'
    return 'passed' if statuses and all(s == 'passed' for s in statuses) else 'failed'


def train_baseline(index):
    counts: dict[int, dict[str, Counter]] = {task: {k: Counter() for k in ('mouse', 'wheel')} for task in range(17)}
    sources = []
    for source in index.report['sources']:
        if source['split'] != 'train':
            continue
        sources.append(source['artifact_id'])
        for row in index.views[source['artifact_id']].rows:
            if row['valid']:
                for k in ('mouse', 'wheel'):
                    counts[row['task_id']][k][row['model_action'][k]] += 1
    tasks: list[dict] = [dict(task_id=t, **{k: dict(n=sum(c.values()), counts={str(i): v for i, v in sorted(c.items())},
        mode=min(c, key=lambda i: (-c[i], i)) if c else None) for k, c in heads.items()}) for t, heads in counts.items()]
    return dict(status='ready' if all(t[k]['n'] for t in tasks for k in ('mouse', 'wheel')) else 'insufficient_evidence',
                source_split='train', source_ids=sources, tasks=tasks)


def policy_metrics(rows, baseline):
    require(baseline['source_split'] == 'train' and len(baseline['tasks']) == 17, '需要 train task-conditioned baseline')
    modes = {t['task_id']: t for t in baseline['tasks']}
    require(set(modes) == set(range(17)), 'Baseline task 不完整')
    predictions, nlls = [], []
    for row in rows:
        probabilities = row['probabilities']
        arrays = {k: np.asarray(probabilities[k], dtype=np.float64) for k in ('binary', 'mouse', 'wheel')}
        for k, width in (('binary', 21), ('mouse', 121), ('wheel', 3)):
            p = arrays[k]
            require(p.shape == (width,) and np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()
                    and (k == 'binary' or abs(float(p.sum()) - 1) < 1e-5), '非法 policy 機率')
        predicted = dict(binary=(arrays['binary'] >= .5).astype(int).tolist(),
                         mouse=int(arrays['mouse'].argmax()), wheel=int(arrays['wheel'].argmax()))
        predictions.append(predicted)
        target = row['action']
        probabilities_at_target = [p if bit else 1-p for p, bit in zip(arrays['binary'], target['binary'])]
        probabilities_at_target += [arrays[k][target[k]] for k in ('mouse', 'wheel')]
        nlls.append(-math.fsum(math.log(p) for p in probabilities_at_target) if all(probabilities_at_target) else math.inf)
    controls = {}
    for i, control in enumerate(ACTION_CODEC['controls']):
        counts = classification([bool(r['action']['binary'][i]) for r in rows], [bool(p['binary'][i]) for p in predictions])
        f1 = 2*counts['tp']/(2*counts['tp']+counts['fp']+counts['fn']) if counts['positives'] else None
        controls[control] = dict(**counts, f1=f1, status='included' if f1 is not None else 'missing_positives')
    included = [v['f1'] for v in controls.values() if v['f1'] is not None]
    macro = math.fsum(included)/len(included) if included else None
    continuous = {}
    for k, zero in (('mouse', 60), ('wheel', 1)):
        pairs = [(r, p) for r, p in zip(rows, predictions) if r['action'][k] != zero]
        missing = sum(modes[r['task_id']][k]['mode'] is None for r, _ in pairs)
        correct = sum(r['action'][k] == p[k] for r, p in pairs)
        baseline_correct = sum(r['action'][k] == modes[r['task_id']][k]['mode'] for r, _ in pairs)
        n = len(pairs)
        accuracy = correct/n if n else None
        baseline_accuracy = baseline_correct/n if n and not missing else None
        passed = bool(n and not missing and 2*correct >= n and 10*(correct-baseline_correct) >= n)
        continuous[k] = dict(n=n, correct=correct, baseline_correct=baseline_correct if not missing else None,
            missing_baseline=missing, accuracy=accuracy, baseline_accuracy=baseline_accuracy,
            improvement_pp=100*(correct-baseline_correct)/n if n and not missing else None,
            status='insufficient_evidence' if not n or missing else 'passed' if passed else 'failed')
    nonfinite = sum(not math.isfinite(v) for v in nlls)
    n = len(rows)
    raw_noop = sum(p == ACTION_CODEC['noop'] for p in predictions)
    forbidden = sum(forbidden_buttons(p['binary']) for p in predictions)
    states = [v['status'] for v in continuous.values()]
    states.append('insufficient_evidence' if macro is None or nonfinite else 'passed' if macro >= .6 else 'failed')
    return dict(status=gate_status(states), n=n, per_control=controls, binary_macro_f1=macro,
                included_controls=len(included), **continuous,
                joint_nll='infinity' if nonfinite else math.fsum(nlls)/n if n else None, nonfinite_nll=nonfinite,
                noop=dict(predicted=raw_noop, actual=sum(r['action'] == ACTION_CODEC['noop'] for r in rows), n=n,
                          rate=raw_noop/n if n else None),
                forbidden=dict(count=forbidden, n=n, rate=forbidden/n if n else None))


def evaluation_rows(index):
    """Metadata only: privileged targets are never part of the model call."""
    relevant: dict[str, set] = defaultdict(set)
    for artifact, start in sequence_pools(index, 64, 'validation')['relevant']:
        relevant[artifact].update(range(start, start + 64))
    result = []
    for source in index.report['sources']:
        if source['split'] != 'validation':
            continue
        artifact = source['artifact_id']
        view = index.views[artifact]
        complete = {e['episode_id'] for e in source['episodes'] if e['validity_status'] == 'valid'
                    and e['episode_outcome'] is not None and e['final_capture_id'] is not None and e['start_ticks'] is not None
                    and not view.dataset.metadata['diagnostic_mode']}
        segment, previous = -1, None
        for i, row in enumerate(view.rows):
            first = view.dataset.rows[row['start']]
            if previous != (first['episode_id'], row['task_id']) or first['is_first'] or not row['valid']:
                segment += 1
            previous = (first['episode_id'], row['task_id']) if row['valid'] else None
            reward_eligible = first['episode_id'] in complete and row['valid']
            policy_eligible = i in relevant[artifact]
            if reward_eligible or policy_eligible:
                result.append(dict(artifact_id=artifact, model_index=i, episode_id=first['episode_id'], segment=segment,
                    task_id=row['task_id'], reward=row['reward'], action=row['model_action'],
                    non_active=any(n != row['task_id'] for n in row['node_completions']),
                    reward_eligible=reward_eligible, policy_eligible=policy_eligible,
                    transition_indices=list(range(row['start'], row['stop']))))
    return result


def score_agent(index, predictions, *, baseline=None):
    expected = evaluation_rows(index)
    require([(r['artifact_id'], r['model_index']) for r in predictions] ==
            [(r['artifact_id'], r['model_index']) for r in expected], '評估必須完整、依序且不可重複 transition')
    actual_baseline = train_baseline(index)
    require(baseline is None or baseline == actual_baseline, '凍結 baseline 與 train 不符')
    rows = [dict(**r, score=p['score'], probabilities=p['probabilities']) for r, p in zip(expected, predictions)]
    rewards = [r for r in rows if r['reward_eligible']]
    policies = [r for r in rows if r['policy_eligible']]
    return dict(reward=reward_metrics(rewards), policy=policy_metrics(policies, actual_baseline),
        per_task={str(t): policy_metrics([r for r in policies if r['task_id'] == t], actual_baseline) for t in range(17)},
        baseline=actual_baseline, transitions=rows)


@torch.no_grad()
def evaluate_agent(checkpoint_path, index, inputs, output, *, device='cuda', deadline=None):
    value = read_agent_checkpoint(checkpoint_path)
    verify_seal(inputs)
    require(value['index_id'] == index.report['artifact_id'] == inputs['index_id']
            and value['sources'] == index.report['sources']
            and value['provenance'].get('evaluation_inputs_id') == inputs['artifact_id'], '評估 checkpoint 資料來源不符')
    if value['provenance'].get('implementation'):
        verify_implementation(value['provenance'])
    source = value['tokenizer_source']
    require(file_info(source['path']) == source['checkpoint'], 'Tokenizer checkpoint 已改變')
    tokenizer, _ = load_tokenizer(source['path'], device=device)
    model = Agent(Dynamics(DynamicsConfig(**value['model_config']))).to(device).eval()
    model.load_state_dict({**{f'dynamics.{k}': v for k, v in value['model'].items()}, **value['agent']})
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    recipe = seal(dict(schema='dsp-agent-evaluation-recipe/1', checkpoint_sha256=file_info(checkpoint_path)['sha256'],
        formal=value['formal'], status='pending' if value['formal'] else 'engineering_only',
        index_id=value['index_id'], agent_config=value['agent_config'],
        history_steps=64, signal=.1, generation_seed=2601, precision='bf16' if torch.device(device).type == 'cuda' else 'float32',
        **value['provenance']))
    atomic_save(output / 'recipe.json', recipe)
    predictions = []
    for row in evaluation_rows(index):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('已達預算，policy/reward 評估未完成')
        view = index.views[row['artifact_id']]
        end = start = row['model_index']
        while start > max(0, end - 63):
            previous = view.rows[start-1]
            first = view.dataset.rows[view.rows[start]['start']]
            if not previous['valid'] or first['is_first'] or view.dataset.rows[previous['start']]['episode_id'] != row['episode_id']:
                break
            start -= 1
        batch = view.sequence(start, end-start+1)
        tensors = {k: torch.from_numpy(v).unsqueeze(0).to(device) for k, v in batch['inputs'].items()}
        past = incoming_actions({k: tensors[k] for k in ('binary', 'mouse', 'wheel')})
        seed = int(sha(f"2601:{row['artifact_id']}:{end}".encode())[:8], 16)
        generator = torch.Generator(device=device).manual_seed(seed)
        with torch.autocast(torch.device(device).type, dtype=torch.bfloat16, enabled=torch.device(device).type == 'cuda'):
            clean = tokenizer.encode(tensors['observation']).float()
            noisy = .1 * clean + .9 * torch.randn(clean.shape, device=device, generator=generator)
            outputs = model(noisy, past, tensors['task_condition'], torch.full(clean.shape[:2], .1, device=device))
        logits = {k: v[0, -1, 0].float() for k, v in outputs.items()}
        probabilities = {k: (v.sigmoid() if k == 'binary' else v.softmax(-1)).tolist()
                         for k, v in logits.items() if k != 'reward'}
        predictions.append(dict(artifact_id=row['artifact_id'], model_index=end,
                                score=reward_expectation(logits['reward']).item(), probabilities=probabilities))
    result = score_agent(index, predictions, baseline=inputs.get('baseline'))
    report = seal(dict(schema='dsp-agent-metrics/1', recipe_id=recipe['artifact_id'],
        checkpoint_sha256=recipe['checkpoint_sha256'], formal=value['formal'], index_id=value['index_id'],
        status='pending' if value['formal'] else 'engineering_only',
        **value['provenance'], **result))
    atomic_save(output / 'metrics.json', report)
    # A policy/reward report cannot certify the candidate without its own dynamics gate.
    gate = combine_gates(report, index, inputs, checkpoint_path=checkpoint_path, recipe=recipe)
    atomic_save(output / 'gate.json', gate)
    return gate


def combine_gates(metrics, index, inputs, *, checkpoint_path, recipe, prediction=None):
    value = read_agent_checkpoint(checkpoint_path)
    for artifact in (metrics, inputs, recipe):
        verify_seal(artifact)
    require(metrics['checkpoint_sha256'] == file_info(checkpoint_path)['sha256'] == recipe['checkpoint_sha256']
            and metrics['recipe_id'] == recipe['artifact_id'] and metrics['formal'] == value['formal'] == recipe['formal']
            and metrics['index_id'] == value['index_id'] == index.report['artifact_id'] == inputs['index_id'],
            '第二階段評估 checkpoint 或 recipe 不符')
    require(all(metrics.get(k) == recipe.get(k) == value['provenance'].get(k) for k in
                ('protocol_id', 'data_freeze_id', 'evaluation_inputs_id', 'annotations_id', 'implementation'))
            and metrics['evaluation_inputs_id'] == inputs['artifact_id'], '第二階段評估凍結來源不同')
    rescored = score_agent(index, metrics['transitions'], baseline=inputs.get('baseline'))
    require(all(metrics[k] == v for k, v in rescored.items()), '第二階段評分內容不符')
    dynamics = dict(status='pending', threshold_status='pending')
    if prediction is not None:
        require(prediction['metrics']['checkpoint_sha256'] == metrics['checkpoint_sha256'], 'Dynamics gate 不是此第二階段 checkpoint')
        dynamics = score_prediction(prediction['metrics'], inputs, prediction['gate']['judgments'],
                                    checkpoint_path=checkpoint_path, recipe=prediction['recipe'])
        require(dynamics == prediction['gate'], 'Dynamics gate 內容不符')
    status = gate_status([metrics['reward']['status'], metrics['policy']['status'], dynamics['threshold_status']])
    return seal(dict(schema='dsp-agent-gate/1', status=status if value['formal'] else 'engineering_only',
        threshold_status=status, checkpoint_sha256=metrics['checkpoint_sha256'], report_id=metrics['artifact_id'],
        reward=metrics['reward'], policy=metrics['policy'], dynamics=dynamics,
        qualified=value['formal'] and status == 'passed'))
