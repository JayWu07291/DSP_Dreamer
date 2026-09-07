"""Integration checks on disposable copies, never on original evidence."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

import auto_finalize as worker
from merge_prototype import require, verify_published
from storage_probe import file_sha, save


parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=False)
original = {p.name: file_sha(p) for p in args.source.iterdir() if p.is_file()}
run = args.out / 'cleanup-resume'
shutil.copytree(args.source, run)
command = [sys.executable, str(Path(worker.__file__).resolve()), '--run', str(run)]


def execute(suffix, extra=(), success=True):
    with (args.out / (suffix + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run(command + list(extra), stdout=log, stderr=log)
    require((result.returncode == 0) == success, 'unexpected worker status: ' + suffix)


execute('interrupted-cleanup', ['--test-stop-cleanup-after', '2'], success=False)
manifest = verify_published(run)
inventory = manifest['automatic_finalization']['cleanup_sources']
removed = [name for name in inventory if not (run / name).exists()]
require(len(removed) == 2, 'cleanup interruption did not stop after two files')
remaining = [name for name in inventory if (run / name).exists()]
changed = next(run / name for name in remaining if name.endswith('.json') and (run / name).stat().st_size > 0)
before = changed.read_bytes()
require(before, 'empty tamper target')
changed.write_bytes(bytes([before[0] ^ 1]) + before[1:])
execute('changed-source', success=False)
require(all((run / name).exists() for name in remaining), 'deleted source after mismatch')
changed.write_bytes(before)
execute('resume-cleanup')
require(set(p.name for p in run.iterdir()) == worker.ARTIFACT_FILES, 'extra files after cleanup')
verify_published(run)
execute('idempotent')
require(set(p.name for p in run.iterdir()) == worker.ARTIFACT_FILES, 'extra files after retry')

# Reconstruct a crash between publishing the first file and the manifest.
publication = args.out / 'publication-resume'
shutil.copytree(run, publication)
artifact = publication / '.finalizing' / 'artifact'
artifact.mkdir(parents=True)
(publication / 'manifest.json').rename(publication / 'manifest.json.partial')
(publication / 'frames.ndjson').rename(artifact / 'frames.ndjson')
worker.finalize(publication, worker.storage.FFMPEG)
require(set(p.name for p in publication.iterdir()) == worker.ARTIFACT_FILES, 'publication retry incomplete')

# No real disk exhaustion; fail the capacity check before it can write or remove sources.
low_space = args.out / 'low-space'
shutil.copytree(args.source, low_space)
with patch.object(worker.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(1, 1, 0)):
    try:
        worker.finalize(low_space, worker.storage.FFMPEG)
        raise AssertionError('accepted full disk')
    except ValueError as error:
        require('insufficient' in str(error), 'unexpected capacity error')
require({p.name: file_sha(p) for p in low_space.iterdir() if p.is_file()} == original,
        'low-space source changed')
require({p.name: file_sha(p) for p in args.source.iterdir() if p.is_file()} == original,
        'original evidence changed')
save(args.out / 'report.json', {
    'source_run': str(args.source), 'original_evidence_unchanged': True,
    'merged_frames': manifest['verification']['frames'],
    'cleanup_interrupted_after_files': len(removed), 'changed_source_blocks_all_deletion': True,
    'cleanup_resume': 'pass', 'idempotent_retry': 'pass', 'publication_resume': 'pass',
    'low_space_preserves_sources': True, 'final_files': sorted(worker.ARTIFACT_FILES),
    'limitations': ['Controlled failure injection, not power-loss durability.',
                    'Unity stop hook requires a new in-game recording.']})
print('PASS: automatic merge, publication, cleanup, retries, mismatch and capacity guards')
