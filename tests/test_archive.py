from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest

from dsp_dreamer import Recording, publish, verify_recording, compile_recording, open_dataset
from dsp_dreamer.contract import InvalidRecording, file_info

FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


def make_source(path, count=3):
    with Recording.synthetic(path, FFMPEG) as recording:
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for i in range(count):
            frame = recording.request(50 + 50 * i, i, i)
            recording.complete(frame, np.full((360, 640, 4), i % 256, dtype=np.uint8))
    return path


def test_publication_cleanup_and_retry_preserve_evidence_and_other_files(tmp_path):
    source = make_source(tmp_path / "source")
    other = source / "unrelated.txt"
    other.write_text("keep")
    destination = tmp_path / "evidence"
    publish(source, destination, FFMPEG, cleanup=True)
    before = {p.name: file_info(p) for p in destination.iterdir()}
    assert not (source / "segment-000000.mkv").exists()
    assert other.read_text() == "keep"
    publish(source, destination, FFMPEG, cleanup=True)
    assert before == {p.name: file_info(p) for p in destination.iterdir()}
    assert verify_recording(destination, FFMPEG)[0]["frame_count"] == 3


def test_truncated_tail_recovers_verified_prefix_into_new_artifact(tmp_path):
    from dsp_dreamer import recover
    source = make_source(tmp_path / "source", 205)
    tail = source / "segment-000001.mkv"
    tail.write_bytes(tail.read_bytes()[:100])
    before = {p.name: file_info(p) for p in source.iterdir() if p.is_file()}
    evidence = recover(source, tmp_path / "recovered", FFMPEG)
    manifest, frames, _ = verify_recording(evidence, FFMPEG)
    assert len(frames) == 200
    assert manifest["recovery"]["excluded_from_ordinal"] == 200
    assert manifest["recovery"]["recording_complete"] is False
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert len(dataset) == 199 and dataset[-1]["bootstrap_mask"] == 0
    assert before == {p.name: file_info(p) for p in source.iterdir() if p.is_file()}


@pytest.mark.parametrize("target", ["frames.ndjson", "manifest.json"])
def test_partial_publication_is_refused_by_compiler_and_can_retry(tmp_path, monkeypatch, target):
    source = make_source(tmp_path / "source")
    destination = tmp_path / "evidence"
    rename = Path.rename

    def interrupted(path, other):
        if Path(other) == destination / target:
            raise OSError("injected publication interruption")
        return rename(path, other)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", interrupted)
        with pytest.raises(OSError, match="injected"):
            publish(source, destination, FFMPEG, cleanup=True)
    with pytest.raises(FileNotFoundError):
        compile_recording(destination, tmp_path / "refused", FFMPEG)
    assert (source / "SOURCE.json").exists()
    publish(source, destination, FFMPEG, cleanup=True)
    assert verify_recording(destination, FFMPEG)[0]["frame_count"] == 3


def test_cleanup_interruption_can_retry_without_changing_evidence(tmp_path, monkeypatch):
    source = make_source(tmp_path / "source")
    destination = tmp_path / "evidence"
    unlink = Path.unlink

    def interrupted(path, *args, **kwargs):
        if path == source / "segment-000000.mkv":
            raise OSError("injected cleanup interruption")
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupted)
        with pytest.raises(OSError, match="injected"):
            publish(source, destination, FFMPEG, cleanup=True)
    before = {p.name: file_info(p) for p in destination.iterdir()}
    publish(source, destination, FFMPEG, cleanup=True)
    assert before == {p.name: file_info(p) for p in destination.iterdir()}
    assert not (source / "segment-000000.mkv").exists()


def test_low_space_and_source_changes_preserve_sources(tmp_path, monkeypatch):
    source = make_source(tmp_path / "source")
    before = {p.name: file_info(p) for p in source.iterdir()}
    with monkeypatch.context() as patch:
        patch.setattr(shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(100, 99, 1))
        with pytest.raises(InvalidRecording, match="free space"):
            publish(source, tmp_path / "low-space", FFMPEG, cleanup=True)
    assert before == {p.name: file_info(p) for p in source.iterdir()}
    event_path = source / "events.ndjson"
    event_path.write_text(event_path.read_text().replace('"wheel": 0', '"wheel": 1'))
    with pytest.raises(InvalidRecording, match="seal"):
        publish(source, tmp_path / "changed", FFMPEG, cleanup=True)
    assert not (tmp_path / "changed" / "manifest.json").exists()
    assert (source / "segment-000000.mkv").exists()


def test_source_change_during_merge_and_merge_failure_keep_sources(tmp_path, monkeypatch):
    source = make_source(tmp_path / "source")
    copyfile = shutil.copyfile

    def changed(first, second, *args, **kwargs):
        result = copyfile(first, second, *args, **kwargs)
        if Path(first) == source / "segment-000000.mkv":
            with Path(first).open("ab") as stream:
                stream.write(b"changed")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "copyfile", changed)
        with pytest.raises(InvalidRecording, match="Source changed"):
            publish(source, tmp_path / "changed", FFMPEG, cleanup=True)
    assert (source / "SOURCE.json").exists()
    source = make_source(tmp_path / "merge-source")
    with monkeypatch.context() as patch:
        def failed(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "injected ffmpeg merge")
        patch.setattr(subprocess, "run", failed)
        with pytest.raises(subprocess.CalledProcessError):
            publish(source, tmp_path / "merge", FFMPEG, cleanup=True)
    assert (source / "segment-000000.mkv").exists()
    assert not (tmp_path / "merge" / "manifest.json").exists()


def test_changed_cleanup_inventory_cannot_delete_another_session(tmp_path):
    source = make_source(tmp_path / "source")
    other = make_source(tmp_path / "other")
    destination = publish(source, tmp_path / "evidence", FFMPEG)
    path = destination / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["source_files"]["../other/segment-000000.mkv"] = file_info(other / "segment-000000.mkv")
    path.write_text(json.dumps(manifest))
    with pytest.raises(InvalidRecording, match="Unsafe"):
        publish(source, destination, FFMPEG, cleanup=True)
    assert (other / "segment-000000.mkv").exists()
    assert (source / "SOURCE.json").exists()


def test_changed_source_before_cleanup_refuses_all_deletion(tmp_path):
    source = make_source(tmp_path / "source")
    destination = publish(source, tmp_path / "evidence", FFMPEG)
    with (source / "events.ndjson").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(InvalidRecording, match="Source changed"):
        publish(source, destination, FFMPEG, cleanup=True)
    assert (source / "frames.ndjson").exists()
    assert (source / "segment-000000.mkv").exists()


def test_unsealed_or_corrupted_first_segment_cannot_recover(tmp_path):
    from dsp_dreamer import recover
    source = make_source(tmp_path / "source", 200)
    (source / "segment-000000.mkv").write_bytes(b"bad")
    with pytest.raises(InvalidRecording, match="No verified continuous prefix"):
        recover(source, tmp_path / "recovered", FFMPEG)
    assert not (tmp_path / "recovered").exists()


def test_finish_retries_completed_dataset(tmp_path):
    source = make_source(tmp_path / "source")
    command = [sys.executable, "-m", "dsp_dreamer", "finish", "--source", str(source), "--ffmpeg", str(FFMPEG)]
    subprocess.run(command, check=True, capture_output=True)
    evidence = source.with_name(source.name + ".evidence")
    before = {p.name: file_info(p) for p in evidence.iterdir()}
    subprocess.run(command, check=True, capture_output=True)
    assert before == {p.name: file_info(p) for p in evidence.iterdir()}


def test_native_writer_termination_recovers_checkpoint(tmp_path):
    from dsp_dreamer import recover
    project = Path(__file__).parent / "ArchiveRecovery" / "ArchiveRecovery.csproj"
    subprocess.run(["dotnet", "build", str(project), "--no-restore", "--nologo", "-v:q"], check=True, capture_output=True)
    executable = project.parent / "bin" / "Debug" / "net472" / "ArchiveRecovery.exe"
    source = tmp_path / "native"
    worker = subprocess.Popen([str(executable), str(source), str(FFMPEG)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        deadline = time.monotonic() + 30
        while not (source / "checkpoint-000000.json").exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (source / "checkpoint-000000.json").exists(), worker.communicate(timeout=1)
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=10)
    assert not (source / "SOURCE.json").exists()
    evidence = recover(source, tmp_path / "recovered", FFMPEG)
    assert verify_recording(evidence, FFMPEG)[0]["frame_count"] == 200
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert len(dataset) == 199 and dataset[-1]["bootstrap_mask"] == 0


def test_recovery_trims_lifecycle_and_progress_without_claiming_completion(tmp_path):
    from dsp_dreamer import recover
    source = tmp_path / "source"
    with Recording.synthetic(source, FFMPEG) as recording:
        recording.metadata.update(progress_version=3, progress_tech_ids=[1001, 1002, 1003, 1004, 1005])
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="split", mecha_seed=1, camera_seed=2, policy_seed=3))
        episode = recording.episode["episode_id"]
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for i in range(205):
            ticks = (i + 1) * 50
            if i == 1:
                recording.event(ticks - 1, "progress_fact", episode_id=episode, kind="lander_work", work_ticks=1)
            frame = recording.request(ticks, i, i)
            recording.event(ticks, "progress_observation", episode_id=episode, capture_id=frame["capture_id"])
            recording.complete(frame, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.end_episode(ticks + 1, reason="stopped")
    # A torn final NDJSON record invalidates SOURCE but leaves the checkpoint prefix intact.
    index = source / "frames.ndjson"
    index.write_bytes(index.read_bytes()[:-10])
    evidence = recover(source, tmp_path / "recovered", FFMPEG)
    manifest, frames, _ = verify_recording(evidence, FFMPEG)
    assert len(frames) == 200
    assert manifest["episodes"][0]["validity_status"] == "incomplete"
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert dataset[0]["reward"] == 1 and dataset[0]["source"]["split_group_id"] == "split"
    assert dataset[-1]["bootstrap_mask"] == 0 and not dataset[-1]["valid"]
    assert dataset.metadata["recovery"]["recording_complete"] is False
    assert recover(source, evidence, FFMPEG) == evidence


def test_archiver_process_termination_can_resume_publication(tmp_path):
    source = make_source(tmp_path / "source")
    destination = tmp_path / "evidence"
    script = tmp_path / "worker.py"
    script.write_text('''import sys, time
from pathlib import Path
from dsp_dreamer import publish
rename = Path.rename
def paused(path, target):
    if Path(target).name == "manifest.json":
        Path(sys.argv[3]).write_text("ready")
        time.sleep(60)
    return rename(path, target)
Path.rename = paused
publish(sys.argv[1], sys.argv[2], sys.argv[4], cleanup=True)
''')
    marker = tmp_path / "ready"
    worker = subprocess.Popen([sys.executable, str(script), str(source), str(destination), str(marker), str(FFMPEG)],
        env=dict(os.environ, PYTHONPATH=str(Path.cwd())), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 30
        while not marker.exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=10)
    assert not (destination / "manifest.json").exists()
    publish(source, destination, FFMPEG, cleanup=True)
    assert verify_recording(destination, FFMPEG)[0]["frame_count"] == 3
