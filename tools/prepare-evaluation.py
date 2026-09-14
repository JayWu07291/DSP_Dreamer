"""Rebuild a fixed evaluation input packet from verified datasets."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dsp_dreamer.contract import atomic_save, load
from dsp_dreamer.evaluation_protocol import prepare_evaluation, read_protocol, validate_trials
from dsp_dreamer.training_index import TrainingIndex


def main():
    parser = argparse.ArgumentParser(description='依凍結協定產生評估名單與待驗證缺口；不執行模型或人工判讀')
    parser.add_argument('--source', nargs='+', type=Path, required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, default=Path('protocols/evaluation-v1.json'))
    parser.add_argument('--candidates', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    protocol = read_protocol(args.protocol)
    registry = load(args.registry)
    index = TrainingIndex(args.source, registry, length=64)
    validate_trials(load(args.protocol.parent / 'evaluation-trials-v1.json'), registry,
                    [v.dataset.metadata['trial_manifest'] for v in index.views.values()], expected_id=protocol['trials_id'])
    packet = prepare_evaluation(index, protocol, load(args.candidates) if args.candidates else None)
    atomic_save(args.out, packet)
    print(json.dumps(dict(artifact_id=packet['artifact_id'], status=packet['status'],
                          training_authorized=packet['training_authorized'], out=str(args.out))))


if __name__ == '__main__':
    main()
