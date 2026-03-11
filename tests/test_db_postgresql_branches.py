import asyncio
import builtins
from collections import deque
from types import SimpleNamespace

import pytest

from core.db import Database


class _AcquireCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self):
        self.execute_calls = []
        self.fetchrow_queue = deque()
        self.fetch_queue = deque()
        self.fetchval_queue = deque()
        self.execute_queue = deque()

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        if self.execute_queue:
            return self.execute_queue.popleft()
        return "EXECUTE 1"

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
        self.closed = False

    def acquire(self):
        return _AcquireCtx(self.conn)

    async def close(self):
        self.closed = True


def _pg_db():
    cfg = SimpleNamespace(
        DATABASE_URL="postgresql://user:pass@localhost:5432/sidar",
        DB_POOL_SIZE=3,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=2,
    )
    db = Database(cfg=cfg)
    conn = _FakeConn()
    pool = _FakePool(conn)
    db._pg_pool = pool
    return db, conn, pool


def test_connect_postgresql_reports_missing_asyncpg(monkeypatch):
    cfg = SimpleNamespace(DATABASE_URL="postgresql://u:p@localhost/db", DB_POOL_SIZE=2)
    db = Database(cfg=cfg)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "asyncpg":
            raise ImportError("missing asyncpg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError):
        asyncio.run(db.connect())


def test_postgresql_branches_for_schema_user_session_and_quota():
    db, conn, pool = _pg_db()

    async def _run():
        await db.init_schema()

        # ensure_user existing then create path
        conn.fetchrow_queue.append({"id": "u-1", "username": "alice", "role": "admin", "created_at": "now"})
        found = await db.ensure_user("alice", role="admin")
        assert found.id == "u-1"

        conn.fetchrow_queue.append(None)
        created = await db.ensure_user("bob", role="user")
        assert created.username == "bob"

        # auth paths
        conn.fetchrow_queue.append({"id": "u-1", "username": "alice", "password_hash": None, "role": "admin", "created_at": "now"})
        assert await db.authenticate_user("alice", "pw") is None

        conn.fetchrow_queue.append({"id": "u-1", "username": "alice", "password_hash": "pbkdf2_sha256$s$dead", "role": "admin", "created_at": "now"})
        assert await db.authenticate_user("alice", "pw") is None

        # session listing/loading
        conn.fetch_queue.append([
            {"id": "s1", "user_id": "u-1", "title": "t", "created_at": "c", "updated_at": "u"}
        ])
        sessions = await db.list_sessions("u-1")
        assert sessions[0].id == "s1"

        conn.fetchrow_queue.append({"id": "s1", "user_id": "u-1", "title": "t", "created_at": "c", "updated_at": "u"})
        assert (await db.load_session("s1", user_id="u-1")) is not None

        conn.fetchrow_queue.append(None)
        assert await db.load_session("missing") is None

        # update/delete branches
        conn.execute_queue.extend(["UPDATE 1", "UPDATE 0", "DELETE 1", "DELETE 0"])
        assert await db.update_session_title("s1", "new") is True
        assert await db.update_session_title("s1", "new2") is False
        assert await db.delete_session("s1") is True
        assert await db.delete_session("missing", user_id="u-1") is False

        # token + quotas + usage + quota status
        tok = await db.create_auth_token("u-1", ttl_days=1)
        assert tok.user_id == "u-1"

        conn.fetchrow_queue.append({"id": "u-1", "username": "alice", "role": "admin", "created_at": "now"})
        assert (await db.get_user_by_token(tok.token)) is not None

        await db.upsert_user_quota("u-1", daily_token_limit=100, daily_request_limit=4)
        await db.record_provider_usage_daily("u-1", "OpenAI", tokens_used=40, requests_inc=2)

        conn.fetchrow_queue.append({"daily_token_limit": 100, "daily_request_limit": 4})
        conn.fetchrow_queue.append({"requests_used": 4, "tokens_used": 100})
        status = await db.get_user_quota_status("u-1", "openai")
        assert status["token_limit_exceeded"] is True
        assert status["request_limit_exceeded"] is True

        # list users + admin stats
        conn.fetch_queue.append([
            {
                "id": "u-1",
                "username": "alice",
                "role": "admin",
                "created_at": "now",
                "daily_token_limit": 100,
                "daily_request_limit": 4,
            }
        ])
        users = await db.list_users_with_quotas()
        assert users[0]["daily_token_limit"] == 100

        conn.fetch_queue.append([
            {
                "id": "u-1",
                "username": "alice",
                "role": "admin",
                "created_at": "now",
                "daily_token_limit": 100,
                "daily_request_limit": 4,
            }
        ])
        conn.fetchrow_queue.append({"total_tokens_used": 100, "total_api_requests": 4})
        stats = await db.get_admin_stats()
        assert stats["total_tokens_used"] == 100

        # message branches
        await db.create_session("u-1", "title")
        conn.fetchrow_queue.append({"id": 7})
        msg = await db.add_message("s1", "user", "hello", 5)
        assert msg.id == 7

        conn.fetch_queue.append([
            {"id": 7, "session_id": "s1", "role": "user", "content": "hello", "tokens_used": 5, "created_at": "now"}
        ])
        msgs = await db.get_session_messages("s1")
        assert msgs[0].content == "hello"

        await db.close()

    asyncio.run(_run())
    assert pool.closed is True
    assert any("CREATE TABLE IF NOT EXISTS users" in q for q, _ in conn.execute_calls)
