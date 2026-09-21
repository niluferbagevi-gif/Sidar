"""Browser automation settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_bool_env, get_int_env, get_list_env


@dataclass(frozen=True)
class BrowserSettings:
    """``managers/browser_manager.py`` Playwright/CDP automation settings."""

    browser_provider: str
    browser_headless: bool
    browser_timeout_ms: int
    browser_allowed_domains: list[str]


def load_browser_settings() -> BrowserSettings:
    """Load browser automation settings from environment variables."""
    return BrowserSettings(
        browser_provider=os.getenv("BROWSER_PROVIDER", "auto"),
        browser_headless=get_bool_env("BROWSER_HEADLESS", True),
        browser_timeout_ms=get_int_env("BROWSER_TIMEOUT_MS", 15000),
        browser_allowed_domains=get_list_env("BROWSER_ALLOWED_DOMAINS", []),
    )
