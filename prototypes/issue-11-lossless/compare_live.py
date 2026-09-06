"""Compare equal-duration capture windows, without claiming identical workloads."""
import argparse
import json
from pathlib import Path
import statistics
from storage_probe import records, save

p = argparse.ArgumentParser()
p.add_argument('--runs', type=Path, nargs=2, required=True)
p.add_argument('--seconds', type=float, default=600)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
result = []
for run in a.runs:
    captures, samples, gaps = [], [], []
    frequency = None
    session = None
    for e in records(run/'events.ndjson'):
        if e['type'] == 'session_start':
            session = e
            frequency = e['stopwatch_frequency']
        elif e['type'] == 'capture_written' and e['requested_ticks'] < frequency*a.seconds:
            captures.append(e)
        elif e['type'] == 'storage_sample' and e['ticks'] < frequency*a.seconds:
            samples.append(e)
        elif e['type'] == 'capture_gap' and e['first_due_ticks'] < frequency*a.seconds:
            gaps.append(e)
    write_ms = sorted(e['storage_write_ms'] for e in captures)
    first, last = samples[0], samples[-1]
    cpu_seconds = (last['ticks']-first['ticks'])/frequency
    rss = [e['game_working_set_bytes'] for e in samples if e['game_working_set_bytes'] > 0]
    result.append(dict(run=run.name, codec=session['storage_codec'], probe_version=session['probe_version'],
        window_seconds=a.seconds, written_frames=len(captures), effective_hz=len(captures)/a.seconds,
        scheduler_gap_count=sum(e['count'] for e in gaps),
        writer_queue_max=max(e['writer_queue_depth'] for e in captures),
        sampled_queue_max=max(e['writer_queue_depth'] for e in samples),
        write_ms=dict(median=statistics.median(write_ms), p95=write_ms[int(len(write_ms)*.95)],
                      p99=write_ms[int(len(write_ms)*.99)], maximum=max(write_ms)),
        cpu_sampling_interval_seconds=cpu_seconds,
        game_mean_cores=(last['game_cpu_seconds']-first['game_cpu_seconds'])/cpu_seconds,
        encoder_mean_cores=(last['encoder_cpu_seconds']-first['encoder_cpu_seconds'])/cpu_seconds,
        game_rss_max_bytes=max(rss) if rss else None,
        encoder_memory='not_applicable_raw' if session['storage_codec']=='raw' else 'unavailable_in_0.1.14'))
report = dict(method='First 600 seconds of each session, relative to session clock. Human workloads differ; this is not a controlled codec-only causal comparison.', runs=result)
save(a.out, report)
print(json.dumps(report, indent=2))
