"""Traceable 10 Hz windows over immutable transitions, using original input time."""
from bisect import bisect_left
import copy
import json

import numpy as np

from .actions import ACTION_CODEC, encode_action
from .contract import file_info, require, sha
from .dataset import aggregate, open_dataset


class ModelView:
    def __init__(self, dataset):
        self.dataset = dataset
        self.metadata = dict(schema="dsp-model-view/1", loader_version="0.1.0", model_hz=10,
                             source_artifact_id=dataset.metadata["artifact_id"],
                             source_completed=file_info(dataset.path / "COMPLETED"),
                             action_codec=copy.deepcopy(ACTION_CODEC),
                             observation=dict(dtype="float32", shape=[3, 360, 640], color_space="sRGB", range=[0, 1]),
                             pairing="two adjacent captures within episode; incomplete tails masked")
        self.metadata["artifact_id"] = sha(json.dumps(self.metadata, sort_keys=True).encode())
        ticks = [e["ticks"] for e in dataset.events]
        self.rows = []
        index = 0
        while index < len(dataset.rows):
            first = dataset.rows[index]
            stop = index + 1
            if stop < len(dataset.rows):
                second = dataset.rows[stop]
                if (not first["is_last"] and not second["is_first"]
                        and first["episode_id"] == second["episode_id"]
                        and first["attempt_id"] == second["attempt_id"]):
                    stop += 1
            parts = dataset.rows[index:stop]
            last = parts[-1]
            start, end = first["requested_ticks"], last["next_requested_ticks"]
            events = dataset.events[bisect_left(ticks, start):bisect_left(ticks, end)]
            action = aggregate([e for e in events if e["type"] == "input"], start, end,
                               json.loads(first["action_json"])["start_held"])
            valid = len(parts) == 2 and all(p["valid"] for p in parts)
            valid &= not any(action[k] for k in ("ambiguous", "unsupported", "forbidden"))
            nodes = sorted({n for p in parts for n in p["node_completions"]})
            rewards = [int(i in nodes) for i in range(16)]
            self.rows.append(dict(start=index, stop=stop, action=action, valid=bool(valid),
                model_action=encode_action(action) if valid else None,
                event_refs=[e["sequence_number"] for e in events if e["type"] != "input"],
                task_id=first["task_id"], next_task_id=last["next_task_id"],
                task_switches=[dict(ticks=p["next_requested_ticks"], task_id=p["next_task_id"])
                               for p in parts if p["task_id"] != p["next_task_id"]],
                reward_vector=rewards, reward=rewards[first["task_id"]] if first["task_id"] < 16 else 0,
                node_completions=nodes, bootstrap_mask=last["bootstrap_mask"] if valid else 0))
            index = stop

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        first = self.dataset.rows[row["start"]]
        last = self.dataset.rows[row["stop"] - 1]
        rgb = self.dataset.rgb
        return dict(inputs=dict(observation=np.asarray(rgb[first["observation_index"]], dtype=np.float32).transpose(2, 0, 1) / 255,
                                task_condition=np.eye(17, dtype=np.float32)[row["task_id"]],
                                action=copy.deepcopy(row["model_action"])),
                    targets=dict(next_observation=np.asarray(rgb[last["next_observation_index"]], dtype=np.float32).transpose(2, 0, 1) / 255,
                                 reward_vector=np.asarray(row["reward_vector"], dtype=np.uint8), reward=row["reward"],
                                 next_task_id=row["next_task_id"], bootstrap_mask=row["bootstrap_mask"],
                                 is_terminal=last["is_terminal"], truncation=last["truncation"]),
                    actual_action=copy.deepcopy(row["action"]), event_refs=row["event_refs"].copy(),
                    task_switches=copy.deepcopy(row["task_switches"]), node_completions=row["node_completions"].copy(),
                    validity=dict(valid=row["valid"], incomplete_window=row["stop"] - row["start"] != 2,
                                  gap=any(p["gap"] for p in self.dataset.rows[row["start"]:row["stop"]]),
                                  episode_outcome=last["episode_outcome"], validity_status=last["validity_status"],
                                  validity_reasons=last["validity_reasons"].copy()),
                    valid_mask=True, loss_mask=row["valid"],
                    source=dict(artifact_id=self.metadata["source_artifact_id"],
                                recording_artifact_id=self.dataset.metadata["source_artifact_id"],
                                recording_session_id=self.dataset.metadata["recording_session_id"],
                                episode_id=first["episode_id"], attempt_id=first["attempt_id"],
                                split_group_id=(self.dataset.metadata.get("trial_manifest") or {}).get("split_group_id", first["episode_id"]),
                                transition_indices=list(range(row["start"], row["stop"])),
                                observation_index=first["observation_index"], next_observation_index=last["next_observation_index"],
                                capture_id=first["capture_id"], next_capture_id=last["next_capture_id"],
                                requested_ticks=first["requested_ticks"], next_requested_ticks=last["next_requested_ticks"],
                                ticks_frequency=self.dataset.metadata["ticks_frequency"]))

    def sequence_starts(self, length):
        require(type(length) is int and length > 0, "Invalid sequence length")
        result, run = [], 0
        for index, row in enumerate(self.rows):
            first = self.dataset.rows[row["start"]]
            if index and (first["is_first"] or first["episode_id"] != self.dataset.rows[self.rows[index - 1]["start"]]["episode_id"]):
                run = 0
            run = run + 1 if row["valid"] else 0
            if run >= length:
                result.append(index - length + 1)
        return result

    def sequence(self, start, length, *, burn_in=0):
        require(type(start) is int and 0 <= start < len(self), "Invalid sequence start")
        require(type(length) is int and length > 0 and type(burn_in) is int and 0 <= burn_in < length,
                "Invalid sequence length/burn-in")
        require(self.rows[start]["valid"], "Sequence starts in invalid range")
        items = []
        episode = self.dataset.rows[self.rows[start]["start"]]["episode_id"]
        for index in range(start, min(start + length, len(self))):
            row = self.rows[index]
            first = self.dataset.rows[row["start"]]
            if not row["valid"] or first["episode_id"] != episode or index > start and first["is_first"]:
                break
            items.append(self[index])
        count = len(items)
        valid_mask = np.arange(length) < count
        loss_mask = valid_mask & (np.arange(length) >= burn_in)
        inputs = dict(observation=np.zeros((length, 3, 360, 640), dtype=np.float32),
                      task_condition=np.zeros((length, 17), dtype=np.float32),
                      binary=np.zeros((length, 20), dtype=np.int64),
                      mouse=np.full(length, 60, dtype=np.int64), wheel=np.ones(length, dtype=np.int64))
        targets = dict(next_observation=np.zeros_like(inputs["observation"]),
                       reward_vector=np.zeros((length, 16), dtype=np.uint8), reward=np.zeros(length, dtype=np.float32),
                       next_task_id=np.full(length, 16, dtype=np.int64), bootstrap_mask=np.zeros(length, dtype=np.float32),
                       is_terminal=np.zeros(length, dtype=bool), truncation=np.zeros(length, dtype=bool))
        for i, item in enumerate(items):
            for name in ("observation", "task_condition"):
                inputs[name][i] = item["inputs"][name]
            for name in ("binary", "mouse", "wheel"):
                inputs[name][i] = item["inputs"]["action"][name]
            for name in targets:
                targets[name][i] = item["targets"][name]
        return dict(inputs=inputs, targets=targets, valid_mask=valid_mask, loss_mask=loss_mask,
                    source=[item["source"] for item in items])


def open_model_view(path):
    return ModelView(open_dataset(path))
