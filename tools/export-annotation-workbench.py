"""Export source-verified RGB and a human review queue; never approve labels."""
import argparse
from collections import defaultdict
import itertools
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsp_dreamer.contract import atomic_save, file_info, load, require, sha
from dsp_dreamer.evaluation_protocol import prepare_evaluation, read_protocol, seal, validate_trials
from dsp_dreamer.training_index import TrainingIndex
from dsp_dreamer.video import check_ffmpeg


def png_bytes(rgb):
    require(rgb.shape == (360, 640, 3) and rgb.dtype == np.uint8, 'Expected native uint8 RGB')
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    raw = b''.join(b'\0' + row.tobytes() for row in rgb)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 640, 360, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 3)) + chunk(b'IEND', b''))


def review_queue(index, limit):
    """Balanced work ordering only; final sampling remains in the frozen protocol."""
    pools = defaultdict(list)
    for source in index.report['sources']:
        if source['split'] != 'validation' or source['source_kind'] != 'live':
            continue
        view = index.views[source['artifact_id']]
        for start in view.sequence_starts(79):
            row = dict(artifact_id=source['artifact_id'], start=start, task_id=view.rows[start+64]['task_id'])
            pools[row['task_id']].append(row)
    for pool in pools.values():
        pool.sort(key=lambda r: sha(json.dumps([2201, r], sort_keys=True).encode()))
    interleaved = itertools.chain.from_iterable(itertools.zip_longest(*(pools[t] for t in sorted(pools))))
    return [r for r in interleaved if r is not None][:limit], {str(t): len(p) for t, p in pools.items()}


def export_workbench(index, protocol, out, ffmpeg, evidence_root, *, queue_size=400):
    require(not out.exists(), 'Refusing workbench overwrite')
    check_ffmpeg(ffmpeg)
    out.mkdir(parents=True)
    (out / 'images').mkdir()
    (out / 'video').mkdir()
    before = {str(v.dataset.path): file_info(v.dataset.path / 'COMPLETED') for v in index.views.values()}
    packet = prepare_evaluation(index, protocol)
    index.save(out / 'training-index.json')
    atomic_save(out / 'evaluation-inputs.json', packet)
    queue, available = review_queue(index, queue_size)
    image_records = {}
    def export_image(artifact, observation):
        key = f'{artifact}-{observation}'
        relative = f'images/{key}.png'
        if key not in image_records:
            rgb = np.asarray(index.views[artifact].dataset.rgb[observation])
            (out / relative).write_bytes(png_bytes(rgb))
            image_records[key] = dict(path=relative, rgb_sha256=sha(rgb.tobytes()), file=file_info(out / relative))
        return relative
    recon = []
    for n, row in enumerate(packet['reconstruction']['selected']):
        recon.append(dict(row, id=f'R{n+1:03}', image=export_image(row['artifact_id'], row['observation_index'])))
    evidence = {}
    for path in sorted(evidence_root.glob('*/manifest.json')):
        manifest = load(path)
        evidence[manifest['artifact_id']] = path.parent
    videos = {}
    for source in index.report['sources']:
        if source['split'] != 'validation':
            continue
        view = index.views[source['artifact_id']]
        folder = evidence[source['recording_artifact_id']]
        require(file_info(folder / 'manifest.json') == view.dataset.metadata['source_manifest'], 'Evidence manifest mismatch')
        manifest = load(folder / 'manifest.json')
        require(file_info(folder / 'recording.mkv') == manifest['files']['recording.mkv'], 'Evidence video checksum mismatch')
        relative = f"video/{source['artifact_id']}.mp4"
        print(f'建立影片導覽 {folder.name}', flush=True)
        subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-n', '-i', str(folder / 'recording.mkv'),
            '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '15', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            str(out / relative)], check=True, timeout=600)
        videos[source['artifact_id']] = relative
    predictions = []
    for n, row in enumerate(queue):
        view = index.views[row['artifact_id']]
        parts = view.rows[row['start']:row['start']+79]
        first = view.dataset.rows[parts[0]['start']]
        last_history = view.dataset.rows[parts[63]['stop']-1]
        fifth = view.dataset.rows[parts[68]['stop']-1]
        final = view.dataset.rows[parts[78]['stop']-1]
        predictions.append(dict(row, id=f'P{n+1:03}', video=videos[row['artifact_id']],
            begin=first['observation_index']/20, boundary=last_history['next_observation_index']/20,
            end=(final['next_observation_index']+1)/20,
            images=[export_image(row['artifact_id'], r['next_observation_index']) for r in (last_history, fifth, final)],
            observation_index=final['next_observation_index'],
            evidence=f"{row['artifact_id']}:captures:{first['capture_id']}-{final['next_capture_id']}"))
    for sample in recon + predictions:
        sample.pop('task_id')
    data = dict(schema='dsp-annotation-workbench/1', protocol_id=protocol['artifact_id'],
        evaluation_inputs_id=packet['artifact_id'], index_id=index.report['artifact_id'],
        reconstruction=recon, prediction=predictions, available_prediction_starts=available,
        status='pending', training_authorized=False)
    # JSON is embedded as data, never HTML. The offline page needs no server or dependencies.
    (out / 'data.js').write_text('const WORK = ' + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + ';\n', encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('annotation-workbench.html'), out / 'index.html')
    require(before == {str(v.dataset.path): file_info(v.dataset.path / 'COMPLETED') for v in index.views.values()}, 'Source changed')
    atomic_save(out / 'export.json', seal(dict(schema='dsp-annotation-export/1', inputs_id=packet['artifact_id'],
        sources=before, images=image_records, video_note='壓縮影片僅供操作分類導覽；標註使用無損原圖 PNG',
        files={p.relative_to(out).as_posix(): file_info(p) for p in out.rglob('*') if p.is_file()},
        reconstruction_count=len(recon), prediction_review_queue=len(predictions), status='pending', training_authorized=False)))
    return packet


def main():
    parser = argparse.ArgumentParser(description='匯出原圖、影片導覽與人工標註工作頁，不凍結人工標籤')
    parser.add_argument('--source', type=Path, nargs='+', required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, default=Path('protocols/evaluation-v1.json'))
    parser.add_argument('--evidence-root', type=Path, default=Path('runs/live'))
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    protocol = read_protocol(args.protocol)
    index = TrainingIndex(args.source, load(args.registry), length=64)
    validate_trials(load(args.protocol.parent / 'evaluation-trials-v1.json'), index.report['registry'],
                    [v.dataset.metadata['trial_manifest'] for v in index.views.values()], expected_id=protocol['trials_id'])
    export_workbench(index, protocol, args.out, args.ffmpeg, args.evidence_root)
    print('工作頁匯出完成，人工標註仍待驗證。')


if __name__ == '__main__':
    main()
