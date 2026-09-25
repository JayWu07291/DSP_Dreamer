"""Append-only progress plus console/traceback capture; no ledger polling."""
from contextlib import redirect_stderr, redirect_stdout, ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import cast, TextIO

from .contract import atomic_save


class TrainingLog:
    def __init__(self, directory, settings):
        self.directory, self.settings = Path(directory), settings

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=False)
        atomic_save(self.directory / 'config.json', self.settings)
        self.started = time.monotonic()
        self.stack = ExitStack()
        self.events = self.stack.enter_context((self.directory / 'events.jsonl').open('x', encoding='utf-8'))
        self.console = self.stack.enter_context((self.directory / 'console.log').open('x', encoding='utf-8'))
        self.stdout, self.stderr = sys.stdout, sys.stderr
        self.stack.enter_context(redirect_stdout(cast(TextIO, self)))
        self.stack.enter_context(redirect_stderr(cast(TextIO, self)))
        print(f'Training logs: {self.directory.resolve()}', flush=True)
        self.emit('started', config=str(self.directory / 'config.json'))
        return self

    def write(self, text):
        self.stdout.write(text)
        self.console.write(text)
        self.console.flush()
        return len(text)

    def flush(self):
        self.stdout.flush()
        self.console.flush()

    def emit(self, event, **values):
        row = dict(timestamp=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic() - self.started,
                   event=event, **values)
        self.events.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        self.events.flush()
        detail = {k: v for k, v in values.items() if k in ('stage', 'step', 'loss', 'total', 'mse', 'lpips',
                  'learning_rate', 'learning_rates', 'seconds', 'path', 'status', 'planned_updates', 'error')}
        print(f"[{row['timestamp']}] {event} {json.dumps(detail, ensure_ascii=False)}", flush=True)
        os.fsync(self.events.fileno())
        os.fsync(self.console.fileno())

    def __exit__(self, kind, error, tb):
        try:
            if kind is not None:
                traceback.print_exception(kind, error, tb)
            self.emit('failed' if error is not None else 'finished', error=str(error) if error else None)
            atomic_save(self.directory / 'status.json', dict(status='failed' if error is not None else 'finished',
                error=str(error) if error else None, elapsed_seconds=time.monotonic() - self.started))
        finally:
            self.stack.close()
