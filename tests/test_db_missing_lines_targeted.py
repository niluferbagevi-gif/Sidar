import asyncio
import importlib.util
import json
import sys
import types
from collections import deque
from pathlib import Path
from types import SimpleNamespace


def _load_db_module():
    jwt_mod = types.ModuleType("jwt")

    class _PyJWTError(Exception):
        pass

    def _encode(payload, secret, algorithm="HS256"):
        del secret, algorithm
        return json.dumps(payload)

    def _decode(token, secret, algorithms=None):
        del secret, algorithms
        try:
            return json.loads(token)
        except Exception as exc:
            raise _PyJWTError("invalid") from exc

    jwt_mod.encode = _encode
    jwt_mod.decode = _decode
    jwt_mod.PyJWTError = _PyJWTError
    sys.modules["jwt"] = jwt_mod

    spec = importlib.util.spec_from_file_location("db_under_test", Path("core/db.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _AcquireCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self):
        self.fetchrow_queue = deque()
        self.fetch_queue = deque()
        self.fetchval_queue = deque()
        self.execute_queue = deque()

    async def execute(self, query, *args):
        if self.execute_queue:
            return self.execute_queue.popleft()
        return "OK 1"

    async def fetchrow(self, query, *args):
        if self.fetchrow_queue:
            return self.fetchrow_queue.popleft()
        return None

    async def fetch(self, query, *args):
        if self.fetch_queue:
            return self.fetch_queue.popleft()
        return []

    async def fetchval(self, query, *args):
        if self.fetchval_queue:
            return self.fetchval_queue.popleft()
        return 0


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AcquireCtx(self.conn)


def _sqlite_db(mod, tmp_path):
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        BASE_DIR=tmp_path,
        JWT_SECRET_KEY="dev",
        JWT_ALGORITHM="HS256",
    )
    return mod.Database(cfg=cfg)


def _pg_db(mod):
    cfg = SimpleNamespace(
        DATABASE_URL="postgresql://u:p@localhost/db",
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET_KEY="dev",
        JWT_ALGORITHM="HS256",
    )
    db = mod.Database(cfg=cfg)
    conn = _FakeConn()
    db._pg_pool = _FakePool(conn)
    return db, conn


def test_quote_identifier_and_sqlite_prompt_policy_guards(tmp_path):
    mod = _load_db_module()
    try:
        mod._quote_sql_identifier("")
        assert False
    except ValueError:
        pass
    try:
        mod._quote_sql_identifier("1bad-name")
        assert False
    except ValueError:
        pass

    db = _sqlite_db(mod, tmp_path)

    async def _run():
        await db.connect()
        db.ensure_default_prompt_registry = lambda: asyncio.sleep(0)
        await db.init_schema()

        assert await db.get_active_prompt("") is None

        try:
            await db.upsert_prompt("", "x")
            assert False
        except ValueError:
            pass

        assert await db.activate_prompt(0) is None

        assert await db.check_access_policy(user_id="", resource_type="rag", action="read") is False

        u = await db.ensure_user("policy_user")
        await db.upsert_access_policy(user_id=u.id, tenant_id="default", resource_type="rag", resource_id="*", action="read", effect="allow")
        assert await db.check_access_policy(user_id=u.id, tenant_id="tenant-a", resource_type="rag", action="read", resource_id="x") is True

        await db.upsert_access_policy(user_id=u.id, tenant_id="default", resource_type="rag", resource_id="x", action="read", effect="deny")
        assert await db.check_access_policy(user_id=u.id, tenant_id="tenant-a", resource_type="rag", action="read", resource_id="x") is False

        try:
            await db.upsert_access_policy(user_id=u.id, resource_type="rag", action="read", effect="maybe")
            assert False
        except ValueError:
            pass

        try:
            await db.upsert_access_policy(user_id=u.id, resource_type="", action="")
            assert False
        except ValueError:
            pass

        await db.close()

    asyncio.run(_run())


def test_sqlite_access_schema_alter_and_user_lookup_none_paths(tmp_path):
    mod = _load_db_module()
    db = _sqlite_db(mod, tmp_path)

    async def _run():
        await db.connect()
        assert db._sqlite_conn is not None
        db._sqlite_conn.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT, role TEXT NOT NULL DEFAULT 'user', created_at TEXT NOT NULL)")
        db._sqlite_conn.commit()

        await db._ensure_access_control_schema_sqlite()
        cols = db._sqlite_conn.execute("PRAGMA table_info(users)").fetchall()
        assert any(c[1] == "tenant_id" for c in cols)

        assert await db._get_user_by_id("missing") is None
        await db.close()

    asyncio.run(_run())


def test_postgresql_prompt_policy_and_parse_fallback_paths(tmp_path):
    mod = _load_db_module()
    db, conn = _pg_db(mod)

    async def _run():
        conn.fetch_queue.append([
            {"id": 1, "role_name": "system", "prompt_text": "p", "version": 1, "is_active": True, "created_at": "c", "updated_at": "u"}
        ])
        out = await db.list_prompts("system")
        assert out and out[0].role_name == "system"

        conn.fetch_queue.append([])
        assert await db.list_prompts() == []

        conn.fetchrow_queue.append(None)
        assert await db.get_active_prompt("system") is None
        conn.fetchrow_queue.append({"id": 2, "role_name": "system", "prompt_text": "p2", "version": 2, "is_active": True, "created_at": "c", "updated_at": "u"})
        assert (await db.get_active_prompt("system")).version == 2

        conn.fetchrow_queue.append(None)
        assert await db.activate_prompt(5) is None

        conn.execute_queue.append("UPDATE not-a-number")
        assert await db.update_session_title("s1", "t") is False
        conn.execute_queue.append("DELETE ???")
        assert await db.delete_session("s1") is False

        conn.fetchrow_queue.append(None)
        assert await db._get_user_by_id("nope") is None

        bad_token = json.dumps({"sub": "u1", "role": "", "username": "x"})
        assert db.verify_auth_token(bad_token) is None

        conn.fetch_queue.append([
            {"id": 1, "user_id": "u1", "tenant_id": "t1", "resource_type": "rag", "resource_id": "*", "action": "read", "effect": "allow", "created_at": "c", "updated_at": "u"}
        ])
        rows = await db.list_access_policies("u1", tenant_id="t1")
        assert rows and rows[0].tenant_id == "t1"

        await db.upsert_access_policy(user_id="u1", tenant_id="t1", resource_type="rag", resource_id="*", action="read", effect="allow")

    asyncio.run(_run())
