import json
import subprocess
import sys

from dsp_dreamer.training_index import TrainingIndex
from test_training_index import fixture, registry


def test_metadata_diagnosis_explains_short_and_non_active_completions_without_rgb(tmp_path):
    path = fixture(tmp_path, gap=True)
    index = TrainingIndex([path], registry(("trial", "demonstration")), length=4)
    index_path, report_path = tmp_path / "index.json", tmp_path / "diagnosis.json"
    index.save(index_path)
    # The diagnostic must work without reading media, using the previously sealed index.
    (path / "observations.zarr").rename(path / "media-not-opened")
    command = [sys.executable, "tools/diagnose-task-coverage.py", "--source", str(path),
               "--index", str(index_path), "--report", str(report_path)]
    subprocess.run(command, check=True)
    report = json.loads(report_path.read_text())
    tasks = {r['task_id']: r for r in report['episodes'][0]['tasks']}
    assert tasks[0]['reason'] == 'short_valid_run'
    assert tasks[0]['valid_run_steps'] == 3
    assert tasks[0]['barriers'][0]['gap']
    assert tasks[1]['reason'] == 'non_active_completion'
    assert tasks[2]['reason'] == 'not_completed'
    assert report['rgb_opened'] is False and report['training_authorized'] is False
    assert not any(report['positive_episode_counts'])
    # A second, sealed index with a shorter fixture sequence includes the same reward.
    # Recreate it with the ordinary loader while media is present.
    (path / "media-not-opened").rename(path / "observations.zarr")
    short = TrainingIndex([path], registry(("trial", "demonstration")), length=2)
    short_path = tmp_path / "short-index.json"
    short.save(short_path)
    subprocess.run([*command[:4], '--index', str(short_path), '--report', str(tmp_path / 'short.json')], check=True)
    assert json.loads((tmp_path / 'short.json').read_text())['positive_episode_counts'][0] == 1
    # Reject a changed input table before producing a diagnostic.
    with (path / 'transitions.parquet').open('ab') as output:
        output.write(b'changed')
    result = subprocess.run([*command[:-1], str(tmp_path / 'tampered.json')], capture_output=True, text=True)
    assert result.returncode != 0 and 'checksum mismatch' in result.stderr
    assert not (tmp_path / 'tampered.json').exists()
