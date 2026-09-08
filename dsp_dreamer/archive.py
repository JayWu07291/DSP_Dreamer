"""Verify source segments, remux, and publish immutable four-file evidence."""
from itertools import zip_longest
from pathlib import Path
import shutil
import uuid
import json
import re
import math

from .contract import (CATALOG, ENCODE, FFMPEG_SHA, SCHEMA, atomic_save, file_info,
                       load, records, require, sha)
from .video import check_ffmpeg, decode, run


def validate_metadata(metadata):
    require(metadata["schema"] == SCHEMA and metadata["catalog"] == CATALOG, "Unknown schema or catalog")
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
            require(event.get("name") in ("tech_unlocked", "factory_build", "factory_dismantled", "recording_stopped"), "Unknown game event")
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
    path = Path(path)
    check_ffmpeg(ffmpeg)
    manifest = load(path / "manifest.json")
    validate_metadata(manifest)
    require(manifest["state"] == "verified", "Recording is not complete")
    require(manifest["ffmpeg_sha256"] == FFMPEG_SHA and manifest["encoder_parameters"] == ENCODE,
            "Unknown encoding contract")
    require(set(manifest["files"]) == {"recording.mkv", "events.ndjson", "frames.ndjson"}, "Invalid four-file manifest")
    for name, info in manifest["files"].items():
        require(file_info(path / name) == info, f"File checksum mismatch: {name}")
    frames, events = list(records(path / "frames.ndjson")), list(records(path / "events.ndjson"))
    validate_indices(frames, events)
    require(len(frames) == manifest["frame_count"] and len(events) == manifest["event_count"], "Count mismatch")
    verify_video(ffmpeg, path / "recording.mkv", frames)
    return manifest, frames, events


def publish(source, destination, ffmpeg):
    source, destination = Path(source), Path(destination)
    check_ffmpeg(ffmpeg)
    metadata = load(source / "SOURCE.json")
    validate_metadata(metadata)
    frames, events = list(records(source / "frames.ndjson")), list(records(source / "events.ndjson"))
    validate_indices(frames, events)
    segments = list(dict.fromkeys(frame["segment"] for frame in frames))
    source_files = {name: file_info(source / name) for name in ["SOURCE.json", "frames.ndjson", "events.ndjson", *segments]}
    for segment in segments:
        verify_video(ffmpeg, source / segment, [f for f in frames if f["segment"] == segment])
    destination.mkdir(parents=True, exist_ok=False)
    # Only generated simple filenames enter the concat list. Source paths are never shell code.
    concat = destination / "concat.partial"
    for segment in segments:
        shutil.copyfile(source / segment, destination / segment)
    concat.write_text("".join(f"file '{name}'\n" for name in segments), encoding="utf-8")
    run(ffmpeg, ["-n", "-f", "concat", "-safe", "1", "-i", str(concat), "-map", "0:v:0", "-c", "copy",
                 str(destination / "recording.mkv")])
    verify_video(ffmpeg, destination / "recording.mkv", frames)
    seek_points = sorted({0, len(frames) - 1} | {i for boundary in range(200, len(frames), 200)
                                                for i in (boundary - 1, boundary)})
    for ordinal in seek_points:
        decoded = list(decode(ffmpeg, destination / "recording.mkv", ordinal))
        require(len(decoded) == 1 and sha(decoded[0]) == frames[ordinal]["rgba_sha256"], "Segment boundary seek mismatch")
    for name in ("frames.ndjson", "events.ndjson"):
        shutil.copyfile(source / name, destination / name)
        require(file_info(destination / name) == source_files[name], "Metadata changed during copy")
    require(all(file_info(source / name) == info for name, info in source_files.items()), "Source changed during publication")
    manifest = dict(metadata, state="verified", artifact_id=str(uuid.uuid4()), ffmpeg_sha256=FFMPEG_SHA,
                    encoder_parameters=ENCODE, frame_count=len(frames), event_count=len(events),
                    source_files=source_files, validation={"full_rgba_decode": True, "seek_ordinals": seek_points},
                    files={name: file_info(destination / name) for name in ("recording.mkv", "frames.ndjson", "events.ndjson")})
    # Delete only copies created above; original source evidence is retained for later lifecycle tickets.
    for name in segments:
        (destination / name).unlink()
    concat.unlink()
    atomic_save(destination / "manifest.json", manifest)
    verify_recording(destination, ffmpeg)
    return destination
