"""從正式編譯資料讀回控制證據；完整實機核對通過才發布校正。"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsp_dreamer import open_dataset
from dsp_dreamer.contract import atomic_save
from dsp_dreamer.control import inspect_control, publish_calibration
from dsp_dreamer.diagnostics import inspect_diagnostic

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dataset", required=True)
parser.add_argument("--out", required=True)
mode = parser.add_mutually_exclusive_group()
mode.add_argument("--calibration", action="store_true")
mode.add_argument("--diagnostic", help="獨立觀察元件的 .diagnostic.ndjson 路徑")
args = parser.parse_args()
dataset = open_dataset(args.dataset)
if args.diagnostic:
    result = inspect_diagnostic(dataset, args.diagnostic)
    atomic_save(args.out, result)
elif args.calibration:
    result = publish_calibration(dataset, args.out)
else:
    result = inspect_control(dataset)
    atomic_save(args.out, result)
print(json.dumps(dict(gate_passed=result["gate_passed"], output=args.out), ensure_ascii=False))
