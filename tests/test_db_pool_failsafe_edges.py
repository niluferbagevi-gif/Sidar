import asyncio
from types import SimpleNamespace

import pytest

from core.db import Database


class _BrokenAcquireCtx:
    async def __aenter__(self):
        raise ConnectionError("connection dropped")

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _BrokenPoolAcquire:
    def acquire(self):
        return _BrokenAcquireCtx()


class _BrokenPoolClose:
    def acquire(self):
        return _BrokenAcquireCtx()

    async def close(self):
        raise RuntimeError("close failed")


def _pg_db():
    cfg = SimpleNamespace(
        DATABASE_URL="postgresql://user:pass@localhost:5432/sidar",
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
    )
    return Database(cfg=cfg)


def test_postgresql_policy_calls_surface_connection_drop():
    db = _pg_db()
    db._pg_pool = _BrokenPoolAcquire()

    with pytest.raises(ConnectionError, match="connection dropped"):
        asyncio.run(db.list_access_policies("u-1"))


def test_close_clears_pg_pool_reference_even_if_pool_close_fails():
    db = _pg_db()
    db._pg_pool = _BrokenPoolClose()

    with pytest.raises(RuntimeError, match="close failed"):
        asyncio.run(db.close())

    assert db._pg_pool is None
