"""scripts/migrate_sqlite_to_pg.py için birim testleri."""
from __future__ import annotations

import importlib
import sqlite3
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import asyncio
import pytest


class _DummyTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyConn:
    def __init__(self):
        self.calls: list[tuple] = []
        self.closed = False

    def transaction(self):
        return _DummyTx()

    async def execute(self, query, *args):
        self.calls.append((query, args))

    async def close(self):
        self.closed = True


def _create_sqlite_file(path: Path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    conn.commit()
    conn.close()


def test_load_rows_reads_existing_table(tmp_path):
    mod = importlib.import_module("scripts.migrate_sqlite_to_pg")
    db_path = tmp_path / "source.db"
    _create_sqlite_file(db_path)

    cols, rows = mod._load_rows(db_path, "users")

    assert cols == ["id", "username"]
    assert rows == [(1, "alice")]


def test_copy_table_dry_run_returns_count(tmp_path):
    mod = importlib.import_module("scripts.migrate_sqlite_to_pg")
    db_path = tmp_path / "source.db"
    _create_sqlite_file(db_path)
    conn = _DummyConn()

    count = asyncio.run(mod._copy_table(conn, db_path, "users", dry_run=True))

    assert count == 1
    assert conn.calls == []


def test_copy_table_executes_truncate_and_insert(tmp_path):
    mod = importlib.import_module("scripts.migrate_sqlite_to_pg")
    db_path = tmp_path / "source.db"
    _create_sqlite_file(db_path)
    conn = _DummyConn()

    count = asyncio.run(mod._copy_table(conn, db_path, "users", dry_run=False))

    assert count == 1
    assert any("TRUNCATE TABLE users" in q for q, _ in conn.calls)
    assert any("INSERT INTO users" in q for q, _ in conn.calls)


def test_migrate_raises_when_sqlite_missing(tmp_path):
    mod = importlib.import_module("scripts.migrate_sqlite_to_pg")
    path = tmp_path / "missing.db"

    asyncpg_stub = types.ModuleType("asyncpg")

    async def _connect(*, dsn: str):
        return _DummyConn()

    asyncpg_stub.connect = _connect
    sys.modules["asyncpg"] = asyncpg_stub

    with pytest.raises(FileNotFoundError):
        asyncio.run(mod.migrate(path, "postgresql://user:pass@localhost:5432/sidar", dry_run=True))


def test_migrate_raises_when_asyncpg_missing(tmp_path, monkeypatch):
    mod = importlib.import_module("scripts.migrate_sqlite_to_pg")
    db_path = tmp_path / "source.db"
    _create_sqlite_file(db_path)

    original_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "asyncpg":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    with pytest.raises(RuntimeError, match="asyncpg"):
        asyncio.run(mod.migrate(db_path, "postgresql://user:pass@localhost:5432/sidar", dry_run=True))


def test_migrate_connects_and_closes(monkeypatch, tmp_path, capsys):
    mod = importlib.import_module("scripts.migrate_sqlite_to_pg")
    db_path = tmp_path / "source.db"
    _create_sqlite_file(db_path)

    dummy_conn = _DummyConn()
    asyncpg_stub = types.ModuleType("asyncpg")

    async def _connect(*, dsn: str):
        assert dsn.startswith("postgresql://")
        return dummy_conn

    asyncpg_stub.connect = _connect
    sys.modules["asyncpg"] = asyncpg_stub

    monkeypatch.setattr(mod, "TABLES_IN_ORDER", ["users"])
    asyncio.run(mod.migrate(db_path, "postgresql://user:pass@localhost:5432/sidar", dry_run=True))

    out = capsys.readouterr().out
    assert "[DRY-RUN] users: 1 row" in out
    assert dummy_conn.closed is True


def test_main_parses_args_and_calls_asyncio_run(monkeypatch):
    mod = importlib.import_module("scripts.migrate_sqlite_to_pg")
    called = {}

    monkeypatch.setattr(
        mod.argparse.ArgumentParser,
        "parse_args",
        lambda _self: SimpleNamespace(sqlite_path="/tmp/s.db", postgres_dsn="postgresql://x", dry_run=True),
    )

    def _fake_run(coro):
        called["coro_name"] = coro.cr_code.co_name
        coro.close()

    monkeypatch.setattr(mod.asyncio, "run", _fake_run)
    mod.main()

    assert called["coro_name"] == "migrate"
