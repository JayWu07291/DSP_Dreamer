"""Summarize a completed run without changing its evidence."""
import argparse
import bisect
from collections import Counter
import json
from pathlib import Path
import statistics
import math

from storage_probe import records, save, file_sha

p = argparse.ArgumentParser()
p.add_argument('--run', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=False)
s = json.loads((a.run / 'summary.json').read_text(encoding='utf-8-sig'))
captures, samples, gaps, targets = [], [], [], []
task_counts, panels = Counter(), Counter()
inputs = 0
cursor_missing = []
max_delta = (0, None)
frequency = None
for e in records(a.run / 'events.ndjson'):
    kind = e['type']
    if kind == 'session_start':
        frequency = e['stopwatch_frequency']
    elif kind == 'capture_written':
        captures.append(e)
        if e['cursor_visible'] and not e['cursor_composited']:
            cursor_missing.append(e)
    elif kind == 'storage_sample':
        samples.append(e)
    elif kind in ('capture_drop', 'capture_gap', 'writer_error'):
        gaps.append(e)
    elif kind == 'task_event':
        task_counts[e['name']] += 1
        if e['name'] in ('panel_opened', 'panel_closed'):
            panels[e.get('panel', '') + ':' + e['name']] += 1
        if e['name'] in ('panel_opened', 'factory_build', 'factory_dismantled') and len(targets) < 50:
            targets.append(e)
    elif kind == 'input_sample':
        inputs += 1
        delta = abs(e.get('mouse_dx', 0)) + abs(e.get('mouse_dy', 0))
        if delta > max_delta[0]:
            max_delta = (delta, e)

duration = s['elapsed_seconds']
if not frequency:
    raise ValueError('Missing session clock frequency')
images = ((a.run / 'frames.rgba').stat().st_size if s['storage_codec'] == 'raw'
          else sum(f.stat().st_size for f in a.run.glob('*.mkv')))
events_bytes = (a.run / 'events.ndjson').stat().st_size
indices_bytes = sum(f.stat().st_size for f in a.run.glob('*.index.ndjson'))
minutes = []
for minute in range(math.ceil(samples[-1]['ticks'] / frequency / 60)):
    block = [e for e in samples if minute * 60 * frequency <= e['ticks'] < (minute + 1) * 60 * frequency]
    queues = [e['writer_queue_depth'] for e in block]
    minutes.append(dict(minute=minute, sample_count=len(block), max_queue=max(queues, default=None),
                        mean_queue=statistics.mean(queues) if queues else None))
times = [c['requested_ticks'] for c in captures]
preview = [dict(label='start', capture=captures[0]), dict(label='end', capture=captures[-1])]
seen = set()
for e in targets:
    key = e['name'] if e['name'] != 'panel_opened' else e.get('panel', '')
    if key in seen:
        continue
    seen.add(key)
    i = min(bisect.bisect_left(times, e['ticks'] + frequency // 2), len(captures) - 1)
    preview.append(dict(label=key, capture=captures[i]))
    if len(preview) >= 7:
        break
if max_delta[1]:
    i = min(bisect.bisect_left(times, max_delta[1]['ticks']), len(captures) - 1)
    preview.append(dict(label='largest observed mouse delta', capture=captures[i]))
write_ms = sorted(c['storage_write_ms'] for c in captures)
report = dict(run=str(a.run.resolve()), summary=s, frames=len(captures), image_bytes=images,
    image_gib=images / 2**30, image_gib_per_capture_hour=images / duration * 3600 / 2**30,
    same_frames_raw_gib=s['writer_bytes'] / 2**30, image_bytes_saved_fraction=1-images / s['writer_bytes'],
    events_bytes=events_bytes, index_bytes=indices_bytes,
    image_events_indices_gib=(images+events_bytes+indices_bytes) / 2**30,
    encoder_average_cores=s['encoder_cpu_seconds'] / duration,
    encoder_memory_measurement=('not_applicable_raw' if s['storage_codec'] == 'raw' else
        'sampled' if s['encoder_peak_working_set_bytes'] > 0 else 'unavailable'),
    game_cpu_average_cores=samples[-1]['game_cpu_seconds'] / (samples[-1]['ticks'] / frequency),
    game_rss_sampled_max=max(x['game_working_set_bytes'] for x in samples),
    game_memory_measurement='unavailable' if not any(x['game_working_set_bytes'] > 0 for x in samples) else 'sampled',
    write_ms=dict(median=statistics.median(write_ms), p95=write_ms[int(len(write_ms)*.95)],
                  p99=write_ms[int(len(write_ms)*.99)], maximum=max(write_ms)),
    queue_by_minute=minutes, gap_events=gaps, task_counts=dict(task_counts), panels=dict(panels),
    visible_cursor_not_composited=len(cursor_missing),
    cursor_uncomposited_locations=[{k:c[k] for k in ('capture_id','cursor_x','cursor_y','cursor_index','cursor_glyph_source','segment','decoded_frame_index')} for c in cursor_missing],
    source_summary_sha256=file_sha(a.run / 'summary.json'), source_events_sha256=file_sha(a.run / 'events.ndjson'),
    raw_control_run='this_run' if s['storage_codec'] == 'raw' else 'see_comparison_report',
    visual_and_workload_confirmation='pending')
save(a.out / 'analysis.json', report)
save(a.out / 'preview-index.json', preview)
print(json.dumps({k:v for k,v in report.items() if k not in ('summary','cursor_uncomposited_locations','gap_events','queue_by_minute','panels')}, indent=2))
