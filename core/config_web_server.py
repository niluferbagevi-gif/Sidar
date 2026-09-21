"""Web server bind host/port settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_int_env


@dataclass(frozen=True)
class WebServerSettings:
    """Web arayüzü (``web_server.py``/``main.py``) bind host/port settings."""

    web_host: str
    web_port: int
    web_gpu_port: int


def load_web_server_settings() -> WebServerSettings:
    """Load web server bind host/port settings from environment variables."""
    return WebServerSettings(
        web_host=os.getenv("WEB_HOST", "127.0.0.1"),
        web_port=get_int_env("WEB_PORT", 7860),
        web_gpu_port=get_int_env("WEB_GPU_PORT", 7861),
    )
