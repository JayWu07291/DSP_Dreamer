"""Regression: run the actual worker with invalid Windows console handles."""
import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import traceback

parser = argparse.ArgumentParser()
parser.add_argument('--run', type=Path, required=True)
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--child', action='store_true')
parser.add_argument('--all-handles', action='store_true')
args = parser.parse_args()
if args.child:
    import auto_finalize
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.SetStdHandle.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    # GUI/Mono can leave inherited console handles unusable. Python's own
    # streams go to a diagnostic file, but child launch must not inherit these.
    with args.report.with_suffix('.log').open('w', encoding='utf-8') as log:
        sys.stdout = sys.stderr = log
        for handle in ((-10, -11, -12) if args.all_handles else (-11,)):
            if not kernel.SetStdHandle(handle & 0xffffffff, ctypes.c_void_p(-1)):
                raise ctypes.WinError(ctypes.get_last_error())
        try:
            sys.argv = ['auto_finalize.py', '--run', str(args.run)]
            auto_finalize.main()
            args.report.write_text(json.dumps({'pass': True, 'files': sorted(p.name for p in args.run.iterdir())}))
        except Exception:
            args.report.write_text(json.dumps({'pass': False, 'error': traceback.format_exc()}))
            sys.exit(1)
else:
    result = subprocess.run([sys.executable, __file__, '--child', '--run', str(args.run),
                             '--report', str(args.report)] + (['--all-handles'] if args.all_handles else []), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(args.report.read_text())
    sys.exit(result.returncode)
