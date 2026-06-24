"""Validation and normalization helpers for Sidar configuration."""

from __future__ import annotations

from urllib.parse import urlparse


def normalize_ai_provider(provider: str | None) -> str:
    """Normalize configured AI provider names for consistent validation and routing."""
    return (provider or "ollama").strip().lower() or "ollama"


def is_valid_http_url(value: str | None) -> bool:
    """Validate required HTTP(S) endpoint settings without leaking the raw value."""
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    parsed = urlparse(stripped)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
