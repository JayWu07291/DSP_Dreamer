"""Recover only sealed, fully decoded prefixes; never repair the original evidence."""
import copy
import hashlib
import json
import re
from pathlib import Path
import shutil
import uuid

from .archive import (capacity_preflight, checked_path, publish, validate_indices,
                      validate_metadata, verify_video)
from .contract import InvalidRecording, atomic_save, file_info, load, require, write_records
from .lifecycle import validate_lifecycle
from .progress import replay_progress
from .video import check_ffmpeg


def seal_files(root, segments):
    return {name: file_info(root / name) for name in ["frames.ndjson", "events.ndjson", *segments]}


def read_prefix(path, info):
    require(type(info["bytes"]) is int and info["bytes"] >= 0, "Invalid sealed length")
    with path.open("rb") as stream:
        data = stream.read(info["bytes"])
    require(len(data) == info["bytes"] and hashlib.sha256(data).hexdigest() == info["sha256"],
            f"Sealed prefix changed: {path.name}")
    require(not data or data.endswith(b"\n"), "Truncated sealed NDJSON")
    return [json.loads(line) for line in data.decode("utf-8-sig").splitlines()]


def recover(source, destination, ffmpeg):
    source, destination = Path(source).absolute(), Path(destination).absolute()
    require(source == source.resolve() and destination == destination.resolve(), "Aliased recovery directory")
    require(source.drive == destination.drive, "Recovery requires source and evidence on the same volume")
    marker = destination / "manifest.json"
    receipt = destination.with_name(destination.name + ".publish.json")
    if marker.exists() or receipt.exists():
        manifest = load(marker if marker.exists() else receipt)
        require(manifest.get("recovery", {}).get("source_root") == str(source), "Different recovery source")
        recovered = Path(manifest["publication"]["source_root"])
        require(recovered.parent == source and re.fullmatch(r"recovery-[0-9a-f-]{36}", recovered.name),
                "Unsafe recovered work directory")
        return publish(recovered, destination, ffmpeg, cleanup=True)
    require(not destination.exists(), "Recovery needs a new artifact destination")
    check_ffmpeg(ffmpeg)
    candidates = ([source / "SOURCE.json"] if (source / "SOURCE.json").exists() else [])
    candidates += sorted(source.glob("checkpoint-*.json"), reverse=True)
    failures = []
    for candidate in candidates:
        try:
            checkpoint_info = file_info(checked_path(source, candidate.name))
            metadata = load(candidate)
            validate_metadata(metadata)
            sealed = metadata["sealed_files"]
            frames = read_prefix(checked_path(source, "frames.ndjson"), sealed["frames.ndjson"])
            events = read_prefix(checked_path(source, "events.ndjson"), sealed["events.ndjson"])
            validate_indices(frames, events)
            segments = list(dict.fromkeys(f["segment"] for f in frames))
            require(set(sealed) == {"frames.ndjson", "events.ndjson", *segments}, "Invalid checkpoint inventory")
            for segment in segments:
                path = checked_path(source, segment)
                require(file_info(path) == sealed[segment], "Sealed segment changed")
                verify_video(ffmpeg, path, [f for f in frames if f["segment"] == segment])
            metadata = copy.deepcopy(metadata)
            cutoff = frames[-1]["requested_ticks"]
            events = [e for e in events if e["ticks"] <= cutoff]
            if "lifecycle_version" in metadata:
                ids = {f["episode_id"] for f in frames}
                metadata["episodes"] = [e for e in metadata["episodes"] if e["episode_id"] in ids]
                events = [e for e in events if e.get("episode_id") is None or e["episode_id"] in ids]
                for episode in metadata["episodes"]:
                    selected = [f for f in frames if f["episode_id"] == episode["episode_id"]]
                    episode["start_ticks"] = selected[0]["requested_ticks"]
                    if episode["final_capture_id"] != selected[-1]["capture_id"]:
                        episode.update(end_ticks=selected[-1]["requested_ticks"], final_capture_id=None,
                            episode_outcome=None, validity_status="incomplete",
                            validity_reasons=list(dict.fromkeys([*episode["validity_reasons"], "recorder_fault"])))
            validate_lifecycle(metadata, frames)
            replay_progress(metadata, frames, events)
            require(file_info(candidate) == checkpoint_info, "Checkpoint changed")
        except (InvalidRecording, OSError, ValueError, KeyError, TypeError) as error:
            failures.append(dict(checkpoint=candidate.name, error=str(error)))
            continue
        break
    else:
        raise InvalidRecording(f"No verified continuous prefix: {failures}")
    capacity_preflight(source, sum(info["bytes"] for info in sealed.values()), copies=3)
    recovered = source / ("recovery-" + str(uuid.uuid4()))
    recovered.mkdir()
    for segment in segments:
        shutil.copyfile(checked_path(source, segment), recovered / segment)
        require(file_info(recovered / segment) == sealed[segment], "Source changed during recovery")
    # Recheck sidecar prefixes as well as the original checkpoint after copying.
    for name in ("frames.ndjson", "events.ndjson"):
        read_prefix(checked_path(source, name), sealed[name])
    require(file_info(candidate) == checkpoint_info, "Checkpoint changed during recovery")
    write_records(recovered / "frames.ndjson", frames)
    write_records(recovered / "events.ndjson", events)
    metadata["recovery"] = dict(recording_complete=False, source_root=str(source),
        checkpoint=candidate.name, checkpoint_info=checkpoint_info, failures=failures,
        excluded_from_ordinal=len(frames), excluded_after_ticks=cutoff, excluded_to_ordinal=None)
    metadata["sealed_files"] = seal_files(recovered, segments)
    atomic_save(recovered / "SOURCE.json", metadata)
    return publish(recovered, destination, ffmpeg, cleanup=True)
