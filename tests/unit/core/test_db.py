from __future__ import annotations

import json
import importlib.util
import sqlite3
import sys
import types
from dataclasses import dataclass
from datetime import datetime

import jwt
import pytest
from unittest.mock import AsyncMock

from core.db import (
    Database,
    _expires_in,
    _hash_password,
    _json_dumps,
    _quote_sql_identifier,
    _utc_now_iso,
    _verify_password,
)


@dataclass
class DummyCfg:
    DATABASE_URL: str
    BASE_DIR: str
    DB_POOL_SIZE: int = 2
    DB_SCHEMA_VERSION_TABLE: str = "schema_versions"
    DB_SCHEMA_TARGET_VERSION: int = 2
    JWT_SECRET_KEY: str = "test-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_TTL_DAYS: int = 3


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePgAdapter:
    """DB testleri için davranış odaklı, kırılgan olmayan fake PostgreSQL adaptörü."""

    def __init__(self) -> None:
        self.conn = AsyncMock()
        self.closed = False

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self.conn)

    async def close(self) -> None:
        self.closed = True

    def set_timeout_error(self) -> None:
        self.conn.execute.side_effect = TimeoutError("db request timed out")

    def set_conflict_error(self) -> None:
        self.conn.execute.side_effect = RuntimeError("conflict")

    def set_disconnect_error(self) -> None:
        self.conn.execute.side_effect = ConnectionError("database connection lost")


@pytest.mark.asyncio
async def test_init_schema_postgresql_executes_all_queries(tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    db._backend = "postgresql"
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    await db._init_schema_postgresql()

    assert fake_pg.conn.execute.await_count > 20


@pytest.mark.asyncio
async def test_ensure_default_prompt_registry_postgres_branches(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    db._backend = "postgresql"
    db._pg_pool = FakePgAdapter()

    async def _none_active(_role):
        return None

    async def _raise_upsert(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "get_active_prompt", _none_active)
    monkeypatch.setattr(db, "upsert_prompt", _raise_upsert)

    class _Loader:
        def exec_module(self, module):
            module.SIDAR_SYSTEM_PROMPT = "system-prompt"

    monkeypatch.setattr(
        importlib.util,
        "spec_from_file_location",
        lambda *_args, **_kwargs: types.SimpleNamespace(loader=_Loader()),
    )
    monkeypatch.setattr(importlib.util, "module_from_spec", lambda _spec: types.SimpleNamespace())

    await db.ensure_default_prompt_registry()


@pytest.mark.asyncio
async def test_list_prompts_postgresql_role_and_no_role(tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    db._backend = "postgresql"
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    rows = [
        {
            "id": 1,
            "role_name": "system",
            "prompt_text": "p1",
            "version": 1,
            "is_active": True,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        }
    ]
    fake_pg.conn.fetch = AsyncMock(return_value=rows)

    prompts = await db.list_prompts()
    assert prompts[0].role_name == "system"

    prompts2 = await db.list_prompts("system")
    assert prompts2[0].prompt_text == "p1"


def test_helper_functions_basic_contracts() -> None:
    now = _utc_now_iso()
    exp = _expires_in(1)
    assert datetime.fromisoformat(now)
    assert datetime.fromisoformat(exp)

    hashed = _hash_password("abc123")
    assert hashed.startswith("pbkdf2_sha256$")
    assert _verify_password("abc123", hashed)
    assert not _verify_password("wrong", hashed)
    assert not _verify_password("abc123", "invalid")

    assert _quote_sql_identifier("schema_versions") == '"schema_versions"'
    assert _json_dumps({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'


@pytest.mark.parametrize("identifier", ["", "1abc", "bad-name", "bad space"])
def test_quote_sql_identifier_rejects_invalid(identifier: str) -> None:
    with pytest.raises(ValueError):
        _quote_sql_identifier(identifier)


@pytest.mark.asyncio
async def test_user_session_message_lifecycle(sqlite_db: Database) -> None:
    user = await sqlite_db.create_user("alice", role="admin", password="pw")
    auth = await sqlite_db.authenticate_user("alice", "pw")
    assert auth is not None
    assert auth.id == user.id

    session = await sqlite_db.create_session(user.id, "ilk")
    loaded = await sqlite_db.load_session(session.id, user_id=user.id)
    assert loaded is not None
    assert loaded.title == "ilk"

    assert await sqlite_db.update_session_title(session.id, "yeni") is True
    await sqlite_db.add_message(session.id, "user", "merhaba", tokens_used=-5)
    await sqlite_db.add_message(session.id, "assistant", "selam")

    messages = await sqlite_db.get_session_messages(session.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].tokens_used == 0

    replaced = await sqlite_db.replace_session_messages(
        session.id,
        [{"role": "user", "content": "x"}, {"content": ""}, {"content": "y"}],
    )
    assert replaced == 2
    messages = await sqlite_db.get_session_messages(session.id)
    assert [m.content for m in messages] == ["x", "y"]

    sessions = await sqlite_db.list_sessions(user.id)
    assert len(sessions) == 1

    assert await sqlite_db.delete_session(session.id, user_id="wrong") is False
    assert await sqlite_db.delete_session(session.id, user_id=user.id) is True


@pytest.mark.asyncio
async def test_create_duplicate_user_raises_integrity_error(sqlite_db: Database) -> None:
    await sqlite_db.create_user("unique_user", password="pw")
    with pytest.raises(sqlite3.IntegrityError):
        await sqlite_db.create_user("unique_user", password="pw2")


@pytest.mark.asyncio
async def test_prompt_registry_flow(sqlite_db: Database) -> None:
    with pytest.raises(ValueError):
        await sqlite_db.upsert_prompt("", "")

    p1 = await sqlite_db.upsert_prompt("System", "prompt-v1", activate=True)
    p2 = await sqlite_db.upsert_prompt("system", "prompt-v2", activate=False)
    assert p2.version == p1.version + 1
    assert p2.is_active is False

    active = await sqlite_db.get_active_prompt("system")
    assert active is not None
    assert active.prompt_text == "prompt-v1"

    activated = await sqlite_db.activate_prompt(p2.id)
    assert activated is not None
    assert activated.prompt_text == "prompt-v2"

    prompts = await sqlite_db.list_prompts("system")
    assert len(prompts) >= 3


@pytest.mark.asyncio
async def test_access_policy_precedence_and_fallback(sqlite_db: Database) -> None:
    user = await sqlite_db.create_user("bob", password="pw")

    await sqlite_db.upsert_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="repo",
        action="read",
        resource_id="*",
        effect="allow",
    )
    assert await sqlite_db.check_access_policy(
        user_id=user.id,
        tenant_id="tenant-x",
        resource_type="repo",
        action="read",
        resource_id="r1",
    )

    await sqlite_db.upsert_access_policy(
        user_id=user.id,
        tenant_id="tenant-x",
        resource_type="repo",
        action="read",
        resource_id="r1",
        effect="deny",
    )
    assert not await sqlite_db.check_access_policy(
        user_id=user.id,
        tenant_id="tenant-x",
        resource_type="repo",
        action="read",
        resource_id="r1",
    )

    with pytest.raises(ValueError):
        await sqlite_db.upsert_access_policy(user_id=user.id, resource_type="repo", action="write", effect="maybe")


@pytest.mark.asyncio
async def test_run_sqlite_op_rolls_back_on_failure(sqlite_db: Database) -> None:
    user = await sqlite_db.create_user("rollback", password="pw")

    def _failing_op() -> None:
        assert sqlite_db._sqlite_conn is not None
        sqlite_db._sqlite_conn.execute(
            "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("s1", user.id, "t", _utc_now_iso(), _utc_now_iso()),
        )
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await sqlite_db._run_sqlite_op(_failing_op)

    assert await sqlite_db.load_session("s1") is None


@pytest.mark.asyncio
async def test_jwt_token_flow_prefers_db_user(sqlite_db: Database) -> None:
    user = await sqlite_db.create_user("jwt-user", role="admin", password="pw", tenant_id="tenant-a")
    token_record = await sqlite_db.create_auth_token(
        user.id,
        role="admin",
        username="jwt-user",
        tenant_id="tenant-a",
        ttl_days=1,
    )

    parsed = sqlite_db.verify_auth_token(token_record.token)
    assert parsed is not None
    assert parsed.id == user.id

    resolved = await sqlite_db.get_user_by_token(token_record.token)
    assert resolved is not None
    assert resolved.username == "jwt-user"


@pytest.mark.asyncio
async def test_run_sqlite_op_requires_initialized_connection(tmp_path) -> None:
    cfg = DummyCfg(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'sidar_test.db'}",
        BASE_DIR=str(tmp_path),
    )
    db = Database(cfg)

    with pytest.raises(RuntimeError):
        await db._run_sqlite_op(lambda: None)


@pytest.mark.asyncio
async def test_ensure_default_prompt_registry_branches(monkeypatch: pytest.MonkeyPatch, sqlite_db: Database) -> None:
    class _BrokenLoader:
        def exec_module(self, module):
            module.SIDAR_SYSTEM_PROMPT = "sys prompt"

    class _BrokenSpec:
        loader = _BrokenLoader()

    monkeypatch.setattr("importlib.util.spec_from_file_location", lambda *args, **kwargs: _BrokenSpec())
    monkeypatch.setattr("importlib.util.module_from_spec", lambda spec: types.SimpleNamespace())

    async def _missing_prompt(*_args, **_kwargs):
        return None

    async def _raise(*_args, **_kwargs):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(sqlite_db, "get_active_prompt", _missing_prompt)
    monkeypatch.setattr(sqlite_db, "upsert_prompt", _raise)

    await sqlite_db.ensure_default_prompt_registry()


@pytest.mark.asyncio
async def test_verify_and_get_user_by_token_invalid_paths(sqlite_db: Database) -> None:
    payload = {"sub": "u1", "role": "", "username": "x", "tenant_id": "default"}
    bad_token = jwt.encode(payload, sqlite_db.cfg.JWT_SECRET_KEY, algorithm=sqlite_db.cfg.JWT_ALGORITHM)
    assert sqlite_db.verify_auth_token(bad_token) is None

    assert await sqlite_db.get_user_by_token("not-a-token") is None


@pytest.mark.asyncio
async def test_access_control_schema_sqlite_adds_missing_tenant_column(tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'ac.db'}", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    await db.connect()
    assert db._sqlite_conn is not None
    await db._run_sqlite_op(
        lambda: db._sqlite_conn.executescript(
            """
            DROP TABLE IF EXISTS users;
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
    )
    await db._ensure_access_control_schema_sqlite()
    cols = await db._run_sqlite_op(lambda: db._sqlite_conn.execute("PRAGMA table_info(users)").fetchall())
    assert "tenant_id" in {str(col[1]) for col in cols}
    await db.close()


@pytest.mark.asyncio
async def test_campaign_content_checklist_coverage_workflow(sqlite_db: Database) -> None:
    campaign = await sqlite_db.upsert_marketing_campaign(
        tenant_id="t1",
        name="Launch",
        channel="x",
        objective="Awareness",
        metadata={"k": "v"},
    )
    updated = await sqlite_db.upsert_marketing_campaign(campaign_id=campaign.id, tenant_id="t1", name="Launch 2", status="ACTIVE")
    assert updated.status == "active"

    asset = await sqlite_db.add_content_asset(
        campaign_id=campaign.id,
        tenant_id="t1",
        asset_type="post",
        title="Hello",
        content="World",
        metadata={"lang": "tr"},
    )
    assert json.loads(asset.metadata_json)["lang"] == "tr"

    checklist = await sqlite_db.add_operation_checklist(
        tenant_id="t1",
        title="Todo",
        items=["a", {"step": "b"}, {"": "drop"}, "   "],
        status="DONE",
    )
    assert checklist.status == "done"

    task = await sqlite_db.create_coverage_task(tenant_id="t1", command="pytest", pytest_output="ok", target_path="core/db.py")
    await sqlite_db.add_coverage_finding(
        task_id=task.id,
        finding_type="missing_test",
        target_path="core/db.py",
        summary="line missed",
        details={"line": 10},
    )
    assert len(await sqlite_db.list_coverage_tasks(tenant_id="t1", status="pending_review")) == 1


@pytest.mark.asyncio
async def test_postgresql_session_ops_with_fake_adapter() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    fake_pg.conn.fetch.side_effect = [
        [{"id": "s1", "user_id": "u1", "title": "t", "created_at": "c", "updated_at": "u"}],
        [{"id": 1, "session_id": "s1", "role": "assistant", "content": "hi", "tokens_used": 1, "created_at": "c"}],
    ]
    fake_pg.conn.fetchrow.return_value = {"id": "s1", "user_id": "u1", "title": "t", "created_at": "c", "updated_at": "u"}
    fake_pg.conn.execute.side_effect = ["UPDATE 1", "DELETE 1", "DELETE BAD"]

    sessions = await db.list_sessions("u1")
    assert len(sessions) == 1
    assert await db.update_session_title("s1", "updated") is True
    assert await db.delete_session("s1") is True
    assert await db.delete_session("s1") is False

    messages = await db.get_session_messages("s1")
    assert len(messages) == 1


@pytest.mark.asyncio
async def test_postgresql_adapter_timeout_path() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    fake_pg.set_timeout_error()
    db._pg_pool = fake_pg

    with pytest.raises(TimeoutError):
        await db.update_session_title("s1", "updated")


@pytest.mark.asyncio
async def test_postgresql_adapter_disconnect_path() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    fake_pg.set_disconnect_error()
    db._pg_pool = fake_pg

    with pytest.raises(ConnectionError):
        await db.update_session_title("s1", "updated")


@pytest.mark.asyncio
async def test_postgresql_adapter_conflict_and_close_path() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    fake_pg.set_conflict_error()
    db._pg_pool = fake_pg

    with pytest.raises(RuntimeError, match="conflict"):
        await db.update_session_title("s1", "updated")

    await db.close()
    assert fake_pg.closed is True

@pytest.mark.asyncio
async def test_ensure_user_and_ensure_user_id_paths(sqlite_db: Database) -> None:
    created = await sqlite_db.ensure_user("ensured-user", role="admin")
    existing = await sqlite_db.ensure_user("ensured-user", role="user")
    assert existing.id == created.id
    assert existing.role == "admin"

    ensured = await sqlite_db.ensure_user_id("fixed-id", username="fixed-name", role="reviewer", tenant_id="tenant-z")
    assert ensured.id == "fixed-id"
    assert ensured.tenant_id == "tenant-z"

    same = await sqlite_db.ensure_user_id("fixed-id")
    assert same.username == "fixed-name"


@pytest.mark.asyncio
async def test_marketing_and_content_listing_filters_and_validations(sqlite_db: Database) -> None:
    with pytest.raises(ValueError):
        await sqlite_db.upsert_marketing_campaign(name="")

    c1 = await sqlite_db.upsert_marketing_campaign(tenant_id="tenant-1", name="C1", status="DRAFT")
    c2 = await sqlite_db.upsert_marketing_campaign(tenant_id="tenant-1", name="C2", status="ACTIVE")
    _ = c2

    active = await sqlite_db.list_marketing_campaigns(tenant_id="tenant-1", status="active", limit=1)
    assert len(active) == 1
    assert active[0].status == "active"

    with pytest.raises(ValueError):
        await sqlite_db.add_content_asset(campaign_id=c1.id, tenant_id="tenant-1", asset_type="", title="x", content="y")

    a1 = await sqlite_db.add_content_asset(campaign_id=c1.id, tenant_id="tenant-1", asset_type="post", title="T1", content="Body")
    _a2 = await sqlite_db.add_content_asset(campaign_id=c1.id, tenant_id="tenant-1", asset_type="post", title="T2", content="Body")

    all_assets = await sqlite_db.list_content_assets(tenant_id="tenant-1", limit=10)
    by_campaign = await sqlite_db.list_content_assets(tenant_id="tenant-1", campaign_id=c1.id, limit=10)
    assert len(by_campaign) == len(all_assets) == 2
    assert by_campaign[0].campaign_id == a1.campaign_id


@pytest.mark.asyncio
async def test_operation_checklist_and_coverage_management(sqlite_db: Database) -> None:
    with pytest.raises(ValueError):
        await sqlite_db.add_operation_checklist(tenant_id="t1", title="", items=[])

    checklist = await sqlite_db.add_operation_checklist(
        tenant_id="t1",
        title="Ops",
        items=["one", {"step": "two"}, {"": "drop"}, "   "],
        status="PENDING",
    )
    checklists = await sqlite_db.list_operation_checklists(tenant_id="t1", limit=5)
    assert checklists[0].id == checklist.id

    with pytest.raises(ValueError):
        await sqlite_db.create_coverage_task(tenant_id="t1", command="", pytest_output="x")

    task = await sqlite_db.create_coverage_task(
        tenant_id="t1",
        command="pytest -q",
        pytest_output="ok",
        status="IN_PROGRESS",
        review_payload_json='{"score":1}',
    )
    assert task.status == "IN_PROGRESS"

    with pytest.raises(ValueError):
        await sqlite_db.add_coverage_finding(task_id=task.id, finding_type="", target_path="a", summary="b")

    finding = await sqlite_db.add_coverage_finding(
        task_id=task.id,
        finding_type="missing_test",
        target_path="core/db.py",
        summary="needs more tests",
        severity="HIGH",
    )
    assert finding.severity == "HIGH"

    tasks = await sqlite_db.list_coverage_tasks(tenant_id="t1", status="IN_PROGRESS", limit=3)
    assert tasks and tasks[0].id == task.id


@pytest.mark.asyncio
async def test_quota_usage_and_admin_stats(sqlite_db: Database) -> None:
    user = await sqlite_db.create_user("quota-user", password="pw")

    await sqlite_db.upsert_user_quota(user.id, daily_token_limit=100, daily_request_limit=5)
    await sqlite_db.record_provider_usage_daily(user.id, "OpenAI", tokens_used=40, requests_inc=2)
    await sqlite_db.record_provider_usage_daily(user.id, "OpenAI", tokens_used=60, requests_inc=3)

    status = await sqlite_db.get_user_quota_status(user.id, "openai")
    assert status["tokens_used"] == 100
    assert status["requests_used"] == 5
    assert status["token_limit_exceeded"] is True
    assert status["request_limit_exceeded"] is True

    users = await sqlite_db.list_users_with_quotas()
    quota_user = next(item for item in users if item["id"] == user.id)
    assert quota_user["daily_token_limit"] == 100

    stats = await sqlite_db.get_admin_stats()
    assert stats["total_users"] >= 1
    assert stats["total_tokens_used"] >= 100
    assert stats["total_api_requests"] >= 5


@pytest.mark.asyncio
async def test_audit_log_sqlite_validation_and_listing(sqlite_db: Database) -> None:
    user = await sqlite_db.create_user("audit-user", password="pw")

    with pytest.raises(ValueError):
        await sqlite_db.record_audit_log(action="", resource="repo", ip_address="127.0.0.1", allowed=True)

    await sqlite_db.record_audit_log(
        user_id=user.id,
        tenant_id="tenant-a",
        action="READ",
        resource="repo/1",
        ip_address="",
        allowed=True,
    )
    await sqlite_db.record_audit_log(
        user_id=user.id,
        tenant_id="tenant-a",
        action="write",
        resource="repo/2",
        ip_address="10.0.0.2",
        allowed=False,
    )

    by_user = await sqlite_db.list_audit_logs(user_id=user.id, limit=10)
    assert len(by_user) == 2
    assert by_user[0].ip_address in {"unknown", "10.0.0.2"}

    all_logs = await sqlite_db.list_audit_logs(limit=1)
    assert len(all_logs) == 1


@pytest.mark.asyncio
async def test_postgresql_marketing_and_coverage_branches() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    campaign_row = {
        "id": 10,
        "tenant_id": "t1",
        "name": "Launch",
        "channel": "x",
        "objective": "awareness",
        "status": "active",
        "owner_user_id": "u1",
        "budget": 10.5,
        "metadata_json": "{}",
        "created_at": "c",
        "updated_at": "u",
    }
    asset_row = {
        "id": 20,
        "campaign_id": 10,
        "tenant_id": "t1",
        "asset_type": "post",
        "title": "hello",
        "content": "world",
        "channel": "x",
        "metadata_json": "{}",
        "created_at": "c",
        "updated_at": "u",
    }
    checklist_row = {
        "id": 30,
        "campaign_id": 10,
        "tenant_id": "t1",
        "title": "ops",
        "items_json": "[]",
        "status": "pending",
        "owner_user_id": "u1",
        "created_at": "c",
        "updated_at": "u",
    }
    task_row = {
        "id": 40,
        "tenant_id": "t1",
        "requester_role": "coverage",
        "command": "pytest",
        "pytest_output": "ok",
        "status": "pending_review",
        "target_path": "core/db.py",
        "suggested_test_path": "tests/unit/core/test_db.py",
        "review_payload_json": "{}",
        "created_at": "c",
        "updated_at": "u",
    }
    finding_row = {
        "id": 50,
        "task_id": 40,
        "finding_type": "missing_test",
        "target_path": "core/db.py",
        "summary": "line missed",
        "severity": "medium",
        "details_json": "{}",
        "created_at": "c",
    }

    fake_pg.conn.fetchrow = AsyncMock(side_effect=[campaign_row, campaign_row, asset_row, checklist_row, task_row, finding_row])
    fake_pg.conn.fetch = AsyncMock(side_effect=[[campaign_row], [asset_row], [checklist_row], [task_row]])

    created = await db.upsert_marketing_campaign(tenant_id="t1", name="Launch", status="ACTIVE")
    assert created.id == 10
    updated = await db.upsert_marketing_campaign(campaign_id=10, tenant_id="t1", name="Launch2")
    assert updated.name == "Launch"

    campaigns = await db.list_marketing_campaigns(tenant_id="t1", status="active", limit=5)
    assert campaigns and campaigns[0].id == 10

    asset = await db.add_content_asset(campaign_id=10, tenant_id="t1", asset_type="post", title="hello", content="world")
    assert asset.id == 20
    assets = await db.list_content_assets(tenant_id="t1", campaign_id=10, limit=3)
    assert assets and assets[0].campaign_id == 10

    checklist = await db.add_operation_checklist(tenant_id="t1", title="ops", items=["a"], campaign_id=10)
    assert checklist.id == 30
    checklists = await db.list_operation_checklists(tenant_id="t1", campaign_id=10, limit=3)
    assert checklists and checklists[0].id == 30

    task = await db.create_coverage_task(tenant_id="t1", command="pytest", pytest_output="ok")
    assert task.id == 40
    finding = await db.add_coverage_finding(task_id=40, finding_type="missing_test", target_path="core/db.py", summary="line missed")
    assert finding.id == 50
    tasks = await db.list_coverage_tasks(tenant_id="t1", status="pending_review", limit=3)
    assert tasks and tasks[0].id == 40


@pytest.mark.asyncio
async def test_postgresql_quota_admin_and_replace_messages_paths() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    fake_pg.conn.fetchrow = AsyncMock(
        side_effect=[
            {"daily_token_limit": 100, "daily_request_limit": 5},
            {"requests_used": 5, "tokens_used": 100},
            {"total_tokens_used": 100, "total_api_requests": 5},
        ]
    )
    fake_pg.conn.fetch = AsyncMock(return_value=[
        {
            "id": "u1",
            "username": "john",
            "role": "user",
            "created_at": "c",
            "daily_token_limit": 100,
            "daily_request_limit": 5,
        }
    ])

    await db.upsert_user_quota("u1", daily_token_limit=100, daily_request_limit=5)
    await db.record_provider_usage_daily("u1", "OpenAI", tokens_used=100, requests_inc=5)
    status = await db.get_user_quota_status("u1", "openai")
    assert status["token_limit_exceeded"] is True

    users = await db.list_users_with_quotas()
    assert users[0]["id"] == "u1"
    stats = await db.get_admin_stats()
    assert stats["total_users"] == 1

    class _Tx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_pg.conn.transaction = lambda: _Tx()
    replaced = await db.replace_session_messages("s1", [{"content": "x"}, {"role": "user", "content": "y"}])
    assert replaced == 2

@pytest.mark.asyncio
async def test_sqlite_backend_path_resolution_and_connect_idempotent(tmp_path) -> None:
    rel_cfg = DummyCfg(DATABASE_URL="sqlite:///relative.db", BASE_DIR=str(tmp_path))
    rel_db = Database(rel_cfg)
    assert rel_db._backend == "sqlite"
    assert rel_db._sqlite_path == tmp_path / "relative.db"

    abs_path = tmp_path / "absolute.db"
    abs_cfg = DummyCfg(DATABASE_URL=f"sqlite+aiosqlite:///{abs_path}", BASE_DIR=str(tmp_path))
    db = Database(abs_cfg)
    await db._connect_sqlite()
    first_conn = db._sqlite_conn
    await db._connect_sqlite()
    assert db._sqlite_conn is first_conn
    await db.close()


@pytest.mark.asyncio
async def test_connect_postgresql_branch_matrix(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", BASE_DIR=str(tmp_path))

    already_connected = Database(cfg)
    already_connected._pg_pool = object()
    await already_connected._connect_postgresql()

    missing_dep = Database(cfg)
    real_import = __import__

    def _raise_import(name, *args, **kwargs):
        if name == "asyncpg":
            raise ImportError("no asyncpg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _raise_import)
    with pytest.raises(RuntimeError, match="asyncpg"):
        await missing_dep._connect_postgresql()
    monkeypatch.setattr("builtins.__import__", real_import)

    class _AsyncpgStub:
        class PoolError(Exception):
            pass

    timeout_db = Database(cfg)

    async def _raise_timeout(**_kwargs):
        raise TimeoutError("pool timeout")

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(create_pool=_raise_timeout, PoolError=_AsyncpgStub.PoolError))
    with pytest.raises(TimeoutError):
        await timeout_db._connect_postgresql()

    pool_error_db = Database(cfg)

    async def _raise_pool(**_kwargs):
        raise _AsyncpgStub.PoolError("pool is down")

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(create_pool=_raise_pool, PoolError=_AsyncpgStub.PoolError))
    with pytest.raises(_AsyncpgStub.PoolError):
        await pool_error_db._connect_postgresql()

    generic_db = Database(cfg)

    async def _raise_generic(**_kwargs):
        raise RuntimeError("connection failed")

    monkeypatch.setitem(sys.modules, "asyncpg", types.SimpleNamespace(create_pool=_raise_generic, PoolError=_AsyncpgStub.PoolError))
    with pytest.raises(RuntimeError, match="connection failed"):
        await generic_db._connect_postgresql()


@pytest.mark.asyncio
async def test_postgresql_schema_helpers_and_init_routing(tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    await db._ensure_access_control_schema_postgresql()
    await db._ensure_audit_log_schema_postgresql()
    assert fake_pg.conn.execute.await_count >= 6

    calls: list[str] = []

    async def _mark(name: str):
        calls.append(name)

    db._backend = "postgresql"
    db._init_schema_postgresql = lambda: _mark("init")
    db._ensure_access_control_schema_postgresql = lambda: _mark("ac")
    db._ensure_audit_log_schema_postgresql = lambda: _mark("audit")
    db._ensure_schema_version_postgresql = lambda: _mark("version")
    db.ensure_default_prompt_registry = lambda: _mark("prompt")

    await db.init_schema()
    assert calls == ["init", "ac", "audit", "version", "prompt"]


@pytest.mark.asyncio
async def test_postgresql_create_session_and_add_message_paths(tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg
    fake_pg.conn.fetchrow = AsyncMock(return_value={"id": 777})

    session = await db.create_session("user-1", "hello")
    assert session.user_id == "user-1"

    message = await db.add_message(session.id, "assistant", "reply", tokens_used=3)
    assert message.id == 777
    assert message.tokens_used == 3
