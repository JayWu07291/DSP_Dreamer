import json
from pathlib import Path
import copy
import subprocess
import sys

import numpy as np
import pytest

from dsp_dreamer import Recording, InvalidRecording, compile_recording
from dsp_dreamer.training_index import TrainingIndex


FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


def fixture(path, *, group="trial", retries=1, gap=False, fault=False):
    with Recording.synthetic(path / "source", FFMPEG) as recording:
        recording.metadata.update(progress_version=1, progress_tech_ids=[1001, 1002, 1003, 1004, 1005])
        for attempt in range(retries):
            offset = attempt * 1000
            recording.begin_attempt(dict(manifest_id=group, split_group_id=group,
                                         mecha_seed=1, camera_seed=2, policy_seed=3))
            recording.input(offset, held=[], down=[], up=[], delta=[0, 0], wheel=0)
            # A non-active completion, then active completion and a switch to waiting.
            for ticks, fact in [(60, dict(kind="research_queue", tech_ids=[1001, 1002, 1003, 1004, 1005])),
                                (160, dict(kind="lander_work", work_ticks=1)),
                                (360, dict(kind="item_received", item_id=1002, count=1, origin="manual"))]:
                recording.event(offset + ticks, "progress_fact", episode_id=recording.episode["episode_id"], **fact)
            if gap:
                recording.gap(offset + 310, "scheduler", gap_start_ticks=offset + 300, gap_end_ticks=offset + 310)
            for ticks in range(0, 601, 50):
                if ticks == 600:
                    recording.end_episode(offset + 599, None if fault else "timeout", "recorder_fault" if fault else None)
                request = recording.request(offset + ticks, ticks, ticks)
                recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(path / "evidence")
    return compile_recording(evidence, path / "dataset", FFMPEG)


def registry(*entries):
    return dict(schema="dsp-split-registry/1", manifests=[
        dict(manifest_id=group, split_group_id=group, purpose=purpose) for group, purpose in entries])


def test_retry_indices_coverage_and_determinism(tmp_path):
    path = fixture(tmp_path, retries=2)
    index = TrainingIndex([path], registry(("trial", "demonstration")), length=2)
    report = index.report
    source = report["sources"][0]
    assert source["uniform"] == [0, 1, 2, 3, 4, 7, 8, 9, 10, 11]
    assert source["relevant"] == [0, 1, 7, 8]
    assert source["progress"] == [2, 3, 9, 10]
    stats = report["splits"][source["split"]]
    assert stats["valid_complete_episodes"] == 2
    assert stats["valid_complete_hours"] == pytest.approx(1.198 / 3600)
    assert stats["tasks"][0]["active_reward_episodes"] == 2
    assert stats["tasks"][1]["active_reward_episodes"] == 0
    assert stats["tasks"][1]["non_active_completions"] == 2
    assert stats["waiting_windows"] == 8
    assert stats["tasks"][0]["live_active_reward_episodes"] == 0
    assert not report["coverage_gate_passed"]
    assert len(stats["tasks"]) == 16
    assert TrainingIndex([path], registry(("trial", "demonstration")), length=2).report == report
    output, verification = tmp_path / "index.json", tmp_path / "verification.json"
    index.save(output)
    subprocess.run([sys.executable, "tools/verify-training-index.py", "--source", str(path),
                    "--index", str(output), "--report", str(verification)], check=True)
    # The switch at the last row's next observation also crosses a prompt boundary.
    assert json.loads(verification.read_text())["checks"][0]["cross_task_starts"] == 4


def test_stage_two_uses_exact_halves_and_loader_masks(tmp_path):
    path = fixture(tmp_path)
    index = TrainingIndex([path], registry(("trial", "demonstration")), length=2)
    split = index.report["sources"][0]["split"]
    samples = index.sample_stage_two(split, 10, seed=42)
    assert samples == index.sample_stage_two(split, 10, seed=42)
    assert [s["pool"] for s in samples].count("uniform") == 5
    assert [s["pool"] for s in samples].count("relevant") == 5
    for sample in samples:
        batch = index.sequence(sample, burn_in=1)
        assert batch["valid_mask"].tolist() == [True, True]
        for name in ("dynamics", "policy", "reward"):
            enabled = (sample["pool"] == "uniform") == (name == "dynamics")
            assert batch[f"{name}_loss_mask"].tolist() == [False, enabled]
    for size in (0, 3, True):
        with pytest.raises(InvalidRecording):
            index.sample_stage_two(split, size, seed=42)
    with pytest.raises(InvalidRecording):
        index.sequence(dict(samples[0], start=1000))
    with pytest.raises(InvalidRecording):
        index.sample_stage_two("development", 2, seed=42)


def test_fault_gap_short_sequences_and_reserved_group(tmp_path):
    path = fixture(tmp_path, retries=2, gap=True, fault=True)
    reg = registry(("trial", "demonstration"))
    index = TrainingIndex([path], reg, length=2)
    source = index.report["sources"][0]
    assert source["uniform"] == [0, 1, 7, 8]
    assert source["relevant"] == [0, 1, 7, 8]
    assert source["progress"] == []
    stats = index.report["splits"][source["split"]]
    assert stats["valid_complete_episodes"] == 0
    assert stats["legal_prefix_hours"] == pytest.approx(.8 / 3600)
    assert TrainingIndex([path], reg, length=8).report["sources"][0]["uniform"] == []
    for purpose in ("development", "final"):
        heldout = copy.deepcopy(reg)
        heldout["manifests"].append(dict(manifest_id="reserved", split_group_id="trial", purpose=purpose))
        excluded = TrainingIndex([path], heldout, length=2)
        assert excluded.report["sources"][0]["split"] is None
        assert excluded.report["sources"][0]["uniform"] == []
        assert all(s["sequences"] == 0 for s in excluded.report["splits"].values())
        with pytest.raises(InvalidRecording, match="No uniform"):
            excluded.sample_stage_two("train", 2, seed=0)
    with pytest.raises(InvalidRecording, match="Unregistered"):
        TrainingIndex([path], registry(), length=2)
    with pytest.raises(InvalidRecording, match="split group mismatch"):
        TrainingIndex([path], dict(reg, manifests=[dict(reg["manifests"][0], split_group_id="another")]), length=2)
    with pytest.raises(InvalidRecording, match="Duplicate recording"):
        TrainingIndex([path, path], reg, length=2)


def test_frozen_export_reopens_and_rejects_tampering(tmp_path):
    path = fixture(tmp_path / "input")
    index = TrainingIndex([path], registry(("trial", "demonstration")), length=2)
    output = tmp_path / "index.json"
    index.save(output)
    assert TrainingIndex.open(output, [path]).report == index.report
    with pytest.raises(InvalidRecording, match="overwrite"):
        index.save(output)
    report = json.loads(output.read_text())
    report["sources"][0]["uniform"].append(1000)
    output.write_text(json.dumps(report))
    with pytest.raises(InvalidRecording, match="checksum"):
        TrainingIndex.open(output, [path])


def test_all_splits_are_fixed_and_input_order_does_not_change_report(tmp_path):
    paths = [fixture(tmp_path / group, group=group) for group in ("0", "9", "trial")]
    reg = registry(*[(group, "demonstration") for group in ("0", "9", "trial")])
    index = TrainingIndex(paths, reg, length=2)
    assert {s["split_group_id"]: (s["split"], s["bucket"]) for s in index.report["sources"]} == {
        "0": ("train", 5), "9": ("validation", 87), "trial": ("offline-test", 94)}
    for split, needed in (("train", 20), ("validation", 3), ("offline-test", 3)):
        stats = index.report["splits"][split]
        assert stats["sequences"] == 5
        assert all(t["deficit"] == needed for t in stats["tasks"])
        for sample in index.sample_stage_two(split, 2, seed=0):
            assert sample["split"] == split
            assert all(s["split_group_id"] == {"train": "0", "validation": "9", "offline-test": "trial"}[split]
                       for s in index.sequence(sample)["source"])
    assert TrainingIndex(list(reversed(paths)), dict(reg, manifests=list(reversed(reg["manifests"]))), length=2).report == index.report
