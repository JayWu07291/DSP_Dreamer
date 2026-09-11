from pathlib import Path
import itertools
import json
import subprocess

import numpy as np
import pytest

from dsp_dreamer import Recording, compile_recording, open_dataset
from dsp_dreamer.control import inspect_control, publish_calibration
from dsp_dreamer import InvalidRecording
from dsp_dreamer.actions import SCANCODES, decode_action, forbidden_buttons
from dsp_dreamer.contract import CONTROLS


FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


def test_native_action_contract_matches_model_codec():
    project = Path(__file__).parent / "ControlReplay"
    subprocess.run(["dotnet", "build", str(project / "ControlReplay.csproj"), "--no-restore"], check=True, capture_output=True)
    result = json.loads(subprocess.check_output([str(project / "bin/Debug/net472/ControlReplay.exe")], text=True))
    assert result["controls"] == CONTROLS
    assert result["scan_codes"] == [v or 0 for v in SCANCODES]
    assert result["scan_codes"][1:3] == [2, 3]
    assert result["pixels"] == [int(np.rint(decode_action(dict(binary=[0] * 20, mouse=i * 11 + 5, wheel=1))["pixel_delta"][0])) for i in range(11)]
    expected = []
    for a, b in itertools.combinations(range(20), 2):
        binary = [int(i in (a, b)) for i in range(20)]
        if not forbidden_buttons(binary):
            expected.append([a, b])
    assert result["legal_pairs"] == expected


def test_requests_never_replace_observed_training_labels(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(55), type="control_request", operation="model_action",
            request_id=1, catalog="action_catalog_v3", binary=[0, 1] + [0] * 18, mouse=60, wheel=1,
            requested_ticks=55, sent_count=1, requested_count=1, succeeded=True))
        # Windows accepted Digit1, but DSP actually saw Digit2. Submission is not observation.
        recording.input(65, held=["Digit2"], down=["Digit2"], up=[], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(175), type="control_request", operation="release_all",
            requested_ticks=175, sent_count=20, requested_count=20, succeeded=True, simulated=False))
        recording.input(185, held=[], down=[], up=["Digit2"], delta=[0, 0], wheel=0)
        for ticks in (50, 100, 150, 200, 250):
            request = recording.request(ticks, 1, 1)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(tmp_path / "evidence")
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert dataset[0]["action"]["binary"][1:3] == [0, 1]
    report = inspect_control(dataset)
    assert report["requests"][0]["observed"] is False
    assert report["requests"][0]["latency_ms"] is None
    assert report["releases"][0]["released"] is True
    assert report["gate_passed"] is False


@pytest.mark.parametrize("fault", [None, "partial_send", "missing_down", "stuck_release", "early_up", "rejected", "deadline_miss", "boundary"])
def test_control_confirmation_and_release_from_compiled_evidence(tmp_path, fault):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata["diagnostic_mode"] = True
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        bits = [int(i == 15) for i in range(20)]
        recording.events.append(dict(recording.identity(55), type="control_request", operation="model_action",
            request_id=1, catalog="action_catalog_v3", binary=bits, mouse=60, wheel=1,
            requested_ticks=55, sent_count=0 if fault == "partial_send" else 1, requested_count=1, succeeded=True))
        recording.input(55 if fault == "boundary" else 65, held=["MouseLeft"], down=[] if fault == "missing_down" else ["MouseLeft"],
                        up=[], delta=[0, 0], wheel=0)
        if fault == "early_up":
            recording.input(85, held=[], down=[], up=["MouseLeft"], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(175), type="control_request", operation="release_all",
            requested_ticks=175, sent_count=20, requested_count=20, succeeded=True))
        recording.input(185, held=["MouseLeft"] if fault == "stuck_release" else [], down=[],
                        up=[] if fault in ("stuck_release", "early_up") else ["MouseLeft"], delta=[0, 0], wheel=0)
        if fault in ("rejected", "deadline_miss"):
            recording.events.append(dict(recording.identity(190), type="control_request", operation=fault))
        for ticks in (50, 100, 150, 200, 250):
            frame = recording.request(ticks, 1, 1)
            recording.complete(frame, np.zeros((360, 640, 4), dtype=np.uint8))
    dataset = open_dataset(compile_recording(recording.publish(tmp_path / "evidence"), tmp_path / "dataset", FFMPEG))
    report = inspect_control(dataset)
    assert report["gate_passed"] is (fault in (None, "boundary"))
    if fault is None:
        assert report["requests"][0]["latency_ms"] == 10
        assert report["requests"][0]["held_ms"] == 120
    if fault == "boundary":
        assert report["requests"][0]["latency_ms"] == 0
    with pytest.raises(InvalidRecording, match="live diagnostic"):
        publish_calibration(dataset, tmp_path / "calibration.json")
    assert not (tmp_path / "calibration.json").exists()
