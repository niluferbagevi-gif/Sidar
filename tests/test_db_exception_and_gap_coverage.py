import asyncio
import builtins
import sqlite3
from types import SimpleNamespace

import jwt
import pytest

from core.db import Database, _quote_sql_identifier


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePgConn:
    def __init__(self):
        self.fetchrow_results = []
        self.fetch_results = []
        self.execute_calls = []

    async def fetchrow(self, query, *args):
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None

    async def fetch(self, query, *args):
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return []

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "EXECUTE 1"


class _FakePgPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AcquireCtx(self._conn)


class _SchemaFailConn:
    def __init__(self):
        self.insert_calls = 0

    def execute(self, query, *args):
        normalized = " ".join(query.split())
        if normalized.startswith("SELECT MAX(version)"):
            return SimpleNamespace(fetchone=lambda: {"v": 0})
        if normalized.startswith("INSERT INTO"):
            self.insert_calls += 1
            raise sqlite3.IntegrityError("duplicate migration")
        return SimpleNamespace(fetchone=lambda: None)

    def commit(self):
        return None


class _Cfg:
    DB_POOL_SIZE = 2
    DB_SCHEMA_VERSION_TABLE = "schema_versions"
    DB_SCHEMA_TARGET_VERSION = 2
    JWT_SECRET_KEY = "sidar-dev-secret"
    JWT_ALGORITHM = "HS256"


async def _sqlite_db(tmp_path):
    cfg = _Cfg()
    cfg.BASE_DIR = tmp_path
    cfg.DATABASE_URL = f"sqlite+aiosqlite:///{(tmp_path / 'sidar.db').as_posix()}"
    db = Database(cfg=cfg)
    await db.connect()
    await db.init_schema()
    return db


def test_quote_sql_identifier_rejects_empty_and_invalid_values():
    with pytest.raises(ValueError, match="cannot be empty"):
        _quote_sql_identifier("")

    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        _quote_sql_identifier("9-invalid-name")


def test_connect_postgresql_missing_asyncpg_and_sqlite_disk_error(monkeypatch, tmp_path):
    pg_cfg = SimpleNamespace(DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", DB_POOL_SIZE=1)
    pg_db = Database(cfg=pg_cfg)
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "asyncpg":
            raise ImportError("asyncpg yok")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(RuntimeError, match="asyncpg bağımlılığı gerekli"):
        asyncio.run(pg_db.connect())

    sqlite_cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{(tmp_path / 'disk_fail.db').as_posix()}",
        BASE_DIR=tmp_path,
    )
    sqlite_db = Database(cfg=sqlite_cfg)
    monkeypatch.setattr(sqlite3, "connect", lambda *_a, **_k: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        asyncio.run(sqlite_db.connect())


def test_sqlite_access_control_schema_adds_missing_tenant_id(tmp_path):
    async def _run():
        db = await _sqlite_db(tmp_path)
        assert db._sqlite_conn is not None
        db._sqlite_conn.execute("DROP TABLE access_policies")
        db._sqlite_conn.execute("DROP TABLE users")
        db._sqlite_conn.execute(
            "CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT NOT NULL, password_hash TEXT, role TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        db._sqlite_conn.commit()

        await db._ensure_access_control_schema_sqlite()

        cols = db._sqlite_conn.execute("PRAGMA table_info(users)").fetchall()
        col_names = {str(col[1]) for col in cols}
        await db.close()
        return col_names

    assert "tenant_id" in asyncio.run(_run())


def test_sqlite_schema_version_integrity_error_bubbles(tmp_path):
    cfg = _Cfg()
    cfg.BASE_DIR = tmp_path
    cfg.DATABASE_URL = f"sqlite+aiosqlite:///{(tmp_path / 'schema_fail.db').as_posix()}"
    db = Database(cfg=cfg)
    db._sqlite_conn = _SchemaFailConn()
    db._sqlite_lock = asyncio.Lock()

    with pytest.raises(sqlite3.IntegrityError, match="duplicate migration"):
        asyncio.run(db._ensure_schema_version_sqlite())

    assert db._sqlite_conn.insert_calls == 1


def test_prompt_registry_and_activation_gap_branches(tmp_path):
    async def _run():
        db = await _sqlite_db(tmp_path)

        prompts = await db.list_prompts()
        assert prompts

        assert await db.get_active_prompt("") is None
        with pytest.raises(ValueError, match="boş olamaz"):
            await db.upsert_prompt("", "")

        assert await db.activate_prompt(0) is None
        assert await db.activate_prompt(999999) is None

        await db.close()

    asyncio.run(_run())


def test_configure_backend_resolves_plain_sqlite_triple_slash_paths(tmp_path):
    cfg = SimpleNamespace(
        DATABASE_URL="sqlite:///relative/db.sqlite",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
    )

    db = Database(cfg=cfg)

    assert db._backend == "sqlite"
    assert db._sqlite_path == tmp_path / "relative" / "db.sqlite"


def test_postgresql_prompt_and_user_lookup_gap_branches():
    cfg = SimpleNamespace(
        DATABASE_URL="postgresql://user:pass@localhost:5432/sidar",
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET_KEY="sidar-dev-secret",
        JWT_ALGORITHM="HS256",
    )
    db = Database(cfg=cfg)
    conn = _FakePgConn()
    db._pg_pool = _FakePgPool(conn)

    async def _run():
        conn.fetchrow_results.append({
            "id": 3,
            "role_name": "system",
            "prompt_text": "aktif prompt",
            "version": 7,
            "is_active": True,
            "created_at": "now",
            "updated_at": "now",
        })
        active = await db.get_active_prompt("system")
        assert active is not None and active.version == 7

        assert await db._get_user_by_id("missing-user") is None

        conn.fetchrow_results.append(None)
        assert await db.activate_prompt(42) is None

        conn.fetchrow_results.append({"id": 8, "role_name": "assistant"})
        conn.fetchrow_results.append({
            "id": 8,
            "role_name": "assistant",
            "prompt_text": "aktifleşti",
            "version": 2,
            "is_active": True,
            "created_at": "now",
            "updated_at": "now",
        })
        activated = await db.activate_prompt(8)
        assert activated is not None and activated.id == 8
        assert len(conn.execute_calls) >= 2

    asyncio.run(_run())


def test_verify_auth_token_missing_role_returns_none_and_sqlite_user_lookup_missing(tmp_path):
    async def _run():
        db = await _sqlite_db(tmp_path)
        assert await db._get_user_by_id("missing-user") is None

        payload = {"sub": "user-1", "username": "alice", "tenant_id": "tenant-A"}
        token = jwt.encode(payload, db.cfg.JWT_SECRET_KEY, algorithm=db.cfg.JWT_ALGORITHM)
        assert db.verify_auth_token(token) is None

        await db.close()

    asyncio.run(_run())


def test_list_access_policies_without_tenant_and_policy_fallback_and_deny(tmp_path):
    async def _run():
        db = await _sqlite_db(tmp_path)
        user = await db.create_user("policy-user", password="123456", tenant_id="default")

        await db.upsert_access_policy(
            user_id=user.id,
            tenant_id="default",
            resource_type="rag",
            resource_id="*",
            action="read",
            effect="allow",
        )
        await db.upsert_access_policy(
            user_id=user.id,
            tenant_id="default",
            resource_type="rag",
            resource_id="doc-1",
            action="read",
            effect="deny",
        )

        all_policies = await db.list_access_policies(user.id)
        assert len(all_policies) == 2

        assert await db.check_access_policy(
            user_id="",
            tenant_id="default",
            resource_type="rag",
            action="read",
            resource_id="doc-1",
        ) is False

        assert await db.check_access_policy(
            user_id=user.id,
            tenant_id="tenant-X",
            resource_type="rag",
            action="read",
            resource_id="other-doc",
        ) is True

        assert await db.check_access_policy(
            user_id=user.id,
            tenant_id="tenant-X",
            resource_type="rag",
            action="read",
            resource_id="doc-1",
        ) is False

        await db.close()

    asyncio.run(_run())