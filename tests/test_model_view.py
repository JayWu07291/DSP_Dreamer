import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dsp_dreamer import Recording, InvalidRecording, compile_recording, open_dataset, open_model_view
from dsp_dreamer.actions import ACTION_CODEC, decode_action, encode_action, validate_action_contract
from dsp_dreamer.contract import file_info
from dsp_dreamer.dataset import aggregate, table_contract


FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


def build(tmp_path, samples, *, ticks=range(0, 451, 50), facts=(), gap=None):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata.update(progress_version=1, progress_tech_ids=[1001, 1002, 1003, 1004, 1005])
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
        for sample in samples:
            recording.input(**sample)
        for time, fact in facts:
            recording.event(time, "progress_fact", episode_id=recording.episode["episode_id"], **fact)
        if gap:
            recording.gap(gap[1], "scheduler", gap_start_ticks=gap[0], gap_end_ticks=gap[1])
        for time in ticks:
            if time == ticks[-1]:
                recording.end_episode(time - 1, "timeout")
            request = recording.request(time, time, time)
            recording.complete(request, np.full((360, 640, 4), [time % 256, 17, 255, 42], dtype=np.uint8))
    evidence = recording.publish(tmp_path / "evidence")
    return compile_recording(evidence, tmp_path / "dataset", FFMPEG)


def sample(ticks, held=(), down=(), up=(), delta=(0, 0), wheel=0, **extra):
    return dict(ticks=ticks, held=list(held), down=list(down), up=list(up), delta=list(delta), wheel=wheel, **extra)


def test_original_time_click_threshold_task_boundary_and_digit_indices(tmp_path):
    path = build(tmp_path, [
        sample(0, ["W"], ["W"]), sample(10, ["W", "Digit1"], ["Digit1"]),
        sample(20, ["W"], up=["Digit1"], delta=[.2, 0], wheel=1),
        sample(50, up=["W"]), sample(75, delta=[-.1, 0], wheel=-1),
        sample(110, ["Digit1"], ["Digit1"]), sample(200, ["Digit1"]), sample(250, up=["Digit1"]),
        sample(310, ["Digit2", "Tab", "R", "E"], ["Digit2", "Tab", "R", "E"]),
        sample(350, up=["Digit2", "Tab", "R", "E"]),
    ], facts=[(50, dict(kind="lander_work", work_ticks=1)),
              (100, dict(kind="research_queue", tech_ids=[1001, 1002, 1003, 1004, 1005]))])
    dataset, view = open_dataset(path), open_model_view(path)
    assert len(dataset) == 9 and len(view) == 5
    first, second, third, fourth = [view[i] for i in range(4)]
    assert first["actual_action"]["held_fraction"]["Digit1"] == .1
    assert first["inputs"]["action"]["binary"][1] == 1
    assert first["inputs"]["action"]["mouse"] == 82 and first["inputs"]["action"]["wheel"] == 1
    assert first["actual_action"]["down_counts"]["Digit1"] == first["actual_action"]["up_counts"]["Digit1"] == 1
    assert second["actual_action"]["end_held"] == third["actual_action"]["start_held"] == ["Digit1"]
    assert third["actual_action"]["held_fraction"]["Digit1"] == .5
    assert third["inputs"]["action"]["binary"][1] == 1
    assert [i for i, v in enumerate(fourth["inputs"]["action"]["binary"]) if v] == [2, 3, 5, 19]
    assert first["targets"]["reward"] == second["targets"]["reward"] == 1
    assert first["targets"]["reward_vector"].tolist() == [1] + [0] * 15
    assert first["task_switches"] == [dict(ticks=100, task_id=1)]
    assert second["task_switches"] == [dict(ticks=150, task_id=16)]
    assert first["source"]["transition_indices"] == [0, 1]
    assert second["source"]["requested_ticks"] == 100
    assert first["actual_action"]["sample_refs"] == [e["sequence_number"] for e in dataset.events if e["type"] == "input" and 0 <= e["ticks"] < 100]
    assert not set(first["event_refs"]) & set(second["event_refs"])
    assert first["inputs"]["observation"].shape == (3, 360, 640)
    assert first["inputs"]["observation"].dtype == np.float32
    np.testing.assert_array_equal(first["inputs"]["observation"][:, 359, 639], np.array([0, 17, 255], np.float32) / 255)
    assert set(first["inputs"]) == {"observation", "task_condition", "action"}
    assert view.sequence_starts(3) == [0, 1]
    batch = view.sequence(0, 6, burn_in=1)
    assert batch["valid_mask"].tolist() == [True] * 4 + [False] * 2
    assert batch["loss_mask"].tolist() == [False] + [True] * 3 + [False] * 2
    assert view[4]["valid_mask"] and not view[4]["loss_mask"] and view[4]["targets"]["bootstrap_mask"] == 0
    assert view.metadata == open_model_view(path).metadata


def test_second_down_across_20hz_boundary_excludes_bc_and_dynamics(tmp_path):
    path = build(tmp_path, [sample(10, ["MouseLeft"], ["MouseLeft"]), sample(20, up=["MouseLeft"]),
                            sample(60, ["MouseLeft"], ["MouseLeft"]), sample(70, up=["MouseLeft"])], ticks=range(0, 301, 50))
    dataset, view = open_dataset(path), open_model_view(path)
    assert all(dataset.rows[i]["valid"] for i in (0, 1))
    assert view[0]["actual_action"]["ambiguous"] and view[0]["inputs"]["action"] is None
    assert view.sequence_starts(1) == [1, 2]
    with pytest.raises(InvalidRecording, match="invalid range"):
        view.sequence(0, 1)
    assert view[2]["targets"]["truncation"] and view[2]["targets"]["bootstrap_mask"] == 1


@pytest.mark.parametrize("keys", [["W", "S"], ["A", "D"], ["LeftControl", "LeftShift"],
    ["MouseLeft", "MouseRight"], ["MouseLeft", "MouseMiddle"], ["MouseRight", "MouseMiddle"]])
def test_forbidden_combinations(keys):
    action = aggregate([], 0, 100, keys)
    assert action["forbidden"]
    with pytest.raises(InvalidRecording):
        encode_action(action)


@pytest.mark.parametrize("keys", [["A", "W"], ["D", "W"], ["LeftControl", "MouseLeft"],
    ["LeftShift", "MouseLeft"], ["LeftShift", "R"], ["Digit1", "Digit2"]])
def test_legal_combinations(keys):
    assert set(decode_action(encode_action(aggregate([], 0, 100, keys)))["held"]) == set(keys)


@pytest.mark.parametrize("key", ["Numpad1", "Keypad1", "RightControl", "RightShift", "Mouse3", "CapsLock", "F8", "unknown"])
def test_unsupported_inputs_remain_evidence(key):
    action = aggregate([dict(sample(10, [key], [key]), sequence_number=42)], 0, 100, [])
    assert action["unsupported"] and action["down_counts"][key] == 1 and action["sample_refs"] == [42]
    assert action["binary"][1] == 0


def test_quantizer_roundtrips_all_classes_and_unique_noop():
    for mouse in range(121):
        for wheel in range(3):
            code = dict(binary=[0] * 20, mouse=mouse, wheel=wheel)
            decoded = decode_action(code)
            actual = aggregate([dict(sample(0, delta=decoded["observed_delta"], wheel=decoded["wheel"]), sequence_number=0)], 0, 100, [])
            assert encode_action(actual) == code
            assert (decoded["pixel_delta"] == [0, 0] and decoded["wheel"] == 0) == (mouse == 60 and wheel == 1)
    assert ACTION_CODEC["scan_codes"][1] == 0x02 and ACTION_CODEC["unity_names"][1] == "Alpha1"
    for old in ("action_catalog_v1", "action_catalog_v2"):
        with pytest.raises(InvalidRecording, match="legacy checkpoints"):
            validate_action_contract(dict(ACTION_CODEC, catalog=old, binary_width=17))


def test_horizontal_wheel_illegal_order_and_threshold():
    action = aggregate([dict(sample(0, horizontal_wheel=1), sequence_number=0),
                        dict(sample(1, horizontal_wheel=-1), sequence_number=1)], 0, 100, [])
    assert action["unsupported"] and action["horizontal_wheel"] == 0
    action = aggregate([dict(sample(50, up=["W"]), sequence_number=0)], 0, 100, ["W"])
    assert action["binary"][4] == 1
    action = aggregate([dict(sample(49, up=["W"]), sequence_number=0)], 0, 100, ["W"])
    assert action["binary"][4] == 0
    action = aggregate([dict(sample(50, ["Digit1"]), sequence_number=0)], 0, 100, [])
    assert action["ambiguous"]


def test_gap_cannot_be_hidden_by_resampling_or_padding(tmp_path):
    path = build(tmp_path, [sample(0)], ticks=[0, 50, 150, 200, 250, 300, 350], gap=(100, 150))
    view = open_model_view(path)
    assert not view[0]["loss_mask"] and view[0]["source"]["next_requested_ticks"] == 150
    assert view.sequence_starts(2) == [1]
    assert view.sequence(1, 3)["valid_mask"].tolist() == [True, True, False]


def reseal(path):
    marker = json.loads((path / "COMPLETED").read_text())
    marker["files"] = {p.relative_to(path).as_posix(): file_info(p) for p in path.rglob("*") if p.is_file() and p.name != "COMPLETED"}
    (path / "COMPLETED").write_text(json.dumps(marker))


@pytest.mark.parametrize("corruption", ["schema", "catalog", "codec", "missing", "time", "index", "event", "reference", "action", "action_dtype", "table", "checksum"])
def test_loader_rejects_incompatible_or_corrupt_artifacts(tmp_path, corruption):
    path = build(tmp_path, [sample(0)], ticks=range(0, 201, 50))
    metadata = json.loads((path / "dataset.json").read_text())
    if corruption in ("schema", "catalog", "codec", "missing"):
        if corruption == "schema":
            metadata["schema"] = "dsp-transitions/99"
        elif corruption == "catalog":
            metadata["catalog"] = "action_catalog_v1"
        elif corruption == "codec":
            metadata["action_codec"]["mu"] = 6
        else:
            del metadata["ticks_frequency"]
    elif corruption == "event":
        name = "events.parquet"
        rows = pq.read_table(path / name).to_pylist()
        event = json.loads(rows[0]["payload_json"])
        event["type"] = rows[0]["type"] = "unknown"
        rows[0]["payload_json"] = json.dumps(event)
        pq.write_table(pa.Table.from_pylist(rows), path / name, compression="zstd")
        metadata["tables"][name] = table_contract(path / name)
    elif corruption != "checksum":
        name = "transitions.parquet"
        rows = pq.read_table(path / name).to_pylist()
        if corruption == "time":
            rows[1]["requested_ticks"] = 1
        elif corruption == "index":
            rows[0]["next_observation_index"] = 100
        elif corruption == "reference":
            rows[0]["event_refs"] = [9999]
        elif corruption in ("action", "action_dtype"):
            action = json.loads(rows[0]["action_json"])
            action["binary"][1] = 1 if corruption == "action" else 0.0
            rows[0]["action_json"] = json.dumps(action)
        pq.write_table(pa.Table.from_pylist(rows), path / name, compression="snappy" if corruption == "table" else "zstd")
        metadata["tables"][name] = table_contract(path / name)
    (path / "dataset.json").write_text(json.dumps(metadata))
    if corruption == "checksum":
        with (path / "dataset.json").open("a") as stream:
            stream.write(" ")
    if corruption != "checksum":
        reseal(path)
    with pytest.raises(InvalidRecording):
        open_model_view(path)


def test_sequences_do_not_cross_attempts(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        for start in (0, 200):
            recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
            recording.input(**sample(start))
            for ticks in (start, start + 50, start + 100):
                if ticks == start + 100:
                    recording.end_episode(ticks - 1, "timeout")
                request = recording.request(ticks, 1, 1)
                recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(tmp_path / "evidence")
    view = open_model_view(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert view.sequence_starts(1) == [0, 2] and view.sequence_starts(2) == []
    assert view[0]["source"]["attempt_id"] != view[2]["source"]["attempt_id"]
    assert view[0]["source"]["split_group_id"] == view[2]["source"]["split_group_id"] == "trial"
    assert view.sequence(0, 2)["valid_mask"].tolist() == [True, False]


def test_unknown_control_excludes_following_windows_without_erasing_evidence(tmp_path):
    path = build(tmp_path, [sample(0), sample(110, ["RightControl"], ["RightControl"], horizontal_wheel=1),
                            sample(120, up=["RightControl"])], ticks=range(0, 301, 50))
    view = open_model_view(path)
    assert view.sequence_starts(1) == [0]
    assert view[1]["actual_action"]["unsupported"]
    assert view[1]["actual_action"]["horizontal_wheel"] == 1
    assert view[1]["actual_action"]["down_counts"] == {"RightControl": 1}
    assert view.sequence(0, 3)["valid_mask"].tolist() == [True, False, False]
    rows = pq.read_table(path / "transitions.parquet").to_pylist()
    for row in rows[4:]:
        row.update(valid=True, bootstrap_mask=1)
    pq.write_table(pa.Table.from_pylist(rows), path / "transitions.parquet", compression="zstd")
    reseal(path)
    with pytest.raises(InvalidRecording, match="trainable"):
        open_model_view(path)


def test_lifecycle_invalid_tail_cannot_be_resealed_as_trainable(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
        recording.input(**sample(0))
        for ticks in (0, 50, 100, 150, 200):
            if ticks == 200:
                recording.end_episode(175, reason="human_intervention")
            request = recording.request(ticks, 1, 1)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(tmp_path / "evidence")
    path = compile_recording(evidence, tmp_path / "dataset", FFMPEG)
    assert open_model_view(path).sequence_starts(1) == [0]
    rows = pq.read_table(path / "transitions.parquet").to_pylist()
    rows[-1].update(valid=True, bootstrap_mask=1)
    pq.write_table(pa.Table.from_pylist(rows), path / "transitions.parquet", compression="zstd")
    reseal(path)
    with pytest.raises(InvalidRecording, match="lifecycle"):
        open_model_view(path)
