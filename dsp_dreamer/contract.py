"""Versioned interchange contract for the single-episode recording path."""
import hashlib
import json
import os
from pathlib import Path

SCHEMA = "dsp-recording/1"
CATALOG = "action_catalog_v3"
CONTROLS = ["Escape", "Digit1", "Digit2", "Tab", "W", "R", "T", "LeftControl",
            "A", "S", "D", "F", "LeftShift", "X", "C", "MouseLeft", "MouseRight", "MouseMiddle", "Space", "E"]
FFMPEG_SHA = "04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00"
FRAME_BYTES = 640 * 360 * 4
ENCODE = ["-c:v", "ffv1", "-level", "3", "-coder", "1", "-context", "0",
          "-g", "1", "-slicecrc", "1", "-slices", "4", "-threads", "4", "-pix_fmt", "bgra"]


class InvalidRecording(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidRecording(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_info(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"bytes": Path(path).stat().st_size, "sha256": digest}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_save(path, value):
    path = Path(path)
    require(not path.exists(), f"Refusing overwrite: {path}")
    partial = path.with_name(path.name + ".partial")
    save(partial, value)
    # Windows rename fails if destination exists. Publication never replaces evidence.
    partial.rename(path)


def records(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line in stream:
            require(bool(line.strip()), "Empty NDJSON record")
            yield json.loads(line)


def write_records(path, rows):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
