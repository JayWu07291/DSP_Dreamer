"""Pinned FFV1 encoder and streaming, lossless RGBA decoder."""
import subprocess
from pathlib import Path

from .contract import ENCODE, FFMPEG_SHA, FRAME_BYTES, file_info, require


def check_ffmpeg(executable):
    require(file_info(executable)["sha256"] == FFMPEG_SHA, "Unknown FFmpeg executable hash")


def run(executable, arguments):
    return subprocess.run([str(executable), "-hide_banner", "-loglevel", "error", *arguments],
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=180)


class Encoder:
    def __init__(self, executable, path):
        self.path = Path(path)
        self.errors = self.path.with_suffix(".encoder.log").open("xb")
        self.process = subprocess.Popen(
            [str(executable), "-hide_banner", "-loglevel", "error", "-n", "-f", "rawvideo",
             "-pix_fmt", "rgba", "-video_size", "640x360", "-framerate", "20", "-i", "pipe:0",
             "-an", *ENCODE, "-f", "matroska", str(path)], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=self.errors,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def write(self, rgba):
        require(len(rgba) == FRAME_BYTES, "Expected 640x360 RGBA")
        assert self.process.stdin is not None
        self.process.stdin.write(rgba)

    def close(self):
        try:
            assert self.process.stdin is not None
            self.process.stdin.close()
            require(self.process.wait(timeout=30) == 0, "Encoder failed; source retained")
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.errors.close()


def decode(executable, path, ordinal=None):
    args = [] if ordinal is None else ["-ss", f"{ordinal / 20:.6f}"]
    args += ["-i", str(path), "-map", "0:v:0"]
    if ordinal is not None:
        args += ["-frames:v", "1"]
    args += ["-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1"]
    # A temporary stderr file avoids a pipe deadlock while decoding long recordings.
    import tempfile
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([str(executable), "-hide_banner", "-loglevel", "error", *args],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            assert process.stdout is not None
            while True:
                frame = process.stdout.read(FRAME_BYTES)
                if not frame:
                    break
                require(len(frame) == FRAME_BYTES, "Truncated decoded frame")
                yield frame
            require(process.wait(timeout=30) == 0, "Video decode failed")
        finally:
            assert process.stdout is not None
            process.stdout.close()
            if process.poll() is None:
                process.kill()
                process.wait()
