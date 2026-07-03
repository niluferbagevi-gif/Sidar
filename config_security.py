"""Security-related runtime configuration helpers for Sidar."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from core.config_env_helpers import get_int_env
from core.config_secrets import is_weak_secret


@dataclass(frozen=True)
class SecuritySettings:
    """JWT/API-key settings resolved after Sidar's dotenv load chain."""

    sidar_skip_default_dotenv: bool
    sidar_keys_file: str
    access_level: str
    api_key: str
    jwt_secret_key_explicitly_configured: bool
    jwt_secret_key: str
    jwt_algorithm: str
    jwt_ttl_days: int


def load_security_settings(
    *, getenv: Callable[[str, str | None], str | None] = os.getenv
) -> SecuritySettings:
    """Resolve security settings without coupling JWT signing secrets to API keys."""
    explicit_jwt_secret = bool((getenv("JWT_SECRET_KEY", "") or "").strip())
    jwt_secret_key = getenv("JWT_SECRET_KEY", None) or secrets.token_urlsafe(32)
    return SecuritySettings(
        sidar_skip_default_dotenv=(getenv("SIDAR_SKIP_DEFAULT_DOTENV", "") or "").strip().lower()
        in {"1", "true", "yes", "on"},
        sidar_keys_file=getenv("SIDAR_KEYS_FILE", "~/.sidar_keys.env") or "~/.sidar_keys.env",
        access_level=getenv("ACCESS_LEVEL", "sandbox") or "sandbox",
        api_key=getenv("API_KEY", "") or "",
        jwt_secret_key_explicitly_configured=explicit_jwt_secret,
        jwt_secret_key=jwt_secret_key,
        jwt_algorithm=getenv("JWT_ALGORITHM", "HS256") or "HS256",
        jwt_ttl_days=get_int_env("JWT_TTL_DAYS", 7),
    )


def get_missing_security_runtime_keys(
    *,
    api_key: str,
    jwt_secret_key: str,
    jwt_secret_key_explicitly_configured: bool,
    is_production: bool,
    is_test_env: bool,
    web_concurrency: int = 1,
    postgres_password: str = "",
    database_url: str = "",
) -> list[str]:
    """Return unresolved security keys that should block runtime startup."""
    missing: list[str] = []
    requires_stable_jwt = is_production or int(web_concurrency or 1) > 1
    if (
        not str(jwt_secret_key or "").strip()
        or (requires_stable_jwt and not jwt_secret_key_explicitly_configured)
    ) and not is_test_env:
        missing.append("JWT_SECRET_KEY")

    if is_production and not str(api_key or "").strip():
        missing.append("API_KEY")

    if is_production and _has_weak_postgres_runtime_secret(
        postgres_password=postgres_password,
        database_url=database_url,
    ):
        missing.append("POSTGRES_PASSWORD")

    return missing


def _has_weak_postgres_runtime_secret(*, postgres_password: str, database_url: str) -> bool:
    """Return whether production lacks a strong PostgreSQL credential."""
    if not is_weak_secret(postgres_password):
        return False

    embedded_password = _postgres_password_from_database_url(database_url)
    return embedded_password is None or is_weak_secret(embedded_password)


def _postgres_password_from_database_url(database_url: str) -> str | None:
    """Extract a PostgreSQL password from DATABASE_URL without validating connectivity."""
    raw_url = str(database_url or "").strip()
    if not raw_url:
        return None
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return None
    if not parsed.scheme.startswith("postgresql"):
        return None
    if parsed.password is None:
        return None
    return unquote(parsed.password)
