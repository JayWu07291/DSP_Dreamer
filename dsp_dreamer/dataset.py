"""Compile actual input over half-open request-time intervals and read verified datasets."""
from collections import Counter
from pathlib import Path
import json
import uuid
import copy

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zarr
from zarr.codecs.blosc import BloscCodec

from .archive import capacity_preflight, verify_recording, validate_events
from .actions import ACTION_CODEC, forbidden_buttons, validate_action_contract
from .contract import CATALOG, CONTROLS, atomic_save, file_info, load, require, save, sha
from .video import decode
from .lifecycle import transition_lifecycle
from .progress import FIELDS, TASKS, MILESTONES, replay_progress, validate_progress_row


def observation_contract(count):
    return dict(dtype="uint8", shape=[count, 360, 640, 3], chunks=[1, 360, 640, 3],
                shards=None, codec="blosc/zstd", zarr_format=3, color_space="sRGB", layout="HWC")


def table_contract(path):
    table = pq.ParquetFile(path)
    return dict(schema=table.schema_arrow.serialize().to_pybytes().hex(),
                rows=table.metadata.num_rows, row_group_size=1024,
                row_groups=[dict(rows=table.metadata.row_group(i).num_rows,
                    columns=[dict(name=table.metadata.row_group(i).column(j).path_in_schema,
                                  dtype=table.metadata.row_group(i).column(j).physical_type,
                                  codec=table.metadata.row_group(i).column(j).compression)
                             for j in range(table.metadata.num_columns)])
                            for i in range(table.metadata.num_row_groups)])


def aggregate(samples, start, end, initial):
    held = set(initial)
    start_held = sorted(held)
    duration: Counter[str] = Counter()
    down: Counter[str] = Counter()
    up: Counter[str] = Counter()
    delta, wheel, horizontal_wheel = [0.0, 0.0], 0.0, 0.0
    cursor = start
    ambiguous = False
    unsupported = bool(held - set(CONTROLS))
    refs = []
    for sample in samples:
        ticks = sample["ticks"]
        for key in held:
            duration[key] += ticks - cursor
        cursor = ticks
        downs, ups, current = set(sample["down"]), set(sample["up"]), set(sample["held"])
        ambiguous |= bool(downs & held or ups - held or downs & ups)
        ambiguous |= current != (held - ups) | downs
        down.update(sample["down"])
        up.update(sample["up"])
        held = current
        unsupported |= bool((held | downs | ups) - set(CONTROLS)) or bool(sample.get("horizontal_wheel", 0))
        delta = [delta[i] + sample["delta"][i] for i in range(2)]
        wheel += sample["wheel"]
        horizontal_wheel += sample.get("horizontal_wheel", 0)
        refs.append(sample["sequence_number"])
    for key in held:
        duration[key] += end - cursor
    fraction = {key: duration[key] / (end - start) for key in sorted(set(CONTROLS) | set(duration))}
    active = {key for key in CONTROLS if down[key] > 0 or fraction[key] >= 0.5}
    forbidden = forbidden_buttons([int(key in active) for key in CONTROLS])
    ambiguous |= any(count > 1 for count in (*down.values(), *up.values()))
    return dict(start_held=start_held, end_held=sorted(held), held_fraction=fraction,
                down_counts=dict(down), up_counts=dict(up), delta=delta, wheel=wheel, horizontal_wheel=horizontal_wheel,
                sample_refs=refs, ambiguous=bool(ambiguous), unsupported=bool(unsupported),
                forbidden=forbidden, binary=[int(key in active) for key in CONTROLS])


def compile_recording(source, destination, ffmpeg):
    source, destination = Path(source), Path(destination)
    manifest, frames, events = verify_recording(source, ffmpeg)
    # Uncompressed RGB plus the agreed 2 GiB/hour table allowance and 1 GiB scratch reserve.
    capacity_preflight(destination, len(frames) * (640 * 360 * 3 + (2 * 1024 ** 3 // 72000)), copies=1)
    events.sort(key=lambda event: (event["ticks"], event["sequence_number"]))
    progress = replay_progress(manifest, frames, events)
    scheduler_gaps = [e for e in events if e["type"] == "gap" and e["reason"] == "scheduler"]
    destination.mkdir(parents=True, exist_ok=False)
    group = zarr.open_group(str(destination / "observations.zarr"), mode="w", zarr_format=3)
    rgb = group.create_array("rgb", shape=(len(frames), 360, 640, 3), chunks=(1, 360, 640, 3),
                             dtype="uint8", compressors=[BloscCodec(cname="zstd", clevel=3)])
    rgb_hashes = []
    for index, raw in enumerate(decode(ffmpeg, source / "recording.mkv")):
        require(sha(raw) == frames[index]["rgba_sha256"], "Source changed during compile")
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(360, 640, 4)[:, :, :3].copy()
        rgb[index] = pixels
        rgb_hashes.append(sha(pixels.tobytes()))
    rows = []
    derived_episodes = copy.deepcopy(manifest.get("episodes", []))
    control_faults = set()
    held = []
    event_index = 0
    for index, (first, second) in enumerate(zip(frames, frames[1:])):
        start, end = first["requested_ticks"], second["requested_ticks"]
        while event_index < len(events) and events[event_index]["ticks"] < start:
            if events[event_index]["type"] == "input":
                held = events[event_index]["held"]
            event_index += 1
        interval = []
        while event_index < len(events) and events[event_index]["ticks"] < end:
            interval.append(events[event_index])
            event_index += 1
        samples = [event for event in interval if event["type"] == "input"]
        action = aggregate(samples, start, end, held)
        held = action["end_held"]
        gap = second["capture_id"] != first["capture_id"] + 1 or any(
            e["type"] == "gap" and e["reason"] != "scheduler" for e in interval)
        gap |= any(e["gap_start_ticks"] < end and e["gap_end_ticks"] > start for e in scheduler_gaps)
        invalid_input = any(not s.get("focused", True) for s in samples)
        lifecycle = transition_lifecycle(manifest, first, second)
        if action["unsupported"]:
            control_faults.add(lifecycle["episode_id"])
        if lifecycle["episode_id"] in control_faults:
            lifecycle["lifecycle_valid"] = False
        valid = not (gap or invalid_input or action["ambiguous"] or action["unsupported"] or action["forbidden"])
        valid &= lifecycle.pop("lifecycle_valid")
        valid &= not manifest.get("diagnostic_mode", False)
        last = index == len(frames) - 2 or second.get("episode_id") != frames[index + 2].get("episode_id")
        if not valid or last and lifecycle["validity_status"] != "valid":
            lifecycle["bootstrap_mask"] = 0
        rows.append(dict(observation_index=index, next_observation_index=index + 1,
                         requested_ticks=start, next_requested_ticks=end, capture_id=first["capture_id"],
                         next_capture_id=second["capture_id"],
                         next_episode_id=second.get("episode_id", manifest["episode_id"]),
                         next_attempt_id=second.get("attempt_id", manifest["attempt_id"]), action_json=json.dumps(action, sort_keys=True),
                         event_refs=[e["sequence_number"] for e in interval if e["type"] != "input"],
                         valid=valid, **lifecycle, **progress[index],
                         gap=gap, is_first=index == 0 or first.get("episode_id") != frames[index - 1].get("episode_id"),
                         is_last=last))
    for episode in derived_episodes:
        if episode["episode_id"] in control_faults:
            if "unknown_control" not in episode["validity_reasons"]:
                episode["validity_reasons"].append("unknown_control")
            if episode["validity_status"] == "valid":
                episode["validity_status"] = "invalid"
            for row in rows:
                if row["episode_id"] == episode["episode_id"]:
                    row["validity_status"] = episode["validity_status"]
                    row["validity_reasons"] = episode["validity_reasons"]
    pq.write_table(pa.Table.from_pylist(rows), destination / "transitions.parquet", compression="zstd", row_group_size=1024)
    # All raw event fields remain available without repeating observation pixels.
    event_rows = [{"ticks": e["ticks"], "sequence_number": e["sequence_number"], "type": e["type"],
                   "payload_json": json.dumps(e, sort_keys=True)} for e in events]
    event_schema = pa.schema([("ticks", pa.int64()), ("sequence_number", pa.int64()),
                             ("type", pa.string()), ("payload_json", pa.string())])
    pq.write_table(pa.Table.from_pylist(event_rows, schema=event_schema), destination / "events.parquet", compression="zstd", row_group_size=1024)
    metadata = dict(schema="dsp-transitions/4", catalog=CATALOG, artifact_id=str(uuid.uuid4()),
                    source_artifact_id=manifest["artifact_id"], source_manifest=file_info(source / "manifest.json"),
                    source_kind=manifest["source_kind"], episode_id=manifest["episode_id"],
                    ticks_frequency=manifest["ticks_frequency"], frame_count=len(frames), rgb_sha256=rgb_hashes,
                    observation=observation_contract(len(frames)),
                    table=dict(compression="zstd", row_group_size=1024),
                    tools=dict(compiler="0.1.0", zarr=zarr.__version__, pyarrow=pa.__version__, numpy=np.__version__))
    metadata.update(recording_session_id=manifest["recording_session_id"], attempt_id=manifest["attempt_id"],
                    trial_manifest=manifest.get("trial_manifest"), episodes=derived_episodes,
                    source_catalog=manifest["catalog"], controls=CONTROLS,
                    diagnostic_mode=manifest.get("diagnostic_mode", False))
    metadata.update(progress_version=manifest.get("progress_version"), tasks=TASKS, milestones=MILESTONES)
    metadata["recovery"] = manifest.get("recovery")
    metadata.update(action_codec=ACTION_CODEC, capture_hz=20, runtime=manifest.get("runtime"),
                    array_metadata=rgb.metadata.to_dict(),
                    tables={name: table_contract(destination / name) for name in ("transitions.parquet", "events.parquet")})
    save(destination / "dataset.json", metadata)
    files = {p.relative_to(destination).as_posix(): file_info(p) for p in destination.rglob("*") if p.is_file()}
    completed = dict(schema="dsp-completed/1", files=files)
    # The same loader validation must pass before publishing COMPLETED.
    Dataset(destination, _completed=completed)
    require(file_info(source / "manifest.json") == metadata["source_manifest"], "Source manifest changed")
    for name, info in manifest["files"].items():
        require(file_info(source / name) == info, "Recording changed during compile")
    atomic_save(destination / "COMPLETED", completed)
    return destination


class Dataset:
    def __init__(self, path, *, _completed=None):
        self.path = Path(path)
        completed = load(self.path / "COMPLETED") if _completed is None else _completed
        require(completed["schema"] == "dsp-completed/1", "Unknown completion schema")
        actual = {p.relative_to(self.path).as_posix() for p in self.path.rglob("*") if p.is_file()} - {"COMPLETED"}
        require(actual == set(completed["files"]), "Dataset file inventory mismatch")
        for name, info in completed["files"].items():
            require(file_info(self.path / name) == info, f"Dataset checksum mismatch: {name}")
        self.metadata = load(self.path / "dataset.json")
        require({"schema", "catalog", "artifact_id", "source_artifact_id", "source_manifest", "source_kind",
                 "recording_session_id", "attempt_id", "episode_id", "ticks_frequency", "frame_count", "rgb_sha256",
                 "observation", "table", "tools", "trial_manifest", "episodes", "source_catalog", "controls",
                 "diagnostic_mode", "progress_version", "tasks", "milestones", "recovery", "runtime",
                 "action_codec", "capture_hz", "array_metadata", "tables"} <= self.metadata.keys(), "Missing dataset field")
        require(self.metadata["schema"] == "dsp-transitions/4" and self.metadata["catalog"] == CATALOG,
                "Unsupported dataset schema/catalog. Recompile original evidence into a new dataset.")
        require(self.metadata.get("controls") == CONTROLS, "Invalid control order")
        require(type(self.metadata["frame_count"]) is int and self.metadata["frame_count"] >= 2, "Invalid frame count")
        require(self.metadata["table"] == dict(compression="zstd", row_group_size=1024), "Unsupported table contract")
        validate_action_contract(self.metadata.get("action_codec"))
        require(self.metadata.get("capture_hz") == 20 and type(self.metadata.get("ticks_frequency")) is int
                and self.metadata["ticks_frequency"] > 0, "Invalid capture clock")
        require(type(self.metadata.get("diagnostic_mode")) is bool, "Missing diagnostic mode")
        require(self.metadata["observation"] == observation_contract(self.metadata["frame_count"]), "Unknown observation codec/layout")
        group = zarr.open_group(str(self.path / "observations.zarr"), mode="r")
        self.rgb = group["rgb"]
        assert isinstance(self.rgb, zarr.Array)
        actual_array = json.loads(json.dumps(self.rgb.metadata.to_dict()))
        require(actual_array == self.metadata.get("array_metadata"), "Array metadata mismatch")
        require(self.rgb.chunks == (1, 360, 640, 3) and self.rgb.shards is None
                and self.rgb.metadata.zarr_format == 3
                and actual_array["codecs"] == [dict(name="bytes"),
                    BloscCodec(cname="zstd", clevel=3, typesize=1, shuffle="bitshuffle").to_dict()],
                "Unsupported actual observation codec/layout")
        require(list(self.rgb.shape) == self.metadata["observation"]["shape"] and self.rgb.dtype == np.uint8,
                "Observation shape/dtype mismatch")
        for name in ("transitions.parquet", "events.parquet"):
            actual_table = table_contract(self.path / name)
            require(actual_table == self.metadata.get("tables", {}).get(name), "Table schema/layout mismatch")
            require(all(0 <= group["rows"] <= 1024 and all(c["codec"] == "ZSTD" for c in group["columns"])
                        for group in actual_table["row_groups"]), "Unsupported table codec/layout")
        self.rows = pq.read_table(self.path / "transitions.parquet").to_pylist()
        event_rows = pq.read_table(self.path / "events.parquet").to_pylist()
        self.events = [json.loads(e["payload_json"]) for e in event_rows]
        validate_events(self.events)
        require(all(all(row[k] == event[k] for k in ("ticks", "sequence_number", "type"))
                    for row, event in zip(event_rows, self.events)), "Event payload identity mismatch")
        require(self.events == sorted(self.events, key=lambda e: (e["ticks"], e["sequence_number"])),
                "Nonmonotonic event time")
        require(self.metadata.get("tasks") == TASKS and self.metadata.get("milestones") == MILESTONES,
                "Invalid task/milestone catalog. Recompile original evidence.")
        version = self.metadata.get("progress_version")
        require(version is None or type(version) is int and version in (1, 2, 3), "Unknown progress version")
        require(len(self.rows) == self.metadata["frame_count"] - 1, "Invalid transition count")
        event_index, held = 0, []
        control_faults = set()
        scheduler_gaps = [e for e in self.events if e["type"] == "gap" and e["reason"] == "scheduler"]
        lifecycle_metadata = dict(self.metadata)
        if self.metadata["episodes"]:
            lifecycle_metadata["lifecycle_version"] = 1
        for index, row in enumerate(self.rows):
            required = {"observation_index", "next_observation_index", "requested_ticks", "next_requested_ticks",
                        "capture_id", "next_capture_id", "action_json", "event_refs", "valid", "gap", "episode_id",
                        "attempt_id", "next_episode_id", "next_attempt_id", "episode_outcome", "validity_status", "validity_reasons", "is_terminal",
                        "truncation", "bootstrap_mask", "is_first", "is_last"}
            require(required <= row.keys(), "Missing transition field")
            require(all(type(row[k]) is int and row[k] >= 0 for k in ("observation_index", "next_observation_index",
                        "requested_ticks", "next_requested_ticks", "capture_id", "next_capture_id")), "Invalid transition index/time")
            require(row["capture_id"] < row["next_capture_id"] and (index == 0 or
                    row["capture_id"] == self.rows[index - 1]["next_capture_id"]), "Nonmonotonic capture index")
            validate_progress_row(row, version in (1, 2, 3))
            stored_action = json.loads(row["action_json"])
            require(isinstance(stored_action["binary"], list) and len(stored_action["binary"]) == len(CONTROLS)
                    and all(type(v) is int and v in (0, 1) for v in stored_action["binary"]), "Invalid action width/bits")
            require(not self.metadata["diagnostic_mode"] or not row["valid"] and row["bootstrap_mask"] == 0,
                    "Diagnostic recording cannot train")
            require(row["observation_index"] == index and row["next_observation_index"] == index + 1,
                    "Invalid observation index")
            require(row["requested_ticks"] < row["next_requested_ticks"], "Invalid interval time")
            if index:
                require(row["requested_ticks"] == self.rows[index - 1]["next_requested_ticks"], "Nonmonotonic transition time")
            while event_index < len(self.events) and self.events[event_index]["ticks"] < row["requested_ticks"]:
                if self.events[event_index]["type"] == "input":
                    held = self.events[event_index]["held"]
                event_index += 1
            interval = []
            while event_index < len(self.events) and self.events[event_index]["ticks"] < row["next_requested_ticks"]:
                interval.append(self.events[event_index])
                event_index += 1
            action = aggregate([e for e in interval if e["type"] == "input"], row["requested_ticks"], row["next_requested_ticks"], held)
            require(stored_action == action, "Actual action differs from input evidence")
            held = action["end_held"]
            if action["unsupported"]:
                control_faults.add(row["episode_id"])
            gap = row["next_capture_id"] != row["capture_id"] + 1 or any(
                e["type"] == "gap" and e["reason"] != "scheduler" for e in interval)
            gap |= any(e["gap_start_ticks"] < row["next_requested_ticks"] and
                       e["gap_end_ticks"] > row["requested_ticks"] for e in scheduler_gaps)
            require(row["gap"] == gap, "Gap differs from input evidence")
            require(row["event_refs"] == [e["sequence_number"] for e in interval if e["type"] != "input"], "Invalid event reference")
            require(all(type(row[k]) is bool for k in ("valid", "gap", "is_terminal", "truncation", "is_first", "is_last"))
                    and type(row["bootstrap_mask"]) is int and row["bootstrap_mask"] in (0, 1), "Invalid validity flags")
            require(not row["valid"] or not any(action[k] for k in ("ambiguous", "unsupported", "forbidden"))
                    and not row["gap"] and row["episode_id"] not in control_faults
                    and all(e.get("focused", True) for e in interval if e["type"] == "input"),
                    "Invalid input marked trainable")
            require(row["valid"] or row["bootstrap_mask"] == 0, "Invalid bootstrap target")
            first = {k: row[k] for k in ("requested_ticks", "capture_id", "episode_id", "attempt_id")}
            second = {k: row["next_" + k] for k in first}
            require(index == 0 or all(first[k] == self.rows[index - 1]["next_" + k] for k in first),
                    "Discontinuous observation identity")
            require(not self.metadata["episodes"] or all(any(e["episode_id"] == f["episode_id"]
                    and e["attempt_id"] == f["attempt_id"] for e in self.metadata["episodes"])
                    for f in (first, second)), "Unknown episode/attempt")
            lifecycle = transition_lifecycle(lifecycle_metadata, first, second)
            is_first = index == 0 or row["episode_id"] != self.rows[index - 1]["episode_id"]
            is_last = index == len(self.rows) - 1 or row["next_episode_id"] != self.rows[index + 1]["next_episode_id"]
            require(row["is_first"] == is_first and row["is_last"] == is_last, "Invalid episode boundary")
            lifecycle_valid = lifecycle.pop("lifecycle_valid")
            require(not row["valid"] or lifecycle_valid, "Invalid lifecycle marked trainable")
            if not row["valid"] or is_last and row["validity_status"] != "valid":
                lifecycle["bootstrap_mask"] = 0
            require(all(row[k] == v for k, v in lifecycle.items()), "Invalid lifecycle target")
        require(len(self.metadata["rgb_sha256"]) == self.metadata["frame_count"], "Missing RGB checksums")
        for index, expected in enumerate(self.metadata["rgb_sha256"]):
            require(sha(np.asarray(self.rgb[index]).tobytes()) == expected, "Compiled RGB checksum mismatch")

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        return dict(observation=np.asarray(self.rgb[row["observation_index"]]),
                    next_observation=np.asarray(self.rgb[row["next_observation_index"]]),
                    action=json.loads(row["action_json"]), event_refs=row["event_refs"], valid=row["valid"],
                    **{key: row[key] for key in FIELDS},
                    **{key: row[key] for key in ("episode_outcome", "validity_status", "validity_reasons",
                       "is_terminal", "truncation", "bootstrap_mask", "is_first", "is_last")},
                    source=dict(artifact_id=self.metadata["source_artifact_id"], capture_id=row["capture_id"],
                                recording_session_id=self.metadata["recording_session_id"],
                                episode_id=row["episode_id"], attempt_id=row["attempt_id"],
                                split_group_id=(self.metadata.get("trial_manifest") or {}).get("split_group_id", row["episode_id"]),
                                next_capture_id=row["next_capture_id"], requested_ticks=row["requested_ticks"],
                                next_requested_ticks=row["next_requested_ticks"]))

    def sequence_starts(self, length):
        require(type(length) is int and length > 0, "Invalid sequence length")
        return [start for start in range(len(self.rows) - length + 1)
                if all(row["valid"] and row["episode_id"] == self.rows[start]["episode_id"]
                       for row in self.rows[start:start + length])]


def open_dataset(path):
    try:
        return Dataset(path)
    except (KeyError, TypeError, IndexError) as error:
        from .contract import InvalidRecording
        raise InvalidRecording(f"Missing or invalid dataset field: {error}") from error
