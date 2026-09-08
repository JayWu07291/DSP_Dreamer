from pathlib import Path

import numpy as np

from dsp_dreamer import Recording, compile_recording, open_dataset
from dsp_dreamer import verify_recording, InvalidRecording
import pytest
import json


FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


def test_record_compile_read_preserves_adjacent_observations_and_actual_actions(tmp_path):
    """The public recording seam uses request identity even with reversed callbacks."""
    with Recording.synthetic(tmp_path / "source", FFMPEG, ticks_frequency=1000) as recording:
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        first = recording.request(50, unity_frame=3, game_tick=2)
        recording.input(50, held=["Digit1"], down=["Digit1"], up=[], delta=[2, -1], wheel=1)
        second = recording.request(100, unity_frame=6, game_tick=5)
        recording.input(100, held=[], down=[], up=["Digit1"], delta=[3, 4], wheel=-1)
        third = recording.request(150, unity_frame=9, game_tick=8)
        recording.complete(second, np.full((360, 640, 4), [9, 8, 7, 6], dtype=np.uint8))
        recording.complete(first, np.full((360, 640, 4), [1, 2, 3, 4], dtype=np.uint8))
        recording.complete(third, np.full((360, 640, 4), [5, 6, 7, 8], dtype=np.uint8))
    artifact = recording.publish(tmp_path / "evidence")
    compile_recording(artifact, tmp_path / "dataset", FFMPEG)
    dataset = open_dataset(tmp_path / "dataset")
    item = dataset[0]
    assert item["observation"][0, 0].tolist() == [1, 2, 3]
    assert item["next_observation"][0, 0].tolist() == [9, 8, 7]
    assert item["action"]["delta"] == [2, -1]
    assert item["action"]["down_counts"]["Digit1"] == 1
    assert item["action"]["held_fraction"]["Digit1"] == 1.0
    assert dataset[1]["action"]["delta"] == [3, 4]
    assert dataset[1]["action"]["up_counts"]["Digit1"] == 1
    assert item["source"]["capture_id"] == first["capture_id"]


@pytest.fixture
def evidence(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for i in range(205):
            request = recording.request(50 + i * 50, unity_frame=i * 3, game_tick=i * 3)
            recording.complete(request, np.full((360, 640, 4), [i % 256, 2, 3, (i * 13) % 256], dtype=np.uint8))
    return recording.publish(tmp_path / "evidence")


def test_segment_boundary_short_tail_and_nonconstant_alpha(evidence, tmp_path):
    manifest, frames, _ = verify_recording(evidence, FFMPEG)
    assert set(p.name for p in evidence.iterdir()) == {"recording.mkv", "frames.ndjson", "events.ndjson", "manifest.json"}
    assert manifest["validation"]["seek_ordinals"] == [0, 199, 200, 204]
    assert frames[200]["segment_ordinal"] == 0
    compile_recording(evidence, tmp_path / "dataset", FFMPEG)
    dataset = open_dataset(tmp_path / "dataset")
    assert dataset[199]["observation"][0, 0].tolist() == [199, 2, 3]
    assert dataset[199]["next_observation"][0, 0].tolist() == [200, 2, 3]
    assert dataset[203]["next_observation"][0, 0].tolist() == [204, 2, 3]


@pytest.mark.parametrize("filename", ["recording.mkv", "frames.ndjson", "events.ndjson", "manifest.json"])
def test_compiler_refuses_missing_file(evidence, tmp_path, filename):
    (evidence / filename).unlink()
    with pytest.raises((InvalidRecording, FileNotFoundError)):
        compile_recording(evidence, tmp_path / "dataset", FFMPEG)
    assert not (tmp_path / "dataset" / "COMPLETED").exists()


def test_compiler_refuses_checksum_error(evidence, tmp_path):
    with (evidence / "events.ndjson").open("ab") as stream:
        stream.write(b"{}\n")
    with pytest.raises(InvalidRecording, match="checksum"):
        compile_recording(evidence, tmp_path / "dataset", FFMPEG)


def test_loader_refuses_changed_table(evidence, tmp_path):
    compile_recording(evidence, tmp_path / "dataset", FFMPEG)
    with (tmp_path / "dataset" / "transitions.parquet").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(InvalidRecording, match="checksum"):
        open_dataset(tmp_path / "dataset")


def test_unknown_live_fingerprint_cannot_publish(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        for ticks in (0, 50):
            request = recording.request(ticks, unity_frame=ticks, game_tick=ticks)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    source = tmp_path / "source" / "SOURCE.json"
    metadata = json.loads(source.read_text())
    metadata.update(source_kind="live", runtime=dict(bepinex_version="5.4.23.5", harmonyx_version="2.9.0",
                    platform="Windows x64 Unity Mono", target_framework="net472", fingerprint_verified=True,
                    game_version="unknown", unity_version="unknown", plugin_version="unknown",
                    input_settings_sha256="unknown", binary_hashes={"unknown": "unknown"}))
    source.write_text(json.dumps(metadata))
    with pytest.raises(InvalidRecording, match="fingerprint"):
        recording.publish(tmp_path / "evidence")


def test_boundary_events_and_same_tick_input_keep_sequence_order(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks in (50, 100, 150):
            request = recording.request(ticks, unity_frame=ticks, game_tick=ticks)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
            if ticks == 100:
                recording.input(100, held=["W"], down=["W"], up=[], delta=[1, 0], wheel=0)
                recording.input(100, held=[], down=[], up=["W"], delta=[2, 0], wheel=0)
                recording.event(100, "tech_unlocked", tech_id=1001)
    evidence = recording.publish(tmp_path / "evidence")
    compile_recording(evidence, tmp_path / "dataset", FFMPEG)
    dataset = open_dataset(tmp_path / "dataset")
    assert dataset[0]["event_refs"] == []
    assert len(dataset[1]["event_refs"]) == 1
    assert dataset[1]["action"]["delta"] == [3, 0]
    assert dataset[1]["action"]["held_fraction"]["W"] == 0
    assert dataset[1]["action"]["binary"][4] == 1


def test_unknown_event_is_refused_at_publication(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.event(0, "unregistered_event")
        for ticks in (0, 50):
            request = recording.request(ticks, unity_frame=ticks, game_tick=ticks)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    with pytest.raises(InvalidRecording, match="event"):
        recording.publish(tmp_path / "evidence")


def test_scheduler_gap_invalidates_preceding_interval_only(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks in (50, 150, 200):
            request = recording.request(ticks, unity_frame=ticks, game_tick=ticks)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
            if ticks == 150:
                recording.gap(151, "scheduler", gap_start_ticks=100, gap_end_ticks=150)
    evidence = recording.publish(tmp_path / "evidence")
    compile_recording(evidence, tmp_path / "dataset", FFMPEG)
    dataset = open_dataset(tmp_path / "dataset")
    assert dataset[0]["valid"] is False
    assert dataset[1]["valid"] is True


def test_compiler_sorts_actual_input_by_ticks_then_sequence(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        recording.input(100, held=[], down=[], up=[], delta=[2, 0], wheel=0)
        recording.input(50, held=[], down=[], up=[], delta=[1, 0], wheel=0)
        for ticks in (50, 100, 150):
            request = recording.request(ticks, unity_frame=ticks, game_tick=ticks)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(tmp_path / "evidence")
    compile_recording(evidence, tmp_path / "dataset", FFMPEG)
    dataset = open_dataset(tmp_path / "dataset")
    assert dataset[0]["action"]["delta"] == [1, 0]
    assert dataset[1]["action"]["delta"] == [2, 0]
