"""Paired free prediction over the frozen validation sequences, with explicit denominators."""
from collections import Counter
from pathlib import Path
import math
import time

import numpy as np
from PIL import Image
import torch

from .actions import ACTION_CODEC
from .contract import atomic_save, file_info, require
from .dynamics import Dynamics, DynamicsConfig
from .dynamics_training import read_dynamics_checkpoint, load_tokenizer, require_reconstruction
from .evaluation_protocol import CATEGORIES, ITEM_TYPES, seal, verify_seal, _validate_regions


CONDITIONS = ('correct', 'noop', 'shuffled', 'copy_last')
STEPS = (1, 5, 15)


def validate_prediction_inputs(index, inputs):
    verify_seal(inputs)
    require(inputs['index_id'] == index.report['artifact_id'], '預測 index 不符')
    sources = {s['artifact_id']: s for s in index.report['sources']}
    selected = inputs['prediction']['selected']
    samples = {(s['artifact_id'], s['start']): s for s in selected}
    require(len(samples) == len(selected), '重複預測序列')
    legal = {}
    for sample in selected:
        artifact, start = sample['artifact_id'], sample['start']
        require(artifact in sources and sources[artifact]['split'] == 'validation', '預測只能使用 validation')
        if artifact not in legal:
            legal[artifact] = set(index.views[artifact].sequence_starts(79))
        require(type(start) is int and start in legal[artifact] and sample['category'] in CATEGORIES,
                '預測缺少 64 個歷史及 15 個合法未來視窗')
        require(sample['task_id'] == index.views[artifact].rows[start + 64]['task_id'], '預測 task 不符')
        _validate_regions(sample['regions'])
        require(len(sample['regions']) == 1 and sample['regions'][0][2] - sample['regions'][0][0] >= 64
                and sample['regions'][0][3] - sample['regions'][0][1] >= 64, '受影響區域需至少 64×64')
        require(sample['key_states'] and all(k['type'] in ITEM_TYPES and isinstance(k['expected'], str)
                and k['expected'].strip() for k in sample['key_states']), '缺少關鍵狀態標註')
        donor = samples.get((sample['shuffle_donor']['artifact_id'], sample['shuffle_donor']['start']))
        require(donor is not None and donor['task_id'] == sample['task_id']
                and donor['category'] == sample['category'], '打亂動作需同 task、同類別的已選序列')
        assert donor is not None
        actual = [r['model_action'] for r in index.views[artifact].rows[start+64:start+79]]
        shuffled = [r['model_action'] for r in index.views[donor['artifact_id']].rows[donor['start']+64:donor['start']+79]]
        different = any(a != ACTION_CODEC['noop'] for a in actual[:5])
        require(sample['action_difference'] == dict(noop=different, shuffled=actual[:5] != shuffled[:5], copy_last=different),
                '凍結動作差異與 loader 不符')


@torch.no_grad()
def evaluate_prediction(checkpoint_path, index, loss, inputs, output, *, device='cuda', limit=200, deadline=None):
    require(type(limit) is int and 0 < limit <= 200, '無效評估數量')
    validate_prediction_inputs(index, inputs)
    value = read_dynamics_checkpoint(checkpoint_path)
    require(value['index_id'] == index.report['artifact_id'] and value['sources'] == index.report['sources']
            and value['metric'] == loss.identity and value['provenance']['evaluation_inputs_id'] == inputs['artifact_id'],
            '評估 checkpoint 資料或 metric 不符')
    source = value['tokenizer_source']
    require(file_info(source['path']) == source['checkpoint'], 'Tokenizer checkpoint 已改變')
    if value['formal']:
        require_reconstruction(value['reconstruction'], source['checkpoint']['sha256'], value['provenance'])
        require(all(s['source_kind'] == 'live' for s in index.report['sources'] if s['split'] == 'validation'),
                '正式評估不可使用合成資料')
    tokenizer, _ = load_tokenizer(source['path'], device=device)
    model = Dynamics(DynamicsConfig(**value['model_config'])).to(device).eval()
    model.load_state_dict(value['model'])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    recipe = seal(dict(schema='dsp-prediction-recipe/1', checkpoint_sha256=file_info(checkpoint_path)['sha256'],
        tokenizer_source=source, model_config=value['model_config'], metric=loss.identity,
        formal=value['formal'], steps=list(STEPS), history_steps=64, forward_passes=4, context_signal=.1,
        precision='bf16' if torch.device(device).type == 'cuda' else 'float32',
        target_alignment='64 個 history transitions 的最後 next observation 起始；未來第 k 個 next observation',
        **value['provenance']))
    atomic_save(output / 'recipe.json', recipe)
    rows = []
    for number, sample in enumerate(inputs['prediction']['selected'][:limit], 1):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('已達預算，預測評估未完成')
        view = index.views[sample['artifact_id']]
        history = view.sequence(sample['start'], 64)
        future = view.sequence(sample['start'] + 64, 15)
        frames = np.concatenate((history['inputs']['observation'], history['targets']['next_observation'][-1:]))
        rgb = torch.from_numpy(frames).unsqueeze(0).to(device)
        past_actions = {k: torch.from_numpy(history['inputs'][k]).unsqueeze(0).to(device) for k in ('binary', 'mouse', 'wheel')}
        actual = {k: torch.from_numpy(future['inputs'][k]).unsqueeze(0).to(device) for k in past_actions}
        donor = sample['shuffle_donor']
        donor_rows = index.views[donor['artifact_id']].rows[donor['start']+64:donor['start']+79]
        shuffled = {k: torch.tensor([[r['model_action'][k] for r in donor_rows]], device=device) for k in past_actions}
        noop = {k: torch.tensor(ACTION_CODEC['noop'][k], device=device).expand_as(v) for k, v in actual.items()}
        targets = torch.from_numpy(future['targets']['next_observation'][[s-1 for s in STEPS]]).to(device)
        copied = rgb[0, -1:].expand(3, -1, -1, -1)
        with torch.autocast(torch.device(device).type, dtype=torch.bfloat16, enabled=torch.device(device).type == 'cuda'):
            # Encode the real history exactly once; every generated condition starts here.
            latents = tokenizer.encode(rgb)[:, -64:].float()
        conditions = {}
        images = {}

        def save_images(name, tensors):
            files = {}
            for step, tensor in zip(STEPS, tensors):
                filename = f'P{number:03d}-{name}-{step:02d}.png'
                Image.fromarray((tensor.float().permute(1, 2, 0).cpu().numpy() * 255).round().astype(np.uint8)).save(output / filename)
                files[str(step)] = dict(path=filename, **file_info(output / filename))
            images[name] = files

        save_images('target', targets)
        x0, y0, x1, y1 = sample['regions'][0]
        for name in CONDITIONS:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('已達預算，預測評估未完成')
            if name == 'copy_last':
                prediction = copied
            else:
                with torch.autocast(torch.device(device).type, dtype=torch.bfloat16, enabled=torch.device(device).type == 'cuda'):
                    predicted_latents = model.rollout(latents, past_actions,
                        {'correct': actual, 'noop': noop, 'shuffled': shuffled}[name], seed=sample['generation_seed'])
                    prediction = tokenizer.decode(predicted_latents[:, [s-1 for s in STEPS]])[0].float()
            metrics = {}
            for step, p, target in zip(STEPS, prediction, targets):
                mse, perceptual = loss.per_frame(p[None], target[None])[0].tolist()
                region = loss.per_frame(p[None, :, y0:y1, x0:x1], target[None, :, y0:y1, x0:x1])[0, 1].item()
                metrics[str(step)] = dict(mse=mse, lpips=perceptual, region_lpips=region)
            conditions[name] = metrics
            save_images(name, prediction)
        rows.append(dict(sample=sample, conditions=conditions, images=images,
                         target_sources=[future['source'][s-1] for s in STEPS]))
        del history, future, frames, rgb, targets, copied, latents, prediction
    report = seal(dict(schema='dsp-prediction-metrics/1', recipe_id=recipe['artifact_id'],
        checkpoint_sha256=recipe['checkpoint_sha256'], formal=value['formal'], samples=rows, **value['provenance']))
    atomic_save(output / 'metrics.json', report)
    judgments = dict(schema='dsp-prediction-judgments/1', report_id=report['artifact_id'],
        checkpoint_sha256=report['checkpoint_sha256'], evaluation_inputs_id=inputs['artifact_id'],
        items=[dict(sample_id=f'P{i+1:03d}-K{j+1:03d}', correct=None, reviewer='', evidence='',
                    expected=state, image=rows[i]['images']['correct']['15'])
               for i, row in enumerate(rows) for j, state in enumerate(row['sample']['key_states'])])
    atomic_save(output / 'judgments-template.json', judgments)
    result = score_prediction(report, inputs)
    atomic_save(output / 'gate.json', result)
    return result


def score_prediction(metrics, inputs, judgments=None):
    for artifact in (metrics, inputs):
        verify_seal(artifact)
    require(metrics['evaluation_inputs_id'] == inputs['artifact_id'] and type(metrics['formal']) is bool,
            '預測評分 artifact 不符')
    selected, rows = inputs['prediction']['selected'], metrics['samples']
    require(len(rows) <= len(selected) and [r['sample'] for r in rows] == selected[:len(rows)], '預測評分名單不符')
    for row in rows:
        require(set(row['conditions']) == set(CONDITIONS), '缺少配對 baseline')
        for condition in row['conditions'].values():
            require(set(condition) == {'1', '5', '15'}, '缺少預測步數')
            require(all(type(v.get(k)) in (int, float) and math.isfinite(v[k]) and v[k] >= 0
                        for v in condition.values() for k in ('mse', 'lpips', 'region_lpips')), '非有限或非法預測分數')
    items = [(f'P{i+1:03d}-K{j+1:03d}', sample) for i, sample in enumerate(selected)
             for j, _ in enumerate(sample['key_states'])]
    reviews = {}
    if judgments is not None:
        if 'artifact_id' in judgments:
            verify_seal(judgments)
        require(judgments['report_id'] == metrics['artifact_id']
                and judgments['checkpoint_sha256'] == metrics['checkpoint_sha256']
                and judgments['evaluation_inputs_id'] == inputs['artifact_id'], '人工判讀身分不符')
        allowed = {key for key, _ in items}
        for review in judgments['items']:
            key = review['sample_id']
            require(key in allowed and key not in reviews and (review['correct'] is None or type(review['correct']) is bool),
                    '未知、重複或非法人工判讀')
            require(review['correct'] is None or all(isinstance(review.get(k), str) and review[k].strip()
                    for k in ('reviewer', 'evidence')), '人工判讀缺 reviewer/evidence')
            reviews[key] = review['correct']

    def counts(subset):
        total = len(subset)
        correct = sum(reviews.get(key) is True for key, _ in subset)
        pending = sum(reviews.get(key) is None for key, _ in subset)
        return dict(total=total, correct=correct, pending=pending,
                    accuracy=correct / total if total and not pending else None)

    recognition = counts(items)
    categories = {kind: counts([(key, s) for key, s in items if s['category'] == kind]) for kind in CATEGORIES}
    comparisons: dict[str, dict] = {}
    for category in CATEGORIES:
        pool = [r for r in rows if r['sample']['category'] == category]
        comparisons[category] = {}
        for baseline in CONDITIONS[1:]:
            pairs = []
            for row in pool:
                correct = row['conditions']['correct']['5']['region_lpips']
                error = row['conditions'][baseline]['5']['region_lpips']
                reasons = ([] if row['sample']['action_difference'][baseline] else ['no_action_difference'])
                if error == 0:
                    reasons.append('baseline_error_zero')
                pairs.append(dict(artifact_id=row['sample']['artifact_id'], start=row['sample']['start'],
                                  correct=correct, baseline=error, exclusion_reasons=reasons))
            comparable = [p for p in pairs if not p['exclusion_reasons']]
            correct_mean = float(np.mean([p['correct'] for p in comparable])) if comparable else None
            baseline_mean = float(np.mean([p['baseline'] for p in comparable])) if comparable else None
            improvement = ((baseline_mean - correct_mean) / baseline_mean
                           if baseline_mean and correct_mean is not None else None)
            comparisons[category][baseline] = dict(candidates=len(pairs), denominator=len(comparable),
                no_action_difference=sum('no_action_difference' in p['exclusion_reasons'] for p in pairs),
                zero_error=sum('baseline_error_zero' in p['exclusion_reasons'] for p in pairs),
                correct_mean=correct_mean, baseline_mean=baseline_mean, relative_improvement=improvement,
                passed=improvement is not None and improvement >= .1, pairs=pairs)
    quotas = Counter(s['category'] for s in selected)
    required = [comparisons[c][b] for c in CATEGORIES[:3] for b in CONDITIONS[1:]]
    insufficient = (quotas != Counter({c: 50 for c in CATEGORIES}) or any(not s['key_states'] for s in selected)
                    or len(rows) == len(selected) and any(v['denominator'] == 0 for v in required))
    status = ('engineering_only' if not metrics['formal'] else 'insufficient_evidence' if insufficient
              else 'pending' if len(rows) != 200 or recognition['pending']
              else 'passed' if all(v['passed'] for v in required) and recognition['accuracy'] >= .8
                   and all(categories[c]['accuracy'] >= .7 for c in CATEGORIES[:3]) else 'failed')

    def averages(subset):
        return dict(sequences=len(subset), conditions={c: {str(s): {k:
            float(np.mean([r['conditions'][c][str(s)][k] for r in subset])) if subset else None
            for k in ('mse', 'lpips', 'region_lpips')} for s in STEPS} for c in CONDITIONS})

    return seal(dict(schema='dsp-prediction-gate/1', status=status, report_id=metrics['artifact_id'],
        judgments=seal({k: v for k, v in judgments.items() if k != 'artifact_id'}) if judgments is not None else None,
        sequences=len(rows), quotas=dict(quotas), recognition=recognition, categories=categories,
        comparisons=comparisons, overall=averages(rows),
        per_category={c: averages([r for r in rows if r['sample']['category'] == c]) for c in CATEGORIES},
        per_task={str(t): dict(**averages([r for r in rows if r['sample']['task_id'] == t]),
                  recognition=counts([(key, s) for key, s in items if s['task_id'] == t])) for t in range(17)}))
