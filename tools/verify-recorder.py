"""核對 #21 新實機四檔、逐幀讀回模型視圖並匯出錄製品質；不代替人工情境驗收。"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsp_dreamer import open_model_view, verify_recording
from dsp_dreamer.contract import atomic_save, file_info, require
from dsp_dreamer.video import decode


def verify(source, dataset_path, ffmpeg):
    started = time.perf_counter()
    manifest, frames, events = verify_recording(source, ffmpeg)
    require('benchmark_replay' not in manifest, 'Benchmark replay cannot count as live acceptance evidence')
    require(manifest['source_kind'] == 'live', 'Live evidence required')
    source_info = file_info(source / 'manifest.json')
    view = open_model_view(dataset_path)
    dataset = view.dataset
    require(dataset.metadata['source_manifest'] == source_info, 'Different dataset source')
    # Read one image at a time; the existing loader still holds event/transition metadata in RAM.
    for i, raw in enumerate(decode(ffmpeg, source / 'recording.mkv')):
        expected = np.frombuffer(raw, np.uint8).reshape(360, 640, 4)[:, :, :3]
        require(np.array_equal(dataset.rgb[i], expected), f'Compiled RGB differs at {i}')
    for i in range(len(view)):
        item = view[i]
        require(item['inputs']['observation'].shape == (3, 360, 640), 'Model image shape differs')
        require(item['inputs']['observation'].dtype == np.float32, 'Model dtype differs')
    frequency = manifest['ticks_frequency']
    spans = []
    for episode in manifest['episodes']:
        selected = [f for f in frames if f['episode_id'] == episode['episode_id']]
        if len(selected) < 2:
            continue
        spans.append(dict(episode_id=episode['episode_id'], frames=len(selected),
                          first_ticks=selected[0]['requested_ticks'], last_ticks=selected[-1]['requested_ticks'],
                          seconds=(selected[-1]['requested_ticks'] - selected[0]['requested_ticks']) / frequency,
                          outcome=episode['episode_outcome'], validity=episode['validity_status']))
    seconds = sum(s['seconds'] for s in spans)
    require(seconds > 0, 'No capture duration')
    gaps = Counter({k: 0 for k in ('scheduler', 'no_free_buffer', 'gpu_readback_error', 'writer_backpressure')})
    gap_rows = [e for e in events if e['type'] == 'gap']
    for event in gap_rows:
        gaps[event['reason']] += event['missed'] if event['reason'] == 'scheduler' else 1
    lost = sum(gaps.values())
    expected_slots = len(frames) + lost
    written_intervals = sum(s['frames'] - 1 for s in spans)
    # ponytail: capture-time queue samples miss transient peaks; add runtime high-water counters if needed.
    queues = {}
    for field in ('capture_buffers_busy', 'writer_queue_count', 'event_queue_count', 'gpu_pending'):
        values = [f[field] for f in frames]
        n = max(1, len(values) // 10)
        queues[field] = dict(min=min(values), max=max(values), first_decile_mean=sum(values[:n]) / n,
                             last_decile_mean=sum(values[-n:]) / n, samples=len(values))
    latency = {}
    for field in ('readback_completed_ticks', 'writer_started_ticks', 'encoder_submitted_ticks'):
        values = [(f[field] - f['requested_ticks']) * 1000 / frequency for f in frames]
        require(min(values) >= 0, 'Timing precedes request')
        latency[field] = dict(min_ms=min(values), max_ms=max(values), p50_ms=float(np.percentile(values, 50)),
                              p95_ms=float(np.percentile(values, 95)), p99_ms=float(np.percentile(values, 99)))
    evidence_bytes = sum(p.stat().st_size for p in source.iterdir() if p.is_file())
    dataset_bytes = sum(p.stat().st_size for p in dataset_path.rglob('*') if p.is_file())
    require(file_info(source / 'manifest.json') == source_info, 'Source changed')
    return dict(schema='dsp-recorder-acceptance/1', measured_utc=datetime.now(timezone.utc).isoformat(),
                source=str(source), dataset=str(dataset_path), source_manifest=source_info,
                dataset_completed=file_info(dataset_path / 'COMPLETED'), runtime=manifest['runtime'],
                diagnostic_mode=manifest['diagnostic_mode'], capture_rate_hz=manifest['capture_rate_hz'],
                frame_count=len(frames), event_count=len(events), spans=spans, capture_seconds=seconds,
                expected_slots=expected_slots, lost_slots=lost, gap_counts=dict(gaps), gap_events=gap_rows,
                dropped_fraction=lost / expected_slots, written_intervals=written_intervals,
                written_hz=written_intervals / seconds, configured_rate_fraction=written_intervals / seconds / 20,
                queue_samples=queues, latency=latency, episodes=manifest['episodes'],
                compiled_episodes=dataset.metadata['episodes'],
                complete_successes=sum(s['outcome'] == 'success' and s['validity'] == 'valid' for s in spans),
                rgba_verified=manifest['validation'], rgb_frames_compared=len(frames), model_windows_read=len(view),
                array_metadata=dataset.metadata['array_metadata'], observation_contract=dataset.metadata['observation'],
                table_layout=dataset.metadata['tables'], evidence_bytes=evidence_bytes, dataset_bytes=dataset_bytes,
                evidence_gib_per_capture_hour=evidence_bytes / 1024 ** 3 / (seconds / 3600),
                dataset_gib_per_capture_hour=dataset_bytes / 1024 ** 3 / (seconds / 3600),
                verification_seconds=time.perf_counter() - started,
                limitations=['queue 為 capture 時點取樣，不是連續峰值',
                             'encoder_submitted_ticks 是 pipe 提交與 hash 完成，不是持久化時間',
                             '尚須人工確認 UI、播放、重綁、失焦與釋放，以及獨立資源量測；本報告不宣告整票通過'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), 'Report already exists')
    result = verify(args.evidence, args.dataset, args.ffmpeg)
    atomic_save(args.out, result)
    print(json.dumps({k: result[k] for k in ('frame_count', 'capture_seconds', 'dropped_fraction', 'written_hz')}))
