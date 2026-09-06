"""Throwaway lossless storage experiment. Never modifies source recordings.

DWG1 chunks: magic, then repeated little-endian uint32 length + one gzip member
per complete RGBA frame. Index is external; timestamps never come from video PTS.
"""
import argparse
import contextlib
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import threading
import time

FFMPEG = r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe"
RUNS = Path(r"E:\Steam\steamapps\common\Dyson Sphere Program\BepInEx\plugins\DSPDreamerCaptureProbe\runs")
FRAME_BYTES = 640 * 360 * 4
ENCODE = ['-c:v', 'ffv1', '-level', '3', '-coder', '1', '-context', '0',
          '-g', '1', '-slicecrc', '1', '-slices', '4', '-threads', '4', '-pix_fmt', 'bgra']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, value):
    with open(path, 'x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())


def records(path):
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            yield json.loads(line)


class Metrics:
    """Sample Windows process CPU/RSS, including registered codec child processes.

    CPU is summed core-seconds, not a misleading machine-normalized percentage.
    RSS is sampled at 10 ms and may miss shorter peaks.
    """
    def __init__(self):
        self.handles = []
        self.peak = 0
        self.cpu = 0
        self.stop = threading.Event()

    def add(self, pid):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        h = kernel.OpenProcess(0x410, False, pid)
        if not h:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handles.append((h, self.sample(h)[0]))

    @staticmethod
    def sample(h):
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        ps = ctypes.WinDLL('psapi', use_last_error=True)
        ts = [ctypes.c_ulonglong() for _ in range(4)]
        if not k.GetProcessTimes(ctypes.c_void_p(h), *[ctypes.byref(x) for x in ts]):
            raise ctypes.WinError(ctypes.get_last_error())
        class Memory(ctypes.Structure):
            _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [(n, ctypes.c_size_t) for n in
                ['peak', 'rss', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile']]
        m = Memory()
        m.cb = ctypes.sizeof(m)
        ps.GetProcessMemoryInfo(ctypes.c_void_p(h), ctypes.byref(m), m.cb)
        return (ts[2].value + ts[3].value) / 1e7, m.rss

    def poll(self):
        while not self.stop.wait(.01):
            self.collect()

    def collect(self):
        samples = [(self.sample(h), base) for h, base in list(self.handles)]
        self.cpu = sum(s[0] - base for s, base in samples)
        self.peak = max(self.peak, sum(s[1] for s, base in samples))

    def __enter__(self):
        self.start = time.perf_counter()
        self.add(os.getpid())
        self.thread = threading.Thread(target=self.poll, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()
        self.collect()
        self.seconds = time.perf_counter() - self.start
        for h, base in self.handles:
            ctypes.WinDLL('kernel32').CloseHandle(ctypes.c_void_p(h))

    def result(self, n):
        return dict(wall_seconds=self.seconds, cpu_core_seconds=self.cpu,
                    mean_cores=self.cpu / self.seconds, sampled_peak_rss_bytes=self.peak,
                    frames_per_second=n / self.seconds)


def read_exact(f, n):
    data = bytearray()
    while len(data) < n:
        chunk = f.read(n - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def source_frames(run, captures):
    with open(run / 'frames.rgba', 'rb') as f:
        for c in captures:
            if c['byte_count'] != FRAME_BYTES:
                raise ValueError('Unexpected frame dimensions')
            f.seek(c['file_offset'])
            b = read_exact(f, FRAME_BYTES)
            if len(b) != FRAME_BYTES:
                raise ValueError('Truncated source frame')
            yield b


def encode(path, frames, codec, ffmpeg, metrics):
    if codec.startswith('gzip'):
        with open(path, 'xb') as f:
            f.write(b'DWG1')
            for b in frames:
                c = gzip.compress(b, compresslevel=int(codec[-1]), mtime=0)
                f.write(struct.pack('<I', len(c)))
                f.write(c)
            f.flush()
            os.fsync(f.fileno())
        return ['python.gzip.compress', codec, 'mtime=0']
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
           '-f', 'rawvideo', '-pix_fmt', 'rgba', '-video_size', '640x360',
           '-framerate', '20', '-i', 'pipe:0', '-map', '0:v:0', '-an', '-fps_mode', 'passthrough',
           *ENCODE, '-f', 'matroska', str(path)]
    with open(str(path) + '.stderr', 'xb') as err:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err, creationflags=0x08000000)
        metrics.add(p.pid)
        try:
            for b in frames:
                p.stdin.write(b)
            p.stdin.close()
            if p.wait() != 0:
                raise RuntimeError('FFV1 encode failed: ' + str(path))
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
    with open(path, 'r+b') as f:
        os.fsync(f.fileno())
    return cmd


def decode(path, codec, ffmpeg, metrics=None, start=0, count=None):
    if codec.startswith('gzip'):
        with open(path, 'rb') as f:
            if f.read(4) != b'DWG1':
                raise ValueError('Invalid DWG1 magic')
            i = 0
            while True:
                header = f.read(4)
                if not header:
                    return
                if len(header) != 4:
                    raise ValueError('Truncated record header')
                n, = struct.unpack('<I', header)
                if n > FRAME_BYTES + 4096:
                    raise ValueError('Invalid record length')
                payload = read_exact(f, n)
                if len(payload) != n:
                    raise ValueError('Truncated gzip record')
                if i >= start:
                    b = gzip.decompress(payload)
                    if len(b) != FRAME_BYTES:
                        raise ValueError('Invalid decoded length')
                    yield b
                    if count is not None and i + 1 >= start + count:
                        return
                i += 1
    else:
        # Ordinal selection intentionally decodes the prefix. It never treats PTS as capture time.
        cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-threads', '4', '-i', str(path),
               '-map', '0:v:0', '-an']
        if start or count is not None:
            end = '' if count is None else f':end_frame={start + count}'
            cmd += ['-vf', f'trim=start_frame={start}{end}']
        if count is not None:
            cmd += ['-frames:v', str(count)]
        cmd += ['-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgba', 'pipe:1']
        with open(str(path) + '.decode.stderr', 'ab') as err:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, creationflags=0x08000000)
            if metrics:
                metrics.add(p.pid)
            try:
                while True:
                    b = read_exact(p.stdout, FRAME_BYTES)
                    if not b:
                        break
                    if len(b) != FRAME_BYTES:
                        raise ValueError('Partial decoded frame')
                    yield b
                if p.wait() != 0:
                    raise ValueError('FFV1 decoder reported damage')
            finally:
                p.stdout.close()
                if p.poll() is None:
                    p.kill()
                    p.wait()


def benchmark(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    version = subprocess.check_output([args.ffmpeg, '-version'], text=True)
    import zlib
    save(out / 'environment.json', dict(platform=platform.platform(), python=sys.version,
         ffmpeg=version, ffmpeg_sha256=file_sha(args.ffmpeg), zlib=zlib.ZLIB_RUNTIME_VERSION,
         source_branch='codex/prototype-issue-4-recorder',
         source_commit=subprocess.check_output(['git', 'rev-parse', 'codex/prototype-issue-4-recorder'], text=True).strip(),
         method='Sequential offline runs; warm filesystem cache possible; 10ms sampled process RSS; no live game.'))
    # Preflight deliberately varies alpha, unlike ordinary opaque game captures.
    alpha = bytes(range(256)) * (FRAME_BYTES // 256)
    for codec in args.codecs:
        target = out / ('alpha-' + codec + ('.mkv' if codec == 'ffv1' else '.dwg'))
        with Metrics() as m:
            encode(target, [alpha, alpha[::-1]], codec, args.ffmpeg, m)
        got = list(decode(target, codec, args.ffmpeg))
        if got != [alpha, alpha[::-1]]:
            raise ValueError('Nonopaque RGBA preflight failed: ' + codec)
    selections = [('20260901T024749Z', 0, 200), ('20260901T024749Z', 400, 200),
                  ('20260901T024749Z', 1000, 200), ('20260901T025133Z', 1200, 200),
                  ('20260902T145501Z', 0, 433)]
    reports = []
    sources = {}
    for run_id, start, count in selections:
        run = args.runs / run_id
        if run_id not in sources:
            events = list(records(run / 'events.ndjson'))
            captures = [dict(e, event_line=i + 1) for i, e in enumerate(events) if e['type'] == 'capture_written']
            if len({c['capture_id'] for c in captures}) != len(captures):
                raise ValueError('Duplicate capture ID')
            sources[run_id] = (events, captures)
            save(out / (run_id + '-source.json'), dict(run=str(run),
                 files={p.name:dict(bytes=p.stat().st_size, sha256=file_sha(p)) for p in
                        [run / 'frames.rgba', run / 'events.ndjson', run / 'summary.json']},
                 summary=json.loads((run / 'summary.json').read_text(encoding='utf-8-sig'))))
        events, all_captures = sources[run_id]
        captures = all_captures[start:start + count]
        if len(captures) != count:
            raise ValueError('Source selection out of range')
        hashes = [sha(b) for b in source_frames(run, captures)]
        name = f'{run_id}-{start}-{count}'
        selected = dict(name=name, source_run=run_id, ordinal_start=start, frame_count=count,
             ordering='source capture_written order',
             index=[dict(c, decoded_frame_index=i, rgba_sha256=h) for i, (c, h) in enumerate(zip(captures, hashes))],
             task_events=[e for e in events if e['type'] == 'task_event' and
                          captures[0]['requested_ticks'] <= e.get('ticks', -1) <= captures[-1]['requested_ticks']])
        save(out / (name + '-index.json'), selected)
        for codec in args.codecs:
            path = out / (name + '-' + codec + ('.mkv' if codec == 'ffv1' else '.dwg'))
            print('Encoding', name, codec, flush=True)
            with Metrics() as enc:
                command = encode(path, source_frames(run, captures), codec, args.ffmpeg, enc)
            with Metrics() as dec:
                decoded = [sha(b) for b in decode(path, codec, args.ffmpeg, dec)]
            if decoded != hashes:
                raise ValueError('Frame hashes/count/order mismatch')
            with Metrics() as seek:
                partial = [sha(b) for b in decode(path, codec, args.ffmpeg, seek, count // 2, 16)]
            if partial != hashes[count // 2:count // 2 + 16]:
                raise ValueError('Ordinal partial read mismatch')
            encoded_sha = file_sha(path)
            # Damage only a dedicated copy, leaving source and verified candidates intact.
            damaged = out / (path.name + '.truncated')
            keep = path.stat().st_size * 3 // 4
            with open(path, 'rb') as src, open(damaged, 'xb') as dst:
                remaining = keep
                while remaining:
                    b = src.read(min(1048576, remaining))
                    dst.write(b)
                    remaining -= len(b)
            recovered = []
            error = None
            try:
                for b in decode(damaged, codec, args.ffmpeg):
                    h = sha(b)
                    if len(recovered) >= len(hashes) or h != hashes[len(recovered)]:
                        raise ValueError('Damaged frame or ordering mismatch')
                    recovered.append(h)
            except (ValueError, EOFError, gzip.BadGzipFile) as e:
                error = str(e)
            report = dict(clip=name, codec=codec, frames=count, encoded_bytes=path.stat().st_size,
                 rgba_bytes=count * FRAME_BYTES, rgba_roundtrip='pass', encoded_sha256=encoded_sha,
                 projected_image_gib_per_capture_hour_at_20hz=path.stat().st_size / count * 72000 / 2**30,
                 encode=enc.result(count), decode_and_hash=dec.result(count), ordinal_read_16=seek.result(16),
                 command=command, truncation=dict(bytes_retained=keep, verified_prefix_frames=len(recovered),
                 decoder_error=error, accepted_as_sealed=False, checksum_mismatch=file_sha(damaged) != encoded_sha),
                 live_20hz_30min='not_tested',
                 buffer_note='Streams frames without a raw staging file; sampled process RSS includes buffers and codec memory')
            reports.append(report)
            save(out / (name + '-' + codec + '-result.json'), report)
            print(json.dumps({k:report[k] for k in ['clip', 'codec', 'encoded_bytes', 'rgba_roundtrip']}), flush=True)
    save(out / 'results.json', reports)


def verify_run(args):
    run = args.run.resolve()
    manifest_paths = sorted(run.glob('segment-*.unverified.json'))
    if not manifest_paths:
        summary_path = run / 'summary.json'
        if summary_path.exists():
            s = json.loads(summary_path.read_text(encoding='utf-8-sig'))
            if s.get('storage_codec') == 'raw':
                events = list(records(run / 'events.ndjson'))
                frames = [e for e in events if e['type'] == 'capture_written']
                raw = run / 'frames.rgba'
                if len(frames) != s['written_frames'] or raw.stat().st_size != len(frames) * FRAME_BYTES:
                    raise ValueError('Raw baseline size/count mismatch')
                if any(e['file_offset'] != i * FRAME_BYTES or e['byte_count'] != FRAME_BYTES for i, e in enumerate(frames)):
                    raise ValueError('Raw baseline offsets mismatch')
                report = dict(test='raw_live_baseline', summary=s, frames=len(frames),
                              rgba_sha256=file_sha(raw), events_sha256=file_sha(run / 'events.ndjson'),
                              duration_30min=s['elapsed_seconds'] >= 1800,
                              raw_comparison_10min_gates=(s['elapsed_seconds'] >= 600 and s['configured_hz'] == 20
                                  and s['drop_rate'] < .01 and s['effective_hz'] >= 19 and s['readback_errors'] == 0
                                  and s['writer_drops'] == 0 and not s['storage_failed']),
                              visual_and_workload_review='pending')
                save(run / ('verification-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '.json'), report)
                print(json.dumps(report, indent=2))
                return
        raise ValueError('No closed segments; use recover on an unfinished segment')
    live = (run / 'summary.json').exists()
    events = list(records(run / 'events.ndjson')) if live else []
    writes = {e['capture_id']: e for e in events if e['type'] == 'capture_written'}
    ids = []
    ticks = []
    results = []
    ffmpeg_version = subprocess.check_output([args.ffmpeg, '-version'], text=True).splitlines()[0]
    for manifest_path in manifest_paths:
        m = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
        path = run / m['file']
        if path.parent != run:
            raise ValueError('Segment path escapes run')
        index_path = path.with_suffix('.index.ndjson')
        index = list(records(index_path))
        if len(index) != m['frames'] or m['width'] != 640 or m['height'] != 360:
            raise ValueError('Manifest dimensions or count mismatch')
        if [i['decoded_frame_index'] for i in index] != list(range(len(index))):
            raise ValueError('Index ordinal mismatch')
        if any(i['segment'] != path.name for i in index):
            raise ValueError('Index segment mismatch')
        if live:
            for i in index:
                e = writes.get(i['capture_id'])
                keys = ['requested_ticks', 'game_tick', 'segment', 'decoded_frame_index', 'rgba_sha256',
                        'unity_frame', 'cursor_visible', 'cursor_x', 'cursor_y', 'cursor_index']
                if e is None or any(i[k] != e[k] for k in keys):
                    raise ValueError('Segment index differs from append-only capture event')
        expected = [i['rgba_sha256'] for i in index]
        with Metrics() as met:
            decoded = [sha(b) for b in decode(path, m['codec'], args.ffmpeg, met)]
        if decoded != expected:
            raise ValueError('Decoded hashes/count/order mismatch: ' + path.name)
        # The smoke harness additionally verifies independently against original evidence bytes.
        if not live:
            source = Path(index[0]['source_run'])
            source_rows = [dict(i, file_offset=i['source_file_offset']) for i in index]
            if [sha(b) for b in source_frames(source, source_rows)] != decoded:
                raise ValueError('Smoke result differs from original source evidence')
        ids += [i['capture_id'] for i in index]
        ticks += [i['requested_ticks'] for i in index]
        sealed = dict(m, state='sealed_verified', encoded_sha256=file_sha(path),
            index_file=index_path.name, index_sha256=file_sha(index_path),
            rgba_sha256=decoded, capture_ids=[i['capture_id'] for i in index],
            ffmpeg_verifier=ffmpeg_version, verification=met.result(len(index)))
        sealed_path = Path(str(path) + '.sealed.json')
        if sealed_path.exists():
            old = json.loads(sealed_path.read_text())
            if old['encoded_sha256'] != sealed['encoded_sha256'] or old['index_sha256'] != sealed['index_sha256']:
                raise ValueError('Previously sealed evidence changed')
        else:
            save(sealed_path, sealed)
        results.append(dict(file=path.name, frames=len(index), encoded_bytes=path.stat().st_size,
                            rgba_roundtrip='pass', decode=met.result(len(index))))
    if len(set(ids)) != len(ids) or any(a >= b for a, b in zip(ticks, ticks[1:])):
        raise ValueError('Capture IDs duplicate or request order is not strictly increasing')
    incomplete = [p.name for p in run.glob('*.partial')]
    report = dict(segments=results, frames=len(ids), incomplete=incomplete,
                  decoded_evidence='verified_prefix' if incomplete else 'pass',
                  live_20hz_30min='not_tested')
    if live:
        s = json.loads((run / 'summary.json').read_text(encoding='utf-8-sig'))
        gates = dict(duration=s['elapsed_seconds'] >= 1800,
                     configured_hz=s['configured_hz'] == 20,
                     drop_rate=s['drop_rate'] < .01, effective_hz=s['effective_hz'] >= 19,
                     readback_errors=s['readback_errors'] == 0, writer_drops=s['writer_drops'] == 0,
                     storage_errors=not s.get('storage_failed', True),
                     counts=len(ids) == s['written_frames'] == len(writes),
                     segments_complete=not incomplete,
                     queue_bound=s['max_writer_queue'] <= 12)
        report.update(summary=s, gates=gates,
                      live_20hz_30min='numeric_gates_pass_visual_and_workload_review_pending' if all(gates.values()) else 'fail_or_short_run',
                      source_events_sha256=file_sha(run / 'events.ndjson'),
                      source_summary_sha256=file_sha(run / 'summary.json'))
    save(run / ('verification-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '.json'), report)
    print(json.dumps(report, indent=2))


def recover(args):
    # Report only. A recoverable prefix never becomes a sealed segment automatically.
    path = args.file.resolve()
    expected = []
    with open(args.index, encoding='utf-8-sig') as f:
        for line in f:
            try:
                expected.append(json.loads(line)['rgba_sha256'])
            except json.JSONDecodeError:
                break
    actual = []
    error = None
    try:
        for b in decode(path, args.codec, args.ffmpeg):
            h = sha(b)
            if len(actual) >= len(expected) or h != expected[len(actual)]:
                raise ValueError('Frame does not match indexed prefix')
            actual.append(h)
    except (ValueError, EOFError, gzip.BadGzipFile) as e:
        error = str(e)
    report = dict(file=str(path), verified_prefix_frames=len(actual), indexed_frames=len(expected),
                  decoder_error=error, state='incomplete_not_sealed', rgba_sha256=actual)
    save(args.out, report)
    print(json.dumps({k:v for k,v in report.items() if k != 'rgba_sha256'}, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ffmpeg', default=FFMPEG)
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('benchmark')
    b.add_argument('--runs', type=Path, default=RUNS)
    b.add_argument('--out', type=Path, required=True)
    b.add_argument('--codecs', nargs='+', choices=['ffv1', 'gzip1', 'gzip6'], default=['ffv1', 'gzip1'])
    v = sub.add_parser('verify-run')
    v.add_argument('--run', type=Path, required=True)
    r = sub.add_parser('recover')
    r.add_argument('--file', type=Path, required=True)
    r.add_argument('--index', type=Path, required=True)
    r.add_argument('--codec', choices=['ffv1', 'gzip1'], required=True)
    r.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if args.command == 'benchmark':
        benchmark(args)
    elif args.command == 'verify-run':
        verify_run(args)
    elif args.command == 'recover':
        recover(args)
