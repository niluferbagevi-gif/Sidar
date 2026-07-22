"""Environment value parsing helpers for Sidar configuration."""

from __future__ import annotations

import logging
import os
import warnings

logger = logging.getLogger(__name__)


def get_bool_env(key: str, default: bool = False) -> bool:
    """Return a strict boolean environment value."""
    raw_val = os.getenv(key)
    if raw_val is None or not raw_val.strip():
        return default
    val = raw_val.strip().lower()
    if val == "true":
        return True
    if val == "false":
        return False
    raise ValueError(f"{key} must be either 'true' or 'false' (case-insensitive); got {raw_val!r}.")


def get_external_bool_env(key: str, default: bool = False) -> bool:
    """Return a boolean environment value for third-party library conventions."""
    raw_val = os.getenv(key)
    if raw_val is None or not raw_val.strip():
        return default
    val = raw_val.strip().lower()
    if val in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if val in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    raise ValueError(
        f"{key} must be a boolean accepted by the external provider "
        f"('true'/'false', '1'/'0', 'yes'/'no', or 'on'/'off'); got {raw_val!r}."
    )


def get_web_scrape_max_chars(default: int = 12000) -> int:
    """Resolve preferred WEB_SCRAPE_MAX_CHARS with deprecated WEB_FETCH fallback."""
    if os.getenv("WEB_SCRAPE_MAX_CHARS") is not None:
        return get_int_env("WEB_SCRAPE_MAX_CHARS", default)
    if os.getenv("WEB_FETCH_MAX_CHARS") is not None:
        warnings.warn(
            "WEB_FETCH_MAX_CHARS is deprecated; use WEB_SCRAPE_MAX_CHARS instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return get_int_env("WEB_FETCH_MAX_CHARS", default)
    return default


def get_int_env(key: str, default: int = 0) -> int:
    """Return an integer environment value, warning and falling back on malformed input."""
    raw_val = os.getenv(key)
    if raw_val is None or not raw_val.strip():
        return default
    try:
        return int(raw_val)
    except (ValueError, TypeError):
        logger.warning(
            "%s ortam değişkeni geçerli bir tam sayı değil (%r); varsayılan %r kullanılacak.",
            key,
            raw_val,
            default,
        )
        return default


def get_float_env(key: str, default: float = 0.0) -> float:
    """Return a float environment value, warning and falling back on malformed input."""
    raw_val = os.getenv(key)
    if raw_val is None or not raw_val.strip():
        return default
    try:
        return float(raw_val)
    except (ValueError, TypeError):
        logger.warning(
            "%s ortam değişkeni geçerli bir ondalık sayı değil (%r); varsayılan %r kullanılacak.",
            key,
            raw_val,
            default,
        )
        return default


def get_list_env(key: str, default: list[str] | None = None, separator: str = ",") -> list[str]:
    """Return a stripped list environment value split by ``separator``."""
    if default is None:
        default = []
    value = os.getenv(key, "")
    if not value:
        return default
    return [item.strip() for item in value.split(separator) if item.strip()]


def get_prefixed_env(prefix_key: str, legacy_key: str, default: str = "") -> str:
    """Read a Sidar-prefixed env var while preserving a legacy fallback."""
    prefixed_value = os.getenv(prefix_key)
    if prefixed_value is not None:
        return prefixed_value
    return os.getenv(legacy_key, default)


def get_optional_prefixed_env(prefix_key: str, legacy_key: str) -> str | None:
    """Read an optional Sidar-prefixed env var with legacy fallback."""
    prefixed_value = os.getenv(prefix_key)
    if prefixed_value is not None:
        return prefixed_value
    return os.getenv(legacy_key)


def get_int_prefixed_env(prefix_key: str, legacy_key: str, default: int = 0) -> int:
    """Read a prefixed/legacy integer environment value, warning on malformed input."""
    raw_value = get_optional_prefixed_env(prefix_key, legacy_key)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return int(raw_value)
    except (ValueError, TypeError):
        logger.warning(
            "%s / %s ortam değişkeni geçerli bir tam sayı değil (%r); varsayılan %r kullanılacak.",
            prefix_key,
            legacy_key,
            raw_value,
            default,
        )
        return default


def get_float_prefixed_env(prefix_key: str, legacy_key: str, default: float = 0.0) -> float:
    """Read a prefixed/legacy float environment value, warning on malformed input."""
    raw_value = get_optional_prefixed_env(prefix_key, legacy_key)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return float(raw_value)
    except (ValueError, TypeError):
        logger.warning(
            "%s / %s ortam değişkeni geçerli bir ondalık sayı değil (%r); varsayılan %r "
            "kullanılacak.",
            prefix_key,
            legacy_key,
            raw_value,
            default,
        )
        return default


def get_bool_prefixed_env(prefix_key: str, legacy_key: str, default: bool = False) -> bool:
    """Read a strict prefixed/legacy boolean environment value."""
    raw_value = get_optional_prefixed_env(prefix_key, legacy_key)
    if raw_value is None or not raw_value.strip():
        return default
    val = raw_value.strip().lower()
    if val == "true":
        return True
    if val == "false":
        return False
    raise ValueError(
        f"{prefix_key} / {legacy_key} must be either 'true' or 'false' "
        f"(case-insensitive); got {raw_value!r}."
    )
