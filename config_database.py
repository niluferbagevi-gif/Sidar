"""Database configuration helpers for Sidar's config facade."""

from __future__ import annotations

import os

from core import config_postgres
from core.config_env_helpers import get_int_env


def build_postgres_dsn(*, host: str | None = None) -> str:
    """Build Sidar's async PostgreSQL DSN from normalized POSTGRES_* variables."""
    return config_postgres.build_postgres_dsn(host=host, getenv=os.getenv)


def get_database_url() -> str:
    """Resolve DATABASE_URL, deriving it from POSTGRES_* variables when absent."""
    return config_postgres.get_database_url(getenv=os.getenv)


def get_container_database_url() -> str:
    """Resolve the container DSN from SIDAR_CONTAINER_DATABASE_URL or POSTGRES_* values."""
    return config_postgres.get_container_database_url(getenv=os.getenv)


def default_auto_migrate_enabled() -> bool:
    """Enable runtime Alembic auto-migrate outside production by default."""
    return os.getenv("SIDAR_ENV", "").strip().lower() != "production"


def get_db_pool_size_default() -> int:
    """Return the profile-aware default PostgreSQL pool size."""
    return config_postgres.get_db_pool_size_default(
        get_int_env=get_int_env, cpu_count=os.cpu_count()
    )
