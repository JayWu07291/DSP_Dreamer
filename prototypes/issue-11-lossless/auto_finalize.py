"""Post-recording worker: verify, merge, publish, then clean this run only.

Runs separately from Unity. Retry the same command after a failure. Never scans
other sessions. Deletion requires a verified final artifact and recorded hashes.
"""
import argparse
import contextlib
import json
import msvcrt
import os
from pathlib import Path
import re
import shutil
import traceback
from types import SimpleNamespace

import merge_prototype as merger
import storage_probe as storage


ROOT_TEMP = re.compile(r'(segment-\d+\.(mkv(?:\.(?:decode\.stderr|sealed\.json|unverified\.json))?|index\.ndjson)|summary\.json|verification-[\w-]+\.json)\Z')
WORK_FILES = {'concat.txt', 'remux.stderr', 'decode.stderr', 'report.json',
              'worker.log', 'error.txt', 'interrupted-before-publish.json'}
ARTIFACT_FILES = {'recording.mkv', 'events.ndjson', 'frames.ndjson', 'manifest.json'}


def safe_file(root, relative):
    path = root / relative
    storage_path = path.resolve()
    merger.require(storage_path.is_relative_to(root.resolve()) and storage_path != root.resolve(),
                   'path escapes session')
    merger.require(not path.is_symlink() and not path.is_junction(), 'linked file refused')
    # Also reject linked parent directories.
    for parent in path.parents:
        if parent == root:
            break
        merger.require(not parent.is_symlink() and not parent.is_junction(), 'linked parent refused')
    return path


def scratch_files(run):
    work = run / '.finalizing'
    if not work.exists():
        return []
    merger.require(not work.is_symlink() and not work.is_junction(), 'linked workspace refused')
    found = []
    for path in work.iterdir():
        if path.name == 'artifact':
            merger.require(path.is_dir() and not path.is_symlink() and not path.is_junction(),
                           'invalid artifact directory')
            for child in path.iterdir():
                merger.require(child.name.removesuffix('.partial') in ARTIFACT_FILES and child.is_file(),
                               'unknown scratch artifact')
                found.append(safe_file(run, child.relative_to(run)))
        else:
            merger.require(path.name in WORK_FILES and path.is_file(), 'unknown scratch file')
            found.append(safe_file(run, path.relative_to(run)))
    return found


def clear_scratch(run):
    # Explicitly enumerated, contained paths only; no recursive delete.
    paths = scratch_files(run)
    for path in paths:
        path.unlink()
    for directory in (run / '.finalizing' / 'artifact', run / '.finalizing'):
        if directory.exists():
            directory.rmdir()


def cleanup(run, stop_after=None):
    for name in ARTIFACT_FILES:
        merger.require(safe_file(run, name).is_file(), 'missing final file')
    manifest = merger.verify_published(run)
    inventory = manifest['automatic_finalization']['cleanup_sources']
    # Validate ALL surviving sources before deleting ANY of them.
    remaining = []
    for name, expected in inventory.items():
        merger.require(ROOT_TEMP.fullmatch(name) is not None, 'unapproved cleanup filename')
        path = safe_file(run, name)
        if path.exists():
            merger.require(path.is_file() and path.stat().st_size == expected['bytes'] and
                           storage.file_sha(path) == expected['sha256'], 'cleanup source changed: ' + name)
            remaining.append(path)
    scratch_files(run)  # Validate scratch paths before source removal.
    for i, path in enumerate(remaining):
        path.unlink()
        if stop_after is not None and i + 1 == stop_after:
            raise RuntimeError('TEST: interrupted cleanup')
    clear_scratch(run)


def publish(run):
    pending = run / 'manifest.json.partial'
    manifest = json.loads(pending.read_text(encoding='utf-8'))
    merger.require(set(manifest['files']) == ARTIFACT_FILES - {'manifest.json'}, 'invalid publication')
    moves = []
    for name, expected in manifest['files'].items():
        destination = safe_file(run, name)
        source = destination if destination.exists() else safe_file(run, '.finalizing/artifact/' + name)
        merger.require(source.stat().st_size == expected['bytes'] and
                       storage.file_sha(source) == expected['sha256'], 'publication file mismatch: ' + name)
        if source != destination:
            moves.append((source, destination))
    for source, destination in moves:
        source.rename(destination)
    pending.rename(run / 'manifest.json')


def finalize(run, ffmpeg, stop_after=None):
    merger.require(run.is_dir() and not run.is_symlink() and not run.is_junction(), 'invalid run')
    run = run.resolve()
    storage.FFMPEG = ffmpeg
    merger.FFMPEG = ffmpeg
    if (run / 'manifest.json').exists():
        cleanup(run, stop_after)
        return
    if (run / 'manifest.json.partial').exists():
        publish(run)
        cleanup(run, stop_after)
        return
    summary = json.loads((run / 'summary.json').read_text(encoding='utf-8-sig'))
    merger.require(summary['storage_codec'] == 'ffv1' and not summary['storage_failed'] and
                   summary['written_frames'] > 0, 'source not a complete FFV1 session')
    merger.require(not list(run.glob('*.partial')), 'unfinished source segment')
    merger.require(summary['configured_hz'] == 20 and summary['width'] == 640 and
                   summary['height'] == 360, 'unsupported recording format')
    # Conservatively reserve a full output copy plus 1 GiB. Sources remain intact
    # on out-of-space errors at any later stage too.
    source_size = sum(p.stat().st_size for p in run.iterdir() if p.is_file())
    merger.require(shutil.disk_usage(run).free > source_size + 1024**3, 'insufficient merge space')
    clear_scratch(run)
    # Only known scratch output was removed; all original source files remain.
    work = run / '.finalizing'
    work.mkdir()
    with (work / 'worker.log').open('w', encoding='utf-8') as log, contextlib.redirect_stdout(log):
        storage.verify_run(SimpleNamespace(run=run, ffmpeg=ffmpeg))
    inventory = {}
    source_reports = {}
    for path in run.iterdir():
        if ROOT_TEMP.fullmatch(path.name):
            safe_file(run, path.name)
            inventory[path.name] = {'bytes': path.stat().st_size, 'sha256': storage.file_sha(path)}
            if path.name.startswith('verification-'):
                source_reports[path.name] = json.loads(path.read_text(encoding='utf-8-sig'))
    # merge() requires a new directory. Preserve verification output inside its
    # known diagnostic file, then restore that after merge creates the workspace.
    verification_log = (work / 'worker.log').read_text(encoding='utf-8')
    (work / 'worker.log').unlink()
    work.rmdir()
    merger.merge(run, work)
    (work / 'worker.log').write_text(verification_log, encoding='utf-8')
    artifact = work / 'artifact'
    manifest = merger.verify_published(artifact)
    manifest['automatic_finalization'] = {
        'cleanup_sources': inventory, 'source_verification_reports': source_reports,
        'cleanup_rule': 'Only hash-matching listed source files after final artifact verification.'}
    # events.ndjson already exists and must stay byte-identical throughout.
    merger.require(storage.file_sha(run / 'events.ndjson') == manifest['files']['events.ndjson']['sha256'],
                   'source events changed')
    temporary_manifest = run / 'manifest.json.partial'
    storage.save(temporary_manifest, manifest)
    publish(run)
    cleanup(run, stop_after)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--ffmpeg', default=storage.FFMPEG)
    parser.add_argument('--test-stop-cleanup-after', type=int)
    args = parser.parse_args()
    run = args.run.resolve()
    merger.require(run.is_dir(), 'missing run')
    lock_path = safe_file(run, '.finalize.lock')
    # OS releases byte lock after a crash. Keeping a stale lock file is harmless.
    with lock_path.open('a+b') as lock:
        lock.seek(0)
        if lock.read(1) == b'':
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            finalize(run, args.ffmpeg, args.test_stop_cleanup_after)
        except Exception:
            work = run / '.finalizing'
            work.mkdir(exist_ok=True)
            safe_file(run, '.finalizing/error.txt').write_text(traceback.format_exc(), encoding='utf-8')
            raise
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    lock_path.unlink()


if __name__ == '__main__':
    main()
