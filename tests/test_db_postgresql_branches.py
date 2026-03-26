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
        self.fetchrow_calls = []
        self.fetch_calls = []
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
        self.fetchrow_calls.append((query, args))
        if self.fetchrow_queue:
            return self.fetchrow_queue.popleft()
        return None

    async def fetch(self, query, *args):
        self.fetch_calls.append((query, args))
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


def test_connect_postgresql_generic_pool_failure_logs_warning(monkeypatch):
    cfg = SimpleNamespace(DATABASE_URL="postgresql://u:p@localhost/db", DB_POOL_SIZE=2)
    db = Database(cfg=cfg)
    warnings = []

    class _Asyncpg:
        @staticmethod
        async def create_pool(**_kwargs):
            raise RuntimeError("socket closed")

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "asyncpg":
            return _Asyncpg
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr("core.db.logger.warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    with pytest.raises(RuntimeError, match="socket closed"):
        asyncio.run(db.connect())

    assert any("oluşturulamadı" in msg for msg in warnings)


def test_postgresql_session_create_and_delete_parse_edge_cases():
    db, conn, _pool = _pg_db()

    async def _run():
        created = await db.create_session("u-1", "title")
        assert created.user_id == "u-1"

        conn.execute_queue.append("DELETE ???")
        deleted = await db.delete_session(created.id)
        assert deleted is False

    asyncio.run(_run())


def test_postgresql_prompt_and_operations_queries_cover_optional_filters_and_inactive_prompt():
    db, conn, _pool = _pg_db()

    async def _run():
        conn.fetchval_queue.append(0)
        conn.fetchrow_queue.append(
            {
                "id": 5,
                "role_name": "reviewer",
                "prompt_text": "Draft prompt",
                "version": 1,
                "is_active": False,
                "created_at": "now",
                "updated_at": "now",
            }
        )
        created = await db.upsert_prompt("reviewer", "Draft prompt", activate=False)
        assert created.is_active is False

        conn.fetch_queue.append(
            [{
                "id": 11,
                "tenant_id": "tenant-a",
                "name": "Campaign",
                "channel": "email",
                "objective": "launch",
                "status": "draft",
                "owner_user_id": "u-1",
                "budget": 1.0,
                "metadata_json": "{}",
                "created_at": "c1",
                "updated_at": "u1",
            }]
        )
        campaigns = await db.list_marketing_campaigns(tenant_id="tenant-a", status=None, limit=1)
        assert campaigns[0].status == "draft"

        conn.fetch_queue.append(
            [{
                "id": 21,
                "campaign_id": 11,
                "tenant_id": "tenant-a",
                "asset_type": "landing_page",
                "title": "LP",
                "content": "<main/>",
                "channel": "web",
                "metadata_json": "{}",
                "created_at": "c2",
                "updated_at": "u2",
            }]
        )
        assets = await db.list_content_assets(tenant_id="tenant-a", campaign_id=None, limit=1)
        assert assets[0].campaign_id == 11

        conn.fetchrow_queue.append(
            {
                "id": 31,
                "campaign_id": 11,
                "tenant_id": "tenant-a",
                "title": "Ops",
                "items_json": '["step"]',
                "status": "pending",
                "owner_user_id": "",
                "created_at": "c3",
                "updated_at": "u3",
            }
        )
        checklist = await db.add_operation_checklist(
            campaign_id=None,
            tenant_id="tenant-a",
            title="Ops",
            items=[{}, " step "],
            status="pending",
            owner_user_id="",
        )
        assert checklist.items_json == '["step"]'

        conn.fetch_queue.append(
            [{
                "id": 31,
                "campaign_id": 11,
                "tenant_id": "tenant-a",
                "title": "Ops",
                "items_json": '["step"]',
                "status": "pending",
                "owner_user_id": "",
                "created_at": "c3",
                "updated_at": "u3",
            }]
        )
        checklists = await db.list_operation_checklists(tenant_id="tenant-a", campaign_id=None, limit=1)
        assert checklists[0].campaign_id == 11

    asyncio.run(_run())

    assert conn.execute_calls == []
    prompt_insert_query, prompt_insert_args = conn.fetchrow_calls[0]
    assert "INSERT INTO prompt_registry" in prompt_insert_query
    assert prompt_insert_args[3] is False

    campaigns_query, campaigns_args = conn.fetch_calls[0]
    assert "AND status=$2" not in campaigns_query
    assert campaigns_args == ("tenant-a", 1)

    assets_query, assets_args = conn.fetch_calls[1]
    assert "AND campaign_id=$2" not in assets_query
    assert assets_args == ("tenant-a", 1)

    checklist_insert_query, checklist_insert_args = conn.fetchrow_calls[1]
    assert "INSERT INTO operation_checklists" in checklist_insert_query
    assert checklist_insert_args[3] == '["step"]'

    checklists_query, checklists_args = conn.fetch_calls[2]
    assert "AND campaign_id=$2" not in checklists_query
    assert checklists_args == ("tenant-a", 1)


def test_postgresql_get_active_prompt_none_and_list_coverage_tasks_query_variants():
    db, conn, _pool = _pg_db()

    async def _run():
        assert await db.get_active_prompt("system") is None

        conn.fetch_queue.append(
            [
                {
                    "id": 41,
                    "tenant_id": "tenant-a",
                    "requester_role": "coverage",
                    "command": "pytest -q",
                    "pytest_output": "ok",
                    "status": "pending_review",
                    "target_path": "core/db.py",
                    "suggested_test_path": "tests/test_db_runtime.py",
                    "review_payload_json": "{}",
                    "created_at": "now",
                    "updated_at": "now",
                }
            ]
        )
        tasks_all = await db.list_coverage_tasks(tenant_id="tenant-a", status=None, limit=2)

        conn.fetch_queue.append(
            [
                {
                    "id": 42,
                    "tenant_id": "tenant-a",
                    "requester_role": "coverage",
                    "command": "pytest -q",
                    "pytest_output": "ok",
                    "status": "pending_review",
                    "target_path": "core/db.py",
                    "suggested_test_path": "tests/test_db_runtime.py",
                    "review_payload_json": "{}",
                    "created_at": "now",
                    "updated_at": "now",
                }
            ]
        )
        tasks_filtered = await db.list_coverage_tasks(tenant_id="tenant-a", status="pending_review", limit=1)

        assert tasks_all[0].id == 41
        assert tasks_filtered[0].id == 42

    asyncio.run(_run())

    active_prompt_query, active_prompt_args = conn.fetchrow_calls[0]
    assert "FROM prompt_registry" in active_prompt_query
    assert active_prompt_args == ("system",)

    list_all_query, list_all_args = conn.fetch_calls[0]
    assert "AND status=$2" not in list_all_query
    assert list_all_args == ("tenant-a", 2)

    list_filtered_query, list_filtered_args = conn.fetch_calls[1]
    assert "AND status=$2" in list_filtered_query
    assert list_filtered_args == ("tenant-a", "pending_review", 1)


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


def test_postgresql_marketing_operations_and_coverage_crud_branches():
    db, conn, _pool = _pg_db()

    async def _run():
        with pytest.raises(ValueError, match="campaign name is required"):
            await db.upsert_marketing_campaign(name=" ")

        conn.fetchrow_queue.append({
            "id": 11,
            "tenant_id": "tenant-a",
            "name": "Launch",
            "channel": "instagram",
            "objective": "lead",
            "status": "draft",
            "owner_user_id": "u-1",
            "budget": 25.0,
            "metadata_json": '{"region":"TR"}',
            "created_at": "c1",
            "updated_at": "u1",
        })
        created = await db.upsert_marketing_campaign(
            tenant_id="tenant-a",
            name="Launch",
            channel="instagram",
            objective="lead",
            owner_user_id="u-1",
            budget=25.0,
            metadata={"region": "TR"},
        )
        assert created.id == 11

        conn.fetchrow_queue.append({
            "id": 11,
            "tenant_id": "tenant-a",
            "name": "Launch v2",
            "channel": "linkedin",
            "objective": "pipeline",
            "status": "active",
            "owner_user_id": "u-2",
            "budget": 40.0,
            "metadata_json": '{"segment":"b2b"}',
            "created_at": "c1",
            "updated_at": "u2",
        })
        updated = await db.upsert_marketing_campaign(
            campaign_id=11,
            tenant_id="tenant-a",
            name="Launch v2",
            channel="linkedin",
            objective="pipeline",
            status="ACTIVE",
            owner_user_id="u-2",
            budget=40.0,
            metadata={"segment": "b2b"},
        )
        assert updated.status == "active"

        conn.fetchrow_queue.append(None)
        with pytest.raises(ValueError, match="campaign not found"):
            await db.upsert_marketing_campaign(campaign_id=999, tenant_id="tenant-a", name="missing")

        conn.fetch_queue.append([
            {
                "id": 11,
                "tenant_id": "tenant-a",
                "name": "Launch v2",
                "channel": "linkedin",
                "objective": "pipeline",
                "status": "active",
                "owner_user_id": "u-2",
                "budget": 40.0,
                "metadata_json": '{"segment":"b2b"}',
                "created_at": "c1",
                "updated_at": "u2",
            }
        ])
        campaigns = await db.list_marketing_campaigns(tenant_id="tenant-a", status="active", limit=1)
        assert campaigns[0].channel == "linkedin"

        with pytest.raises(ValueError, match="asset_type, title and content are required"):
            await db.add_content_asset(campaign_id=11, asset_type="", title="", content="")

        conn.fetchrow_queue.append({
            "id": 21,
            "campaign_id": 11,
            "tenant_id": "tenant-a",
            "asset_type": "landing_page",
            "title": "LP",
            "content": "<main/>",
            "channel": "web",
            "metadata_json": '{"lang":"tr"}',
            "created_at": "c2",
            "updated_at": "u2",
        })
        asset = await db.add_content_asset(
            campaign_id=11,
            tenant_id="tenant-a",
            asset_type="landing_page",
            title="LP",
            content="<main/>",
            channel="web",
            metadata={"lang": "tr"},
        )
        assert asset.id == 21

        conn.fetch_queue.append([
            {
                "id": 21,
                "campaign_id": 11,
                "tenant_id": "tenant-a",
                "asset_type": "landing_page",
                "title": "LP",
                "content": "<main/>",
                "channel": "web",
                "metadata_json": '{"lang":"tr"}',
                "created_at": "c2",
                "updated_at": "u2",
            }
        ])
        assets = await db.list_content_assets(tenant_id="tenant-a", campaign_id=11, limit=1)
        assert assets[0].campaign_id == 11

        with pytest.raises(ValueError, match="title is required"):
            await db.add_operation_checklist(title=" ", items=[])

        conn.fetchrow_queue.append({
            "id": 31,
            "campaign_id": 11,
            "tenant_id": "tenant-a",
            "title": "Ops",
            "items_json": '[{"type":"vendor"}]',
            "status": "planned",
            "owner_user_id": "u-1",
            "created_at": "c3",
            "updated_at": "u3",
        })
        checklist = await db.add_operation_checklist(
            campaign_id=11,
            tenant_id="tenant-a",
            title="Ops",
            items=[{"type": "vendor"}],
            status="planned",
            owner_user_id="u-1",
        )
        assert checklist.id == 31

        conn.fetch_queue.append([
            {
                "id": 31,
                "campaign_id": 11,
                "tenant_id": "tenant-a",
                "title": "Ops",
                "items_json": '[{"type":"vendor"}]',
                "status": "planned",
                "owner_user_id": "u-1",
                "created_at": "c3",
                "updated_at": "u3",
            }
        ])
        checklists = await db.list_operation_checklists(tenant_id="tenant-a", campaign_id=11, limit=1)
        assert checklists[0].status == "planned"

        with pytest.raises(ValueError, match="command is required"):
            await db.create_coverage_task(command=" ", pytest_output="")

        conn.fetchrow_queue.append({
            "id": 41,
            "tenant_id": "tenant-a",
            "requester_role": "coverage",
            "command": "pytest -q",
            "pytest_output": "1 failed",
            "status": "pending_review",
            "target_path": "core/db.py",
            "suggested_test_path": "tests/test_db_postgresql_branches.py",
            "review_payload_json": '{"decision":"pending"}',
            "created_at": "c4",
            "updated_at": "u4",
        })
        task = await db.create_coverage_task(
            tenant_id="tenant-a",
            requester_role="coverage",
            command="pytest -q",
            pytest_output="1 failed",
            status="pending_review",
            target_path="core/db.py",
            suggested_test_path="tests/test_db_postgresql_branches.py",
            review_payload_json='{"decision":"pending"}',
        )
        assert task.id == 41

        with pytest.raises(ValueError, match="finding_type and summary are required"):
            await db.add_coverage_finding(task_id=41, finding_type="", target_path="", summary="")

        conn.fetchrow_queue.append({
            "id": 51,
            "task_id": 41,
            "finding_type": "missing_coverage",
            "target_path": "core/db.py",
            "summary": "Eksik satırlar",
            "severity": "high",
            "details_json": '{"lines":[1,2]}',
            "created_at": "c5",
        })
        finding = await db.add_coverage_finding(
            task_id=41,
            finding_type="missing_coverage",
            target_path="core/db.py",
            summary="Eksik satırlar",
            severity="high",
            details={"lines": [1, 2]},
        )
        assert finding.id == 51

        conn.fetch_queue.append([
            {
                "id": 41,
                "tenant_id": "tenant-a",
                "requester_role": "coverage",
                "command": "pytest -q",
                "pytest_output": "1 failed",
                "status": "pending_review",
                "target_path": "core/db.py",
                "suggested_test_path": "tests/test_db_postgresql_branches.py",
                "review_payload_json": '{"decision":"pending"}',
                "created_at": "c4",
                "updated_at": "u4",
            }
        ])
        tasks = await db.list_coverage_tasks(tenant_id="tenant-a", status="pending_review", limit=1)
        assert tasks[0].target_path == "core/db.py"

    asyncio.run(_run())