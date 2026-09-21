"""LoRA/QLoRA fine-tuning settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env, get_float_env, get_int_env


@dataclass(frozen=True)
class LoraTrainingSettings:
    """LoRA/QLoRA fine-tuning hyperparameters and output settings."""

    enable_lora_training: bool
    lora_base_model: str
    lora_rank: int
    lora_alpha: int
    lora_dropout: float
    lora_epochs: int
    lora_batch_size: int
    lora_use_4bit: bool
    lora_output_dir: str


def load_lora_training_settings() -> LoraTrainingSettings:
    """Load LoRA/QLoRA fine-tuning settings from environment variables."""
    return LoraTrainingSettings(
        enable_lora_training=get_bool_env("ENABLE_LORA_TRAINING", False),
        lora_base_model=os.getenv("LORA_BASE_MODEL", ""),
        lora_rank=get_int_env("LORA_RANK", 8),
        lora_alpha=get_int_env("LORA_ALPHA", 16),
        lora_dropout=get_float_env("LORA_DROPOUT", 0.05),
        lora_epochs=get_int_env("LORA_EPOCHS", 3),
        lora_batch_size=get_int_env("LORA_BATCH_SIZE", 4),
        lora_use_4bit=get_bool_env("LORA_USE_4BIT", True),
        lora_output_dir=os.getenv("LORA_OUTPUT_DIR", "data/lora_adapters"),
    )
