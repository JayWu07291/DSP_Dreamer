import json
from pathlib import Path

import numpy as np
import pytest

from dsp_dreamer import Recording, compile_recording, open_dataset, InvalidRecording
from dsp_dreamer.contract import file_info

FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


@pytest.mark.parametrize("source_catalog", ["action_catalog_v2", "action_catalog_v3"])
def test_space_and_inventory_recompile_without_changing_old_indices(tmp_path, source_catalog):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata["catalog"] = source_catalog
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        recording.input(50, held=["Space", "E", "Digit1"], down=["Space", "E", "Digit1"], up=[], delta=[0, 0], wheel=0)
        recording.input(100, held=[], down=[], up=["Space", "E", "Digit1"], delta=[0, 0], wheel=0)
        for ticks in (50, 100):
            request = recording.request(ticks, 1, 1)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.end_episode(125, "timeout")
        request = recording.request(150, 1, 1)
        recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(tmp_path / "evidence")
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert dataset.metadata["catalog"] == "action_catalog_v3"
    assert dataset.metadata["source_catalog"] == source_catalog
    assert dataset[0]["valid"] and not dataset[0]["action"]["unsupported"]
    buttons = dataset[0]["action"]["binary"]
    assert len(buttons) == 20 and [i for i, value in enumerate(buttons) if value] == [1, 18, 19]
    assert dataset[-1]["bootstrap_mask"] == 1
    path = tmp_path / "dataset" / "dataset.json"
    path.write_text(json.dumps(dict(dataset.metadata, catalog="action_catalog_v2")))
    marker_path = tmp_path / "dataset" / "COMPLETED"
    marker = json.loads(marker_path.read_text())
    marker["files"]["dataset.json"] = file_info(path)
    marker_path.write_text(json.dumps(marker))
    with pytest.raises(InvalidRecording, match="Recompile"):
        open_dataset(tmp_path / "dataset")


def test_diagnostic_recording_is_readable_but_not_trainable(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata["diagnostic_mode"] = True
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks in (50, 100):
            request = recording.request(ticks, 1, 1)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
    evidence = recording.publish(tmp_path / "evidence")
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert dataset.metadata["diagnostic_mode"] is True
    assert not dataset[0]["valid"] and dataset.sequence_starts(1) == []
