"""Synthetic capture adapter; live Unity capture writes the same source format."""
import uuid
from pathlib import Path

import numpy as np

from .contract import CATALOG, SCHEMA, atomic_save, require, sha, write_records
from .video import Encoder, check_ffmpeg


class Recording:
    @classmethod
    def synthetic(cls, path, ffmpeg, ticks_frequency=1000):
        return cls(path, ffmpeg, ticks_frequency)

    def __init__(self, path, ffmpeg, frequency):
        check_ffmpeg(ffmpeg)
        require(frequency > 0, "Invalid clock frequency")
        self.path, self.ffmpeg = Path(path), Path(ffmpeg)
        self.path.mkdir(parents=True, exist_ok=False)
        self.metadata = dict(schema=SCHEMA, catalog=CATALOG, source_kind="synthetic",
                             ticks_frequency=frequency, recording_session_id=str(uuid.uuid4()),
                             attempt_id=str(uuid.uuid4()), episode_id=str(uuid.uuid4()))
        self.frames, self.events, self.pending = [], [], {}
        self.sequence = self.next_capture = self.next_write = self.segment = 0
        self.encoder: Encoder | None = Encoder(ffmpeg, self.path / "segment-000000.mkv")
        self.closed = False

    def identity(self, ticks):
        result = dict(ticks=ticks, sequence_number=self.sequence)
        self.sequence += 1
        return result

    def input(self, ticks, **fields):
        self.events.append(dict(self.identity(ticks), type="input", **fields))

    def event(self, ticks, name, **fields):
        self.events.append(dict(self.identity(ticks), type="game_event", name=name, **fields))

    def request(self, ticks, unity_frame, game_tick):
        require(not self.closed and self.next_capture - self.next_write < 12, "Capture buffers exhausted")
        request = dict(self.identity(ticks), requested_ticks=ticks, capture_id=self.next_capture,
                       unity_frame=unity_frame, game_tick=game_tick, cursor={"visible": False})
        self.next_capture += 1
        self.pending[request["capture_id"]] = [request.copy(), None]
        return request

    def complete(self, request, rgba):
        capture_id = request["capture_id"]
        require(capture_id in self.pending, "Unknown or duplicate callback")
        entry = self.pending[capture_id]
        require(entry[0] == request and entry[1] is None, "Callback changed request identity")
        require(rgba.shape == (360, 640, 4) and rgba.dtype == np.uint8, "Invalid RGBA buffer")
        entry[1] = rgba.tobytes()
        while self.next_write in self.pending and self.pending[self.next_write][1] is not None:
            frame, data = self.pending.pop(self.next_write)
            if self.encoder is None:
                self.encoder = Encoder(self.ffmpeg, self.path / f"segment-{self.segment:06}.mkv")
            self.encoder.write(data)
            frame.update(ordinal=self.next_write, segment=f"segment-{self.segment:06}.mkv",
                         segment_ordinal=self.next_write % 200, rgba_sha256=sha(data))
            self.frames.append(frame)
            self.next_write += 1
            if self.next_write % 200 == 0:
                self.encoder.close()
                self.encoder = None
                self.segment += 1

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if self.encoder is not None:
            self.encoder.close()
        self.closed = True
        if kind is None:
            require(not self.pending and len(self.frames) >= 2, "Incomplete recording")
            write_records(self.path / "frames.ndjson", self.frames)
            write_records(self.path / "events.ndjson", self.events)
            atomic_save(self.path / "SOURCE.json", self.metadata)

    def publish(self, destination):
        from .archive import publish
        return publish(self.path, destination, self.ffmpeg)
