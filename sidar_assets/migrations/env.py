from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
from collections.abc import Callable
from logging.config import fileConfig
from os import PathLike
from pathlib import Path
from typing import Protocol, TextIO, cast

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.models import Base


class DotenvLoader(Protocol):
    def __call__(
        self,
        dotenv_path: str | PathLike[str] | None = None,
        stream: TextIO | None = None,
        verbose: bool = False,
        override: bool = False,
        interpolate: bool = True,
        encoding: str | None = "utf-8",
    ) -> bool: ...


def _missing_load_dotenv(
    dotenv_path: str | PathLike[str] | None = None,
    stream: TextIO | None = None,
    verbose: bool = False,
    override: bool = False,
    interpolate: bool = True,
    encoding: str | None = "utf-8",
) -> bool:
    del dotenv_path, stream, verbose, override, interpolate, encoding
    return False


def _resolve_dotenv_loader() -> DotenvLoader:
    if importlib.util.find_spec("dotenv") is None:
        return _missing_load_dotenv
    dotenv_module = importlib.import_module("dotenv")
    return cast(DotenvLoader, dotenv_module.load_dotenv)


_load_dotenv = _resolve_dotenv_loader()


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


def _configured_database_url(section: dict[str, str] | None = None) -> str:
    raw_url = None
    if section is not None:
        raw_url = section.get("sqlalchemy.url")
    url = raw_url or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "Alembic sqlalchemy.url is not configured; set DATABASE_URL or sqlalchemy.url."
        )
    return url


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
    connectable = cast(
        "AsyncEngine | Engine | None", context.config.attributes.get("connection", None)
    )

    if connectable is None:
        section = dict(config.get_section(config.config_ini_section) or {})
        x_database_url = _load_database_url()
        if x_database_url:
            section["sqlalchemy.url"] = x_database_url

        url = _configured_database_url(section)
        try:
            connectable = create_async_engine(url, poolclass=pool.NullPool)
        except InvalidRequestError:
            connectable = create_engine(url, poolclass=pool.NullPool)

    if not isinstance(connectable, AsyncEngine):
        with connectable.connect() as connection:
            do_run_migrations(connection)
        connectable.dispose()
        return

    async with connectable.connect() as connection:
        sync_runner: Callable[[Connection], None] = do_run_migrations
        await connection.run_sync(sync_runner)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()