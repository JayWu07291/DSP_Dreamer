import pytest
import random
import numpy as np

torch = pytest.importorskip('torch')

from dsp_dreamer.tokenizer import CausalTokenizer, TokenizerConfig


def test_native_reconstruction_is_causal_and_differentiable():
    torch.set_num_threads(2)
    torch.manual_seed(24)
    model = CausalTokenizer(TokenizerConfig(width=32, heads=4)).eval()
    frames = torch.rand(1, 3, 3, 360, 640)
    with torch.no_grad():
        latents, reconstruction = model(frames)
        changed = frames.clone()
        changed[:, 2] = 0
        other_latents, other = model(changed)
        changed = frames.clone()
        changed[:, 0] = 0
        _, changed_history = model(changed)
    assert latents.shape == (1, 3, 64, 32)
    assert reconstruction.shape == frames.shape
    torch.testing.assert_close(latents[:, :2], other_latents[:, :2], rtol=0, atol=0)
    torch.testing.assert_close(reconstruction[:, :2], other[:, :2], rtol=0, atol=0)
    assert not torch.equal(reconstruction[:, 2], other[:, 2])
    assert not torch.equal(reconstruction[:, 2], changed_history[:, 2])
    model.train()
    _, masked = model(frames, generator=torch.Generator().manual_seed(2202))
    masked.square().mean().backward()
    assert model.patch_embed.weight.grad.abs().sum() > 0
    assert model.mask_token.grad.abs().sum() > 0


def test_loader_update_resume_repeats_next_update(tmp_path):
    from test_training_index import fixture, registry
    from dsp_dreamer.training_index import TrainingIndex
    from dsp_dreamer.tokenizer_training import TokenizerTrainer, TrainingConfig, ReconstructionLoss
    from dsp_dreamer.contract import InvalidRecording

    path = fixture(tmp_path / "source", group="train")
    index = TrainingIndex([path], registry(("train", "demonstration")), length=2)
    metric = ReconstructionLoss("data/torch-cache")
    trainer = TokenizerTrainer(index, metric, TokenizerConfig(width=32, heads=4),
        TrainingConfig(updates=4, microbatch=1, accumulation=1, short_length=2, long_length=2), device="cpu")
    first = trainer.update()
    assert first['mse'] > 0 and first['lpips'] > 0 and first['samples']
    checkpoint = tmp_path / "step1.pt"
    random.random()
    np.random.random()
    torch.rand(3)
    trainer.save(checkpoint)
    expected_rng = (random.random(), np.random.random(), torch.rand(3).tolist())
    expected = trainer.update()
    restored = TokenizerTrainer.restore(checkpoint, index, metric, device="cpu")
    assert (random.random(), np.random.random(), torch.rand(3).tolist()) == expected_rng
    actual = restored.update()
    assert actual == expected
    for key, tensor in trainer.model.state_dict().items():
        torch.testing.assert_close(tensor, restored.model.state_dict()[key], rtol=0, atol=0)
    with checkpoint.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(InvalidRecording, match='checksum'):
        TokenizerTrainer.restore(checkpoint, index, metric, device="cpu")


def test_reconstruction_gate_keeps_missing_reviews_in_denominator():
    from dsp_dreamer.evaluation_protocol import seal, ITEM_TYPES
    from dsp_dreamer.tokenizer_evaluation import score_reconstruction

    selected = [dict(artifact_id='source', observation_index=i, model_index=i, capture_id=i,
                     task_id=i % 17) for i in range(200)]
    inputs = seal(dict(reconstruction=dict(selected=selected)))
    annotations = seal(dict(items=[dict(sample_id=str(i), artifact_id='source', observation_index=i,
        type=kind, eligible=True) for i, kind in enumerate(ITEM_TYPES)],
        ui_regions=[dict(ui_type=kind) for kind in ('technology', 'backpack', 'crafting', 'building', 'lab')]))
    metrics = seal(dict(evaluation_inputs_id=inputs['artifact_id'], annotations_id=annotations['artifact_id'],
        checkpoint_sha256='abc', frames=[dict(sample=row, mse=.2, lpips=.3, ui_mse=.1, ui_pixels=10)
                                       for row in selected]))
    result = score_reconstruction(metrics, inputs, annotations)
    assert result['status'] == 'pending'
    assert result['recognition']['total'] == 4 and result['recognition']['pending'] == 4
    judgments = dict(report_id=metrics['artifact_id'], annotations_id=annotations['artifact_id'],
        checkpoint_sha256='abc', items=[dict(sample_id=str(i), correct=True, reviewer='human', evidence='review')
                                      for i in range(4)])
    assert score_reconstruction(metrics, inputs, annotations, judgments)['status'] == 'passed'
    first_id = score_reconstruction(metrics, inputs, annotations, judgments)['artifact_id']
    judgments['items'][0]['evidence'] = 'a different reviewed image'
    assert score_reconstruction(metrics, inputs, annotations, judgments)['artifact_id'] != first_id
    judgments['items'][0]['correct'] = False
    assert score_reconstruction(metrics, inputs, annotations, judgments)['status'] == 'failed'
    judgments['items'][0]['correct'] = None
    assert score_reconstruction(metrics, inputs, annotations, judgments)['status'] == 'pending'
    missing = seal({**{k: v for k, v in annotations.items() if k != 'artifact_id'}, 'items': annotations['items'][1:]})
    changed_metrics = seal({**{k: v for k, v in metrics.items() if k != 'artifact_id'}, 'annotations_id': missing['artifact_id']})
    assert score_reconstruction(changed_metrics, inputs, missing)['status'] == 'insufficient_evidence'
