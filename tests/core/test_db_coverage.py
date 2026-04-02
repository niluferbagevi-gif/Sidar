from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import types

import pytest

if importlib.util.find_spec("jwt") is None:
    jwt_stub = types.ModuleType("jwt")

    class _JwtError(Exception):
        pass

    jwt_stub.PyJWTError = _JwtError
    jwt_stub.decode = lambda *_args, **_kwargs: {}
    jwt_stub.encode = lambda *_args, **_kwargs: "token"
    sys.modules["jwt"] = jwt_stub

from core.db import Database


@pytest.mark.asyncio
async def test_connect_init_schema_and_basic_user_token_flow(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'sidar_test.db'}",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_TTL_DAYS=7,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
    )
    db = Database(cfg)

    await db.connect()
    await db.init_schema()

    user = await db.create_user("coverage-user", role="admin", password="s3cret", tenant_id="tenant-a")
    token = await db.create_auth_token(
        user.id,
        role=user.role,
        username=user.username,
        tenant_id=user.tenant_id,
    )

    resolved = await db.get_user_by_token(token.token)
    assert resolved is not None
    assert resolved.id == user.id
    assert resolved.username == "coverage-user"
    assert resolved.role == "admin"
    assert resolved.tenant_id == "tenant-a"

    await db.close()


@pytest.mark.asyncio
async def test_init_schema_creates_coverage_tables_and_indexes(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'schema_test.db'}",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
    )
    db = Database(cfg)
    await db.connect()
    await db.init_schema()

    def _table_names() -> set[str]:
        assert db._sqlite_conn is not None
        rows = db._sqlite_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {str(r[0]) for r in rows}

    tables = await db._run_sqlite_op(_table_names)
    assert "coverage_tasks" in tables
    assert "coverage_findings" in tables
    assert "access_policies" in tables
    assert "audit_logs" in tables

    await db.close()


@pytest.mark.asyncio
async def test_run_sqlite_op_requires_connection(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'no_connect.db'}",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
    )
    db = Database(cfg)

    with pytest.raises(RuntimeError, match="SQLite bağlantısı başlatılmadı"):
        await db._run_sqlite_op(lambda: None)


def test_verify_auth_token_returns_none_on_jwt_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'jwt_error.db'}",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET_KEY="secret",
        JWT_ALGORITHM="HS256",
    )
    db = Database(cfg)

    class _JwtErr(Exception):
        pass

    monkeypatch.setattr("core.db.jwt.PyJWTError", _JwtErr)

    def _raise_decode(*_args, **_kwargs):
        raise _JwtErr("bad token")

    monkeypatch.setattr("core.db.jwt.decode", _raise_decode)
    assert db.verify_auth_token("invalid") is None


def test_get_user_by_token_falls_back_to_jwt_payload_when_db_user_missing(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'fallback_user.db'}",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET_KEY="secret",
        JWT_ALGORITHM="HS256",
    )
    db = Database(cfg)

    db.verify_auth_token = lambda _token: SimpleNamespace(id="u-1", username="alice", role="admin", tenant_id="tenant-a")
    db._get_user_by_id = lambda _user_id: __import__("asyncio").sleep(0, result=None)

    import asyncio
    resolved = asyncio.run(db.get_user_by_token("opaque"))

    assert resolved is not None
    assert resolved.id == "u-1"
    assert resolved.role == "admin"
