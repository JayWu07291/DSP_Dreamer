import copy
from pathlib import Path
import shutil

import pytest

from dsp_dreamer.contract import InvalidRecording, file_info, load


def test_compatible_actions_preserve_frozen_legal_combinations():
    from itertools import product
    from dsp_dreamer.actions import ACTION_CODEC, forbidden_buttons

    # 凍結版的六組規則；涵蓋所有相關按鍵組合，其他按鍵分別全關／全開。
    pairs = [('W', 'S'), ('A', 'D'), ('LeftControl', 'LeftShift'),
             ('MouseLeft', 'MouseRight'), ('MouseLeft', 'MouseMiddle'), ('MouseRight', 'MouseMiddle')]
    keys = sorted({key for pair in pairs for key in pair})
    for values in product((0, 1), repeat=len(keys)):
        active = {key for key, value in zip(keys, values) if value}
        expected = any(set(pair) <= active for pair in pairs)
        for other in (0, 1):
            binary = [int(key in active) if key in keys else other for key in ACTION_CODEC['controls']]
            assert forbidden_buttons(binary) == expected


def test_frozen_sources_accept_only_reviewed_bytes(tmp_path, monkeypatch):
    from dsp_dreamer.frozen_sources import verify_frozen_implementation, COMPATIBILITY

    compatibility = load(COMPATIBILITY)
    repo = Path(__file__).resolve().parents[1]
    expected = {name: row['frozen'] for name, row in compatibility['files'].items()}
    for name in expected:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, path)
    monkeypatch.chdir(tmp_path)
    source_id = compatibility['source_freeze_id']
    assert verify_frozen_implementation(expected, source_id) == compatibility['artifact_id']
    current = {name: file_info(name) for name in expected}
    assert verify_frozen_implementation(current, 'another-source') is None
    with pytest.raises(InvalidRecording, match='來源'):
        verify_frozen_implementation(expected, 'another-source')
    wrong = copy.deepcopy(expected)
    wrong['dsp_dreamer/actions.py']['sha256'] = '0' * 64
    with pytest.raises(InvalidRecording, match='Frozen implementation changed'):
        verify_frozen_implementation(wrong, source_id)
    extra = Path('other.py')
    extra.write_text('original')
    with_extra = dict(expected, **{str(extra): file_info(extra)})
    extra.write_text('changed')
    with pytest.raises(InvalidRecording, match='other.py'):
        verify_frozen_implementation(with_extra, source_id)
    with Path('dsp_dreamer/actions.py').open('ab') as stream:
        stream.write(b'\n# unreviewed change\n')
    with pytest.raises(InvalidRecording, match='actions.py'):
        verify_frozen_implementation(expected, source_id)
