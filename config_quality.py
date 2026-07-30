"""DLP/HITL/LLM-judge quality-gate configuration for Sidar."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import AliasChoices, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class QualityGateSettings(BaseSettings):
    """DLP/HITL/LLM-judge ortam değişkenlerini tip güvenli şekilde yükler."""

    model_config = SettingsConfigDict(env_file=None, env_file_encoding="utf-8", extra="ignore")

    DLP_ENABLED: bool = True
    HITL_ENABLED: bool = True
    HITL_TIMEOUT_SECONDS: int = 120

    JUDGE_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices("SIDAR_JUDGE_ENABLED", "JUDGE_ENABLED"),
    )
    JUDGE_MODEL: str = Field(
        default="",
        validation_alias=AliasChoices("SIDAR_JUDGE_MODEL", "JUDGE_MODEL"),
    )
    JUDGE_PROVIDER: str = Field(
        default="ollama",
        validation_alias=AliasChoices("SIDAR_JUDGE_PROVIDER", "JUDGE_PROVIDER"),
    )
    JUDGE_SAMPLE_RATE: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices("SIDAR_JUDGE_SAMPLE_RATE", "JUDGE_SAMPLE_RATE"),
    )
    JUDGE_AUTO_FEEDBACK_ENABLED: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SIDAR_JUDGE_AUTO_FEEDBACK_ENABLED", "JUDGE_AUTO_FEEDBACK_ENABLED"
        ),
    )
    JUDGE_AUTO_FEEDBACK_THRESHOLD: float = Field(
        default=8.0,
        ge=0.0,
        le=10.0,
        validation_alias=AliasChoices(
            "SIDAR_JUDGE_AUTO_FEEDBACK_THRESHOLD", "JUDGE_AUTO_FEEDBACK_THRESHOLD"
        ),
    )
    JUDGE_RESPONSE_MODEL: str = Field(
        default="",
        validation_alias=AliasChoices("SIDAR_JUDGE_RESPONSE_MODEL", "JUDGE_RESPONSE_MODEL"),
    )

    @field_validator("JUDGE_MODEL", "JUDGE_PROVIDER", "JUDGE_RESPONSE_MODEL", mode="before")
    @classmethod
    def use_non_blank_legacy_string(cls, value: object, info: ValidationInfo) -> object:
        """Let a legacy judge string win when its preferred alias is blank."""
        if not isinstance(value, str) or value.strip():
            return value

        legacy_key = info.field_name
        if legacy_key is None:
            return value
        legacy_value = os.getenv(legacy_key)
        return legacy_value if legacy_value is not None and legacy_value.strip() else value


def load_quality_gate_settings(*, env_path: Path, skip_default_dotenv: bool) -> QualityGateSettings:
    """Load quality-gate settings with the same dotenv precedence as the config facade."""
    env_file = str(env_path) if env_path.exists() and not skip_default_dotenv else None
    if env_file is None:
        return QualityGateSettings()

    scoped_settings_type: type[QualityGateSettings] = type(
        "ScopedQualityGateSettings",
        (QualityGateSettings,),
        {
            "__module__": __name__,
            "model_config": SettingsConfigDict(
                env_file=env_file, env_file_encoding="utf-8", extra="ignore"
            ),
        },
    )
    return scoped_settings_type()
