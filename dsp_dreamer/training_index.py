"""Fixed corpus splits, legal sequence indices and active-reward coverage."""
from collections import defaultdict
from bisect import bisect_left
import copy
import json
import random
from typing import Any

from .contract import atomic_save, load, require, sha
from .model_view import open_model_view
from .progress import TASKS


COVERAGE_REQUIREMENTS = {"train": 20, "validation": 3, "offline-test": 3}


class TrainingIndex:
    def __init__(self, paths, registry, *, length=64):
        require(type(length) is int and length > 0, "Invalid sequence length")
        require(isinstance(registry, dict) and registry.get("schema") == "dsp-split-registry/1"
                and isinstance(registry.get("manifests"), list), "Invalid split registry")
        manifests, reserved = {}, set()
        for entry in registry["manifests"]:
            require(isinstance(entry, dict) and all(isinstance(entry.get(k), str) and entry[k]
                    for k in ("manifest_id", "split_group_id", "purpose")), "Missing registry identity")
            require(entry["purpose"] in ("demonstration", "development", "final"), "Unknown manifest purpose")
            require(entry["manifest_id"] not in manifests, "Duplicate manifest registration")
            manifests[entry["manifest_id"]] = entry
            if entry["purpose"] != "demonstration":
                reserved.add(entry["split_group_id"])
        # ponytail: O(windows) metadata in RAM; use a disk index if the #21 resource gate fails.
        self.views = {}
        sources = []
        seen_episodes: set[str] = set()
        seen_recordings: set[str] = set()
        stats: dict[str, Any] = {split: dict(valid_complete_episodes=0, valid_complete_hours=0., legal_hours=0.,
                            legal_prefix_hours=0., sequences=0, relevant_sequences=0, progress_sequences=0,
                            waiting_windows=0, non_active_completions=0, tasks=[dict(task_id=i, task=name,
                            active_activations=0, active_reward_episodes=0, live_active_reward_episodes=0,
                            non_active_completions=0, required=threshold, deficit=threshold, passed=False)
                            for i, name in enumerate(TASKS[:16])]) for split, threshold in COVERAGE_REQUIREMENTS.items()}
        views = sorted((open_model_view(path) for path in paths), key=lambda v: v.metadata["source_artifact_id"])
        for view in views:
            metadata = view.dataset.metadata
            trial = metadata["trial_manifest"]
            require(isinstance(trial, dict) and trial.get("manifest_id") in manifests,
                    "Unregistered trial manifest")
            entry = manifests[trial["manifest_id"]]
            group = entry["split_group_id"]
            require(trial.get("split_group_id") == group, "Manifest split group mismatch")
            require("purpose" not in trial or trial["purpose"] == entry["purpose"], "Manifest purpose mismatch")
            # One canonical derivative per recording prevents inflated hours and episode coverage.
            require(metadata["source_artifact_id"] not in seen_recordings, "Duplicate recording derivative")
            seen_recordings.add(metadata["source_artifact_id"])
            episodes = {e["episode_id"]: e for e in metadata["episodes"]}
            require(episodes and not seen_episodes.intersection(episodes), "Missing or duplicate corpus episode")
            seen_episodes.update(episodes)
            bucket = int(sha(group.encode("utf-8")), 16) % 100
            split = None if group in reserved else "train" if bucket < 80 else "validation" if bucket < 90 else "offline-test"
            source = dict(artifact_id=metadata["artifact_id"], model_view=copy.deepcopy(view.metadata),
                          recording_artifact_id=metadata["source_artifact_id"], source_manifest=metadata["source_manifest"],
                          source_kind=metadata["source_kind"], progress_version=metadata["progress_version"],
                          manifest_id=entry["manifest_id"], split_group_id=group, split=split, bucket=bucket,
                          excluded_reason="reserved_group" if split is None else None,
                          episodes=list(episodes.values()), uniform=[], relevant=[], progress=[])
            sources.append(source)
            self.views[source["artifact_id"]] = view
            if split is None:
                continue
            require(metadata["progress_version"] in (1, 2, 3), "Missing progress labels")
            source["uniform"] = view.sequence_starts(length)
            progress_refs = {e["sequence_number"] for e in view.dataset.events if e.get("name") == "progress_fact"}
            completion_prefix, progress_prefix = [0], [0]
            for row in view.rows:
                completion_prefix.append(completion_prefix[-1] + bool(row["node_completions"]))
                progress_prefix.append(progress_prefix[-1] + bool(progress_refs.intersection(row["event_refs"])))
            covered_delta = [0] * (len(view) + 1)
            for start in source["uniform"]:
                end = start + length
                covered_delta[start] += 1
                covered_delta[end] -= 1
                if completion_prefix[end] > completion_prefix[start]:
                    source["relevant"].append(start)
                elif progress_prefix[end] > progress_prefix[start]:
                    source["progress"].append(start)
            summary = stats[split]
            summary["sequences"] += len(source["uniform"])
            summary["relevant_sequences"] += len(source["relevant"])
            summary["progress_sequences"] += len(source["progress"])
            complete = {eid for eid, e in episodes.items() if e["validity_status"] == "valid"
                        and e["episode_outcome"] is not None and e["final_capture_id"] is not None
                        and e["start_ticks"] is not None and not metadata["diagnostic_mode"]}
            summary["valid_complete_episodes"] += len(complete)
            frequency = metadata["ticks_frequency"]
            summary["valid_complete_hours"] += sum((episodes[e]["end_ticks"] - episodes[e]["start_ticks"])
                                                      / frequency / 3600 for e in complete)
            positives = defaultdict(set)
            previous_episode, previous_task, covered = None, None, 0
            for i, row in enumerate(view.rows):
                covered += covered_delta[i]
                first, last = view.dataset.rows[row["start"]], view.dataset.rows[row["stop"] - 1]
                episode, task = first["episode_id"], row["task_id"]
                if row["valid"]:
                    hours = (last["next_requested_ticks"] - first["requested_ticks"]) / frequency / 3600
                    summary["legal_hours"] += hours
                    if episode not in complete:
                        summary["legal_prefix_hours"] += hours
                    if task == 16:
                        summary["waiting_windows"] += 1
                    elif episode != previous_episode or task != previous_task:
                        summary["tasks"][task]["active_activations"] += 1
                    if covered and row["reward"]:
                        positives[task].add(episode)
                    for node in row["node_completions"]:
                        if node != task or node >= 16:
                            summary["non_active_completions"] += 1
                            if node < 16:
                                summary["tasks"][node]["non_active_completions"] += 1
                previous_episode, previous_task = episode, task
            for task, ids in positives.items():
                summary["tasks"][task]["active_reward_episodes"] += len(ids)
                if metadata["source_kind"] == "live":
                    summary["tasks"][task]["live_active_reward_episodes"] += len(ids)
        require(sources, "Empty corpus")
        for summary in stats.values():
            for task in summary["tasks"]:
                task["deficit"] = max(0, task["required"] - task["live_active_reward_episodes"])
                task["passed"] = task["deficit"] == 0
        self.report = dict(schema="dsp-training-index/1", indexer_version="0.1.0", sequence_length=length,
                           split_rule="sha256(UTF-8 split_group_id) as unsigned big-endian integer % 100; 0:80/80:90/90:100",
                           registry=dict(schema=registry["schema"], manifests=sorted(copy.deepcopy(list(manifests.values())),
                                         key=lambda e: e["manifest_id"])),
                           sources=sorted(sources, key=lambda s: s["artifact_id"]), splits=stats,
                           coverage_gate_passed=all(t["passed"] for s in stats.values() for t in s["tasks"]))
        self.report["artifact_id"] = sha(json.dumps(self.report, sort_keys=True, allow_nan=False).encode())
        self._pools = {(split, pool): [(s["artifact_id"], start) for s in self.report["sources"]
                       if s["split"] == split for start in s[pool]]
                       for split in COVERAGE_REQUIREMENTS for pool in ("uniform", "relevant")}

    def sample_stage_two(self, split, batch_size, *, seed):
        require(split in COVERAGE_REQUIREMENTS and type(batch_size) is int and batch_size > 0 and batch_size % 2 == 0
                and type(seed) is int, "Invalid stage-two split/batch size/seed")
        rng = random.Random(seed)
        samples = []
        for pool in ("uniform", "relevant"):
            choices = self._pools[split, pool]
            require(choices, f"No {pool} sequences in {split}")
            for _ in range(batch_size // 2):
                artifact, start = rng.choice(choices)
                samples.append(dict(artifact_id=artifact, start=start, split=split, pool=pool))
        return samples

    def sequence(self, sample, *, burn_in=0):
        require(isinstance(sample, dict) and sample.get("split") in COVERAGE_REQUIREMENTS
                and sample.get("pool") in ("uniform", "relevant")
                and type(sample.get("start")) is int and isinstance(sample.get("artifact_id"), str),
                "Invalid sequence sample")
        choices = self._pools[sample["split"], sample["pool"]]
        key = (sample["artifact_id"], sample["start"])
        position = bisect_left(choices, key)
        require(position < len(choices) and choices[position] == key, "Unindexed sequence sample")
        batch = self.views[sample["artifact_id"]].sequence(sample["start"], self.report["sequence_length"], burn_in=burn_in)
        require(batch["valid_mask"].all(), "Indexed sequence contains padding")
        for name in ("dynamics", "policy", "reward"):
            enabled = (sample["pool"] == "uniform") == (name == "dynamics")
            batch[f"{name}_loss_mask"] = batch["loss_mask"] & enabled
        return batch

    def save(self, path):
        atomic_save(path, self.report)

    @classmethod
    def open(cls, path, sources):
        report = load(path)
        require(isinstance(report, dict) and report.get("schema") == "dsp-training-index/1"
                and all(k in report for k in ("artifact_id", "registry", "sequence_length")), "Invalid training index")
        payload = {k: v for k, v in report.items() if k != "artifact_id"}
        require(report["artifact_id"] == sha(json.dumps(payload, sort_keys=True, allow_nan=False).encode()),
                "Training index checksum mismatch")
        index = cls(sources, report["registry"], length=report["sequence_length"])
        require(index.report == report, "Training index differs from verified sources")
        return index
