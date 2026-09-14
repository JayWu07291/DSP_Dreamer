import importlib.util
from pathlib import Path
import subprocess

import numpy as np
import pytest

from dsp_dreamer import InvalidRecording
from dsp_dreamer.contract import load
from dsp_dreamer.evaluation_protocol import read_protocol, verify_seal
from dsp_dreamer.training_index import TrainingIndex
from test_training_index import FFMPEG, fixture, registry


spec = importlib.util.spec_from_file_location('workbench', Path('tools/export-annotation-workbench.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_png_preserves_native_rgb_and_rejects_wrong_size():
    rgb = np.zeros((360, 640, 3), dtype=np.uint8)
    rgb[0, 0] = [255, 0, 12]
    rgb[-1, -1] = [21, 67, 198]
    result = subprocess.run([str(FFMPEG), '-hide_banner', '-loglevel', 'error', '-i', 'pipe:0',
        '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'], input=module.png_bytes(rgb),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    assert result.stdout == rgb.tobytes()
    with pytest.raises(InvalidRecording):
        module.png_bytes(rgb[:100])


def test_synthetic_evidence_does_not_fill_human_review_queue(tmp_path):
    dataset = fixture(tmp_path)
    index = TrainingIndex([dataset], registry(('trial', 'demonstration')), length=64)
    output = tmp_path / 'workbench'
    packet = module.export_workbench(index, read_protocol('protocols/evaluation-v1.json'), output,
                                    FFMPEG, tmp_path)
    report = load(output / 'export.json')
    verify_seal(report)
    assert report['reconstruction_count'] == report['prediction_review_queue'] == 0
    assert packet['training_authorized'] is False
    assert (output / 'index.html').is_file()
    with pytest.raises(InvalidRecording, match='overwrite'):
        module.export_workbench(index, read_protocol('protocols/evaluation-v1.json'), output, FFMPEG, tmp_path)


def test_video_server_supports_seek_ranges(tmp_path):
    from functools import partial
    from http.client import HTTPConnection
    from http.server import ThreadingHTTPServer
    from threading import Thread

    server_spec = importlib.util.spec_from_file_location('server', Path('tools/serve-annotation-workbench.py'))
    server_module = importlib.util.module_from_spec(server_spec)
    server_spec.loader.exec_module(server_module)
    (tmp_path / 'video.mp4').write_bytes(b'abcdefghij')
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(server_module.Handler, directory=str(tmp_path)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for value, expected in [('bytes=2-5', b'cdef'), ('bytes=-3', b'hij'), ('bytes=7-', b'hij')]:
            client = HTTPConnection(*server.server_address)
            client.request('GET', '/video.mp4', headers={'Range': value})
            response = client.getresponse()
            assert response.status == 206
            assert response.read() == expected
            client.close()
        for value in ['bytes=10-', 'bytes=0-1,3-4', 'invalid', 'bytes=-0']:
            client = HTTPConnection(*server.server_address)
            client.request('GET', '/video.mp4', headers={'Range': value})
            response = client.getresponse()
            assert response.status == 416
            assert response.getheader('Content-Range') == 'bytes */10'
            client.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
