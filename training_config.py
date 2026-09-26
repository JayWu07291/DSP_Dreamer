"""Edit this file before starting a NEW run. tools/train.py A show-config prints resolved values.

Changing a running/resumed run is rejected. Use `A run --restart --init-from PATH`
for a new experiment from learned weights, or omit --init-from for fresh weights.
Times are seconds; A max_seconds=None uses completed updates only. Gates remain frozen.
"""

RUNTIME = dict(
    verify_rgb=False,             # Immutable data/datasets: skip RGB hashes/decompression.
    preflight_seconds=7200,
    validation_seconds=1800,
    validation_updates=50,         # Whichever comes first; 0 disables the update interval.
    update_fraction=.9,            # Time reserved for optimization after benchmark.
    num_threads=4,
    cuda_memory_fraction=.75,      # ~9 GiB allocator cap on 12 GiB; leave room for Windows/CUDA.
)

OPTIMIZER = dict(weight_decay=.01, beta1=.9, beta2=.99, epsilon=1e-8,
                 grad_clip=1., warmup_fraction=.05, min_lr_fraction=.1)
SEQUENCES = dict(microbatch=2, accumulation=8, short_length=32, long_length=80, long_every=4)

# Small Dreamer 4 topology; widths/depths are project choices for RTX 5070 12GB.
# Each group is THREE spatial blocks and ONE causal temporal block.
TOKENIZER = dict(architecture='dsp-block-causal/2', latent_tokens=64, bottleneck=32, width=640,
                 heads=10, encoder_blocks=12, decoder_blocks=12, temporal_every=4, patch_size=20,
                 context=32, attention_softcap=30., attention_chunk_size=8, activation_checkpointing=True)
DYNAMICS = dict(architecture='dsp-block-causal/2', width=1280, heads=20, kv_heads=4, blocks=16,
                registers=8, temporal_every=4, context=64, latent_tokens=64, bottleneck=32,
                attention_softcap=30., attention_chunk_size=16, activation_checkpointing=True)
LOSS_RMS = dict(loss_rms_decay=.99, loss_rms_epsilon=1e-8)

STAGES = {
    'A': dict(**{**OPTIMIZER, 'warmup_fraction': .01, 'min_lr_fraction': 1/3},
              **{**SEQUENCES, 'short_length': 16, 'long_length': 48}, **LOSS_RMS,
              seed=2202, learning_rate=3e-5, max_seconds=None,
              mask_max_probability=.9, mse_weight=1., lpips_weight=.2, updates=2000),
    'B': dict(**OPTIMIZER, **SEQUENCES, **LOSS_RMS, seed=2203, learning_rate=1e-4, max_seconds=57600,
              flow_weight=1., bootstrap_weight=1., updates=None),
    'second': dict(**OPTIMIZER, **SEQUENCES, **LOSS_RMS, seed=2203, learning_rate=1e-4, world_learning_rate=1e-5,
                   max_seconds=21600, flow_weight=1., bootstrap_weight=1.,
                   dynamics_weight=1., policy_weight=1., reward_weight=1., updates=None),
    'third': dict(**OPTIMIZER, **SEQUENCES, seed=2203, learning_rate=1e-4, policy_learning_rate=3e-5,
                  max_seconds=14400, horizon=15, gamma=.997, lambda_=.95, alpha=.5,
                  kl_weight=.3, value_weight=1., updates=None),
}
# A: 2000 ADDITIONAL completed updates when initialized from a trained checkpoint.
# Optional positive max_seconds also stops on time; updates=None needs a time limit.
# Other stages retain their original time budgets. Old shallow checkpoints are incompatible.
# Paper masking and loss normalization are enabled. LR, EMA and model sizes are our
# starting recipe, not unpublished official hyperparameters or a convergence guarantee.
