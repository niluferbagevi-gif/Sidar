from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from types import SimpleNamespace

import pytest


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("jwt"):
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.decode = lambda *_a, **_k: {}
    fake_jwt.encode = lambda *_a, **_k: "token"
    sys.modules["jwt"] = fake_jwt

from core.db import Database


def _cfg(url: str) -> SimpleNamespace:
    return SimpleNamespace(
        DATABASE_URL=url,
        BASE_DIR=".",
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
    )


def test_connect_postgresql_propagates_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(_cfg("postgresql://user:pass@localhost:5432/sidar"))

    async def _raise_timeout(**_kwargs):
        raise TimeoutError("pool timeout")

    asyncpg_stub = types.SimpleNamespace(create_pool=_raise_timeout, PoolError=RuntimeError)
    monkeypatch.setitem(sys.modules, "asyncpg", asyncpg_stub)

    with pytest.raises(TimeoutError, match="pool timeout"):
        asyncio.run(db.connect())


def test_connect_postgresql_propagates_pool_error(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database(_cfg("postgresql://user:pass@localhost:5432/sidar"))

    class _PoolError(Exception):
        pass

    async def _raise_pool_error(**_kwargs):
        raise _PoolError("pool unavailable")

    asyncpg_stub = types.SimpleNamespace(create_pool=_raise_pool_error, PoolError=_PoolError)
    monkeypatch.setitem(sys.modules, "asyncpg", asyncpg_stub)

    with pytest.raises(_PoolError, match="pool unavailable"):
        asyncio.run(db.connect())


def test_init_schema_postgresql_executes_queries() -> None:
    db = Database(_cfg("postgresql://user:pass@localhost:5432/sidar"))
    executed: list[str] = []

    class _Conn:
        async def execute(self, query: str):
            executed.append(query)

    class _Acquire:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_args):
            return False

    db._pg_pool = types.SimpleNamespace(acquire=lambda: _Acquire())

    asyncio.run(db._init_schema_postgresql())

    assert any("CREATE TABLE IF NOT EXISTS users" in q for q in executed)
    assert any("CREATE TABLE IF NOT EXISTS coverage_tasks" in q for q in executed)
    assert any("idx_messages_session_id" in q for q in executed)
