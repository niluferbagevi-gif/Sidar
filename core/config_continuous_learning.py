"""Continuous-learning bundle settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env, get_int_env


@dataclass(frozen=True)
class ContinuousLearningSettings:
    """Judge/feedback-signal continuous-learning bundle generation settings."""

    enable_continuous_learning: bool
    continuous_learning_min_sft_examples: int
    continuous_learning_min_preference_examples: int
    continuous_learning_max_pending_signals: int
    continuous_learning_cooldown_seconds: int
    continuous_learning_output_dir: str
    continuous_learning_sft_format: str


def load_continuous_learning_settings() -> ContinuousLearningSettings:
    """Load continuous-learning bundle settings from environment variables."""
    return ContinuousLearningSettings(
        enable_continuous_learning=get_bool_env("ENABLE_CONTINUOUS_LEARNING", False),
        continuous_learning_min_sft_examples=get_int_env(
            "CONTINUOUS_LEARNING_MIN_SFT_EXAMPLES", 20
        ),
        continuous_learning_min_preference_examples=get_int_env(
            "CONTINUOUS_LEARNING_MIN_PREFERENCE_EXAMPLES", 10
        ),
        continuous_learning_max_pending_signals=get_int_env(
            "CONTINUOUS_LEARNING_MAX_PENDING_SIGNALS", 5000
        ),
        continuous_learning_cooldown_seconds=get_int_env(
            "CONTINUOUS_LEARNING_COOLDOWN_SECONDS", 3600
        ),
        continuous_learning_output_dir=os.getenv(
            "CONTINUOUS_LEARNING_OUTPUT_DIR", "data/continuous_learning"
        ),
        continuous_learning_sft_format=os.getenv("CONTINUOUS_LEARNING_SFT_FORMAT", "alpaca"),
    )
