"""Frozen validation reconstruction outputs and human recognition gate."""
from collections import Counter
from pathlib import Path
import math

import numpy as np
from PIL import Image
import torch

from .contract import atomic_save, file_info, load, require
from .evaluation_protocol import ITEM_TYPES, read_protocol, seal, verify_seal, _validate_regions
from .tokenizer import CausalTokenizer, TokenizerConfig
from .tokenizer_training import read_checkpoint
from .training_index import TrainingIndex


def read_frozen_evaluation(catalog_path, protocol_path):
    catalog = load(catalog_path)
    protocol = read_protocol(protocol_path)
    directory = Path(catalog['evaluation_directory'])
    require(protocol['artifact_id'] == catalog['protocol_id'], 'Protocol identity mismatch')
    artifacts = {}
    for name, expected in catalog['evaluation_files'].items():
        require(file_info(directory / name) == expected, f'Frozen file changed: {name}')
        artifacts[name] = load(directory / name)
        verify_seal(artifacts[name])
    inputs, annotations, freeze = (artifacts[k] for k in
                                  ('evaluation-inputs.json', 'annotations.json', 'data-freeze.json'))
    for field, name in [('source_freeze_id', 'source-freeze.json'), ('candidate_freeze_id', 'candidate-freeze.json'),
                        ('evaluation_inputs_id', 'evaluation-inputs.json'), ('annotations_id', 'annotations.json'),
                        ('annotation_provenance_id', 'annotation-provenance.json'), ('action_evidence_id', 'validation-actions.json')]:
        require(freeze[field] == artifacts[name]['artifact_id'], f'Broken freeze link: {field}')
    require(freeze['artifact_id'] == catalog['data_freeze_id']
            and inputs['artifact_id'] == catalog['evaluation_inputs_id']
            and annotations['artifact_id'] == catalog['annotations_id']
            and freeze['index_id'] == catalog['index_id'], 'Frozen identity mismatch')
    for name, expected in artifacts['source-freeze.json']['files'].items():
        require(file_info(name) == expected, f'Frozen implementation changed: {name}')
    require(all(value['protocol_id'] == protocol['artifact_id'] for value in (inputs, annotations, freeze))
            and freeze['evaluation_inputs_id'] == inputs['artifact_id']
            and freeze['annotations_id'] == annotations['artifact_id']
            and annotations['evaluation_inputs_id'] == inputs['artifact_id']
            and freeze['supplementation_complete'] is True, "評估凍結身分不符")
    return catalog, inputs, annotations, freeze


def open_frozen_corpus(catalog_path, protocol_path):
    catalog, inputs, annotations, freeze = read_frozen_evaluation(catalog_path, protocol_path)
    index = TrainingIndex.open(catalog['training_index'], [s['path'] for s in catalog['sources']])
    require(index.report['artifact_id'] == freeze['index_id'] == inputs['index_id']
            and index.report['coverage_gate_passed'], "資料覆蓋 gate 未通過或 index 不符")
    require(inputs['sources'] == [dict(artifact_id=s['artifact_id'], split=s['split'], model_view=s['model_view'])
                                 for s in index.report['sources']], "模型視圖身分不符")
    selected = inputs['reconstruction']['selected']
    seen = set()
    splits = {s['artifact_id']: s['split'] for s in index.report['sources']}
    for sample in selected:
        artifact, row_number = sample['artifact_id'], sample['model_index']
        require(splits.get(artifact) == 'validation' and type(row_number) is int and row_number >= 0,
                "重建只能使用凍結 validation 圖")
        view = index.views[artifact]
        require(row_number < len(view) and view.rows[row_number]['valid'], "不合法重建視窗")
        row = view.dataset.rows[view.rows[row_number]['start']]
        require(row['observation_index'] == sample['observation_index'] and row['capture_id'] == sample['capture_id']
                and view.rows[row_number]['task_id'] == sample['task_id'], "重建影格身分不符")
        key = (artifact, sample['observation_index'])
        require(key not in seen, "重複重建影格")
        seen.add(key)
    ids = set()
    for item in annotations['items']:
        require(item['sample_id'] not in ids and (item['artifact_id'], item['observation_index']) in seen
                and item['type'] in ITEM_TYPES and type(item['eligible']) is bool, "不合法關鍵項目")
        ids.add(item['sample_id'])
        _validate_regions([item['box']])
        require(isinstance(item['expected'], str) and item['expected'].strip()
                and (item['eligible'] or bool(item['exclusion_reason'])), "缺少標註或排除理由")
    for region in annotations['ui_regions']:
        require((region['artifact_id'], region['observation_index']) in seen, "UI 不屬於重建名單")
        _validate_regions([region['box']])
    provenance = dict(protocol_id=freeze['protocol_id'], data_freeze_id=freeze['artifact_id'],
                      evaluation_inputs_id=inputs['artifact_id'], annotations_id=annotations['artifact_id'])
    return index, inputs, annotations, provenance


@torch.no_grad()
def evaluate_reconstruction(checkpoint_path, index, loss, inputs, annotations, output, *, device='cuda', limit=200, deadline=None):
    import time
    require(type(limit) is int and 0 < limit <= 200, "無效評估數量")
    payload = read_checkpoint(checkpoint_path)
    require(payload['index_id'] == index.report['artifact_id'] and payload['metric'] == loss.identity
            and payload['provenance']['evaluation_inputs_id'] == inputs['artifact_id']
            and payload['provenance']['annotations_id'] == annotations['artifact_id'], "評估 checkpoint 身分不符")
    model = CausalTokenizer(TokenizerConfig(**payload['model_config'])).to(device).eval()
    model.load_state_dict(payload['model'])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    recipe = seal(dict(schema='dsp-tokenizer-evaluation-recipe/1', checkpoint_sha256=file_info(checkpoint_path)['sha256'],
        metric=loss.identity, model_config=payload['model_config'], precision='bf16' if device == 'cuda' else 'float32',
        context='最多 64 個連續合法模型視窗，以被測圖為最後一張；無 masking',
        metrics='float32 sRGB [0,1]；PNG 四捨五入為 uint8，指標在量化前計算', **payload['provenance']))
    atomic_save(output / 'recipe.json', recipe)
    rows = []
    for number, sample in enumerate(inputs['reconstruction']['selected'][:limit], 1):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('已達訓練／評估總預算，未完成重建 gate')
        view = index.views[sample['artifact_id']]
        end = sample['model_index']
        start = end
        episode = view.dataset.rows[view.rows[end]['start']]['episode_id']
        while start > max(0, end - 63):
            previous = view.rows[start - 1]
            current = view.dataset.rows[view.rows[start]['start']]
            if not previous['valid'] or current['is_first'] or view.dataset.rows[previous['start']]['episode_id'] != episode:
                break
            start -= 1
        batch = view.sequence(start, end - start + 1)
        require(batch['valid_mask'].all(), "評估 history 含非法區間")
        frames = torch.from_numpy(batch['inputs']['observation']).unsqueeze(0).to(device)
        with torch.autocast(torch.device(device).type, dtype=torch.bfloat16, enabled=device == 'cuda'):
            _, decoded = model(frames)
        target, predicted = frames[0, -1].float(), decoded[0, -1].float()
        mse, perceptual = loss.per_frame(predicted[None], target[None])[0].tolist()
        mask = torch.zeros((360, 640), dtype=torch.bool, device=device)
        for region in annotations['ui_regions']:
            if (region['artifact_id'], region['observation_index']) == (sample['artifact_id'], sample['observation_index']):
                x0, y0, x1, y1 = region['box']
                mask[y0:y1, x0:x1] = True
        pixels = int(mask.sum().item())
        ui_mse = (predicted - target).square()[:, mask].mean().item() if pixels else None
        images = {}
        for name, tensor in [('source', target), ('reconstruction', predicted)]:
            filename = f'R{number:03d}-{name}.png'
            Image.fromarray((tensor.permute(1, 2, 0).cpu().numpy() * 255).round().astype(np.uint8)).save(output / filename)
            images[name] = dict(path=filename, **file_info(output / filename))
        rows.append(dict(sample=sample, context_start=start, context_length=end-start+1,
                         mse=mse, lpips=perceptual, ui_mse=ui_mse, ui_pixels=pixels, images=images))
        del batch, frames, decoded, target, predicted
    report = seal(dict(schema='dsp-reconstruction-metrics/1', recipe_id=recipe['artifact_id'],
        checkpoint_sha256=recipe['checkpoint_sha256'], frames=rows, **payload['provenance']))
    atomic_save(output / 'metrics.json', report)
    judgments = dict(schema='dsp-reconstruction-judgments/1', report_id=report['artifact_id'],
        annotations_id=annotations['artifact_id'], checkpoint_sha256=report['checkpoint_sha256'],
        items=[dict(sample_id=item['sample_id'], correct=None, reviewer='', evidence='')
               for item in annotations['items'] if item['eligible']])
    atomic_save(output / 'judgments-template.json', judgments)
    result = score_reconstruction(report, inputs, annotations)
    atomic_save(output / 'gate.json', result)
    return result


def score_reconstruction(metrics, inputs, annotations, judgments=None):
    for value in (metrics, inputs, annotations):
        verify_seal(value)
    require(metrics['evaluation_inputs_id'] == inputs['artifact_id']
            and metrics['annotations_id'] == annotations['artifact_id'], "評分 artifact 不符")
    selected = inputs['reconstruction']['selected']
    rows = metrics['frames']
    require([r['sample'] for r in rows] == selected[:len(rows)] and len(rows) <= len(selected), "評分名單不符")
    for row in rows:
        require(all(type(row[k]) in (int, float) and math.isfinite(row[k]) and row[k] >= 0 for k in ('mse', 'lpips'))
                and type(row['ui_pixels']) is int and 0 <= row['ui_pixels'] <= 360*640
                and (row['ui_mse'] is None if row['ui_pixels'] == 0 else
                     type(row['ui_mse']) in (int, float) and math.isfinite(row['ui_mse']) and row['ui_mse'] >= 0),
                "評分包含無效數值")
    eligible = [item for item in annotations['items'] if item['eligible']]
    reviews = {}
    if judgments is not None:
        if 'artifact_id' in judgments:
            verify_seal(judgments)
        require(judgments['report_id'] == metrics['artifact_id']
                and judgments['annotations_id'] == annotations['artifact_id']
                and judgments['checkpoint_sha256'] == metrics['checkpoint_sha256'], "人工判讀身分不符")
        allowed = {item['sample_id'] for item in eligible}
        for review in judgments['items']:
            sid = review['sample_id']
            require(sid in allowed and sid not in reviews and (review['correct'] is None or type(review['correct']) is bool),
                    "未知、重複或不合法人工判讀")
            require(review['correct'] is None or all(isinstance(review.get(k), str) and review[k].strip()
                    for k in ('reviewer', 'evidence')), "判讀缺 reviewer/evidence")
            reviews[sid] = review['correct']

    def counts(items):
        total = len(items)
        correct = sum(reviews.get(i['sample_id']) is True for i in items)
        pending = sum(reviews.get(i['sample_id']) is None for i in items)
        return dict(total=total, correct=correct, pending=pending,
                    accuracy=correct / total if total and not pending else None)

    overall = counts(eligible)
    categories = {kind: counts([i for i in eligible if i['type'] == kind]) for kind in ITEM_TYPES}
    quotas = Counter(s['task_id'] for s in selected)
    ui_types = {r['ui_type'] for r in annotations['ui_regions']}
    insufficient = (len(selected) != 200 or any(quotas[i] < 10 for i in range(17))
                    or any(v['total'] == 0 for v in categories.values())
                    or not {'technology', 'backpack', 'crafting', 'building', 'lab'} <= ui_types)
    status = ('insufficient_evidence' if insufficient else 'pending' if len(rows) != 200 or overall['pending']
              else 'passed' if overall['accuracy'] >= .95 and all(v['accuracy'] >= .9 for v in categories.values())
              else 'failed')
    ui_rows = [r for r in rows if r['ui_pixels']]
    tasks = {(s['artifact_id'], s['observation_index']): s['task_id'] for s in selected}
    return seal(dict(schema='dsp-reconstruction-gate/1', report_id=metrics['artifact_id'], status=status,
        judgments=seal({k: v for k, v in judgments.items() if k != 'artifact_id'}) if judgments is not None else None,
        recognition=overall, categories=categories, excluded=len(annotations['items'])-len(eligible),
        task_quotas={str(i): quotas[i] for i in range(17)},
        per_task={str(i): counts([item for item in eligible if tasks.get((item['artifact_id'], item['observation_index'])) == i])
                  for i in range(17)}, frames=len(rows), mse=float(np.mean([r['mse'] for r in rows])) if rows else None,
        lpips=float(np.mean([r['lpips'] for r in rows])) if rows else None,
        ui_mse=float(np.mean([r['ui_mse'] for r in ui_rows])) if ui_rows else None,
        ui_frames=len(ui_rows), ui_pixels=sum(r['ui_pixels'] for r in ui_rows)))
