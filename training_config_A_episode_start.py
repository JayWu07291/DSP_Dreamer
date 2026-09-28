"""Treatment: replace 1 of 16 sequences with a legal episode-start sequence.

Every other setting comes from the uniform control. Initialize from the SAME
3431-update checkpoint, never from the control arm's result.
"""
from training_config_A_uniform import RUNTIME, TOKENIZER, DYNAMICS, STAGES as BASE_STAGES

STAGES = {**BASE_STAGES, 'A': {**BASE_STAGES['A'], 'episode_start_sequences': 1}}
