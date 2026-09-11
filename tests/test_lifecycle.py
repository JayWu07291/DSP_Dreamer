from pathlib import Path
import json

import numpy as np
import pytest

from dsp_dreamer import Recording, compile_recording, open_dataset, InvalidRecording
from dsp_dreamer.contract import file_info, sha


FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


def test_timeout_final_observation_and_retry_keep_source_identity(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.begin_attempt(dict(manifest_id="trial-1", split_group_id="trial-1",
                                     mecha_seed=17, camera_seed=29, policy_seed=41))
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks in (50, 100):
            request = recording.request(ticks, 1, 1)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.end_episode(120, outcome="timeout")
        request = recording.request(150, 2, 2)
        recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.begin_attempt(recording.metadata["trial_manifest"])
        for ticks in (500, 550):
            request = recording.request(ticks, 3, 3)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.end_episode(575, reason="recorder_fault")
    evidence = recording.publish(tmp_path / "evidence")
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert dataset[1]["bootstrap_mask"] == 1
    assert dataset[1]["truncation"] and not dataset[1]["is_terminal"]
    assert dataset[1]["episode_outcome"] == "timeout"
    assert not dataset[2]["valid"]
    assert dataset[3]["valid"] and dataset[3]["bootstrap_mask"] == 0
    assert dataset[3]["validity_status"] == "incomplete"
    assert dataset[0]["source"]["attempt_id"] != dataset[3]["source"]["attempt_id"]
    assert dataset[0]["source"]["split_group_id"] == dataset[3]["source"]["split_group_id"]
    assert dataset.sequence_starts(2) == [0]
    assert dataset.metadata["schema"] == "dsp-transitions/4"
    metadata_path = tmp_path / "dataset" / "dataset.json"
    old = dict(dataset.metadata, schema="dsp-transitions/1")
    metadata_path.write_text(json.dumps(old), encoding="utf-8")
    marker_path = tmp_path / "dataset" / "COMPLETED"
    marker = json.loads(marker_path.read_text())
    marker["files"]["dataset.json"] = file_info(metadata_path)
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(InvalidRecording, match="Recompile"):
        open_dataset(tmp_path / "dataset")


@pytest.mark.parametrize("outcome,reason,terminal,truncation,bootstrap,valid", [
    ("success", None, True, False, 0, True),
    ("death", None, True, False, 0, True),
    ("unrecoverable", None, True, False, 0, True),
    ("timeout", None, False, True, 1, True),
    ("timeout", "injection_failure", False, True, 0, False),
    (None, "focus_loss", False, False, 0, False),
    (None, "human_intervention", False, False, 0, False),
])
def test_end_results_and_late_callback_use_request_time(tmp_path, outcome, reason, terminal, truncation, bootstrap, valid):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0, paused=True)
        first = recording.request(50, 1, 1)
        second = recording.request(100, 2, 1)
        recording.end_episode(125, outcome, reason)
        recording.complete(second, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.complete(first, np.zeros((360, 640, 4), dtype=np.uint8))
        assert recording.episode["final_capture_id"] is None
        final = recording.request(150, 3, 1)
        recording.complete(final, np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(tmp_path / "evidence")
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert dataset[0]["valid"]  # Paused game ticks do not invalidate elapsed wall-clock input.
    assert dataset[1]["is_terminal"] is terminal
    assert dataset[1]["truncation"] is truncation
    assert dataset[1]["bootstrap_mask"] == bootstrap
    assert dataset[1]["valid"] is valid


def test_unknown_control_blocks_later_sequences_but_keeps_prefix(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks in (50, 100, 150, 200):
            if ticks == 150:
                recording.input(125, held=["F12"], down=["F12"], up=[], delta=[0, 0], wheel=0)
                recording.input(140, held=[], down=[], up=["F12"], delta=[0, 0], wheel=0)
            request = recording.request(ticks, 1, 1)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.end_episode(225, "timeout")
        request = recording.request(250, 1, 1)
        recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(tmp_path / "evidence")
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert dataset.sequence_starts(1) == [0]
    assert all("unknown_control" in dataset[i]["validity_reasons"] for i in range(len(dataset)))
    assert dataset[-1]["bootstrap_mask"] == 0
    assert dataset.metadata["episodes"][0]["validity_status"] == "invalid"


def test_gap_splits_sequences_and_missing_final_masks_only_tail(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks in (50, 100, 150, 200, 250, 300):
            request = recording.request(ticks, 1, 1)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.gap(175, "gpu_readback_error")
        recording.end_episode(325, reason="recorder_fault")
    evidence = recording.publish(tmp_path / "evidence")
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert dataset.sequence_starts(2) == [0, 3]
    assert not dataset[2]["valid"] and dataset[2]["bootstrap_mask"] == 0
    assert dataset[3]["valid"] and dataset[3]["bootstrap_mask"] == 1
    assert dataset[4]["valid"] and dataset[4]["bootstrap_mask"] == 0


def test_live_lifecycle_without_baseline_cannot_publish(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
        for ticks in (50, 100):
            request = recording.request(ticks, 1, 1)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.end_episode(125, reason="recorder_fault")
    path = tmp_path / "source" / "SOURCE.json"
    metadata = json.loads(path.read_text())
    # Deliberately malformed live source: runtime structure passes, but trial provenance is absent.
    hashes = dict.fromkeys(("Assembly-CSharp", "BepInEx", "0Harmony", "DSPDreamer.Recorder", "UnityPlayer", "DSPGAME",
                            "UnityEngine.InputLegacyModule", "UnityEngine.CoreModule", "UnityEngine.ScreenCaptureModule"), "0" * 64)
    hashes["Assembly-CSharp"] = "ae0ba95f75bd879a62aa4ce253b2ab78eaa4fb3c7c595f5e1fee75ebe0e0ef85"
    runtime = dict(bepinex_version="5.4.23.5", harmonyx_version="2.9.0", platform="Windows x64 Unity Mono",
                   target_framework="net472", game_version="test", unity_version="test", plugin_version="test",
                   input_settings_sha256="0" * 64, binary_hashes=hashes)
    digest = sha(json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode())
    runtime.update(fingerprint_verified=True, approved_fingerprint=digest)
    metadata.update(source_kind="live", runtime=runtime)
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(InvalidRecording, match="Missing baseline"):
        recording.publish(tmp_path / "evidence")
