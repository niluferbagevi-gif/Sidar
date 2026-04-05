import asyncio
import importlib
import sys
import types

import pytest


def _import_module_with_stubs():
    fake_config = types.ModuleType("config")

    class _Config:  # pragma: no cover - simple stub
        pass

    fake_config.Config = _Config
    sys.modules["config"] = fake_config

    fake_core_db = types.ModuleType("core.db")

    class _Database:  # pragma: no cover - replaced in tests
        pass

    fake_core_db.Database = _Database
    sys.modules["core.db"] = fake_core_db

    return importlib.import_module("scripts.load_test_db_pool")


class _FakeConn:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    async def execute(self, query: str):
        if self.should_fail:
            raise RuntimeError("boom")
        return query


class _AcquireCtx:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    async def __aenter__(self):
        return _FakeConn(should_fail=self.should_fail)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    def acquire(self, timeout: float):
        assert timeout > 0
        return _AcquireCtx(should_fail=self.should_fail)


class _FakeDb:
    def __init__(self, backend: str = "postgresql"):
        self._backend = backend
        self.pool_size = 7
        self._pg_pool = _FakePool()
        self.connected = False
        self.closed = False

    async def connect(self):
        self.connected = True

    async def close(self):
        self.closed = True


def test_run_once_returns_latency_ms_for_successful_query():
    module = _import_module_with_stubs()
    db = _FakeDb()
    latency = asyncio.run(module._run_once(db, acquire_timeout_s=0.5))
    assert latency is not None
    assert latency >= 0


def test_run_once_returns_none_on_query_failure():
    module = _import_module_with_stubs()
    db = _FakeDb()
    db._pg_pool = _FakePool(should_fail=True)
    latency = asyncio.run(module._run_once(db, acquire_timeout_s=0.5))
    assert latency is None


def test_run_load_test_rejects_non_postgres_and_closes_db(monkeypatch):
    module = _import_module_with_stubs()
    fake_db = _FakeDb(backend="sqlite")

    monkeypatch.setattr(module, "Database", lambda _cfg: fake_db)

    with pytest.raises(RuntimeError, match="yalnızca PostgreSQL"):
        asyncio.run(
            module.run_load_test(
                database_url="postgresql://user:pass@localhost:5432/sidar",
                concurrency=1,
                requests=1,
                warmup_requests=0,
                acquire_timeout_s=0.1,
            )
        )

    assert fake_db.connected is True
    assert fake_db.closed is True
