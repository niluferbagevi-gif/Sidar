from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from logging.config import fileConfig
from pathlib import Path
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.models import Base

_dotenv_module: Any | None
try:
    import dotenv as _dotenv_module
except ModuleNotFoundError:  # pragma: no cover - optional dependency in some test stubs
    _dotenv_module = None


def _fallback_load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
    return False


load_dotenv: Callable[..., bool] = (
    _fallback_load_dotenv
    if _dotenv_module is None
    else _dotenv_module.load_dotenv
)

try:
    import sqlalchemy as _sqlalchemy_module
except ImportError:  # pragma: no cover - only for minimal test doubles
    _sqlalchemy_create_engine: Callable[..., Engine] | None = None
else:
    _sqlalchemy_create_engine = _sqlalchemy_module.create_engine

try:
    from sqlalchemy import exc as _sqlalchemy_exc
except Exception:  # pragma: no cover - only for minimal test doubles
    _InvalidRequestError: type[Exception] = RuntimeError
else:
    _InvalidRequestError = _sqlalchemy_exc.InvalidRequestError

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _preload_dotenv_for_alembic() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        # Keep externally-provided env vars (e.g. test DATABASE_URL) as source of truth.
        load_dotenv(dotenv_path=env_path, override=False)


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


def _configured_database_url() -> str:
    url = _load_database_url() or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("Alembic database URL is not configured")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_configured_database_url(),
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

        url = section.get("sqlalchemy.url") or _configured_database_url()
        try:
            connectable = create_async_engine(url, poolclass=pool.NullPool)
        except _InvalidRequestError:
            if _sqlalchemy_create_engine is None:
                raise
            connectable = _sqlalchemy_create_engine(url, poolclass=pool.NullPool)

    if not isinstance(connectable, AsyncEngine):
        sync_connectable = connectable
        with sync_connectable.connect() as connection:
            do_run_migrations(connection)
        sync_connectable.dispose()
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
