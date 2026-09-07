"""Throwaway session merger. Source runs are read-only; never deletes evidence.

Usage: python merge_prototype.py --run RUN --out NEW_DIRECTORY
Output: artifact/{recording.mkv,events.ndjson,frames.ndjson,manifest.json}.
Diagnostics stay outside artifact. A manifest is published only after verification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from storage_probe import FFMPEG, FRAME_BYTES, file_sha, records, save


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_published(artifact):
    manifest_path = artifact / 'manifest.json'
    require(manifest_path.is_file(), 'no completion manifest')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    require(manifest['state'] == 'verified', 'not verified')
    require(set(manifest['files']) == {'recording.mkv', 'events.ndjson', 'frames.ndjson'},
            'unexpected artifact files')
    for name, expected in manifest['files'].items():
        path = artifact / name
        require(path.stat().st_size == expected['bytes'], f'length mismatch: {name}')
        require(file_sha(path) == expected['sha256'], f'checksum mismatch: {name}')
    require(manifest['verification']['frames'] == manifest['source_summary']['written_frames'],
            'merged count differs from session summary')
    return manifest


def decode_verify(video, frames, log):
    command = [FFMPEG, '-hide_banner', '-nostdin', '-v', 'info', '-i', str(video),
               '-map', '0:v:0', '-vf', 'showinfo', '-fps_mode', 'passthrough',
               '-pix_fmt', 'rgba', '-f', 'rawvideo', 'pipe:1']
    with log.open('wb') as error:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=error)
        try:
            for ordinal, frame in enumerate(frames):
                data = process.stdout.read(FRAME_BYTES)
                require(len(data) == FRAME_BYTES, f'short decode at {ordinal}')
                require(hashlib.sha256(data).hexdigest() == frame['rgba_sha256'],
                        f'RGBA mismatch at {ordinal}')
            require(process.stdout.read(1) == b'', 'unexpected extra frame')
            require(process.wait() == 0, 'decoder failed')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
    times = [float(value) for value in re.findall(
        r'\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:([\d.e+-]+)',
        log.read_text(encoding='utf-8', errors='replace'))]
    require(len(times) == len(frames), 'timestamp count mismatch')
    require(all(abs(t - i / 20) < 0.002 for i, t in enumerate(times)),
            'playback timeline is not continuous 20 fps')
    return {'frames': len(frames), 'rgba_hashes_match': True,
            'playback_timestamps_match_20fps': True, 'last_pts_seconds': times[-1]}


def merge(run, out, stop_before_publish=False):
    started = time.perf_counter()
    require(not out.exists(), 'output must be a new directory')
    out.mkdir(parents=True)
    artifact = out / 'artifact'
    artifact.mkdir()
    segments = sorted(run.glob('segment-*.mkv'))
    require(segments and not list(run.glob('*.partial')), 'incomplete or empty run')
    frames, sources, seals = [], [], []
    for segment in segments:
        seal_path = segment.with_suffix('.mkv.sealed.json')
        seal = json.loads(seal_path.read_text(encoding='utf-8'))
        index = run / seal['index_file']
        require(index.parent.resolve() == run.resolve(), 'index escapes run')
        require(seal['state'] == 'sealed_verified', 'source not verified')
        require(file_sha(segment) == seal['encoded_sha256'], 'source video hash mismatch')
        require(file_sha(index) == seal['index_sha256'], 'source index hash mismatch')
        rows = list(records(index))
        require(len(rows) == seal['frames'], 'source count mismatch')
        for local, row in enumerate(rows):
            require(row['segment'] == segment.name and row['decoded_frame_index'] == local,
                    'source ordinal mismatch')
            require(row['rgba_sha256'] == seal['rgba_sha256'][local], 'source hash list mismatch')
            if frames:
                require(row['capture_id'] > frames[-1]['capture_id'], 'capture order mismatch')
                require(row['requested_ticks'] > frames[-1]['requested_ticks'], 'request order mismatch')
            frames.append(dict(row, video_file='recording.mkv', video_frame_index=len(frames)))
        sources.append({'file': segment.name, 'sha256': seal['encoded_sha256'],
                        'index_file': index.name, 'index_sha256': seal['index_sha256'],
                        'frames': len(rows), 'bytes': segment.stat().st_size})
        seals.append(seal)
    summary = json.loads((run / 'summary.json').read_text(encoding='utf-8-sig'))
    require(len(frames) == summary['written_frames'] and not summary['storage_failed'],
            'missing segments or failed source session')
    events = list(records(run / 'events.ndjson'))
    require(events[0]['type'] == 'session_start' and events[0]['capture_hz'] == 20,
            'prototype supports 20 Hz runs only')
    require(events[0]['width'] == 640 and events[0]['height'] == 360, 'unsupported size')
    # An explicit duration prevents a segment's container duration rounding from
    # accumulating at concat boundaries. Original capture ticks remain in index.
    concat = out / 'concat.txt'
    lines = ['ffconcat version 1.0']
    for segment, source in zip(segments, sources):
        path = segment.resolve().as_posix()
        require("'" not in path and '\n' not in path, 'unsupported concat path')
        lines += [f"file '{path}'", f"duration {source['frames'] / 20:.6f}"]
    concat.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    video = artifact / 'recording.mkv.partial'
    merge_started = time.perf_counter()
    with (out / 'remux.stderr').open('wb') as log:
        subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'warning', '-n',
                        '-f', 'concat', '-safe', '0', '-i', str(concat), '-map', '0:v:0',
                        '-c:v', 'copy', '-f', 'matroska', str(video)], stderr=log, check=True)
    remux_seconds = time.perf_counter() - merge_started
    event_output = artifact / 'events.ndjson.partial'
    shutil.copyfile(run / 'events.ndjson', event_output)
    require(file_sha(event_output) == file_sha(run / 'events.ndjson'), 'event copy mismatch')
    index_output = artifact / 'frames.ndjson.partial'
    with index_output.open('x', encoding='utf-8', newline='\n') as stream:
        for frame in frames:
            stream.write(json.dumps(frame, ensure_ascii=False, separators=(',', ':')) + '\n')
    require(list(records(index_output)) == frames, 'merged index mismatch')
    verification = decode_verify(video, frames, out / 'decode.stderr')
    # Exercise demuxer seeking on both sides of every boundary in the short run,
    # and representative boundaries of long runs, including the final frame.
    boundaries, count = [], 0
    for source in sources[:-1]:
        count += source['frames']
        boundaries.extend([count - 1, count])
    if len(boundaries) > 20:
        boundaries = boundaries[:4] + boundaries[len(boundaries)//2:len(boundaries)//2+4] + boundaries[-4:]
    targets = sorted(set([0, len(frames) - 1] + boundaries))
    for ordinal in targets:
        result = subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-v', 'error',
                                 '-ss', f'{ordinal / 20:.6f}', '-i', str(video),
                                 '-frames:v', '1', '-pix_fmt', 'rgba', '-f', 'rawvideo', 'pipe:1'],
                                capture_output=True, check=True)
        require(len(result.stdout) == FRAME_BYTES and
                hashlib.sha256(result.stdout).hexdigest() == frames[ordinal]['rgba_sha256'],
                f'seek mismatch at {ordinal}')
    verification.update(seek_frame_ordinals=targets, seek_hashes_match=True,
                        events_byte_identical=True, event_records=len(events),
                        frame_index_roundtrip=True, remux_seconds=remux_seconds)
    manifest = {'schema': 'PROTOTYPE-merged-session-v1', 'state': 'verified',
                'source_run': str(run.resolve()), 'session': events[0], 'source_summary': summary,
                'source_segments': sources, 'source_seals': seals,
                'verification': verification, 'files': {},
                'ffmpeg_sha256': file_sha(Path(FFMPEG)),
                'limitations': ['Prototype source lacks global sequence_number; original event order retained.',
                                'Decoder and seek validated; interactive player UI not tested.',
                                'Source cleanup intentionally not implemented.']}
    for path in (video, event_output, index_output):
        manifest['files'][path.name.removesuffix('.partial')] = {
            'bytes': path.stat().st_size, 'sha256': file_sha(path)}
    if stop_before_publish:
        save(out / 'interrupted-before-publish.json', {'manifest_absent': not (artifact / 'manifest.json').exists(),
                                                      'source_retained': all(p.exists() for p in segments)})
        return
    for path in (video, event_output, index_output):
        path.rename(path.with_name(path.name.removesuffix('.partial')))
    save(artifact / 'manifest.json.partial', manifest)
    (artifact / 'manifest.json.partial').rename(artifact / 'manifest.json')
    verify_published(artifact)
    verification['total_seconds'] = time.perf_counter() - started
    save(out / 'report.json', dict(verification, source_segments=len(segments),
                                 source_image_bytes=sum(s['bytes'] for s in sources),
                                 output_files=manifest['files'],
                                 artifact_files=sorted(p.name for p in artifact.iterdir())))
    print(json.dumps(verification), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--stop-before-publish', action='store_true')
    args = parser.parse_args()
    merge(args.run, args.out, args.stop_before_publish)
