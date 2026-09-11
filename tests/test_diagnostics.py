import json
from types import SimpleNamespace

import pytest

from dsp_dreamer.contract import InvalidRecording, file_info
from dsp_dreamer.diagnostics import inspect_diagnostic


def evidence(tmp_path, case="disable"):
    rows = [
        dict(type="header", schema="dsp-diagnostic/1", case=case, ticks_frequency=1000,
             runtime={"approved_fingerprint": "test"}, recording_session_id="session"),
        dict(type="control_request", operation="model_action", binary=[0]*4+[1]+[0]*15, succeeded=True, requested_count=1, sent_count=1),
        dict(type="input", held=["W"], down=["W"], up=[], focused=True),
        dict(type="callback", name="OnDisable"),
        dict(type="game_event", name="episode_ended", reason="stopped"),
        dict(type="control_request", operation="release_all", succeeded=True, requested_count=24, sent_count=24),
        dict(type="callback_completed", name="OnDisable"),
        dict(type="input", held=[], focused=True),
        dict(type="input", held=[], focused=True),
        dict(type="input", held=[], focused=True),
        dict(type="completed", published=True),
    ]
    for i, row in enumerate(rows):
        row.update(index=i, ticks=i*10)
    path = tmp_path / "case.ndjson"
    rows[0]["source"] = str(tmp_path / "case.source")
    dataset = SimpleNamespace(path=tmp_path / "case.source.dataset", metadata=dict(source_kind="live", diagnostic_mode=True,
        runtime=rows[0]["runtime"], recording_session_id="session", ticks_frequency=1000,
        episodes=[dict(validity_status="incomplete", validity_reasons=["stopped"], final_capture_id=None)]),
        events=[dict(type="game_event", name="episode_ended", reason="stopped")], rows=[])
    return path, rows, dataset


def write(path, rows):
    path.write_text("".join(json.dumps(r)+"\n" for r in rows), encoding="utf-8")
    path.with_name(path.name+".complete.json").write_text(json.dumps(dict(sha256=file_info(path)["sha256"])))


def test_lifecycle_requires_callback_release_and_post_callback_observation(tmp_path):
    path, rows, dataset = evidence(tmp_path)
    write(path, rows)
    assert inspect_diagnostic(dataset, path)["gate_passed"]
    for missing in (2, 5, 6, 8):
        damaged = [r for i, r in enumerate(rows) if i != missing]
        for i, r in enumerate(damaged):
            r = dict(r, index=i)
            damaged[i] = r
        write(path, damaged)
        assert not inspect_diagnostic(dataset, path)["gate_passed"]


def test_tampered_or_wrong_recording_rejected(tmp_path):
    path, rows, dataset = evidence(tmp_path)
    write(path, rows)
    path.write_text(path.read_text()+"\n")
    with pytest.raises(InvalidRecording):
        inspect_diagnostic(dataset, path)
    write(path, rows)
    dataset.metadata["recording_session_id"] = "other"
    with pytest.raises(InvalidRecording):
        inspect_diagnostic(dataset, path)


def test_final_fault_must_target_missing_final_capture(tmp_path):
    path, rows, dataset = evidence(tmp_path, "final_readback")
    dataset.metadata["episodes"][0]["validity_reasons"].append("recorder_fault")
    dataset.events = [dict(name="episode_ended", ticks=40), dict(operation="readback_fault_triggered",
        requested_ticks=45, capture_id=9, simulated=True)]
    dataset.rows = [dict(capture_id=7, next_capture_id=8)]
    write(path, rows)
    assert inspect_diagnostic(dataset, path)["gate_passed"]
    dataset.events[1]["requested_ticks"] = 39
    assert not inspect_diagnostic(dataset, path)["gate_passed"]
    dataset.events[1]["requested_ticks"] = 45
    dataset.rows[0]["next_capture_id"] = 9
    assert not inspect_diagnostic(dataset, path)["gate_passed"]


def test_focus_requires_return_and_no_residual_or_resumed_input(tmp_path):
    path, rows, dataset = evidence(tmp_path, "focus_hold")
    rows[4]["reason"] = "focus_loss"
    dataset.metadata["episodes"][0]["validity_reasons"] = ["focus_loss"]
    write(path, rows)
    assert not inspect_diagnostic(dataset, path)["gate_passed"]
    rows[7]["focused"] = False
    write(path, rows)
    assert inspect_diagnostic(dataset, path)["gate_passed"]
    rows[9]["held"] = ["W"]
    write(path, rows)
    assert not inspect_diagnostic(dataset, path)["gate_passed"]


def test_destroy_cannot_pass_with_disable_only(tmp_path):
    path, rows, dataset = evidence(tmp_path, "destroy")
    write(path, rows)
    assert not inspect_diagnostic(dataset, path)["gate_passed"]


@pytest.mark.parametrize("change", ["no_down", "zero_packets"])
def test_held_without_confirmed_injected_press_fails(tmp_path, change):
    path, rows, dataset = evidence(tmp_path)
    if change == "no_down":
        rows[2]["down"] = []
    else:
        rows[1].update(requested_count=0, sent_count=0)
    write(path, rows)
    assert not inspect_diagnostic(dataset, path)["gate_passed"]


def test_focus_checks_last_focused_sample_not_unfocused_reset(tmp_path):
    path, rows, dataset = evidence(tmp_path, "focus_hold")
    rows[3] = dict(rows[3], type="input", focused=False, held=[], down=[], up=["W"])
    rows[4]["reason"] = "focus_loss"
    rows[7]["focused"] = False
    dataset.metadata["episodes"][0]["validity_reasons"] = ["focus_loss"]
    write(path, rows)
    assert inspect_diagnostic(dataset, path)["gate_passed"]
    rows[3]["focused"] = True
    write(path, rows)
    assert not inspect_diagnostic(dataset, path)["gate_passed"]
