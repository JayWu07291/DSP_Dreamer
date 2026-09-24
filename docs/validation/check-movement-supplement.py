"""Check sealed handoff artifacts without reopening source datasets or RGB archives."""
from collections import Counter
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import file_info, load
from dsp_dreamer.evaluation_protocol import _seeded_hash, read_protocol, verify_seal

root = Path('runs/catalog-v4/corpus-integration-20260921')
source_dir = root / 'movement-supplement-source-01'
review_dir = root / 'movement-supplement-review-01'
source = load(source_dir / 'sources.json')
batch = load(review_dir / 'batch.json')
fragment = load(review_dir / 'confirmed-candidates.json')
confirmation = load('docs/validation/movement-priority-01-confirmed-20260924.json')
aggregate = load(confirmation['draft']['path'])
prior = load(root / 'movement-priority-review-01/human-aggregate.json')
old_batch = load(root / 'movement-priority-review-01/batch.json')
for value in (source, batch, fragment, confirmation, aggregate, prior, old_batch):
    verify_seal(value)
for folder, receipt_path in (
        (source_dir, 'docs/validation/movement-supplement-source-01-prepared-20260924.json'),
        (review_dir, 'docs/validation/movement-supplement-review-01-prepared-20260924.json')):
    export = load(folder / 'export.json')
    verify_seal(export)
    assert export == load(receipt_path)
    assert file_info(export['preparer']['path']) == export['preparer']['file']
    for name, info in export['files'].items():
        assert file_info(folder / name) == info, name
assert file_info(confirmation['draft']['path']) == confirmation['draft']['file']
assert load(confirmation['raw_submission']['path']) == confirmation['submission']
assert confirmation['submission']['raw_answer'] == '10 題的三項都正確'
assert aggregate['rows'][:205] == prior['rows']
assert aggregate['agent_region_proposals'] == prior['agent_region_proposals']
assert Counter(r['category'] for r in aggregate['rows'] if r['classification_reviewed']) == dict(movement=23, ui=63, interaction=64, waiting=64)
confirmed = [r for r in aggregate['rows'] if r['reviewed']]
assert len(confirmed) == len(fragment['samples']) == 10
for row, proposal, formal in zip(confirmed, old_batch['proposals'], fragment['samples']):
    assert row['source'] == proposal['source']
    assert row['classification_reviewed'] and row['reviewer'] == 'Jay'
    for field in ('category', 'regions', 'key_states'):
        assert row[field] == proposal['suggested_' + field] == formal[field]
    assert formal['task_id'] == source['original_task_ids'][row['source']['id']]
    assert formal['artifact_id'] == row['source']['artifact_id'] and formal['start'] == row['source']['start']
protocol = read_protocol('protocols/evaluation-v2.json')
assert protocol['artifact_id'] == source['protocol_id'] == batch['protocol_id'] == fragment['protocol_id']
index = load(root / 'workbench/training-index.json')
verify_seal(index)
assert index['artifact_id'] == source['index_id'] == fragment['index_id']
validation = {s['artifact_id']: s for s in index['sources'] if s['split'] == 'validation' and s['source_kind'] == 'live'}
assert len(validation) == 3 and len(source['source_audits']) == 3
for audit in source['source_audits']:
    assert audit['completed'] == validation[audit['artifact_id']]['model_view']['source_completed']
work = json.loads((root / 'workbench/data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
original = {(s['artifact_id'], s['start']) for s in work['prediction']}
pool = source['input_activity_candidates']
assert len(pool) == 947 and all(r['artifact_id'] in validation and r['activity_steps'] >= 3 for r in pool)
assert not original.intersection((r['artifact_id'], r['start']) for r in pool)
assert pool == sorted(pool, key=lambda r: _seeded_hash(protocol['seeds']['sampling'], {k: r[k] for k in ('artifact_id', 'start', 'task_id')}))
chosen = []
for row in pool:
    if all(row['artifact_id'] != p['artifact_id'] or abs(row['start']-p['start']) >= 15 for p in chosen):
        chosen.append(row)
    if len(chosen) == 48:
        break
assert [(r['artifact_id'], r['start']) for r in chosen] == [(r['artifact_id'], r['start']) for r in source['samples']]
for sample in source['samples']:
    observations = [source['images'][p]['observation_index'] for p in sample['images']]
    assert observations[1]-observations[0] == 10 and observations[2]-observations[0] == 30
    assert sample['boundary'] == observations[0]/20 and sample['end'] == (observations[2]+1)/20
assert len(source['images']) == source['rgb_chunks_read'] == 143
assert len(batch['proposals']) == 27 and len(batch['deferred_ids']) == 21
assert {r['source']['id'] for r in batch['proposals']}.isdisjoint(batch['deferred_ids'])
assert {r['source']['id'] for r in batch['proposals']} | set(batch['deferred_ids']) == set(batch['prescreened_ids'])
for row in batch['proposals']:
    assert row['source'] in source['samples'] and not row['reviewed'] and not row['classification_reviewed']
    assert row['suggested_regions'] == [[0, 0, 640, 360]] and row['key_state_step'] == 15
    assert row['suggested_key_states'][0]['type'] == 'cursor' and row['suggested_key_states'][0]['expected']
    for asset in [row['source']['video'], *row['source']['images']]:
        assert os.path.samefile(source_dir / asset, review_dir / asset)
assert batch['training_authorized'] is False and batch['candidates_reviewed'] == 0
page = (review_dir / 'index.html').read_text(encoding='utf-8')
assert page.count('<video ') == 27 and page.count('<figure>') == 81
assert '27 題的三項都正確' in page and '37 段' in page
print('PASS: exact 10 confirmations; 27 pending proposals; source, hashes, timing, priority and hard links; no datasets reopened')
