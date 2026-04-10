"""scripts/load_test_db_pool.py için birim testleri."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import asyncio
import pytest


class _DummyAcquire:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _query: str):
        return None


class _DummyPool:
    def acquire(self):
        return _DummyAcquire()


class _DummyDB:
    def __init__(self, backend: str = "postgresql"):
        self._backend = backend
        self._pg_pool = _DummyPool()
        self.pool_size = 7
        self.connected = False
        self.closed = False

    async def connect(self):
        self.connected = True

    async def close(self):
        self.closed = True


def test_run_load_test_prints_success_for_postgres(monkeypatch, capsys):
    mod = importlib.import_module("scripts.load_test_db_pool")
    dummy_db = _DummyDB(backend="postgresql")
    monkeypatch.setattr(mod, "Database", lambda _cfg: dummy_db)

    asyncio.run(mod.run_load_test("postgresql://u:p@localhost:5432/sidar", concurrency=3, requests=5))

    out = capsys.readouterr().out
    assert "POOL_LOAD_TEST_OK" in out
    assert dummy_db.connected is True
    assert dummy_db.closed is True


def test_run_load_test_raises_for_non_postgres(monkeypatch):
    mod = importlib.import_module("scripts.load_test_db_pool")
    dummy_db = _DummyDB(backend="sqlite")
    monkeypatch.setattr(mod, "Database", lambda _cfg: dummy_db)

    with pytest.raises(RuntimeError, match="yalnızca PostgreSQL"):
        asyncio.run(mod.run_load_test("sqlite:///tmp/a.db", concurrency=2, requests=3))
    assert dummy_db.closed is True


def test_main_parses_args_and_calls_asyncio_run(monkeypatch):
    mod = importlib.import_module("scripts.load_test_db_pool")
    called = {}

    monkeypatch.setattr(
        mod.argparse.ArgumentParser,
        "parse_args",
        lambda _self: SimpleNamespace(database_url="postgresql://x", concurrency=4, requests=9),
    )

    def _fake_run(coro):
        called["coro_name"] = coro.cr_code.co_name
        coro.close()

    monkeypatch.setattr(mod.asyncio, "run", _fake_run)
    mod.main()

    assert called["coro_name"] == "run_load_test"
