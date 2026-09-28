"""Uniform control: 100 additional updates from the 3431-update checkpoint.

Shared recipe for the episode-start comparison. Keep it unchanged between arms.
Run commands and initialization path: docs/research/A-episode-start-comparison.md.
"""
from training_config_A_next import RUNTIME, TOKENIZER, DYNAMICS, STAGES as BASE_STAGES

STAGES = {**BASE_STAGES, 'A': {**BASE_STAGES['A'],
    'updates': 100, 'max_seconds': None, 'seed': 20260928,
    'warmup_fraction': .1,  # Keep 10 warmup steps in this short comparison.
    'episode_start_sequences': 0,
}}
