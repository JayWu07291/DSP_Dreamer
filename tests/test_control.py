from pathlib import Path
import itertools
import json
import subprocess

import numpy as np
import pytest

from dsp_dreamer import Recording, compile_recording, open_dataset
from dsp_dreamer.control import inspect_control, publish_calibration
from dsp_dreamer import InvalidRecording
from dsp_dreamer.actions import ACTION_CODEC, SCANCODES, decode_action, forbidden_buttons
from dsp_dreamer.contract import CATALOG, CONTROLS, sha


FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


def test_native_action_contract_matches_model_codec():
    project = Path(__file__).parent / "ControlReplay"
    subprocess.run(["dotnet", "build", str(project / "ControlReplay.csproj"), "--no-restore"], check=True, capture_output=True)
    result = json.loads(subprocess.check_output([str(project / "bin/Debug/net472/ControlReplay.exe")], text=True))
    assert result["controls"] == CONTROLS
    assert result['codec_sha256'] == sha(json.dumps(ACTION_CODEC, sort_keys=True).encode())
    from dsp_dreamer.runner import timing_report
    cases = [[], [20] * 99 + [101], [80] * 100, [81] * 100, [20] * 500]
    results = [timing_report([dict(step=i, capture_ticks=i * 1000, requested_ticks=i * 1000 + v,
                                  missed=v > 100 or case == 4 and i < 5) for i, v in enumerate(values)], 1000)['passed']
               for case, values in enumerate(cases)]
    assert result['timing_passed'] == results == [False, True, True, False, False]
    assert result["scan_codes"] == [v or 0 for v in SCANCODES]
    assert result["scan_codes"][1:3] == [2, 3]
    assert result["controls"][13] == "X" and result["controls"][20] == "B"
    assert result["scan_codes"][20] == 0x30
    assert result["pixels"] == [int(np.rint(decode_action(dict(binary=[0] * len(CONTROLS), mouse=i * 11 + 5, wheel=1))["pixel_delta"][0])) for i in range(11)]
    expected = []
    for a, b in itertools.combinations(range(len(CONTROLS)), 2):
        binary = [int(i in (a, b)) for i in range(len(CONTROLS))]
        if not forbidden_buttons(binary):
            expected.append([a, b])
    assert result["legal_pairs"] == expected


def test_requests_never_replace_observed_training_labels(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(55), type="control_request", operation="model_action",
            request_id=1, catalog=CATALOG, binary=[0, 1] + [0] * (len(CONTROLS) - 2), mouse=60, wheel=1,
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


@pytest.mark.parametrize("fault", [None, "partial_send", "missing_down", "stuck_release", "early_up", "rejected", "deadline_miss", "boundary", "release_noop", "final_noop_release", "retry_release"])
def test_control_confirmation_and_release_from_compiled_evidence(tmp_path, fault):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata["diagnostic_mode"] = True
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        bits = [int(i == 15) for i in range(len(CONTROLS))]
        recording.events.append(dict(recording.identity(55), type="control_request", operation="model_action",
            request_id=1, catalog=CATALOG, binary=bits, mouse=60, wheel=1,
            requested_ticks=55, sent_count=0 if fault == "partial_send" else 1, requested_count=1, succeeded=True))
        recording.input(55 if fault == "boundary" else 65, held=["MouseLeft"], down=[] if fault == "missing_down" else ["MouseLeft"],
                        up=[], delta=[0, 0], wheel=0)
        if fault == "early_up":
            recording.input(85, held=[], down=[], up=["MouseLeft"], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(175), type="control_request", operation="release_all",
            requested_ticks=175, sent_count=20, requested_count=20, succeeded=True))
        if fault in ("release_noop", "final_noop_release", "retry_release"):
            recording.events.append(dict(recording.identity(176), type="control_request", operation="model_action",
                request_id=2, catalog=CATALOG, **ACTION_CODEC['noop'], requested_ticks=176,
                sent_count=0, requested_count=0, succeeded=True))
        if fault == "final_noop_release":
            recording.events.append(dict(recording.identity(177), type="control_request", operation="release_all",
                requested_ticks=177, sent_count=21, requested_count=21, succeeded=True))
        recording.input(185, held=["MouseLeft"] if fault in ("stuck_release", "retry_release") else [], down=[],
                        up=[] if fault in ("stuck_release", "early_up", "retry_release") else ["MouseLeft"], delta=[0, 0], wheel=0)
        if fault in ("rejected", "deadline_miss"):
            recording.events.append(dict(recording.identity(190), type="control_request", operation=fault))
        if fault in ("release_noop", "retry_release"):
            recording.events.append(dict(recording.identity(225), type="control_request", operation="release_all",
                requested_ticks=225, sent_count=21, requested_count=21, succeeded=True))
            recording.input(235, held=[], down=[], up=["MouseLeft"] if fault == "retry_release" else [], delta=[0, 0], wheel=0)
        for ticks in (50, 100, 150, 200, 250):
            frame = recording.request(ticks, 1, 1)
            recording.complete(frame, np.zeros((360, 640, 4), dtype=np.uint8))
    dataset = open_dataset(compile_recording(recording.publish(tmp_path / "evidence"), tmp_path / "dataset", FFMPEG))
    report = inspect_control(dataset)
    assert report["gate_passed"] is (fault in (None, "boundary", "release_noop", "final_noop_release"))
    if fault == "retry_release":
        assert not report['releases'][0]['released'] and report['releases'][1]['released']
        assert not report['requests'][1]['observed']
    if fault is None:
        assert report["requests"][0]["latency_ms"] == 10
        assert report["requests"][0]["held_ms"] == 120
    if fault == "boundary":
        assert report["requests"][0]["latency_ms"] == 0
    with pytest.raises(InvalidRecording, match="live diagnostic"):
        publish_calibration(dataset, tmp_path / "calibration.json")
    assert not (tmp_path / "calibration.json").exists()


@pytest.mark.parametrize("reset_logged,keypad", [(True, "End"), (True, "Keypad1"), (False, "End"), (True, "Digit1")])
def test_game_reset_and_numpad_identity_keep_actual_inputs(tmp_path, reset_logged, keypad):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata["diagnostic_mode"] = True
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(55), type="control_request", operation="model_action",
            request_id=1, catalog=CATALOG, binary=[int(i == 6) for i in range(len(CONTROLS))], mouse=60, wheel=1,
            requested_ticks=55, sent_count=1, requested_count=1, succeeded=True))
        recording.input(65, held=["T"], down=["T"], up=[], delta=[0, 0], wheel=0)
        if reset_logged:
            recording.events.append(dict(recording.identity(80), type="control_request", operation="game_input_reset",
                                         source="VFInput.ResetAllAxes"))
        recording.input(85, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(175), type="control_request", operation="release_all",
            requested_ticks=175, sent_count=20, requested_count=20, succeeded=True))
        recording.input(185, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(195), type="control_request", operation="identity_probe",
            scan_code=0x4F, requested_ticks=195, sent_count=1, requested_count=1, succeeded=True))
        recording.input(205, held=[keypad], down=[keypad], up=[], delta=[0, 0], wheel=0)
        recording.events.append(dict(recording.identity(215), type="control_request", operation="release_all",
            requested_ticks=215, sent_count=20, requested_count=20, succeeded=True))
        recording.input(225, held=[], down=[], up=[keypad], delta=[0, 0], wheel=0)
        for ticks in (50, 100, 150, 200, 250):
            frame = recording.request(ticks, 1, 1)
            recording.complete(frame, np.zeros((360, 640, 4), dtype=np.uint8))
    dataset = open_dataset(compile_recording(recording.publish(tmp_path / "evidence"), tmp_path / "dataset", FFMPEG))
    report = inspect_control(dataset)
    assert report["gate_passed"] is (reset_logged and keypad != "Digit1")
    assert dataset[0]["action"]["ambiguous"]  # A reset never invents a key-up training label.
