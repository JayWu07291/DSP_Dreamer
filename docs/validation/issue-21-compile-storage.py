"""Measure the complete compiler with an isolated output and temporary directory.

Run from the repository root. Existing output is deliberately refused.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsp_dreamer import compile_recording
from dsp_dreamer.contract import file_info, load, require, save

root = Path('runs/issue21-compile-storage')
root.mkdir(exist_ok=False)
temporary = root / 'temporary'
temporary.mkdir()
os.environ['TMP'] = os.environ['TEMP'] = str(temporary.resolve())
tempfile.tempdir = str(temporary.resolve())
source = Path('runs/live/9a3dccda-e332-4a6d-80f3-d99c16485c12.source.evidence')
original = Path('runs/live/issue21-six-flows-batched')
destination = root / 'dataset'
ffmpeg = Path(r'E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe')
raw = Path('docs/validation/issue-21-compile-storage.ndjson')
stream = raw.open('x', encoding='utf8', newline='\n')
stop = threading.Event()
errors = []
rows = []

def sample():
    started = datetime.now(timezone.utc).isoformat()
    total = count = 0
    for directory, _, files in os.walk(root):
        for name in files:
            try:
                total += os.stat(os.path.join(directory, name)).st_size
                count += 1
            except FileNotFoundError:
                pass
    row = dict(start_utc=started, end_utc=datetime.now(timezone.utc).isoformat(),
               logical_bytes=total, files=count)
    stream.write(json.dumps(row) + '\n')
    stream.flush()
    rows.append(row)

def monitor():
    try:
        while not stop.wait(5):
            sample()
    except Exception as error:
        errors.append(error)

identity = file_info(source / 'manifest.json')
baseline = load(Path('docs/validation/issue-21-six-flows-batched-compile.json'))['completed']
require(file_info(original / 'COMPLETED') == baseline, 'Previously recorded baseline changed')
prior = load(original / 'COMPLETED')
require(file_info(original / 'dataset.json') == prior['files']['dataset.json'], 'Baseline metadata changed')
before = load(original / 'dataset.json')
sample()
worker = threading.Thread(target=monitor)
worker.start()
start = time.perf_counter()
report = dict(pid=os.getpid(), start_utc=datetime.now(timezone.utc).isoformat(),
              source_manifest=identity, root=str(root), temporary=str(temporary))
print(json.dumps(report), flush=True)
try:
    compile_recording(source, destination, ffmpeg)
finally:
    stop.set()
    worker.join()
report.update(compile_seconds=time.perf_counter() - start,
              end_utc=datetime.now(timezone.utc).isoformat())
require(not errors, f'Storage sampling failed: {errors}')
sample()
stream.close()
require(file_info(source / 'manifest.json') == identity, 'Source manifest changed')
receipt = load(destination / 'COMPLETED')
require(file_info(original / 'COMPLETED') == baseline, 'Baseline receipt changed during compile')
require({k: v for k, v in receipt['files'].items() if k != 'dataset.json'} ==
        {k: v for k, v in prior['files'].items() if k != 'dataset.json'}, 'Compiled data differs')
metadata = load(destination / 'dataset.json')
require({k: v for k, v in metadata.items() if k != 'artifact_id'} ==
        {k: v for k, v in before.items() if k != 'artifact_id'}, 'Metadata differs')
times = [datetime.fromisoformat(row['start_utc']) for row in rows]
report.update(raw_samples=dict(path=raw.name, **file_info(raw)), sample_count=len(rows),
              baseline_completed=baseline, first_sample=rows[0], last_sample=rows[-1],
              maximum_sample_start_interval_seconds=max((b-a).total_seconds() for a,b in zip(times, times[1:])),
              sampled_peak_logical_bytes=max(row['logical_bytes'] for row in rows),
              retained_logical_bytes=rows[-1]['logical_bytes'], frame_count=metadata['frame_count'],
              frames_per_second=metadata['frame_count']/report['compile_seconds'],
              completed=file_info(destination / 'COMPLETED'), compiled_data_identical=True,
              limitations=['Logical bytes, not allocated filesystem bytes; periodic scans may miss transient peaks.',
                           'Source and existing datasets are retained outside the measured root and budgeted separately.',
                           'Complete compiler includes source validation and prepublication loader; no extra postpublication readback.'])
save(Path('docs/validation/issue-21-compile-storage.json'), report)
print(json.dumps(report), flush=True)
