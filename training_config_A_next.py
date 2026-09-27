"""A continuation after 431 + 2000 updates; inspect with --config before running.

Uses all current shared/model settings from training_config.py. This is an
additional 1000-update experiment from final-2000.pt, not a fresh model.
"""
from training_config import RUNTIME, TOKENIZER, DYNAMICS, STAGES as BASE_STAGES

STAGES = {**BASE_STAGES, 'A': {**BASE_STAGES['A'],
    'updates': 1000, 'max_seconds': None, 'seed': 20260927,
    'learning_rate': 2e-5, 'warmup_fraction': .01, 'min_lr_fraction': .5,
}}
