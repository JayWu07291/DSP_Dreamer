from dataclasses import dataclass


@dataclass(frozen=True)
class PrototypeConfig:
    """PROTOTYPE ONLY. Small enough to test the three training stages on 12 GB."""

    observation_height: int = 360
    observation_width: int = 640
    model_height: int = 384
    model_width: int = 640
    patch_size: int = 16

    model_dim: int = 512
    latent_tokens: int = 64
    latent_dim: int = 32
    register_tokens: int = 8
    attention_heads: int = 8
    tokenizer_temporal_layers: int = 4
    dynamics_layers: int = 8

    context_steps: int = 64
    short_train_steps: int = 32
    train_steps: int = 80
    batch_size: int = 2
    gradient_accumulation: int = 8
    mtp_distance: int = 8
    imagination_horizon: int = 15
    shortcut_steps: int = 4

    task_count: int = 17
    keyboard_buttons: int = 17
    mouse_classes: int = 121
    wheel_classes: int = 3
    twohot_bins: int = 255

    @property
    def patch_count(self) -> int:
        return (self.model_height // self.patch_size) * (
            self.model_width // self.patch_size
        )
