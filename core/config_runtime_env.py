from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def safe_choice_for_reload(value: object, default: str, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def apply_runtime_env_overrides(
    config_cls: Any,
    *,
    base_dir: Path,
    get_int_env: Any,
    get_database_url: Any,
    get_container_database_url: Any,
    normalize_ai_provider: Any,
) -> None:
    """Apply reload-time environment overrides onto Config class attributes."""
    config_cls.AI_PROVIDER = normalize_ai_provider(os.getenv("AI_PROVIDER", config_cls.AI_PROVIDER))
    config_cls.ACCESS_LEVEL = safe_choice_for_reload(
        os.getenv("ACCESS_LEVEL", config_cls.ACCESS_LEVEL),
        config_cls.ACCESS_LEVEL,
        {"restricted", "sandbox", "full"},
    )
    config_cls.WEB_HOST = os.getenv("WEB_HOST", str(config_cls.WEB_HOST))
    config_cls.WEB_PORT = get_int_env("WEB_PORT", int(config_cls.WEB_PORT))
    config_cls.CODING_MODEL = os.getenv("CODING_MODEL", str(config_cls.CODING_MODEL))
    config_cls.TEXT_MODEL = os.getenv("TEXT_MODEL", str(config_cls.TEXT_MODEL))
    config_cls.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", str(config_cls.GEMINI_API_KEY or ""))
    config_cls.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", str(config_cls.OPENAI_API_KEY or ""))
    config_cls.ANTHROPIC_API_KEY = os.getenv(
        "ANTHROPIC_API_KEY", str(config_cls.ANTHROPIC_API_KEY or "")
    )
    config_cls.API_KEY = os.getenv("API_KEY", str(config_cls.API_KEY or ""))
    config_cls.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", str(config_cls.JWT_SECRET_KEY or ""))
    config_cls.SIDAR_SKIP_DEFAULT_DOTENV = os.getenv(
        "SIDAR_SKIP_DEFAULT_DOTENV", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    config_cls.SIDAR_KEYS_FILE = os.getenv("SIDAR_KEYS_FILE", str(config_cls.SIDAR_KEYS_FILE or ""))
    config_cls.DATABASE_URL = get_database_url()
    config_cls.CONTAINER_DATABASE_URL = get_container_database_url()
