"""Application-level configuration defaults for the Sidar settings facade."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env, get_int_env
from sidar_version import PRODUCT_VERSION


@dataclass(frozen=True)
class AppRuntimeSettings:
    """Small app/runtime settings group consumed by ``config.Config``."""

    project_name: str
    version: str
    debug_mode: bool
    enable_multi_agent: bool
    max_memory_turns: int
    memory_summary_keep_last: int
    cli_fast_mode: bool
    log_level: str
    response_language: str


def load_app_runtime_settings() -> AppRuntimeSettings:
    """Load application-level runtime settings from environment variables."""
    return AppRuntimeSettings(
        project_name="Sidar",
        version=PRODUCT_VERSION,
        debug_mode=get_bool_env("DEBUG_MODE", False),
        enable_multi_agent=True,
        max_memory_turns=get_int_env("MAX_MEMORY_TURNS", 20),
        memory_summary_keep_last=get_int_env("MEMORY_SUMMARY_KEEP_LAST", 4),
        cli_fast_mode=get_bool_env("CLI_FAST_MODE", False),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        response_language=os.getenv("RESPONSE_LANGUAGE", "tr"),
    )
