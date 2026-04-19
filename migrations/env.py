from __future__ import annotations

import asyncio
from logging.config import fileConfig
import os
from pathlib import Path

from alembic import context
from sqlalchemy import pool
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency in some test stubs
    def load_dotenv(*_args, **_kwargs):
        return False
try:
    from sqlalchemy import create_engine
except ImportError:  # pragma: no cover - only for minimal test doubles
    create_engine = None
try:
    from sqlalchemy.exc import InvalidRequestError
except Exception:  # pragma: no cover - only for minimal test doubles
    class InvalidRequestError(Exception):
        pass
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _preload_dotenv_for_alembic() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)


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


def run_migrations_offline() -> None:
    url = _load_database_url() or config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
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

        url = section.get("sqlalchemy.url") or config.get_main_option("sqlalchemy.url")
        try:
            connectable = create_async_engine(url, poolclass=pool.NullPool)
        except InvalidRequestError:
            if create_engine is None:
                raise
            connectable = create_engine(url, poolclass=pool.NullPool)

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
