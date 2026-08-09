"""Audit persistence module split contract tests."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.db.audit as audit
import core.db.audit_log as audit_log


def test_audit_module_is_primary_and_legacy_wrapper_reexports_helpers() -> None:
    assert audit.record_audit_log is audit_log.record_audit_log
    assert audit.list_audit_logs is audit_log.list_audit_logs


def test_monolith_delegates_audit_persistence_to_audit_module() -> None:
    source = Path("core/db/monolith.py").read_text(encoding="utf-8")

    assert "from core.db import audit as db_audit" in source
    assert "db_audit.record_audit_log" in source
    assert "db_audit.list_audit_logs" in source
    assert "from core.db import audit_log as db_audit_log" not in source


class _SqliteAuditDb:
    _backend = "sqlite"

    def __init__(self, conn):
        self._sqlite_conn = conn

    async def _run_sqlite_op(self, func, *, write=True):
        return func()


@pytest.mark.asyncio
async def test_sqlite_audit_insert_error_is_logged_and_masked(caplog) -> None:
    class _Conn:
        def execute(self, *_args):
            raise sqlite3.OperationalError("disk is full")

    db = _SqliteAuditDb(_Conn())

    with pytest.raises(RuntimeError, match="SQLite audit log insert failed"):
        await audit.record_audit_log(
            db,
            record_cls=SimpleNamespace,
            parse_iso_datetime=lambda value: value,
            utc_now_iso=lambda: "2026-07-07T00:00:00+00:00",
            user_id="u1",
            tenant_id="t1",
            action="READ",
            resource="repo/1",
            ip_address="127.0.0.1",
            allowed=True,
        )

    assert "SQLite audit log insert failed" in caplog.text
    assert "disk is full" in caplog.text


@pytest.mark.asyncio
async def test_sqlite_audit_query_error_is_logged_and_masked(caplog) -> None:
    class _Conn:
        def execute(self, *_args):
            raise sqlite3.OperationalError("database is locked")

    db = _SqliteAuditDb(_Conn())

    with pytest.raises(RuntimeError, match="SQLite audit log query failed"):
        await audit.list_audit_logs(db, record_cls=SimpleNamespace, user_id="u1")

    assert "SQLite audit log query failed" in caplog.text
    assert "database is locked" in caplog.text


@pytest.mark.asyncio
async def test_sqlite_audit_filters_user_tenant_and_clamps_limit() -> None:
    captured: dict[str, object] = {}

    class _Cursor:
        def fetchall(self):
            return [
                {
                    "id": 7,
                    "user_id": "u1",
                    "tenant_id": "t1",
                    "action": "read",
                    "resource": "repo/1",
                    "ip_address": "127.0.0.1",
                    "allowed": 1,
                    "timestamp": "2026-07-07T00:00:00+00:00",
                }
            ]

    class _Conn:
        def execute(self, query, params):
            captured["query"] = query
            captured["params"] = params
            return _Cursor()

    db = _SqliteAuditDb(_Conn())

    rows = await audit.list_audit_logs(
        db, record_cls=SimpleNamespace, user_id="  u1  ", tenant_id=" t1 ", limit=5000
    )

    assert "WHERE user_id=? AND tenant_id=?" in str(captured["query"])
    assert captured["params"] == ("u1", "t1", 1000)
    assert rows[0].id == 7
    assert rows[0].allowed is True


class _PgConn:
    def __init__(self):
        self.executed: tuple[str, tuple[object, ...]] | None = None
        self.fetched: tuple[str, tuple[object, ...]] | None = None

    async def execute(self, query, *args):
        self.executed = (query, args)

    async def fetch(self, query, *args):
        self.fetched = (query, args)
        return [
            {
                "id": 9,
                "user_id": "u1",
                "tenant_id": "t1",
                "action": "write",
                "resource": "repo/2",
                "ip_address": "10.0.0.1",
                "allowed": False,
                "timestamp": "2026-07-07T00:00:00+00:00",
            }
        ]


class _PgAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_exc):
        return False


class _PgPool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _PgAcquire(self.conn)


@pytest.mark.asyncio
async def test_postgresql_audit_insert_uses_numbered_placeholders() -> None:
    conn = _PgConn()
    db = SimpleNamespace(_backend="postgresql", _pg_pool=_PgPool(conn))

    await audit.record_audit_log(
        db,
        record_cls=SimpleNamespace,
        parse_iso_datetime=lambda value: f"parsed:{value}",
        utc_now_iso=lambda: "2026-07-07T00:00:00+00:00",
        user_id=" u1 ",
        tenant_id=" t1 ",
        action="LOGIN",
        resource="session/1",
        ip_address="",
        allowed=False,
    )

    assert conn.executed is not None
    query, args = conn.executed
    assert "VALUES ($1, $2, $3, $4, $5, $6, $7)" in query
    assert args == (
        "u1",
        "t1",
        "login",
        "session/1",
        "unknown",
        False,
        "parsed:2026-07-07T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_postgresql_audit_filters_use_numbered_placeholders_and_limit_clamp() -> None:
    conn = _PgConn()
    db = SimpleNamespace(_backend="postgresql", _pg_pool=_PgPool(conn))

    rows = await audit.list_audit_logs(
        db, record_cls=SimpleNamespace, user_id=" u1 ", tenant_id=" t1 ", limit=0
    )

    assert conn.fetched is not None
    query, args = conn.fetched
    assert "WHERE user_id=$1 AND tenant_id=$2" in query
    assert "LIMIT $3" in query
    assert args == ("u1", "t1", 100)
    assert rows[0].id == 9
    assert rows[0].allowed is False
