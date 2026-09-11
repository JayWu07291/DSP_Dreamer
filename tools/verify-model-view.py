"""Recompile existing live evidence and audit 10 Hz views without changing sources."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsp_dreamer import compile_recording, open_model_view, open_dataset, InvalidRecording
from dsp_dreamer.contract import CONTROLS, file_info
from dsp_dreamer.video import decode


def verify(source, destination, ffmpeg):
    source = Path(source)
    before = {p.name: file_info(p) for p in source.iterdir() if p.is_file()}
    old_dataset = source.with_name(source.name.removesuffix(".evidence") + ".dataset")
    old_marker = file_info(old_dataset / "COMPLETED")
    try:
        open_dataset(old_dataset)
    except InvalidRecording as error:
        assert "Recompile" in str(error) or "Missing dataset field" in str(error)
        legacy_rejected = True
    else:
        raise AssertionError("Expected legacy dataset rejection")
    print(f"compile {source}", flush=True)
    compile_recording(source, destination, ffmpeg)
    print(f"audit {destination}", flush=True)
    view = open_model_view(destination)
    dataset = view.dataset
    assert dataset.metadata["source_kind"] == "live" and not dataset.metadata["diagnostic_mode"]
    reasons: Counter[str] = Counter()
    downs: Counter[str] = Counter()
    active_counts: Counter[str] = Counter()
    completions: Counter[int] = Counter()
    switches: list[dict] = []
    sampled: set[int] = set()
    covered: list[int] = []
    for i, window in enumerate(view.rows):
        parts = dataset.rows[window["start"]:window["stop"]]
        actions = [json.loads(p["action_json"]) for p in parts]
        action = window["action"]
        covered.extend(range(window["start"], window["stop"]))
        duration = parts[-1]["next_requested_ticks"] - parts[0]["requested_ticks"]
        assert action["start_held"] == actions[0]["start_held"] and action["end_held"] == actions[-1]["end_held"]
        for field in ("down_counts", "up_counts"):
            counts: Counter[str] = Counter()
            for a in actions:
                counts.update(a[field])
            assert dict(counts) == action[field]
        for key, fraction in action["held_fraction"].items():
            expected = sum(a["held_fraction"].get(key, 0) * (p["next_requested_ticks"] - p["requested_ticks"])
                           for a, p in zip(actions, parts)) / duration
            assert abs(fraction - expected) < 1e-12
        np.testing.assert_allclose(action["delta"], np.sum([a["delta"] for a in actions], axis=0), atol=1e-12)
        for field in ("wheel", "horizontal_wheel"):
            assert abs(action[field] - sum(a[field] for a in actions)) < 1e-12
        assert action["sample_refs"] == [ref for a in actions for ref in a["sample_refs"]]
        assert window["event_refs"] == [ref for p in parts for ref in p["event_refs"]]
        expected_binary = [int(action["down_counts"].get(k, 0) > 0 or action["held_fraction"][k] >= .5) for k in CONTROLS]
        assert action["binary"] == expected_binary
        downs.update(action["down_counts"])
        active_counts.update(k for k, bit in zip(CONTROLS, expected_binary) if bit)
        expected_nodes = sorted({n for p in parts for n in p["node_completions"]})
        assert window["node_completions"] == expected_nodes
        completions.update(expected_nodes)
        assert window["task_id"] == parts[0]["task_id"] and window["next_task_id"] == parts[-1]["next_task_id"]
        assert window["reward"] == int(window["task_id"] < 16 and window["task_id"] in expected_nodes)
        expected_switches = [dict(ticks=p["next_requested_ticks"], task_id=p["next_task_id"])
                             for p in parts if p["task_id"] != p["next_task_id"]]
        assert window["task_switches"] == expected_switches
        switches.extend(dict(window=i, **s) for s in expected_switches)
        flags = {k: action[k] for k in ("ambiguous", "unsupported", "forbidden")}
        flags.update(gap=any(p["gap"] for p in parts), invalid_source=any(not p["valid"] for p in parts),
                     incomplete_window=len(parts) != 2)
        assert window["valid"] == (not any(flags.values()))
        if not window["valid"]:
            assert window["model_action"] is None and window["bootstrap_mask"] == 0
            reasons.update(k for k, value in flags.items() if value)
        if expected_switches or not window["valid"]:
            sampled.add(i)
    assert covered == list(range(len(dataset.rows)))
    sampled.update([0, len(view) - 1, *map(int, np.linspace(0, len(view) - 1, 8))])
    # Independently decode source video for start/next RGB at task and invalid boundaries.
    selected_frames = {dataset.rows[view.rows[i]["start"]]["observation_index"] for i in sampled}
    selected_frames.update(dataset.rows[view.rows[i]["stop"] - 1]["next_observation_index"] for i in sampled)
    original_rgb = {i: np.frombuffer(raw, np.uint8).reshape(360, 640, 4)[:, :, :3].copy()
                    for i, raw in enumerate(decode(ffmpeg, source / "recording.mkv")) if i in selected_frames}
    for i in sorted(sampled):
        item = view[i]
        assert set(item["inputs"]) == {"observation", "task_condition", "action"}
        for rgb, ordinal in [(item["inputs"]["observation"], item["source"]["observation_index"]),
                             (item["targets"]["next_observation"], item["source"]["next_observation_index"])]:
            assert rgb.dtype == np.float32 and rgb.shape == (3, 360, 640)
            np.testing.assert_array_equal(rgb, original_rgb[ordinal].transpose(2, 0, 1).astype(np.float32) / 255)
    starts = view.sequence_starts(64)
    assert starts
    for start in starts:
        rows = view.rows[start:start + 64]
        assert all(w["valid"] for w in rows)
        assert len({dataset.rows[w["start"]]["episode_id"] for w in rows}) == 1
        assert len({dataset.rows[w["start"]]["attempt_id"] for w in rows}) == 1
    for start in {starts[0], starts[-1]}:
        batch = view.sequence(start, 64, burn_in=8)
        assert batch["valid_mask"].all() and not batch["loss_mask"][:8].any() and batch["loss_mask"][8:].all()
    boundary_starts = [i for i, w in enumerate(view.rows[:-1]) if w["valid"] and not view.rows[i + 1]["valid"]]
    for start in boundary_starts:
        batch = view.sequence(start, 3)
        assert batch["valid_mask"].tolist() == [True, False, False]
        assert batch["loss_mask"].tolist() == [True, False, False]
    assert before == {p.name: file_info(p) for p in source.iterdir() if p.is_file()}
    assert file_info(old_dataset / "COMPLETED") == old_marker
    assert dataset.metadata["artifact_id"] != json.loads((old_dataset / "dataset.json").read_text())["artifact_id"]
    return dict(status="passed", evidence=str(source), dataset=str(destination), evidence_files=before,
                dataset_manifest=file_info(Path(destination) / "dataset.json"), completed=file_info(Path(destination) / "COMPLETED"),
                model_view=view.metadata, original_artifacts_unchanged=True, legacy_dataset_rejected=legacy_rejected,
                frames=dataset.metadata["frame_count"], events=len(dataset.events), transitions=len(dataset),
                windows=len(view), valid_windows=sum(w["valid"] for w in view.rows), exclusion_counts=dict(reasons),
                raw_down_counts=dict(downs), active_window_counts=dict(active_counts), completion_counts=dict(completions),
                task_switches=switches, sequence_starts_64=len(starts), padding_boundaries_checked=boundary_starts,
                rgb_windows_checked=sorted(sampled), rgb_frames_checked=sorted(selected_frames),
                episodes=dataset.metadata["episodes"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    result = verify(args.evidence, args.dataset, args.ffmpeg)
    result["implementation_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result["verification_script"] = file_info(__file__)
    with Path(args.report).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ("status", "frames", "windows", "valid_windows", "sequence_starts_64")}), flush=True)
