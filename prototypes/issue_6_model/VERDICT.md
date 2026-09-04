# Prototype verdict for review

The smallest configuration I would carry into the executable specification is:

| Part | Proposed setting |
| --- | --- |
| Input | 640×360 RGB, zero-padded to 640×384 |
| Tokenizer | 16×16 patches, 64 latent tokens, 32 bottleneck channels, 512 model width, 4 causal temporal layers |
| Dynamics | 8 blocks at width 512, 8 attention heads, 8 registers, temporal attention every fourth block |
| Context | 64 steps at 10 Hz, or 6.4 seconds |
| Training batches | 32 steps normally, 80 steps periodically; microbatch 2; accumulate 8 for effective batch 16 |
| Shortcut forcing | x-prediction, minimum step 1/4, bootstrap step 1/2, 4 inference passes, past-context signal level 0.1 in the real implementation |
| Agent heads | 17-way task embedding; one-way agent cross-attention; MTP distance 8; 17 binary controls, 121-way mouse, 3-way wheel, symexp twohot reward |
| Agent data mix | 50% uniform for dynamics loss, 50% task-relevant for policy and reward loss |
| Imagination | One rollout per context, fixed task within a rollout, horizon 15, frozen tokenizer and dynamics, `gamma=0.997`, `lambda=0.95`, PMPO `alpha=0.5`, reverse-KL `beta=0.3` |

Why this shape: the first 47.6 million-parameter run left enough memory to retain full UI resolution and double the latent count. Shrinking the UI image would trade away task information before memory requires it. The final 80-step run is the acceptance measurement because it covers the occasional batch longer than the 64-step context.

This prototype does not answer whether 64 latent tokens reconstruct DSP's smallest icons well enough. Before full training, run a tokenizer-only reconstruction check on real recordings and compare 64 against 96 latent tokens. It also fixes one task for each imagined rollout. Dreamer 4 does not document task switching inside imagination, so changing tasks mid-rollout should remain an ablation rather than the default.

The production budget should keep peak reserved CUDA memory under 10 GiB. The remaining 2 GiB covers LPIPS, real input buffers, CUDA compilation workspaces, metrics, and allocator variation.
