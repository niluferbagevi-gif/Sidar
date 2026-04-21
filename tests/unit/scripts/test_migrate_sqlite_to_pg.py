import asyncio
import sqlite3
from pathlib import Path

import pytest

from scripts import migrate_sqlite_to_pg


def test_load_rows_reads_columns_and_data(tmp_path: Path):
    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users (email) VALUES (?)", ("alice@example.com",))
        conn.commit()
    finally:
        conn.close()

    cols, rows = migrate_sqlite_to_pg._load_rows(db_path, "users")

    assert cols == ["id", "email"]
    assert rows == [(1, "alice@example.com")]


def test_load_rows_returns_columns_for_empty_table(tmp_path: Path):
    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
        conn.commit()
    finally:
        conn.close()

    cols, rows = migrate_sqlite_to_pg._load_rows(db_path, "users")

    assert cols == ["id", "email"]
    assert rows == []


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self):
        self.executed = []

    def transaction(self):
        return _FakeTransaction()

    async def execute(self, query, *params):
        self.executed.append((query, params))


class _FakeAsyncPgConn:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _FakeAsyncPg:
    def __init__(self, conn):
        self._conn = conn

    async def connect(self, dsn: str):
        assert dsn.startswith("postgresql://")
        return self._conn


def test_copy_table_dry_run_reports_row_count(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users (email) VALUES (?)", ("alice@example.com",))
        conn.execute("INSERT INTO users (email) VALUES (?)", ("bob@example.com",))
        conn.commit()
    finally:
        conn.close()

    fake_conn = _FakeConn()
    count = asyncio.run(migrate_sqlite_to_pg._copy_table(fake_conn, db_path, "users", dry_run=True))

    assert count == 2
    assert fake_conn.executed == []


def test_copy_table_writes_rows_inside_transaction(tmp_path: Path):
    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
        conn.execute("INSERT INTO users (email) VALUES (?)", ("alice@example.com",))
        conn.execute("INSERT INTO users (email) VALUES (?)", ("bob@example.com",))
        conn.commit()
    finally:
        conn.close()

    fake_conn = _FakeConn()
    count = asyncio.run(migrate_sqlite_to_pg._copy_table(fake_conn, db_path, "users", dry_run=False))

    assert count == 2
    assert len(fake_conn.executed) == 3
    truncate_query, truncate_params = fake_conn.executed[0]
    first_query, first_params = fake_conn.executed[1]
    second_query, second_params = fake_conn.executed[2]
    assert "TRUNCATE TABLE users" in truncate_query
    assert truncate_params == ()
    assert "INSERT INTO users" in first_query
    assert first_params == (1, "alice@example.com")
    assert "INSERT INTO users" in second_query
    assert second_params == (2, "bob@example.com")


def test_copy_table_returns_zero_when_table_has_no_columns(monkeypatch, tmp_path: Path):
    fake_conn = _FakeConn()

    monkeypatch.setattr(migrate_sqlite_to_pg, "_load_rows", lambda *_: ([], []))

    count = asyncio.run(migrate_sqlite_to_pg._copy_table(fake_conn, tmp_path / "sample.db", "users", dry_run=False))

    assert count == 0
    assert fake_conn.executed == []


def test_migrate_raises_when_sqlite_file_missing(monkeypatch, tmp_path: Path):
    fake_conn = _FakeAsyncPgConn()
    monkeypatch.setitem(__import__("sys").modules, "asyncpg", _FakeAsyncPg(fake_conn))

    with pytest.raises(FileNotFoundError, match="SQLite dosyası bulunamadı"):
        asyncio.run(
            migrate_sqlite_to_pg.migrate(
                sqlite_path=tmp_path / "missing.db",
                postgres_dsn="postgresql://user:pass@localhost:5432/sidar",
                dry_run=True,
            )
        )


def test_migrate_iterates_all_tables(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "sample.db"
    db_path.write_bytes(b"placeholder")
    fake_conn = _FakeAsyncPgConn()

    monkeypatch.setitem(__import__("sys").modules, "asyncpg", _FakeAsyncPg(fake_conn))

    calls = []

    async def _fake_copy_table(conn, sqlite_path, table, dry_run):
        calls.append((conn, sqlite_path, table, dry_run))
        return 3

    monkeypatch.setattr(migrate_sqlite_to_pg, "_copy_table", _fake_copy_table)

    asyncio.run(
        migrate_sqlite_to_pg.migrate(
            sqlite_path=db_path,
            postgres_dsn="postgresql://user:pass@localhost:5432/sidar",
            dry_run=False,
        )
    )

    assert [table for _, _, table, _ in calls] == migrate_sqlite_to_pg.TABLES_IN_ORDER
    assert fake_conn.closed is True


def test_main_parses_args_and_runs_migrate(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "sample.db"
    db_path.write_bytes(b"placeholder")
    seen = {}

    async def _fake_migrate(sqlite_path: Path, postgres_dsn: str, dry_run: bool):
        seen["sqlite_path"] = sqlite_path
        seen["postgres_dsn"] = postgres_dsn
        seen["dry_run"] = dry_run

    original_run = asyncio.run

    def _run(coro):
        return original_run(coro)

    monkeypatch.setattr(
        __import__("sys"),
        "argv",
        [
            "migrate_sqlite_to_pg.py",
            "--sqlite-path",
            str(db_path),
            "--postgres-dsn",
            "postgresql://user:pass@localhost:5432/sidar",
            "--dry-run",
        ],
    )
    monkeypatch.setattr(migrate_sqlite_to_pg, "migrate", _fake_migrate)
    monkeypatch.setattr(migrate_sqlite_to_pg.asyncio, "run", _run)

    migrate_sqlite_to_pg.main()

    assert seen == {
        "sqlite_path": db_path,
        "postgres_dsn": "postgresql://user:pass@localhost:5432/sidar",
        "dry_run": True,
    }
