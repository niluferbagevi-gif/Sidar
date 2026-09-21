"""Web search/fetch settings for ``config.Config``."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.config_env_helpers import get_int_env


@dataclass(frozen=True)
class WebSearchSettings:
    """Search provider selection, credentials and fetch limits for web search."""

    search_engine: str
    tavily_api_key: str
    google_search_api_key: str
    google_search_cx: str
    web_search_max_results: int
    web_fetch_timeout: int


def load_web_search_settings() -> WebSearchSettings:
    """Load web search/fetch settings from environment variables."""
    return WebSearchSettings(
        search_engine=os.getenv("SEARCH_ENGINE", "auto"),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        google_search_api_key=os.getenv("GOOGLE_SEARCH_API_KEY", ""),
        google_search_cx=os.getenv("GOOGLE_SEARCH_CX", ""),
        web_search_max_results=get_int_env("WEB_SEARCH_MAX_RESULTS", 5),
        web_fetch_timeout=get_int_env("WEB_FETCH_TIMEOUT", 15),
    )
