"""100 completed B updates with an unqualified, frozen A tokenizer.

Use tools/train.py B run --exploratory. This is not a formal B qualification.
Source and commands: docs/research/B-exploratory.md.
"""
from training_config import RUNTIME, TOKENIZER, DYNAMICS, STAGES as BASE_STAGES

STAGES = {**BASE_STAGES, 'B': {**BASE_STAGES['B'],
    'updates': 100, 'max_seconds': None, 'seed': 20260928,
    'warmup_fraction': .1,
}}
