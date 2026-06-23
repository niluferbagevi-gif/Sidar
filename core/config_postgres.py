"""PostgreSQL configuration helpers for Sidar.

This module keeps DATABASE_URL derivation and pool-size defaults outside the
large top-level ``config.py`` facade while preserving the same public behavior
through wrapper functions in that module.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from urllib.parse import quote

GetEnv = Callable[[str, str | None], str | None]
GetIntEnv = Callable[[str, int], int]


def _read_env(getenv: GetEnv, key: str, default: str = "") -> str:
    """Read an environment value through an injectable getter."""
    value = getenv(key, default)
    if value is None:
        return default
    return value


def _normalize_postgres_identifier(value: str | None, default: str) -> str:
    """Normalize user/database identifiers before URL encoding."""
    return (value or default).strip() or default


def _normalize_postgres_password(value: str | None, default: str = "sidar") -> str:
    """Keep password whitespace significant while still handling missing values."""
    return default if value is None else value


def _normalize_postgres_host(value: str | None, default: str) -> str:
    """Normalize host-like POSTGRES values without rewriting valid hostnames."""
    return (value or default).strip() or default


def _normalize_postgres_port(value: str | None, default: str = "5432") -> str:
    """Return a safe TCP port string, falling back for malformed values.

    PostgreSQL DSNs built from component environment variables should not emit
    an empty, negative, or out-of-range port segment. Explicit DATABASE_URL
    values are intentionally not parsed or rewritten by these helpers.
    """
    candidate = (value or default).strip() or default
    if not candidate.isdigit():
        return default
    port = int(candidate)
    if 1 <= port <= 65535:
        return str(port)
    return default


def build_postgres_dsn(*, host: str | None = None, getenv: GetEnv = os.getenv) -> str:
    """Build Sidar's async PostgreSQL DSN from normalized POSTGRES_* variables."""
    user = _normalize_postgres_identifier(_read_env(getenv, "POSTGRES_USER", "sidar"), "sidar")
    password = _normalize_postgres_password(_read_env(getenv, "POSTGRES_PASSWORD", "sidar"))
    host_value = host if host is not None else _read_env(getenv, "POSTGRES_HOST", "127.0.0.1")
    resolved_host = _normalize_postgres_host(host_value, "127.0.0.1")
    port = _normalize_postgres_port(_read_env(getenv, "POSTGRES_PORT", "5432"))
    database = _normalize_postgres_identifier(_read_env(getenv, "POSTGRES_DB", "sidar"), "sidar")

    quoted_user = quote(user, safe="")
    quoted_password = quote(password, safe="")
    quoted_database = quote(database, safe="")
    return f"postgresql+asyncpg://{quoted_user}:{quoted_password}@{resolved_host}:{port}/{quoted_database}"


def get_database_url(*, getenv: GetEnv = os.getenv) -> str:
    """Resolve DATABASE_URL, deriving it from POSTGRES_* variables when absent."""
    explicit_url = _read_env(getenv, "DATABASE_URL", "").strip()
    if explicit_url:
        return explicit_url
    return build_postgres_dsn(getenv=getenv)


def get_container_database_url(*, getenv: GetEnv = os.getenv) -> str:
    """Resolve the container DSN from SIDAR_CONTAINER_DATABASE_URL or POSTGRES_* values."""
    explicit_url = _read_env(getenv, "SIDAR_CONTAINER_DATABASE_URL", "").strip()
    if explicit_url:
        return explicit_url
    container_host = _read_env(getenv, "POSTGRES_CONTAINER_HOST", "postgres")
    return build_postgres_dsn(host=container_host, getenv=getenv)


def get_db_pool_size_default(
    *,
    get_int_env: GetIntEnv,
    cpu_count: int | None = None,
) -> int:
    """Compute a bounded PostgreSQL pool size from CPU and server limits."""
    resolved_cpu_count = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))
    per_core = max(1, get_int_env("DB_POOL_SIZE_PER_CORE", 2))
    postgres_max_connections = max(1, get_int_env("POSTGRES_MAX_CONNECTIONS", 100))
    reserve = max(0, get_int_env("DB_POOL_CONNECTION_RESERVE", 10))
    hard_cap = max(1, get_int_env("DB_POOL_SIZE_HARD_CAP", 50))

    max_by_postgres = max(1, postgres_max_connections - reserve)
    return max(2, min(resolved_cpu_count * per_core, max_by_postgres, hard_cap))
