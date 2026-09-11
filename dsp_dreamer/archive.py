"""Verify source segments, remux, and publish immutable four-file evidence."""
from itertools import zip_longest
from pathlib import Path
import shutil
import uuid
import json
import re
import math

from .contract import (CATALOG, ENCODE, FFMPEG_SHA, SCHEMA, file_info,
                       load, records, require, save, sha)
from .video import check_ffmpeg, decode, run
from .lifecycle import validate_lifecycle
from .progress import validate_fact, replay_progress


def validate_metadata(metadata):
    require(metadata["schema"] == SCHEMA and metadata["catalog"] in ("action_catalog_v2", CATALOG), "Unknown schema or catalog")
    require(type(metadata.get("diagnostic_mode", False)) is bool, "Invalid diagnostic mode")
    require(metadata["ticks_frequency"] > 0, "Invalid clock frequency")
    for field in ("recording_session_id", "attempt_id", "episode_id"):
        require(bool(metadata[field]), f"Missing {field}")
    require(metadata["source_kind"] in ("synthetic", "live"), "Unknown source kind")
    if metadata["source_kind"] == "live":
        runtime = metadata["runtime"]
        require(runtime["bepinex_version"] == "5.4.23.5" and runtime["harmonyx_version"] == "2.9.0",
                "Unsupported plugin runtime")
        require(runtime["platform"] == "Windows x64 Unity Mono" and runtime["target_framework"] == "net472",
                "Unsupported platform")
        require(runtime["fingerprint_verified"] is True, "Unknown runtime fingerprint")
        for key in ("game_version", "unity_version", "plugin_version", "input_settings_sha256", "binary_hashes"):
            require(bool(runtime[key]), f"Missing runtime {key}")
        require(runtime["binary_hashes"].get("Assembly-CSharp") ==
                "ae0ba95f75bd879a62aa4ce253b2ab78eaa4fb3c7c595f5e1fee75ebe0e0ef85", "Unknown game fingerprint")
        required = {"Assembly-CSharp", "BepInEx", "0Harmony", "DSPDreamer.Recorder", "UnityPlayer", "DSPGAME",
                    "UnityEngine.InputLegacyModule", "UnityEngine.CoreModule", "UnityEngine.ScreenCaptureModule"}
        require(required <= set(runtime["binary_hashes"]), "Incomplete binary fingerprint")
        require(all(re.fullmatch("[0-9a-f]{64}", digest) for digest in
                    [runtime["input_settings_sha256"], *runtime["binary_hashes"].values()]), "Invalid fingerprint hash")
        candidate = {k: v for k, v in runtime.items() if k not in ("fingerprint_verified", "approved_fingerprint")}
        digest = sha(json.dumps(candidate, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())
        require(runtime.get("approved_fingerprint") == digest, "Runtime fingerprint does not match approval")


def validate_indices(frames, events):
    require(len(frames) >= 2, "Need adjacent observations")
    identities = []
    previous_ticks, previous_capture = -1, -1
    for ordinal, frame in enumerate(frames):
        for name in ("ordinal", "ticks", "requested_ticks", "capture_id", "sequence_number", "unity_frame", "game_tick", "segment_ordinal"):
            require(type(frame.get(name)) is int and frame[name] >= 0, f"Invalid frame {name}")
        require(isinstance(frame.get("cursor"), dict), "Missing request-time cursor")
        require(bool(re.fullmatch("[0-9a-f]{64}", frame.get("rgba_sha256", ""))), "Invalid RGBA checksum")
        require(frame["ordinal"] == ordinal, "Noncontiguous frame ordinal")
        require(frame["ticks"] == frame["requested_ticks"] > previous_ticks, "Nonmonotonic request ticks")
        require(frame["capture_id"] > previous_capture, "Capture identity order changed")
        previous_ticks, previous_capture = frame["ticks"], frame["capture_id"]
        segment = frame["segment"]
        require(segment == f"segment-{ordinal // 200:06}.mkv", "Invalid cross-segment index")
        require(frame["segment_ordinal"] == ordinal % 200, "Invalid segment ordinal")
        identities.append(frame["sequence_number"])
    for event in events:
        for name in ("ticks", "sequence_number"):
            require(type(event.get(name)) is int and event[name] >= 0, f"Invalid event {name}")
        require(event["type"] in ("input", "game_event", "gap", "control_request"), "Unknown event type")
        if event["type"] == "game_event":
            require(event.get("name") in ("tech_unlocked", "factory_build", "factory_dismantled", "recording_stopped",
                    "world_ready", "perturbation_applied", "episode_started", "episode_ended", "progress_fact",
                    "progress_observation"), "Unknown game event")
            if event.get("name") == "progress_fact":
                validate_fact(event)
        if event["type"] == "input":
            for field in ("held", "down", "up"):
                keys = event.get(field)
                require(isinstance(keys, list) and all(isinstance(k, str) and k for k in keys), "Invalid input keys")
                require(len(keys) == len(set(keys)), "Duplicate input key")
            require(isinstance(event.get("delta"), list) and len(event["delta"]) == 2, "Invalid observed delta")
            values = [*event["delta"], event.get("wheel"), event.get("horizontal_wheel", 0)]
            require(all(type(x) in (float, int) and math.isfinite(x) for x in values), "Invalid input number")
        if event["type"] == "gap":
            require(event.get("reason") in ("scheduler", "no_free_buffer", "gpu_readback_error", "writer_backpressure"), "Unknown gap reason")
            if event["reason"] == "scheduler":
                require(type(event.get("gap_start_ticks")) is int and type(event.get("gap_end_ticks")) is int,
                        "Missing scheduler gap range")
                require(0 <= event["gap_start_ticks"] < event["gap_end_ticks"] <= event["ticks"], "Invalid gap range")
        identities.append(event["sequence_number"])
    require(len(set(identities)) == len(identities) and all(x >= 0 for x in identities), "Duplicate sequence identity")


def verify_video(ffmpeg, path, frames):
    count = 0
    for frame, expected in zip_longest(decode(ffmpeg, path), frames):
        require(frame is not None and expected is not None, "Decoded frame count mismatch")
        require(sha(frame) == expected["rgba_sha256"], "RGBA checksum/order mismatch")
        count += 1
    return count


def verify_recording(path, ffmpeg):
    path = Path(path).absolute()
    require(path == path.resolve() and not (path / "manifest.json").is_symlink()
            and (path / "manifest.json").resolve().parent == path, "Aliased evidence directory or manifest")
    check_ffmpeg(ffmpeg)
    manifest = load(path / "manifest.json")
    require({p.name for p in path.iterdir()} == {"manifest.json", "recording.mkv", "frames.ndjson", "events.ndjson"},
            "Unexpected evidence files")
    return verify_payload(path, manifest, ffmpeg)


def verify_payload(path, manifest, ffmpeg):
    validate_metadata(manifest)
    require(manifest["state"] == "verified", "Recording is not complete")
    if "recovery" in manifest:
        recovery = manifest["recovery"]
        require(recovery["recording_complete"] is False and recovery["excluded_from_ordinal"] == manifest["frame_count"],
                "Invalid recovered prefix marker")
    require(manifest["ffmpeg_sha256"] == FFMPEG_SHA and manifest["encoder_parameters"] == ENCODE,
            "Unknown encoding contract")
    require(set(manifest["files"]) == {"recording.mkv", "events.ndjson", "frames.ndjson"}, "Invalid four-file manifest")
    for name, info in manifest["files"].items():
        require(file_info(checked_path(path, name)) == info, f"File checksum mismatch: {name}")
    frames, events = list(records(path / "frames.ndjson")), list(records(path / "events.ndjson"))
    validate_indices(frames, events)
    validate_lifecycle(manifest, frames)
    replay_progress(manifest, frames, events)
    require(len(frames) == manifest["frame_count"] and len(events) == manifest["event_count"], "Count mismatch")
    verify_video(ffmpeg, path / "recording.mkv", frames)
    return manifest, frames, events


def checked_path(root, name):
    root = Path(root).absolute()
    require(root.absolute() == root.resolve(), "Aliased work directory")
    require(isinstance(name, str) and bool(re.fullmatch(
        r"SOURCE\.json|frames\.ndjson|events\.ndjson|segment-\d{6}\.mkv|checkpoint-\d{6}\.json|"
        r"segment-\d{6}\.encoder\.log|recording\.mkv|concat\.partial", name)), "Unsafe cleanup filename")
    path = root / name
    require(path.resolve().parent == root and not path.is_symlink(), "Path escapes work directory")
    return path


def check_files(root, files, missing=False):
    for name, info in files.items():
        path = checked_path(root, name)
        if missing and not path.exists():
            continue
        require(file_info(path) == info, f"Source changed: {name}")


def capacity_preflight(destination, source_bytes, copies=2):
    parent = Path(destination)
    while not parent.exists():
        require(parent.parent != parent, "No existing destination volume")
        parent = parent.parent
    # Source already occupies disk; allow a segment copy, merged copy and 1 GiB reserve.
    require(shutil.disk_usage(parent).free >= copies * source_bytes + 1024 ** 3, "Insufficient free space; source retained")


def cleanup_recording(source, destination, ffmpeg):
    source = Path(source).absolute()
    manifest, _, _ = verify_recording(destination, ffmpeg)
    publication = manifest["publication"]
    require(publication["source_root"] == str(source), "Different source directory")
    work = Path(publication["work_root"])
    require(work.parent == source and re.fullmatch(r"archive-[0-9a-f-]{36}", work.name), "Unsafe work directory")
    groups = [(source, manifest["source_files"]), (work, publication["work_files"])]
    # Check every remaining file before the first deletion, then recheck at unlink.
    for root, files in groups:
        check_files(root, files, missing=True)
    for root, files in groups:
        for name, info in files.items():
            path = checked_path(root, name)
            if path.exists():
                require(file_info(path) == info, f"Source changed before cleanup: {name}")
                path.unlink()


def publish(source, destination, ffmpeg, cleanup=False):
    source, destination = Path(source).absolute(), Path(destination).absolute()
    require(source == source.resolve() and destination == destination.resolve(), "Aliased publication directory")
    require(source.drive == destination.drive, "Publication requires source and evidence on the same volume")
    require(source != destination and source not in destination.parents and destination not in source.parents,
            "Overlapping source and evidence directories")
    check_ffmpeg(ffmpeg)
    if (destination / "manifest.json").exists():
        manifest, _, _ = verify_recording(destination, ffmpeg)
        require(manifest.get("publication", {}).get("source_root") == str(source), "Different source directory")
        check_files(source, manifest["source_files"], missing=True)
        if cleanup:
            cleanup_recording(source, destination, ffmpeg)
        return destination
    receipt = destination.with_name(destination.name + ".publish.json")
    require(not receipt.is_symlink() and receipt.resolve().parent == destination.parent, "Aliased publication receipt")
    if receipt.exists():
        manifest = load(receipt)
        require(manifest["publication"]["source_root"] == str(source), "Different source directory")
        check_files(source, manifest["source_files"])
        return finish_publication(source, destination, manifest, ffmpeg, cleanup)
    require(not destination.exists(), "Unowned partial destination; recover into a new artifact")
    # Snapshot before parsing, then recheck before making any publication visible.
    metadata_info = file_info(source / "SOURCE.json")
    metadata = load(source / "SOURCE.json")
    validate_metadata(metadata)
    sidecars = {name: file_info(source / name) for name in ("frames.ndjson", "events.ndjson")}
    frames, events = list(records(source / "frames.ndjson")), list(records(source / "events.ndjson"))
    validate_indices(frames, events)
    validate_lifecycle(metadata, frames)
    replay_progress(metadata, frames, events)
    segments = list(dict.fromkeys(frame["segment"] for frame in frames))
    source_files = dict(sidecars, **{"SOURCE.json": metadata_info})
    source_files.update({name: file_info(checked_path(source, name)) for name in segments})
    if "sealed_files" in metadata:
        require(metadata["sealed_files"] == {name: source_files[name] for name in [*sidecars, *segments]},
                "Source differs from recording seal")
    for path in source.iterdir():
        if re.fullmatch(r"checkpoint-\d{6}\.json|segment-\d{6}\.encoder\.log", path.name):
            source_files[path.name] = file_info(checked_path(source, path.name))
    check_files(source, source_files)
    source_bytes = sum(info["bytes"] for info in source_files.values())
    capacity_preflight(source, source_bytes)
    for segment in segments:
        verify_video(ffmpeg, source / segment, [f for f in frames if f["segment"] == segment])
    work = source / ("archive-" + str(uuid.uuid4()))
    work.mkdir()
    # Only generated simple filenames enter the concat list. Source paths are never shell code.
    concat = work / "concat.partial"
    for segment in segments:
        shutil.copyfile(source / segment, work / segment)
    concat.write_text("".join(f"file '{name}'\n" for name in segments), encoding="utf-8")
    run(ffmpeg, ["-n", "-f", "concat", "-safe", "1", "-i", str(concat), "-map", "0:v:0", "-c", "copy",
                 str(work / "recording.mkv")])
    verify_video(ffmpeg, work / "recording.mkv", frames)
    seek_points = sorted({0, len(frames) - 1} | {i for boundary in range(200, len(frames), 200)
                                                for i in (boundary - 1, boundary)})
    for ordinal in seek_points:
        decoded = list(decode(ffmpeg, work / "recording.mkv", ordinal))
        require(len(decoded) == 1 and sha(decoded[0]) == frames[ordinal]["rgba_sha256"], "Segment boundary seek mismatch")
    for name in ("frames.ndjson", "events.ndjson"):
        shutil.copyfile(source / name, work / name)
        require(file_info(work / name) == source_files[name], "Metadata changed during copy")
    check_files(source, source_files)
    manifest = dict(metadata, state="verified", artifact_id=str(uuid.uuid4()), ffmpeg_sha256=FFMPEG_SHA,
                    encoder_parameters=ENCODE, frame_count=len(frames), event_count=len(events),
                    source_files=source_files, validation={"full_rgba_decode": True, "seek_ordinals": seek_points},
                    files={name: file_info(work / name) for name in ("recording.mkv", "frames.ndjson", "events.ndjson")},
                    publication=dict(source_root=str(source), work_root=str(work),
                        work_files={p.name: file_info(p) for p in work.iterdir()}))
    destination.parent.mkdir(parents=True, exist_ok=True)
    save(work / "ready.json", manifest)
    (work / "ready.json").rename(receipt)
    return finish_publication(source, destination, manifest, ffmpeg, cleanup)


def finish_publication(source, destination, manifest, ffmpeg, cleanup):
    work = Path(manifest["publication"]["work_root"])
    require(work.parent == source and re.fullmatch(r"archive-[0-9a-f-]{36}", work.name), "Unsafe work directory")
    require(set(manifest["files"]) == {"recording.mkv", "frames.ndjson", "events.ndjson"}, "Invalid publication inventory")
    check_files(work, manifest["publication"]["work_files"], missing=True)
    destination.mkdir(exist_ok=True)
    require(set(p.name for p in destination.iterdir()) <= set(manifest["files"]),
            "Unexpected partial publication files")
    for name, info in manifest["files"].items():
        target = checked_path(destination, name)
        if target.exists():
            require(file_info(target) == info, "Partial publication changed")
        else:
            (work / name).rename(target)
            require(file_info(target) == info, "Published data checksum mismatch")
    verify_payload(destination, manifest, ffmpeg)
    check_files(source, manifest["source_files"])
    receipt = destination.with_name(destination.name + ".publish.json")
    require(load(receipt) == manifest, "Publication receipt changed")
    receipt.rename(destination / "manifest.json")
    verify_recording(destination, ffmpeg)
    if cleanup:
        cleanup_recording(source, destination, ffmpeg)
    return destination
