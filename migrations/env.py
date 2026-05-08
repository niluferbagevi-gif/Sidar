from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
from collections.abc import Callable
from logging.config import fileConfig
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.models import Base

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine


LoadDotenv = Callable[..., bool]
CreateEngine = Callable[..., "Engine"]


def _noop_load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
    return False


def _resolve_load_dotenv() -> LoadDotenv:
    """Return python-dotenv's loader when available without conditional redefinition."""

    if importlib.util.find_spec("dotenv") is None:
        return _noop_load_dotenv
    dotenv_module = importlib.import_module("dotenv")
    candidate = getattr(dotenv_module, "load_dotenv", None)
    if not callable(candidate):
        return _noop_load_dotenv
    return cast(LoadDotenv, candidate)


_load_dotenv: LoadDotenv = _resolve_load_dotenv()
_create_engine_candidate = getattr(sa, "create_engine", None)
_create_engine: CreateEngine | None = (
    cast(CreateEngine, _create_engine_candidate) if callable(_create_engine_candidate) else None
)
_InvalidRequestError = cast(
    type[BaseException],
    getattr(getattr(sa, "exc", None), "InvalidRequestError", RuntimeError),
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _preload_dotenv_for_alembic() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        # Keep externally-provided env vars (e.g. test DATABASE_URL) as source of truth.
        _load_dotenv(dotenv_path=env_path, override=False)


_preload_dotenv_for_alembic()


def _load_database_url() -> str | None:
    x_args = context.get_x_argument(as_dictionary=True)
    value = (x_args.get("database_url") or "").strip()
    if value:
        return value

    env_value = os.getenv("DATABASE_URL", "").strip()
    if env_value:
        return env_value

    return None


LOCAL_DEV_FALLBACK_DATABASE_URL = "postgresql+asyncpg://sidar:sidar@localhost:5432/sidar"
PRODUCTION_ENV_NAMES = {"prod", "production"}


def _is_production_environment() -> bool:
    return os.getenv("SIDAR_ENV", "").strip().lower() in PRODUCTION_ENV_NAMES


def _ensure_database_url_allowed(url: str, *, source: str) -> str:
    normalized_url = str(url or "").strip()
    if (
        source == "alembic.ini"
        and normalized_url == LOCAL_DEV_FALLBACK_DATABASE_URL
        and _is_production_environment()
    ):
        raise RuntimeError(
            "Alembic local development fallback database URL is disabled when "
            "SIDAR_ENV=production. Set DATABASE_URL or pass "
            "-x database_url=... with production credentials."
        )
    return normalized_url


def _configured_database_url(section: dict[str, str] | None = None) -> str:
    raw_url = None
    if section is not None:
        raw_url = section.get("sqlalchemy.url")
    url = raw_url or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "Alembic sqlalchemy.url is not configured; set DATABASE_URL or "
            "-x database_url=..."
        )
    return _ensure_database_url_allowed(url, source="alembic.ini")


def run_migrations_offline() -> None:
    url = _load_database_url() or _configured_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = context.config.attributes.get("connection", None)

    if connectable is None:
        section = config.get_section(config.config_ini_section) or {}
        x_database_url = _load_database_url()
        if x_database_url:
            section["sqlalchemy.url"] = x_database_url

        url = _configured_database_url(section)
        try:
            connectable = create_async_engine(url, poolclass=pool.NullPool)
        except _InvalidRequestError:
            if _create_engine is None:
                raise
            connectable = _create_engine(url, poolclass=pool.NullPool)

    if not isinstance(connectable, AsyncEngine):
        with connectable.connect() as connection:
            do_run_migrations(connection)
        connectable.dispose()
        return

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
