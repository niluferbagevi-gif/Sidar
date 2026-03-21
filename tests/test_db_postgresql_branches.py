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


class _TransactionCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConn:
    def __init__(self):
        self.execute_calls = []
        self.fetchrow_queue = deque()
        self.fetch_queue = deque()
        self.fetchval_queue = deque()
        self.execute_queue = deque()
        self.transaction_calls = 0

    def transaction(self):
        self.transaction_calls += 1
        return _TransactionCtx()

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        await asyncio.sleep(0)
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


def test_postgresql_prompt_and_policy_branches_with_filters_and_validation():
    db, conn, _pool = _pg_db()

    async def _run():
        conn.fetch_queue.append([
            {
                "id": 1,
                "role_name": "system",
                "prompt_text": "p",
                "version": 1,
                "is_active": True,
                "created_at": "c",
                "updated_at": "u",
            }
        ])
        prompts = await db.list_prompts()
        assert prompts[0].role_name == "system"

        conn.fetch_queue.append([
            {
                "id": 2,
                "role_name": "coder",
                "prompt_text": "p2",
                "version": 2,
                "is_active": False,
                "created_at": "c2",
                "updated_at": "u2",
            }
        ])
        filtered_prompts = await db.list_prompts("coder")
        assert filtered_prompts[0].version == 2

        conn.fetch_queue.append([
            {
                "id": 3,
                "user_id": "u-1",
                "tenant_id": "t1",
                "resource_type": "rag",
                "resource_id": "*",
                "action": "read",
                "effect": "allow",
                "created_at": "c",
                "updated_at": "u",
            }
        ])
        policies = await db.list_access_policies("u-1")
        assert policies[0].resource_type == "rag"

        conn.fetch_queue.append([
            {
                "id": 4,
                "user_id": "u-1",
                "tenant_id": "t2",
                "resource_type": "github",
                "resource_id": "repo",
                "action": "write",
                "effect": "deny",
                "created_at": "c",
                "updated_at": "u",
            }
        ])
        tenant_policies = await db.list_access_policies("u-1", tenant_id="t2")
        assert tenant_policies[0].tenant_id == "t2"

        await db.upsert_access_policy(
            user_id="u-1",
            tenant_id="t1",
            resource_type="rag",
            resource_id="*",
            action="read",
            effect="allow",
        )

        with pytest.raises(ValueError):
            await db.upsert_access_policy(
                user_id="u-1",
                tenant_id="t1",
                resource_type="rag",
                resource_id="*",
                action="read",
                effect="bad",
            )

        with pytest.raises(ValueError):
            await db.upsert_access_policy(
                user_id="u-1",
                tenant_id="t1",
                resource_type="",
                resource_id="*",
                action="",
                effect="allow",
            )

    asyncio.run(_run())

def test_connect_postgresql_pool_creation_failure_bubbles(monkeypatch):
    cfg = SimpleNamespace(DATABASE_URL="postgresql://u:p@localhost/db", DB_POOL_SIZE=2)
    db = Database(cfg=cfg)

    class _Asyncpg:
        @staticmethod
        async def create_pool(**_kwargs):
            raise RuntimeError("pool init failed")

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "asyncpg":
            return _Asyncpg
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError):
        asyncio.run(db.connect())


def test_postgresql_session_create_and_delete_parse_edge_cases():
    db, conn, _pool = _pg_db()

    async def _run():
        created = await db.create_session("u-1", "title")
        assert created.user_id == "u-1"

        conn.execute_queue.append("DELETE ???")
        deleted = await db.delete_session(created.id)
        assert deleted is False

    asyncio.run(_run())


def test_connect_postgresql_normalizes_asyncpg_scheme(monkeypatch):
    seen = {}
    cfg = SimpleNamespace(DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", DB_POOL_SIZE=4)
    db = Database(cfg=cfg)

    class _Asyncpg:
        @staticmethod
        async def create_pool(**kwargs):
            seen.update(kwargs)
            return _FakePool(_FakeConn())

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "asyncpg":
            return _Asyncpg
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    asyncio.run(db.connect())

    assert seen["dsn"].startswith("postgresql://")
    assert "+asyncpg" not in seen["dsn"]


def test_postgresql_update_session_title_parse_failure_returns_false():
    db, conn, _pool = _pg_db()

    async def _run():
        conn.execute_queue.append("UPDATE not-a-number")
        ok = await db.update_session_title("s1", "new")
        assert ok is False

    asyncio.run(_run())


def test_postgresql_schema_version_early_return_when_already_current():
    db, conn, _pool = _pg_db()

    async def _run():
        conn.fetchval_queue.append(2)
        await db._ensure_schema_version_postgresql()

    asyncio.run(_run())
    inserts = [q for q, _args in conn.execute_calls if "INSERT INTO" in q]
    assert inserts == []

def test_postgresql_replace_session_messages_supports_concurrent_replacements():
    cfg = SimpleNamespace(
        DATABASE_URL="postgresql://user:pass@localhost:5432/sidar",
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=2,
    )
    db = Database(cfg=cfg)
    conn_a = _FakeConn()
    conn_b = _FakeConn()

    class _RoundRobinPool:
        def __init__(self, conns):
            self._conns = deque(conns)

        def acquire(self):
            conn = self._conns[0]
            self._conns.rotate(-1)
            return _AcquireCtx(conn)

    db._pg_pool = _RoundRobinPool([conn_a, conn_b])

    async def _run():
        first, second = await asyncio.gather(
            db.replace_session_messages(
                "sess-1",
                [
                    {"role": " user ", "content": " first payload "},
                    {"role": "assistant", "content": "   "},
                ],
            ),
            db.replace_session_messages(
                "sess-1",
                [{"role": "", "content": " second payload "}],
            ),
        )

        assert first == 1
        assert second == 1

    asyncio.run(_run())

    for conn in (conn_a, conn_b):
        assert conn.transaction_calls == 1
        assert len(conn.execute_calls) == 3
        assert "DELETE FROM messages WHERE session_id=$1" in conn.execute_calls[0][0]
        assert "INSERT INTO messages" in conn.execute_calls[1][0]
        assert "UPDATE sessions SET updated_at=$2 WHERE id=$1" in conn.execute_calls[2][0]
        assert conn.execute_calls[0][1] == ("sess-1",)
        assert conn.execute_calls[2][1][0] == "sess-1"

    insert_payloads = {conn.execute_calls[1][1][1:4] for conn in (conn_a, conn_b)}
    assert insert_payloads == {
        ("user", "first payload", 0),
        ("assistant", "second payload", 0),
    }
