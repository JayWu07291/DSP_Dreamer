# PROTOTYPE: 12 GB three-stage model

This throwaway prototype answers one question: what is the smallest Dreamer 4-inspired model shape that still exercises all three training stages on the target RTX 5070?

It is not the training implementation. It uses synthetic tensors and intentionally omits the real loader, distributed training, checkpoint recovery, evaluation, and production error handling.

## Run

From the repository root:

```powershell
.\prototypes\issue_6_model\run.ps1
```

The first run creates `tmp/issue-6-venv` and installs NumPy plus the official PyTorch 2.9.0 CUDA 12.8 wheel. Later runs reuse it. To isolate one stage, pass `-Stage world_model`, `-Stage agent_finetune`, or `-Stage imagination`.

The script prints the full configuration, loss, trainable parameter count, elapsed time, and peak allocated and reserved CUDA memory. It also writes `measured_rtx5070.json` beside this file.

## Question under test

The prototype keeps these design commitments:

- A causal tokenizer zero-pads each 640×360 RGB observation to 640×384 without shrinking the UI. Spatial cross-attention produces 64 latent tokens, then causal temporal attention mixes history. The bottleneck is 32 channels per latent token.
- Interactive dynamics predicts clean latent representations from corrupted representations, task-blind low-level actions, signal level, and shortcut step size. It has four space-time blocks and a time-attention layer after the fourth spatial layer.
- A task-conditioned agent token reads world tokens through one-way cross-attention. The world tokens never read the task token. Policy and reward heads use MTP distance 8. Agent fine-tuning gives half of each microbatch to uniform dynamics training and half to task-relevant policy and reward training.
- The policy represents 17 binary keyboard and mouse-button controls, one 121-class joint mouse movement, and a three-class wheel action.
- Imagination freezes the tokenizer and dynamics, starts one rollout per dataset context, performs four denoising passes per generated step, and updates only policy and value heads. The smoke test uses horizon 15, `gamma=0.997`, `lambda=0.95`, balanced PMPO signs, and a reverse behavior-prior term weighted by 0.3.

## Starting hypothesis

Use a 512-wide model, 64 latent tokens, context 64, frequent short sequences of 32, occasional long sequences of 80, microbatch 2, and gradient accumulation 8. At 10 Hz, context 64 covers 6.4 seconds. The 80-step batches exceed the context length, which avoids teaching the transformer that every context starts at an episode boundary. This remains shorter than Dreamer 4's 9.6-second Minecraft context, so context length should be the first scale-up test if memory remains.

The smoke test uses BF16, activation checkpointing, and an AdamW update so parameter, gradient, and optimizer-state allocations appear in the peak. Reserve at least 2 GiB below the 12 GiB limit before accepting a configuration because the synthetic batch does not include loader buffers, logging, compilation workspaces, or real loss implementations such as LPIPS.

## Source constraints

Dreamer 4 uses a causal tokenizer, action-conditioned x-prediction dynamics, four shortcut sampling passes, task-conditioned agent tokens with one-way attention, MTP distance 8, and frozen-transformer imagination by default. Its Minecraft run uses 256 latent tokens, context 192, and batch lengths 64 and 256. Those full settings are reference semantics, not plausible local defaults for this project.
