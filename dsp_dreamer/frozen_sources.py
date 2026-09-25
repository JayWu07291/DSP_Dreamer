"""核對凍結來源實作，僅接受另存且逐檔核對的相容版本。"""
from pathlib import Path

from .contract import file_info, load, require
from .evaluation_protocol import verify_seal


COMPATIBILITY = Path(__file__).resolve().parents[1] / 'protocols/source-compatibility-issue31.json'


def verify_frozen_implementation(files, source_freeze_id):
    changed = {name: (expected, file_info(name)) for name, expected in files.items()
               if file_info(name) != expected}
    if not changed:
        return None
    compatibility = load(COMPATIBILITY)
    verify_seal(compatibility)
    require(compatibility['schema'] == 'dsp-source-compatibility/1'
            and compatibility['source_freeze_id'] == source_freeze_id, '相容性紀錄不適用此凍結來源')
    for name, (expected, actual) in changed.items():
        accepted = compatibility['files'].get(name, {})
        require(accepted.get('frozen') == expected and accepted.get('compatible') == actual,
                f'Frozen implementation changed: {name}')
    return compatibility['artifact_id']
