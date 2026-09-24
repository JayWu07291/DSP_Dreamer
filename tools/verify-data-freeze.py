"""核對搬移後的凍結身分、來源與 split；不重讀 RGB 或原始錄影。"""
import argparse
from collections import Counter
from pathlib import Path
import sys

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dsp_dreamer.contract import atomic_save, file_info, load, require, sha
from dsp_dreamer.evaluation_protocol import read_protocol, seal, validate_trials, verify_seal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    catalog = load("docs/data-catalog.json")
    index = load(catalog["training_index"])
    verify_seal(index)
    require(index["artifact_id"] == catalog["index_id"], "Index identity mismatch")
    protocol = read_protocol("protocols/evaluation-v2.json")
    require(protocol["artifact_id"] == catalog["protocol_id"], "Protocol identity mismatch")
    evaluation = Path(catalog["evaluation_directory"])
    artifacts = {}
    for name, expected in catalog["evaluation_files"].items():
        require(file_info(evaluation / name) == expected, f"Frozen file changed: {name}")
        artifacts[name] = load(evaluation / name)
        verify_seal(artifacts[name])
    freeze = artifacts["data-freeze.json"]
    for field, name in (("source_freeze_id", "source-freeze.json"),
                        ("candidate_freeze_id", "candidate-freeze.json"),
                        ("evaluation_inputs_id", "evaluation-inputs.json"),
                        ("annotations_id", "annotations.json"),
                        ("annotation_provenance_id", "annotation-provenance.json"),
                        ("action_evidence_id", "validation-actions.json")):
        require(freeze[field] == artifacts[name]["artifact_id"], f"Broken freeze link: {field}")
    require(freeze["artifact_id"] == catalog["data_freeze_id"]
            and freeze["index_id"] == index["artifact_id"]
            and freeze["protocol_id"] == protocol["artifact_id"], "Freeze identity mismatch")
    source_freeze = artifacts["source-freeze.json"]
    require(source_freeze["index_id"] == index["artifact_id"]
            and source_freeze["registry"] == index["registry"], "Frozen registry mismatch")
    for name, expected in source_freeze["files"].items():
        require(file_info(name) == expected, f"Frozen implementation changed: {name}")

    indexed = {s["artifact_id"]: s for s in index["sources"]}
    audited = {s["artifact_id"]: s for s in source_freeze["source_audits"]}
    located = {s["artifact_id"]: s for s in catalog["sources"]}
    require(len(indexed) == len(index["sources"]) == len(located) == len(catalog["sources"])
            == len(audited) == len(source_freeze["source_audits"])
            and indexed.keys() == located.keys() == audited.keys(), "Source set mismatch")
    registry = {m["manifest_id"]: m for m in index["registry"]["manifests"]}
    recordings, episodes, trials, sources = set(), set(), [], []
    outcomes: Counter[str] = Counter()
    for artifact_id, source in indexed.items():
        location, audit = located[artifact_id], audited[artifact_id]
        path = Path(location["path"])
        completed = file_info(path / "COMPLETED")
        require(completed == location["completed"] == audit["completed"], "COMPLETED changed")
        manifest = load(path / "COMPLETED")
        require(file_info(path / "dataset.json") == audit["metadata"] == manifest["files"]["dataset.json"],
                "Dataset metadata changed")
        metadata = load(path / "dataset.json")
        require(metadata["artifact_id"] == artifact_id and metadata["source_kind"] == "live"
                and not metadata["diagnostic_mode"] and metadata["capture_hz"] == 20
                and metadata["catalog"] == "action_catalog_v4" and metadata["progress_version"] == 4,
                "Unexpected dataset contract")
        require(metadata["source_manifest"] == audit["source_manifest"] == source["source_manifest"]
                and metadata["source_artifact_id"] == source["recording_artifact_id"]
                and metadata["episodes"] == source["episodes"], "Recording provenance mismatch")
        require(metadata["source_artifact_id"] not in recordings, "Duplicate recording derivative")
        recordings.add(metadata["source_artifact_id"])
        for episode in metadata["episodes"]:
            require(episode["episode_id"] not in episodes, "Duplicate episode")
            episodes.add(episode["episode_id"])
            outcomes[f'{episode["episode_outcome"] or "unfinished"}/{episode["validity_status"]}'] += 1
        trial = metadata["trial_manifest"]
        group = trial["split_group_id"]
        require(registry[trial["manifest_id"]] == dict(manifest_id=trial["manifest_id"],
                split_group_id=group, purpose="demonstration"), "Non-demonstration source")
        bucket = int(sha(group.encode()), 16) % 100
        split = "train" if bucket < 80 else "validation" if bucket < 90 else "offline-test"
        require(source["bucket"] == bucket and source["split_group_id"] == group
                and source["manifest_id"] == trial["manifest_id"]
                and source["split"] == location["split"] == audit["split"] == split,
                "Deterministic split mismatch")
        trials.append(trial)
        require(file_info(path / "transitions.parquet") == manifest["files"]["transitions.parquet"],
                "Transition table changed")
        rows = pq.read_table(path / "transitions.parquet", columns=[
            "valid", "requested_ticks", "next_requested_ticks"]).to_pylist()
        valid_ticks = sum(r["next_requested_ticks"] - r["requested_ticks"] for r in rows if r["valid"])
        sources.append(dict(artifact_id=artifact_id, recording_artifact_id=metadata["source_artifact_id"],
                            source_manifest=source["source_manifest"], split=split, completed=completed,
                            frames=metadata["frame_count"],
                            valid_capture_interval_hours=valid_ticks / metadata["ticks_frequency"] / 3600,
                            declared_dataset_bytes=sum(f["bytes"] for f in manifest["files"].values())
                            + completed["bytes"]))
    trials_file = load("protocols/evaluation-trials-v1.json")
    validate_trials(trials_file, index["registry"], trials, expected_id=protocol["trials_id"])
    require(set(index["splits"]) == {"train", "validation", "offline-test"}, "Unexpected splits")
    passed = True
    for split, required in (("train", 20), ("validation", 3), ("offline-test", 3)):
        tasks = index["splits"][split]["tasks"]
        require([t["task_id"] for t in tasks] == list(range(16)), "Incomplete task coverage")
        for task in tasks:
            deficit = max(0, required - task["live_active_reward_episodes"])
            require(task["required"] == required and task["deficit"] == deficit
                    and task["passed"] == (deficit == 0), "Coverage gate mismatch")
            passed &= deficit == 0
    require(index["coverage_gate_passed"] == passed, "Aggregate coverage gate mismatch")
    report = seal(dict(schema="dsp-data-freeze-audit/1", integrity_checks_passed=True,
                       coverage_gate_passed=passed, index_id=index["artifact_id"],
                       data_freeze_id=freeze["artifact_id"], protocol_id=protocol["artifact_id"],
                       sources=sources, splits=index["splits"], episode_outcomes=dict(outcomes),
                       valid_capture_interval_hours=sum(s["valid_capture_interval_hours"] for s in sources),
                       declared_dataset_bytes=sum(s["declared_dataset_bytes"] for s in sources),
                       model_quality_status=freeze["model_quality_status"],
                       training_authorized=freeze["training_authorized"],
                       offline_test_disclosure_authorized=freeze["offline_test_disclosure_authorized"],
                       not_checked=["human_effort", "recovery_scenario_coverage", "rgb_and_raw_evidence_contents"],
                       verifier=file_info(Path(__file__))))
    atomic_save(args.report, report)
    print("凍結身分與 split 核對通過；人工工時、恢復情境及完整媒體內容不在本次核對範圍。")


if __name__ == "__main__":
    main()
