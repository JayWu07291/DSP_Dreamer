"""Edit this file before starting a NEW run. tools/train.py A show-config prints resolved values.

Changing a running/resumed run is rejected. Use `A run --restart` for fresh weights/budget.
All times are seconds. Evaluation sample lists and quality gates remain frozen.
"""

RUNTIME = dict(
    verify_rgb=False,             # Immutable data/datasets: skip RGB hashes/decompression.
    preflight_seconds=7200,
    validation_seconds=1800,
    validation_updates=50,         # Whichever comes first; 0 disables the update interval.
    update_fraction=.9,            # Time reserved for optimization after benchmark.
    num_threads=4,
)

OPTIMIZER = dict(weight_decay=.01, beta1=.9, beta2=.999, epsilon=1e-8,
                 grad_clip=1., warmup_fraction=.05, min_lr_fraction=.1)
SEQUENCES = dict(microbatch=2, accumulation=8, short_length=32, long_length=80, long_every=4)

# Architecture fields are displayed and validated; the frozen v1 downstream contract is 64 tokens.
TOKENIZER = dict(latent_tokens=64, bottleneck=32, width=512, heads=8, temporal_layers=4,
                 patch_size=20, context=64, activation_checkpointing=True)
DYNAMICS = dict(width=512, heads=8, blocks=8, registers=8, temporal_every=4, context=64,
                latent_tokens=64, bottleneck=32, activation_checkpointing=True)

STAGES = {
    'A': dict(**OPTIMIZER, **SEQUENCES, seed=2202, learning_rate=1e-4, max_seconds=14400,
              mask_max_probability=0., mse_weight=1., lpips_weight=.2, updates=None),
    'B': dict(**OPTIMIZER, **SEQUENCES, seed=2203, learning_rate=1e-4, max_seconds=57600,
              flow_weight=1., bootstrap_weight=1., updates=None),
    'second': dict(**OPTIMIZER, **SEQUENCES, seed=2203, learning_rate=1e-4, world_learning_rate=1e-5,
                   max_seconds=21600, flow_weight=1., bootstrap_weight=1.,
                   dynamics_weight=1., policy_weight=1., reward_weight=1., updates=None),
    'third': dict(**OPTIMIZER, **SEQUENCES, seed=2203, learning_rate=1e-4, policy_learning_rate=3e-5,
                  max_seconds=14400, horizon=15, gamma=.997, lambda_=.95, alpha=.5,
                  kl_weight=.3, value_weight=1., updates=None),
}
# updates=None uses measured throughput and max_seconds; an integer only lowers that limit.
# A retry changes only masking: 0 instead of .9, to first learn unmasked reconstruction.
# This is an experiment, not a proven fix. Revisit masking after inspecting the next outputs.
