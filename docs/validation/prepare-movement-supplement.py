"""Read three frozen validation tables and only requested RGB chunks for review.

This is an evidence extractor, not a replacement Dataset loader or a quality gate.
Input activity prioritizes inspection; only original images support human labels.
"""
import json
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import numpy as np
import pyarrow.parquet as pq
import zarr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer.contract import atomic_save, file_info, load, require
from dsp_dreamer.evaluation_protocol import _seeded_hash, read_protocol, seal, verify_seal
from dsp_dreamer.model_view import ModelView

ROOT = Path('runs/catalog-v4/corpus-integration-20260921')


def prepare():
    out = ROOT / 'movement-supplement-source-01'
    require(not out.exists(), 'Refusing to overwrite supplemental evidence')
    workbench = ROOT / 'workbench'
    export = load(workbench / 'export.json')
    verify_seal(export)
    require(export['artifact_id'] == 'f88618ed686130fa4a21501ec24c6439077dbedc60682782072171ef9fb2366e', 'Wrong workbench')
    for name in ('data.js', 'training-index.json'):
        require(file_info(workbench / name) == export['files'][name], 'Changed source metadata')
    work = json.loads((workbench / 'data.js').read_text(encoding='utf-8').removeprefix('const WORK = ').strip().removesuffix(';'))
    index = load(workbench / 'training-index.json')
    verify_seal(index)
    protocol = read_protocol('protocols/evaluation-v2.json')
    require(index['artifact_id'] == work['index_id'] and protocol['artifact_id'] == work['protocol_id'], 'Identity mismatch')
    integration = load(ROOT / 'review.json')
    verify_seal(integration)
    require(integration['index_id'] == index['artifact_id'], 'Wrong integration')
    sources = [s for s in index['sources'] if s['split'] == 'validation' and s['source_kind'] == 'live']
    require(len(sources) == 3, 'Expected three validation sources')
    existing = {(s['artifact_id'], s['start']) for s in work['prediction']}
    views, completed_by_id, audits, candidates, task_ids = {}, {}, [], [], {}
    for source in sources:
        paths = [Path(p) for p, digest in integration['source_completed'].items()
                 if digest == source['model_view']['source_completed']]
        require(len(paths) == 1, 'Ambiguous validation source path')
        path = paths[0]
        require(file_info(path / 'COMPLETED') == source['model_view']['source_completed'], 'Changed validation manifest')
        completed = load(path / 'COMPLETED')
        files = ('dataset.json', 'transitions.parquet', 'events.parquet')
        for name in files:
            require(file_info(path / name) == completed['files'][name], 'Changed validation table')
        metadata = load(path / 'dataset.json')
        require(metadata['artifact_id'] == source['artifact_id'], 'Wrong validation dataset')
        # Prior integration verified these exact bytes. Do not reopen all RGB chunks
        # through Dataset; ModelView needs only these source-verified tables here.
        dataset = SimpleNamespace(path=path, metadata=metadata,
            rows=pq.read_table(path / 'transitions.parquet').to_pylist(),
            events=[json.loads(e['payload_json']) for e in pq.read_table(path / 'events.parquet').to_pylist()])
        view = ModelView(dataset)
        require(view.metadata == source['model_view'], 'Model view identity changed')
        require(view.sequence_starts(64) == source['uniform'], 'Frozen legal index mismatch')
        legal = view.sequence_starts(79)
        views[source['artifact_id']] = view
        completed_by_id[source['artifact_id']] = completed
        for original in work['prediction']:
            if original['artifact_id'] == source['artifact_id']:
                require(original['start'] in legal, 'Illegal original candidate')
                task_ids[original['id']] = view.rows[original['start']+64]['task_id']
        for start in legal:
            if (source['artifact_id'], start) in existing:
                continue
            actions = [r['model_action'] for r in view.rows[start+64:start+69]]
            # Search hints only: WASD, wheel, or middle-button camera drag.
            activity = sum(any(a['binary'][i] for i in (4, 8, 9, 10)) or a['wheel'] != 1
                           or (a['binary'][17] and a['mouse'] != 60) for a in actions)
            if activity >= 3:
                candidates.append(dict(artifact_id=source['artifact_id'], start=start,
                    task_id=view.rows[start+64]['task_id'], activity_steps=activity))
        audits.append(dict(artifact_id=source['artifact_id'], path=path.as_posix(),
            completed=source['model_view']['source_completed'],
            tables={name: completed['files'][name] for name in files}, legal_79_count=len(legal)))
        print(f"Read validation tables: {source['artifact_id']}; legal starts {len(legal)}", flush=True)
    require(len(task_ids) == 400, 'Incomplete original task mapping')
    seed = protocol['seeds']['sampling']
    candidates.sort(key=lambda r: _seeded_hash(seed, {k: r[k] for k in ('artifact_id', 'start', 'task_id')}))
    chosen = []
    for row in candidates:
        # Review ordering only: avoid asking about overlapping new 1.5-second clips.
        if all(row['artifact_id'] != prior['artifact_id'] or abs(row['start']-prior['start']) >= 15 for prior in chosen):
            chosen.append(row)
        if len(chosen) == 48:
            break
    require(chosen, 'No supplemental inspection candidates')
    out.mkdir()
    (out / 'images').mkdir()
    (out / 'video').mkdir()
    png_bytes = runpy.run_path(str(Path('tools/export-annotation-workbench.py')))['png_bytes']
    samples, images, rgb_files = [], {}, {}
    for n, row in enumerate(chosen, 1):
        view = views[row['artifact_id']]
        dataset, completed = view.dataset, completed_by_id[row['artifact_id']]
        if row['artifact_id'] not in rgb_files:
            for name in ('observations.zarr/zarr.json', 'observations.zarr/rgb/zarr.json'):
                require(file_info(dataset.path / name) == completed['files'][name], 'Changed array metadata')
            rgb_files[row['artifact_id']] = zarr.open_group(str(dataset.path / 'observations.zarr'), mode='r')['rgb']
            require(json.loads(json.dumps(rgb_files[row['artifact_id']].metadata.to_dict())) == dataset.metadata['array_metadata'], 'Array contract mismatch')
        rgb = rgb_files[row['artifact_id']]
        require(rgb.chunks == (1, 360, 640, 3) and rgb.shards is None, 'Unexpected RGB chunk layout')
        parts = view.rows[row['start']:row['start']+79]
        first = dataset.rows[parts[0]['start']]
        anchors = [dataset.rows[parts[i]['stop']-1] for i in (63, 68, 78)]
        relatives = []
        for anchor in anchors:
            observation = anchor['next_observation_index']
            relative = f"images/{row['artifact_id']}-{observation}.png"
            if relative not in images:
                chunk = f'observations.zarr/rgb/c/{observation}/0/0/0'
                require(file_info(dataset.path / chunk) == completed['files'][chunk], 'Changed RGB chunk')
                data = png_bytes(np.asarray(rgb[observation]))
                (out / relative).write_bytes(data)
                images[relative] = dict(file=file_info(out / relative), source_chunk=chunk,
                    source_file=completed['files'][chunk], observation_index=observation, artifact_id=row['artifact_id'])
            relatives.append(relative)
        video = f"video/{row['artifact_id']}.mp4"
        if not (out / video).exists():
            require(file_info(workbench / video) == export['files'][video], 'Changed navigation video')
            os.link(workbench / video, out / video)
        samples.append(dict(artifact_id=row['artifact_id'], start=row['start'], task_id=row['task_id'],
            id=f'M{n:03}', video=video, begin=first['observation_index']/20,
            boundary=anchors[0]['next_observation_index']/20, end=(anchors[2]['next_observation_index']+1)/20,
            images=relatives, observation_index=anchors[2]['next_observation_index'],
            evidence=f"{row['artifact_id']}:captures:{first['capture_id']}-{anchors[2]['next_capture_id']}"))
    batch = seal(dict(schema='dsp-supplemental-inspection-sources/1', protocol_id=protocol['artifact_id'],
        index_id=index['artifact_id'], workbench_id=export['artifact_id'], evaluation_inputs_id=work['evaluation_inputs_id'],
        source_audits=audits, original_task_ids=task_ids, samples=samples, images=images,
        input_activity_candidates=candidates, inspection_rule='seeded row order; >=3/5 input activity; 48 non-overlapping future windows for inspection only',
        original_candidates_preserved=400, automatic_labels=0, candidates_reviewed=0,
        corpus_rebuilt=False, full_dataset_opens=0, validation_table_sources_read=3,
        rgb_chunks_read=len(images), video_bytes_copied=0, video_reencoded=False,
        status='pending', training_authorized=False))
    atomic_save(out / 'sources.json', batch)
    receipt = seal(dict(schema='dsp-supplemental-inspection-export/1', source_batch_id=batch['artifact_id'],
        path=out.as_posix(), files={p.relative_to(out).as_posix():file_info(p) for p in out.rglob('*') if p.is_file()},
        preparer=dict(path=Path(__file__).as_posix(),file=file_info(__file__)),
        status='pending', training_authorized=False))
    atomic_save(out / 'export.json', receipt)
    atomic_save('docs/validation/movement-supplement-source-01-prepared-20260924.json', receipt)
    print(json.dumps(dict(samples=len(samples),eligible=len(candidates),rgb_chunks=len(images),source_batch_id=batch['artifact_id'])))


if __name__ == '__main__':
    prepare()
