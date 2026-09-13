"""Check that failed storage sampling cannot publish a successful replay report."""
from pathlib import Path
import runpy
import sys
import time
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import dsp_dreamer
script = Path(__file__).with_name('issue-21-merge-replay-publish.py')
# Run after the recorded measurement: the existing samples must refuse a repeat
# before the real publisher can run.
with patch.object(dsp_dreamer, 'publish') as publish:
    try:
        runpy.run_path(str(script))
        raise AssertionError('Existing samples accepted')
    except FileExistsError:
        pass
    publish.assert_not_called()

class FailedStream:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def write(self, value): raise OSError('injected storage failure')

original_open = Path.open
def open_sample(path, mode='r', *args, **kwargs):
    if path.name == 'owned-storage.ndjson' and mode == 'x': return FailedStream()
    return original_open(path, mode, *args, **kwargs)

with patch.object(Path, 'open', open_sample), patch.object(dsp_dreamer, 'publish', side_effect=lambda *a, **k: time.sleep(.05)):
    try:
        runpy.run_path(str(script))
        raise AssertionError('Failed sampler accepted')
    except RuntimeError as error:
        assert 'Storage sampling failed' in str(error)
        assert isinstance(error.__cause__, OSError)
print('Existing-sample refusal and background failure propagation passed')
