"""Compile actual input over half-open request-time intervals and read verified datasets."""
from collections import Counter
from pathlib import Path
import json
import uuid

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zarr
from zarr.codecs.blosc import BloscCodec

from .archive import verify_recording
from .contract import CATALOG, CONTROLS, atomic_save, file_info, load, require, save, sha
from .video import decode


def aggregate(samples, start, end, initial):
    held = set(initial)
    start_held = sorted(held)
    duration: Counter[str] = Counter()
    down: Counter[str] = Counter()
    up: Counter[str] = Counter()
    delta, wheel = [0.0, 0.0], 0.0
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
        refs.append(sample["sequence_number"])
    for key in held:
        duration[key] += end - cursor
    fraction = {key: duration[key] / (end - start) for key in sorted(set(CONTROLS) | set(duration))}
    active = {key for key in CONTROLS if down[key] > 0 or fraction[key] >= 0.5}
    forbidden = any(set(pair) <= active for pair in [("W", "S"), ("A", "D"), ("LeftControl", "LeftShift"),
                    ("MouseLeft", "MouseRight"), ("MouseLeft", "MouseMiddle"), ("MouseRight", "MouseMiddle")])
    ambiguous |= any(count > 1 for count in (*down.values(), *up.values()))
    return dict(start_held=start_held, end_held=sorted(held), held_fraction=fraction,
                down_counts=dict(down), up_counts=dict(up), delta=delta, wheel=wheel,
                sample_refs=refs, ambiguous=bool(ambiguous), unsupported=bool(unsupported),
                forbidden=forbidden, binary=[int(key in active) for key in CONTROLS])


def compile_recording(source, destination, ffmpeg):
    source, destination = Path(source), Path(destination)
    manifest, frames, events = verify_recording(source, ffmpeg)
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
        gap = second["capture_id"] != first["capture_id"] + 1 or any(e["type"] == "gap" for e in interval)
        invalid_input = any(not s.get("focused", True) for s in samples)
        rows.append(dict(observation_index=index, next_observation_index=index + 1,
                         requested_ticks=start, next_requested_ticks=end, capture_id=first["capture_id"],
                         next_capture_id=second["capture_id"], action_json=json.dumps(action, sort_keys=True),
                         event_refs=[e["sequence_number"] for e in interval if e["type"] != "input"],
                         valid=not (gap or invalid_input or action["ambiguous"] or action["unsupported"] or action["forbidden"]),
                         gap=gap, is_first=index == 0, is_last=index == len(frames) - 2))
    pq.write_table(pa.Table.from_pylist(rows), destination / "transitions.parquet", compression="zstd", row_group_size=1024)
    # All raw event fields remain available without repeating observation pixels.
    event_rows = [{"ticks": e["ticks"], "sequence_number": e["sequence_number"], "type": e["type"],
                   "payload_json": json.dumps(e, sort_keys=True)} for e in events]
    event_schema = pa.schema([("ticks", pa.int64()), ("sequence_number", pa.int64()),
                             ("type", pa.string()), ("payload_json", pa.string())])
    pq.write_table(pa.Table.from_pylist(event_rows, schema=event_schema), destination / "events.parquet", compression="zstd", row_group_size=1024)
    metadata = dict(schema="dsp-transitions/1", catalog=CATALOG, artifact_id=str(uuid.uuid4()),
                    source_artifact_id=manifest["artifact_id"], source_manifest=file_info(source / "manifest.json"),
                    source_kind=manifest["source_kind"], episode_id=manifest["episode_id"],
                    ticks_frequency=manifest["ticks_frequency"], frame_count=len(frames), rgb_sha256=rgb_hashes,
                    observation=dict(dtype="uint8", shape=[len(frames), 360, 640, 3], chunks=[1, 360, 640, 3],
                                     shards=None, codec="blosc/zstd", zarr_format=3),
                    table=dict(compression="zstd", row_group_size=1024),
                    tools=dict(compiler="0.1.0", zarr=zarr.__version__, pyarrow=pa.__version__, numpy=np.__version__))
    save(destination / "dataset.json", metadata)
    # Reopen actual stored chunks and tables before publication.
    for index in range(len(frames)):
        require(sha(np.asarray(rgb[index]).tobytes()) == rgb_hashes[index], "Compiled RGB checksum mismatch")
    require(pq.read_table(destination / "transitions.parquet").num_rows == len(frames) - 1, "Transition count mismatch")
    files = {p.relative_to(destination).as_posix(): file_info(p) for p in destination.rglob("*") if p.is_file()}
    require(file_info(source / "manifest.json") == metadata["source_manifest"], "Source manifest changed")
    for name, info in manifest["files"].items():
        require(file_info(source / name) == info, "Recording changed during compile")
    atomic_save(destination / "COMPLETED", dict(schema="dsp-completed/1", files=files))
    open_dataset(destination)
    return destination


class Dataset:
    def __init__(self, path):
        self.path = Path(path)
        completed = load(self.path / "COMPLETED")
        require(completed["schema"] == "dsp-completed/1", "Unknown completion schema")
        actual = {p.relative_to(self.path).as_posix() for p in self.path.rglob("*") if p.is_file()} - {"COMPLETED"}
        require(actual == set(completed["files"]), "Dataset file inventory mismatch")
        for name, info in completed["files"].items():
            require(file_info(self.path / name) == info, f"Dataset checksum mismatch: {name}")
        self.metadata = load(self.path / "dataset.json")
        require(self.metadata["schema"] == "dsp-transitions/1" and self.metadata["catalog"] == CATALOG,
                "Unknown dataset schema/catalog")
        require(self.metadata["observation"] == dict(dtype="uint8", shape=[self.metadata["frame_count"], 360, 640, 3],
                    chunks=[1, 360, 640, 3], shards=None, codec="blosc/zstd", zarr_format=3), "Unknown observation codec/layout")
        group = zarr.open_group(str(self.path / "observations.zarr"), mode="r")
        self.rgb = group["rgb"]
        assert isinstance(self.rgb, zarr.Array)
        require(list(self.rgb.shape) == self.metadata["observation"]["shape"] and self.rgb.dtype == np.uint8,
                "Observation shape/dtype mismatch")
        self.rows = pq.read_table(self.path / "transitions.parquet").to_pylist()
        require(len(self.rows) == self.metadata["frame_count"] - 1, "Invalid transition count")
        for index, row in enumerate(self.rows):
            require(row["observation_index"] == index and row["next_observation_index"] == index + 1,
                    "Invalid observation index")
            require(row["requested_ticks"] < row["next_requested_ticks"], "Invalid interval time")
            if index:
                require(row["requested_ticks"] == self.rows[index - 1]["next_requested_ticks"], "Nonmonotonic transition time")
        for index, expected in enumerate(self.metadata["rgb_sha256"]):
            require(sha(np.asarray(self.rgb[index]).tobytes()) == expected, "Compiled RGB checksum mismatch")

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        return dict(observation=np.asarray(self.rgb[row["observation_index"]]),
                    next_observation=np.asarray(self.rgb[row["next_observation_index"]]),
                    action=json.loads(row["action_json"]), event_refs=row["event_refs"], valid=row["valid"],
                    source=dict(artifact_id=self.metadata["source_artifact_id"], capture_id=row["capture_id"],
                                next_capture_id=row["next_capture_id"], requested_ticks=row["requested_ticks"],
                                next_requested_ticks=row["next_requested_ticks"]))


def open_dataset(path):
    return Dataset(path)
