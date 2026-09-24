"""Freeze confirmed labels using the existing sampler and verified validation tables.

--check validates the saved artifacts without reopening datasets or action tables.
The full corpus, RGB archives and train baseline are not rebuilt.
"""
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.actions import ACTION_CODEC
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import (
    CATEGORIES, ITEM_TYPES, _seeded_hash, _validate_regions, prepare_evaluation,
    read_protocol, seal, validate_trials, verify_seal,
)
from dsp_dreamer.model_view import ModelView

ROOT = Path('runs/catalog-v4/corpus-integration-20260921')
OUT = ROOT / 'evaluation-freeze-20260924'
CONFIRMED = Path('docs/validation/sequence-state-completion-02-confirmed-20260924.json')
RECEIPT = Path('docs/validation/evaluation-data-freeze-20260924.json')
FORMAL_FIELDS = {'artifact_id','start','task_id','category','reviewed','evidence','regions','key_states'}


def sealed(path):
    value = load(path)
    verify_seal(value)
    return value


def verify_confirmation():
    receipt = sealed(CONFIRMED)
    aggregate = sealed(receipt['draft']['path'])
    candidates = sealed(receipt['formal_candidates']['path'])
    prior_receipt = sealed('docs/validation/sequence-state-completion-01-confirmed-20260924.json')
    prior = sealed(prior_receipt['draft']['path'])
    prior_candidates = sealed(prior_receipt['formal_candidates']['path'])
    batch = sealed(ROOT / 'sequence-state-completion-02/batch.json')
    export = sealed('docs/validation/sequence-state-completion-02-prepared-20260924.json')
    for r in (receipt,prior_receipt):
        for field in ('draft','formal_candidates','raw_submission'):
            require(file_info(r[field]['path']) == r[field]['file'], 'Changed confirmation source')
    require(sealed(receipt['raw_submission']['path']) == receipt['submission'], 'Changed human answer')
    require(receipt['submission']['raw_answer'] == '127 題的兩項都正確', 'Wrong confirmation')
    require(receipt['submission']['confirmed_fields'] == ['regions','step15_key_states'], 'Wrong confirmation scope')
    require(export['batch_id'] == batch['artifact_id'] == receipt['submission']['batch_id'], 'Wrong reviewed batch')
    require(batch['human_aggregate_id'] == prior['artifact_id'] == aggregate['prior_aggregate_id'], 'Broken aggregate chain')
    require(receipt['proposal_export_id'] == export['artifact_id'], 'Wrong proposal export')
    for name in ('batch.json','index.html'):
        require(file_info(ROOT / 'sequence-state-completion-02' / name) == export['files'][name], 'Changed reviewed page')
    proposals = {p['source']['id']: p for p in batch['proposals']}
    require(len(proposals) == len(receipt['submission']['confirmed_ids']) == 127 and set(proposals) == set(receipt['submission']['confirmed_ids']), 'Wrong confirmed IDs')
    require(len(aggregate['rows']) == len(prior['rows']) == 242, 'Changed row count')
    changed_fields = {'regions','key_states','key_state_step','reviewed','state_confirmation'}
    for old,new in zip(prior['rows'],aggregate['rows']):
        key = new['source']['id']
        if key not in proposals:
            require(new == old, 'Unrelated human row changed')
            continue
        p = proposals[key]
        require({k:v for k,v in old.items() if k not in changed_fields} == {k:v for k,v in new.items() if k not in changed_fields}, 'Original answer changed')
        require(new['source'] == p['source'] and new['category'] == p['category'], 'Changed source/category')
        require(new['regions'] == p['suggested_regions'] and new['key_states'] == p['suggested_key_states'] and new['key_state_step'] == 15 and new['reviewed'], 'Incorrect promotion')
        require(new['state_confirmation']['confirmation_id'] == receipt['submission']['artifact_id'], 'Missing confirmation reference')
    require(candidates['samples'][:114] == prior_candidates['samples'] and len(candidates['samples']) == 241, 'Old candidates changed')
    tasks = sealed(ROOT / 'movement-supplement-source-01/sources.json')
    task_export = sealed(ROOT / 'movement-supplement-source-01/export.json')
    require(file_info(ROOT / 'movement-supplement-source-01/sources.json') == task_export['files']['sources.json'], 'Changed task mapping')
    for p,formal in zip(batch['proposals'],candidates['samples'][114:]):
        s = p['source']
        require(formal == dict(artifact_id=s['artifact_id'],start=s['start'],task_id=tasks['original_task_ids'][s['id']],category=p['category'],reviewed=True,evidence=s['evidence'],regions=p['suggested_regions'],key_states=p['suggested_key_states']), 'Incorrect formal row')
    require(aggregate['complete_counts'] == dict(movement=50,ui=63,interaction=64,waiting=64), 'Incomplete labels')
    require(aggregate['pending_classifications'] == ['P085'], 'Uncertainty removed')
    return receipt, aggregate, candidates


def freeze():
    require(not OUT.exists(), 'Refusing to overwrite frozen output')
    confirmation, aggregate, candidates = verify_confirmation()
    protocol = read_protocol('protocols/evaluation-v2.json')
    index = sealed(ROOT / 'training-index.json')
    base = sealed(ROOT / 'evaluation-inputs.json')
    integration = sealed(ROOT / 'review.json')
    integration_receipt = sealed('docs/validation/corpus-integration-20260921.json')
    require(integration_receipt['integration'] == integration, 'Changed integration review')
    require(index['artifact_id'] == base['index_id'] == aggregate['index_id'] == integration['index_id'], 'Wrong index')
    require(protocol['artifact_id'] == base['protocol_id'] == aggregate['protocol_id'], 'Wrong protocol')
    require(base['artifact_id'] == aggregate['evaluation_inputs_id'] == integration['evaluation_inputs_id'], 'Wrong original inputs')
    require(index['coverage_gate_passed'] and base['baseline']['status'] == 'ready' and base['baseline']['source_split'] == 'train', 'Unmet data gate')
    work = ROOT / 'workbench'
    work_export = sealed(work / 'export.json')
    require(work_export['artifact_id'] == aggregate['workbench_id'], 'Wrong workbench')
    require(file_info(work / 'data.js') == work_export['files']['data.js'], 'Changed image mapping')
    data = json.loads((work / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
    source_audits, views, recorded_trials = [], {}, []
    validation_sources = []
    for source in index['sources']:
        paths = [Path(p) for p,digest in integration['source_completed'].items() if digest == source['model_view']['source_completed']]
        require(len(paths) == 1, 'Ambiguous frozen source')
        path = paths[0]
        require(file_info(path / 'COMPLETED') == source['model_view']['source_completed'], 'Changed source manifest')
        completed = load(path / 'COMPLETED')
        require(file_info(path / 'dataset.json') == completed['files']['dataset.json'], 'Changed source metadata')
        metadata = load(path / 'dataset.json')
        require(metadata['artifact_id'] == source['artifact_id'], 'Wrong source identity')
        recorded_trials.append(metadata['trial_manifest'])
        audit = dict(artifact_id=source['artifact_id'],path=path.as_posix(),split=source['split'],
            completed=source['model_view']['source_completed'],metadata=completed['files']['dataset.json'],
            model_view=source['model_view'],source_manifest=source['source_manifest'])
        if source['split'] == 'validation' and source['source_kind'] == 'live':
            tables = ('transitions.parquet','events.parquet')
            for name in tables:
                require(file_info(path / name) == completed['files'][name], 'Changed validation table')
            dataset = SimpleNamespace(path=path,metadata=metadata,
                rows=pq.read_table(path / 'transitions.parquet').to_pylist(),
                events=[json.loads(e['payload_json']) for e in pq.read_table(path / 'events.parquet').to_pylist()])
            view = ModelView(dataset)
            require(view.metadata == source['model_view'] and view.sequence_starts(64) == source['uniform'], 'Changed legal model view')
            views[source['artifact_id']] = view
            validation_sources.append(source)
            audit['tables'] = {name:completed['files'][name] for name in tables}
        source_audits.append(audit)
    require(len(views) == 3 and len(source_audits) == 24, 'Wrong source counts')
    validate_trials(load('protocols/evaluation-trials-v1.json'),index['registry'],recorded_trials,expected_id=protocol['trials_id'])
    # Only validation participates in these two selections. This in-memory input
    # projection is not a new TrainingIndex artifact. Discard its empty baseline;
    # retain the exact train baseline and full source list from the sealed packet.
    projection = SimpleNamespace(report=dict(artifact_id=index['artifact_id'],sequence_length=64,
        coverage_gate_passed=index['coverage_gate_passed'],sources=validation_sources),views=views)
    selected = prepare_evaluation(projection, protocol, candidates)
    require(selected['reconstruction'] == base['reconstruction'], 'Original 200-image selection changed')
    require(not any(selected['prediction']['deficits'].values()) and len(selected['prediction']['selected']) == 200, 'Prediction quota unmet')
    packet = seal({**{k:v for k,v in base.items() if k != 'artifact_id'},
        'prediction':selected['prediction'], 'annotations_status':'frozen'})
    now = datetime.now(timezone.utc).isoformat()
    evidence = []
    human_rows = {(r['source']['artifact_id'],r['source']['start']):r for r in aggregate['rows'] if r['reviewed']}
    for row in candidates['samples']:
        view = views[row['artifact_id']]; start = row['start']
        require(start in view.sequence_starts(79), 'Illegal confirmed sequence')
        first = view.dataset.rows[view.rows[start]['start']]
        anchors = [view.dataset.rows[view.rows[start+i]['stop']-1] for i in (63,68,78)]
        human = human_rows[(row['artifact_id'],start)]['source']
        require(human['observation_index'] == anchors[-1]['next_observation_index'], 'Wrong step15 source')
        require(row['evidence'] == f"{row['artifact_id']}:captures:{first['capture_id']}-{anchors[-1]['next_capture_id']}", 'Wrong capture evidence')
        evidence.append(dict(artifact_id=row['artifact_id'],start=start,id=human['id'],
            task_id=row['task_id'],category=row['category'],episode_id=first['episode_id'],
            anchor_observations=[a['next_observation_index'] for a in anchors],
            future_actions=[r['model_action'] for r in view.rows[start+64:start+79]],
            task_switches=[r['task_switches'] for r in view.rows[start:start+79]]))
    action_evidence = seal(dict(schema='dsp-frozen-validation-actions/1',index_id=index['artifact_id'],rows=evidence,
        source_audits=source_audits,validation_table_sources_read=3,rgb_chunks_read=0,full_dataset_opens=0))
    ui_receipt = sealed('docs/validation/ui-regions-02-confirmed-20260921.json')
    draft_path = ui_receipt['cumulative_draft']['path']
    require(file_info(draft_path) == ui_receipt['cumulative_draft']['file'], 'Changed reconstruction annotations')
    draft = load(draft_path)
    require(not draft['pending_questions'] and not draft['unresolved_items'], 'Unresolved reconstruction labels')
    require(draft['protocol_id'] == protocol['artifact_id'] and draft['evaluation_inputs_id'] == base['artifact_id'] and draft['index_id'] == index['artifact_id'], 'Wrong annotation inputs')
    images = {r['id']:r for r in data['reconstruction']}
    items, provenance = [], []
    for record in draft['records'].values():
        s = record['source']
        require(s == images[s['id']], 'Changed annotated source')
        require(file_info(work / s['image']) == work_export['files'][s['image']], 'Changed annotated image')
        for i,item in enumerate(record['items'],1):
            _validate_regions([item['box']])
            require(item['type'] in ITEM_TYPES and item['expected'] and item['reviewer'] == 'Jay' and item['reviewed_at'], 'Unconfirmed item')
            sid = f"{s['id']}-I{i:02}"
            items.append(dict(sample_id=sid,artifact_id=s['artifact_id'],observation_index=s['observation_index'],
                **{k:item[k] for k in ('type','box','expected','eligible','exclusion_reason')}))
            provenance.append(dict(sample_id=sid,source=s,original_item=item))
    regions = draft['ui_region_reviews']
    for r in regions:
        s = r['source']; _validate_regions([r['box']])
        require(r['reviewed'] and s == images[s['id']] and file_info(work / s['image']) == work_export['files'][s['image']], 'Unconfirmed UI region')
    require(len(items) == 15 and set(i['type'] for i in items if i['eligible']) == set(ITEM_TYPES), 'Missing key item type')
    require(len(regions) == 8 and {r['ui_type'] for r in regions} == {'backpack','crafting','technology','building','lab'}, 'Missing UI type')
    annotations = seal(dict(schema='dsp-evaluation-annotations/1',protocol_id=protocol['artifact_id'],
        evaluation_inputs_id=packet['artifact_id'],annotator='Jay',frozen_at=now,items=items,
        ui_regions=[dict(artifact_id=r['source']['artifact_id'],observation_index=r['source']['observation_index'],box=r['box'],ui_type=r['ui_type']) for r in regions]))
    annotation_provenance = seal(dict(schema='dsp-frozen-annotation-provenance/1',annotations_id=annotations['artifact_id'],
        original_evaluation_inputs_id=base['artifact_id'],reconstruction_unchanged=True,
        draft=dict(path=draft_path,file=file_info(draft_path)),ui_receipt_id=ui_receipt['artifact_id'],
        items=provenance,ui_region_reviews=regions,whole_frames_reviewed=draft['whole_frames_reviewed']))
    candidate_freeze = seal(dict(schema='dsp-prediction-candidate-freeze/1',protocol_id=protocol['artifact_id'],
        index_id=index['artifact_id'],candidates_id=candidates['artifact_id'],annotator='Jay',frozen_at=now,
        confirmation_id=confirmation['artifact_id'],aggregate_id=aggregate['artifact_id'],
        candidates_count=241,selected_count=200,unresolved=['P085'],unselected_confirmed=41,
        selection_seed=protocol['seeds']['sampling'],selection_key='SHA-256(json.dumps([seed, entire formal row], sort_keys=True, allow_nan=False).encode())'))
    code_files = ('dsp_dreamer/dataset.py','dsp_dreamer/model_view.py','dsp_dreamer/training_index.py',
        'dsp_dreamer/actions.py','dsp_dreamer/progress.py','dsp_dreamer/contract.py','dsp_dreamer/evaluation_protocol.py')
    versions = seal(dict(schema='dsp-evaluation-source-freeze/1',index_id=index['artifact_id'],
        registry=index['registry'],source_audits=source_audits,files={p:file_info(p) for p in code_files},
        indexer_version=index['indexer_version'],action_codec=ACTION_CODEC,
        integration_id=integration['artifact_id'],content_validation='Previously verified corpus bytes; COMPLETED and dataset metadata rechecked; only validation action tables reread. Normal dataset loader must verify content on future use.'))
    data_freeze = seal(dict(schema='dsp-evaluation-data-freeze/1',protocol_id=protocol['artifact_id'],
        index_id=index['artifact_id'],evaluation_inputs_id=packet['artifact_id'],annotations_id=annotations['artifact_id'],
        supplementation_complete=True,frozen_at=now,candidate_freeze_id=candidate_freeze['artifact_id'],
        source_freeze_id=versions['artifact_id'],action_evidence_id=action_evidence['artifact_id'],
        annotation_provenance_id=annotation_provenance['artifact_id'],
        training_authorized=False,offline_test_disclosure_authorized=False,model_quality_status='pending'))
    assets = {'evaluation-inputs.json':packet,'annotations.json':annotations,'annotation-provenance.json':annotation_provenance,
        'candidate-freeze.json':candidate_freeze,'validation-actions.json':action_evidence,
        'source-freeze.json':versions,'data-freeze.json':data_freeze}
    OUT.mkdir()
    for name,value in assets.items():
        atomic_save(OUT / name,value)
    comparisons = {c:{b:sum(r['action_difference'][b] for r in packet['prediction']['selected'] if r['category']==c) for b in ('noop','shuffled','copy_last')} for c in CATEGORIES}
    report = seal(dict(schema='dsp-reviewed-evaluation-freeze-receipt/1',path=OUT.as_posix(),
        data_freeze=data_freeze,files={name:file_info(OUT/name) for name in assets},
        preparer=dict(path=Path(__file__).as_posix(),file=file_info(__file__)),
        reconstruction_count=200,prediction_counts=dict(Counter(r['category'] for r in packet['prediction']['selected'])),
        candidate_counts=aggregate['complete_counts'],key_items=dict(Counter(i['type'] for i in items)),
        ui_region_count=8,ui_frame_count=5,action_comparable_counts=comparisons,
        prior_evaluation_inputs_id=base['artifact_id'],confirmed_receipt_id=confirmation['artifact_id'],
        baseline_unchanged=packet['baseline']==base['baseline'],reconstruction_unchanged=True,
        full_dataset_opens=0,validation_table_sources_read=3,rgb_chunks_read=0,corpus_rebuilt=False,
        media_bytes_copied=0,media_reencoded=False,annotation_status='frozen',data_freeze_status='frozen',
        recipe_freeze_status='pending',model_quality_status='pending',
        closed_loop_trials_status='pending_input_settings_reconciliation',training_authorized=False,
        offline_test_disclosure_authorized=False))
    atomic_save(OUT / 'receipt.json',report); atomic_save(RECEIPT,report)
    print(json.dumps(dict(data_freeze_id=data_freeze['artifact_id'],counts=report['prediction_counts'],comparisons=comparisons)))


def check():
    confirmation,aggregate,candidates = verify_confirmation()
    report = sealed(RECEIPT)
    require(report == sealed(OUT/'receipt.json'), 'Wrong receipt')
    for name,info in report['files'].items():
        require(file_info(OUT/name) == info, 'Changed frozen output')
        sealed(OUT/name)
    require(file_info(__file__) == report['preparer']['file'], 'Changed freeze preparer')
    protocol = read_protocol('protocols/evaluation-v2.json')
    base = sealed(ROOT/'evaluation-inputs.json'); packet = sealed(OUT/'evaluation-inputs.json')
    annotations = sealed(OUT/'annotations.json'); provenance = sealed(OUT/'annotation-provenance.json')
    frozen = sealed(OUT/'data-freeze.json'); candidate_freeze = sealed(OUT/'candidate-freeze.json')
    evidence = sealed(OUT/'validation-actions.json'); versions = sealed(OUT/'source-freeze.json')
    for key in base:
        if key not in ('artifact_id','prediction','annotations_status'):
            require(packet[key] == base[key], 'Original packet changed outside confirmed prediction')
    require(packet['annotations_status']=='frozen' and packet['status']=='pending' and not packet['training_authorized'], 'Conflated data freeze and quality gate')
    require(frozen['protocol_id']==protocol['artifact_id'] and frozen['index_id']==packet['index_id'], 'Wrong freeze provenance')
    require(frozen['evaluation_inputs_id']==packet['artifact_id']==annotations['evaluation_inputs_id'], 'Wrong annotation inputs')
    require(frozen['annotations_id']==annotations['artifact_id']==provenance['annotations_id'], 'Wrong annotations')
    require(frozen['candidate_freeze_id']==candidate_freeze['artifact_id'] and candidate_freeze['candidates_id']==candidates['artifact_id']==packet['prediction']['candidates_id'], 'Wrong candidate freeze')
    require(frozen['source_freeze_id']==versions['artifact_id'] and frozen['action_evidence_id']==evidence['artifact_id'], 'Wrong evidence binding')
    require(datetime.fromisoformat(frozen['frozen_at'])>=datetime.fromisoformat(protocol['frozen_at']) and frozen['supplementation_complete'], 'Invalid freeze order')
    require(not frozen['training_authorized'] and not frozen['offline_test_disclosure_authorized'], 'Unexpected authorization')
    chosen = packet['prediction']['selected']
    require(Counter(r['category'] for r in chosen)=={c:50 for c in CATEGORIES} and len({(r['artifact_id'],r['start']) for r in chosen})==200, 'Wrong sample quotas')
    actions = {(r['artifact_id'],r['start']):r['future_actions'] for r in evidence['rows']}
    for category in CATEGORIES:
        expected = sorted([r for r in candidates['samples'] if r['category']==category],key=lambda r:_seeded_hash(protocol['seeds']['sampling'],r))[:50]
        actual = [r for r in chosen if r['category']==category]
        require({(r['artifact_id'],r['start']) for r in actual}=={(r['artifact_id'],r['start']) for r in expected}, 'Changed whole-row sample ordering')
        groups = defaultdict(list)
        for row in expected: groups[row['task_id']].append(row)
        by_key = {(r['artifact_id'],r['start']):r for r in actual}
        for group in groups.values():
            for i,row in enumerate(group):
                key=(row['artifact_id'],row['start']); result=by_key[key]; donor=group[(i+1)%len(group)]
                require({k:result[k] for k in FORMAL_FIELDS}==row, 'Selected annotation changed')
                require(result['shuffle_donor']==dict(artifact_id=donor['artifact_id'],start=donor['start']), 'Wrong shuffle donor')
                a,b=actions[key],actions[(donor['artifact_id'],donor['start'])]
                non_noop=any(v!=ACTION_CODEC['noop'] for v in a[:5])
                require(len(a)==15 and result['action_difference']==dict(noop=non_noop,shuffled=a[:5]!=b[:5],copy_last=non_noop), 'Wrong action comparison')
                require(result['generation_seed']==int(_seeded_hash(protocol['seeds']['generation'],list(key))[:8],16), 'Wrong generation seed')
    require(len(annotations['items'])==len({i['sample_id'] for i in annotations['items']})==15, 'Wrong reconstruction items')
    require(len(annotations['ui_regions'])==8 and len({(r['artifact_id'],r['observation_index']) for r in annotations['ui_regions']})==5, 'Wrong UI regions')
    for item,p in zip(annotations['items'],provenance['items']):
        require(item['sample_id']==p['sample_id'] and all(item[k]==p['original_item'][k] for k in ('box','type','expected','eligible','exclusion_reason')), 'Human reconstruction answer changed')
    require(provenance['whole_frames_reviewed']==0 and aggregate['pending_classifications']==['P085'], 'Invented whole-frame review or certainty')
    require(report['full_dataset_opens']==report['rgb_chunks_read']==report['media_bytes_copied']==0 and report['validation_table_sources_read']==3, 'Unexpected corpus work')
    print('PASS: 127 exact confirmations; 241 complete; 200 fixed predictions; 200 unchanged reconstruction frames; baseline unchanged; 15 items/8 UI regions; provenance; no new human work')


if __name__=='__main__':
    require(sys.argv[1:] in ([],['--check']), 'Expected no arguments or --check')
    check() if sys.argv[1:] else freeze()
