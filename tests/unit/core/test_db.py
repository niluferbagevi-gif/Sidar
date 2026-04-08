from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import sqlite3
import sys
import types
from dataclasses import dataclass
from datetime import datetime

import pytest

if "jwt" not in sys.modules:
    jwt_module = types.ModuleType("jwt")

    class _PyJWTError(Exception):
        pass

    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _b64d(data: str) -> bytes:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode((data + padding).encode("ascii"))

    def _encode(payload, secret, algorithm="HS256"):
        if algorithm != "HS256":
            raise _PyJWTError("unsupported algorithm")
        header = {"alg": algorithm, "typ": "JWT"}
        part1 = _b64(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        part2 = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{part1}.{part2}".encode("ascii")
        sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{part1}.{part2}.{_b64(sig)}"

    def _decode(token, secret, algorithms=None):
        parts = token.split(".")
        if len(parts) != 3:
            raise _PyJWTError("invalid token")
        part1, part2, sig = parts
        signing_input = f"{part1}.{part2}".encode("ascii")
        expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), sig):
            raise _PyJWTError("bad signature")
        payload = json.loads(_b64d(part2).decode("utf-8"))
        return payload

    jwt_module.encode = _encode
    jwt_module.decode = _decode
    jwt_module.PyJWTError = _PyJWTError
    sys.modules["jwt"] = jwt_module

from core.db import Database, _expires_in, _hash_password, _json_dumps, _quote_sql_identifier, _utc_now_iso, _verify_password
import jwt


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


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sqlite_db(tmp_path, request):
    cfg = DummyCfg(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'sidar_test.db'}",
        BASE_DIR=str(tmp_path),
    )
    db = Database(cfg)
    run(db.connect())
    run(db.init_schema())

    def _close():
        run(db.close())

    request.addfinalizer(_close)
    return db


def test_helper_functions_basic_contracts():
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
def test_quote_sql_identifier_rejects_invalid(identifier):
    with pytest.raises(ValueError):
        _quote_sql_identifier(identifier)


def test_user_session_message_lifecycle(sqlite_db: Database):
    user = run(sqlite_db.create_user("alice", role="admin", password="pw"))
    auth = run(sqlite_db.authenticate_user("alice", "pw"))
    assert auth is not None
    assert auth.id == user.id

    session = run(sqlite_db.create_session(user.id, "ilk"))
    loaded = run(sqlite_db.load_session(session.id, user_id=user.id))
    assert loaded is not None
    assert loaded.title == "ilk"

    assert run(sqlite_db.update_session_title(session.id, "yeni")) is True
    run(sqlite_db.add_message(session.id, "user", "merhaba", tokens_used=-5))
    run(sqlite_db.add_message(session.id, "assistant", "selam"))

    messages = run(sqlite_db.get_session_messages(session.id))
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].tokens_used == 0

    replaced = run(
        sqlite_db.replace_session_messages(
            session.id,
            [{"role": "user", "content": "x"}, {"content": ""}, {"content": "y"}],
        )
    )
    assert replaced == 2
    messages = run(sqlite_db.get_session_messages(session.id))
    assert [m.content for m in messages] == ["x", "y"]

    sessions = run(sqlite_db.list_sessions(user.id))
    assert len(sessions) == 1

    assert run(sqlite_db.delete_session(session.id, user_id="wrong")) is False
    assert run(sqlite_db.delete_session(session.id, user_id=user.id)) is True


def test_prompt_registry_flow(sqlite_db: Database):
    with pytest.raises(ValueError):
        run(sqlite_db.upsert_prompt("", ""))

    p1 = run(sqlite_db.upsert_prompt("System", "prompt-v1", activate=True))
    p2 = run(sqlite_db.upsert_prompt("system", "prompt-v2", activate=False))
    assert p2.version == p1.version + 1
    assert p2.is_active is False

    active = run(sqlite_db.get_active_prompt("system"))
    assert active is not None
    assert active.prompt_text == "prompt-v1"

    activated = run(sqlite_db.activate_prompt(p2.id))
    assert activated is not None
    assert activated.prompt_text == "prompt-v2"

    prompts = run(sqlite_db.list_prompts("system"))
    assert len(prompts) >= 3


def test_access_policy_precedence_and_fallback(sqlite_db: Database):
    user = run(sqlite_db.create_user("bob", password="pw"))

    run(
        sqlite_db.upsert_access_policy(
            user_id=user.id,
            tenant_id="default",
            resource_type="repo",
            action="read",
            resource_id="*",
            effect="allow",
        )
    )
    assert run(
        sqlite_db.check_access_policy(
            user_id=user.id,
            tenant_id="tenant-x",
            resource_type="repo",
            action="read",
            resource_id="r1",
        )
    )

    run(
        sqlite_db.upsert_access_policy(
            user_id=user.id,
            tenant_id="tenant-x",
            resource_type="repo",
            action="read",
            resource_id="r1",
            effect="deny",
        )
    )
    assert not run(
        sqlite_db.check_access_policy(
            user_id=user.id,
            tenant_id="tenant-x",
            resource_type="repo",
            action="read",
            resource_id="r1",
        )
    )

    with pytest.raises(ValueError):
        run(sqlite_db.upsert_access_policy(user_id=user.id, resource_type="repo", action="write", effect="maybe"))


def test_audit_log_record_and_list(sqlite_db: Database):
    run(
        sqlite_db.record_audit_log(
            user_id="u1", action="READ", resource="/x", ip_address="", allowed=True, tenant_id="t1"
        )
    )
    run(
        sqlite_db.record_audit_log(
            user_id="u2", action="write", resource="/y", ip_address="127.0.0.1", allowed=False, tenant_id="t1"
        )
    )

    logs = run(sqlite_db.list_audit_logs(limit=1))
    assert len(logs) == 1

    u1_logs = run(sqlite_db.list_audit_logs(user_id="u1", limit=10))
    assert len(u1_logs) == 1
    assert u1_logs[0].action == "read"
    assert u1_logs[0].ip_address == "unknown"

    with pytest.raises(ValueError):
        run(sqlite_db.record_audit_log(action="", resource="x", ip_address="1", allowed=True))


def test_campaign_content_checklist_coverage_workflow(sqlite_db: Database):
    campaign = run(
        sqlite_db.upsert_marketing_campaign(
            tenant_id="t1", name="Launch", channel="x", objective="Awareness", metadata={"k": "v"}
        )
    )
    updated = run(sqlite_db.upsert_marketing_campaign(campaign_id=campaign.id, tenant_id="t1", name="Launch 2", status="ACTIVE"))
    assert updated.status == "active"
    assert len(run(sqlite_db.list_marketing_campaigns(tenant_id="t1", status="active"))) == 1

    asset = run(
        sqlite_db.add_content_asset(
            campaign_id=campaign.id,
            tenant_id="t1",
            asset_type="post",
            title="Hello",
            content="World",
            metadata={"lang": "tr"},
        )
    )
    assert json.loads(asset.metadata_json)["lang"] == "tr"
    assert len(run(sqlite_db.list_content_assets(tenant_id="t1", campaign_id=campaign.id))) == 1

    checklist = run(
        sqlite_db.add_operation_checklist(
            tenant_id="t1", title="Todo", items=["a", {"step": "b"}, {"": "drop"}, "   "], status="DONE"
        )
    )
    assert checklist.status == "done"
    assert len(json.loads(checklist.items_json)) == 2
    assert len(run(sqlite_db.list_operation_checklists(tenant_id="t1"))) == 1

    task = run(sqlite_db.create_coverage_task(tenant_id="t1", command="pytest", pytest_output="ok", target_path="core/db.py"))
    run(
        sqlite_db.add_coverage_finding(
            task_id=task.id,
            finding_type="missing_test",
            target_path="core/db.py",
            summary="line missed",
            details={"line": 10},
        )
    )
    assert len(run(sqlite_db.list_coverage_tasks(tenant_id="t1", status="pending_review"))) == 1

    with pytest.raises(ValueError):
        run(sqlite_db.create_coverage_task(command="", pytest_output=""))
    with pytest.raises(ValueError):
        run(sqlite_db.add_coverage_finding(task_id=1, finding_type="", target_path="x", summary=""))


def test_quota_usage_and_admin_stats(sqlite_db: Database):
    user = run(sqlite_db.create_user("quota-user", password="pw"))

    run(sqlite_db.upsert_user_quota(user.id, daily_token_limit=10, daily_request_limit=2))
    run(sqlite_db.record_provider_usage_daily(user.id, "openai", tokens_used=6, requests_inc=1))
    run(sqlite_db.record_provider_usage_daily(user.id, "openai", tokens_used=5, requests_inc=1))

    status = run(sqlite_db.get_user_quota_status(user.id, "openai"))
    assert status["tokens_used"] == 11
    assert status["requests_used"] == 2
    assert status["token_limit_exceeded"] is True
    assert status["request_limit_exceeded"] is True

    users = run(sqlite_db.list_users_with_quotas())
    assert any(u["id"] == user.id and u["daily_token_limit"] == 10 for u in users)

    stats = run(sqlite_db.get_admin_stats())
    assert stats["total_users"] >= 1
    assert stats["total_tokens_used"] >= 11


def test_run_sqlite_op_rolls_back_on_failure(sqlite_db: Database):
    user = run(sqlite_db.create_user("rollback", password="pw"))

    def _failing_op():
        assert sqlite_db._sqlite_conn is not None
        sqlite_db._sqlite_conn.execute(
            "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("s1", user.id, "t", _utc_now_iso(), _utc_now_iso()),
        )
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run(sqlite_db._run_sqlite_op(_failing_op))

    assert run(sqlite_db.load_session("s1")) is None
    healthy_session = run(sqlite_db.create_session(user.id, "after-rollback"))
    assert run(sqlite_db.load_session(healthy_session.id, user_id=user.id)) is not None
    sessions = run(sqlite_db.list_sessions(user.id))
    assert len(sessions) == 1
    assert sessions[0].id == healthy_session.id


def test_jwt_token_flow_prefers_db_user(sqlite_db: Database):
    user = run(sqlite_db.create_user("jwt-user", role="admin", password="pw", tenant_id="tenant-a"))
    token_record = run(
        sqlite_db.create_auth_token(user.id, role="admin", username="jwt-user", tenant_id="tenant-a", ttl_days=1)
    )

    parsed = sqlite_db.verify_auth_token(token_record.token)
    assert parsed is not None
    assert parsed.id == user.id

    resolved = run(sqlite_db.get_user_by_token(token_record.token))
    assert resolved is not None
    assert resolved.username == "jwt-user"

    assert sqlite_db.verify_auth_token(token_record.token + "x") is None


def test_run_sqlite_op_requires_initialized_connection(tmp_path):
    cfg = DummyCfg(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'sidar_test.db'}",
        BASE_DIR=str(tmp_path),
    )
    db = Database(cfg)

    with pytest.raises(RuntimeError):
        run(db._run_sqlite_op(lambda: None))


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn
        self.closed = False

    def acquire(self):
        return _FakeAcquire(self._conn)

    async def close(self):
        self.closed = True


class _SchemaConn:
    def __init__(self):
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "OK"

    async def fetchval(self, query, *args):
        self.executed.append((query, args))
        return 0


@pytest.fixture
def pg_db():
    cfg = DummyCfg(
        DATABASE_URL="postgresql://user:pw@localhost:5432/sidar",
        BASE_DIR=".",
    )
    db = Database(cfg)
    return db


def test_postgresql_schema_helpers_and_close(pg_db: Database):
    conn = _SchemaConn()
    pool = _FakePool(conn)
    pg_db._pg_pool = pool

    run(pg_db._init_schema_postgresql())
    run(pg_db._ensure_access_control_schema_postgresql())
    run(pg_db._ensure_audit_log_schema_postgresql())
    run(pg_db._ensure_schema_version_postgresql())

    assert len(conn.executed) > 20

    run(pg_db.close())
    assert pool.closed is True


class _PromptConn:
    def __init__(self):
        self.rows = [
            {"id": 1, "role_name": "system", "prompt_text": "v1", "version": 1, "is_active": True, "created_at": "c", "updated_at": "u"},
            {"id": 2, "role_name": "system", "prompt_text": "v2", "version": 2, "is_active": False, "created_at": "c", "updated_at": "u"},
        ]

    async def fetch(self, query, *args):
        if "WHERE role_name=$1" in query:
            return [self.rows[0]]
        return self.rows

    async def fetchrow(self, query, *args):
        if "SELECT id, role_name FROM prompt_registry" in query:
            return {"id": 2, "role_name": "system"}
        if "WHERE role_name=$1 AND is_active=TRUE" in query:
            return self.rows[0]
        if "INSERT INTO prompt_registry" in query:
            return self.rows[0]
        return self.rows[0]

    async def fetchval(self, query, *args):
        return 2

    async def execute(self, query, *args):
        return "UPDATE 1"


def test_postgresql_prompt_and_session_ops(pg_db: Database):
    conn = _PromptConn()
    pg_db._pg_pool = _FakePool(conn)

    listed = run(pg_db.list_prompts())
    assert len(listed) == 2
    assert run(pg_db.activate_prompt(0)) is None
    assert run(pg_db.get_active_prompt("")) is None

    upserted = run(pg_db.upsert_prompt("system", "hello", activate=True))
    assert upserted.role_name == "system"

    active = run(pg_db.activate_prompt(2))
    assert active is not None


def test_connect_postgresql_import_and_pool_errors(monkeypatch, pg_db: Database):
    class _DummyAsyncPG:
        class PoolError(Exception):
            pass

        @staticmethod
        async def create_pool(**kwargs):
            raise _DummyAsyncPG.PoolError("pool broken")

    monkeypatch.setitem(sys.modules, "asyncpg", _DummyAsyncPG)
    with pytest.raises(_DummyAsyncPG.PoolError):
        run(pg_db._connect_postgresql())

    class _TimeoutAsyncPG:
        PoolError = RuntimeError

        @staticmethod
        async def create_pool(**kwargs):
            raise TimeoutError("slow")

    monkeypatch.setitem(sys.modules, "asyncpg", _TimeoutAsyncPG)
    with pytest.raises(TimeoutError):
        run(pg_db._connect_postgresql())


def test_configure_backend_and_connect_branches(tmp_path, monkeypatch):
    rel_cfg = DummyCfg(DATABASE_URL="sqlite:///nested/app.db", BASE_DIR=str(tmp_path))
    rel_db = Database(rel_cfg)
    assert rel_db._backend == "sqlite"
    assert rel_db._sqlite_path == tmp_path / "nested" / "app.db"

    abs_db = Database(DummyCfg(DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'a.db'}", BASE_DIR=str(tmp_path)))
    run(abs_db.connect())
    existing_conn = abs_db._sqlite_conn
    run(abs_db._connect_sqlite())
    assert abs_db._sqlite_conn is existing_conn
    run(abs_db.close())

    pg_db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR=str(tmp_path)))

    class _AsyncPG:
        PoolError = RuntimeError

        @staticmethod
        async def create_pool(**kwargs):
            return object()

    monkeypatch.setitem(sys.modules, "asyncpg", _AsyncPG)
    run(pg_db.connect())
    assert pg_db._pg_pool is not None
    first_pool = pg_db._pg_pool
    run(pg_db._connect_postgresql())
    assert pg_db._pg_pool is first_pool


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _RichPgConn:
    def __init__(self):
        self.calls = []
        self.ensure_user_row = None
        self.by_id_row = None
        self.auth_row = None
        self.campaign_update_row = {
            "id": 7,
            "tenant_id": "t1",
            "name": "Updated",
            "channel": "x",
            "objective": "obj",
            "status": "active",
            "owner_user_id": "u1",
            "budget": 3.5,
            "metadata_json": "{}",
            "created_at": "c",
            "updated_at": "u",
        }

    def transaction(self):
        return _Tx()

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        if "UPDATE sessions SET title" in query:
            return "BAD"
        if "DELETE FROM sessions" in query:
            return "DELETE 1"
        return "UPDATE 1"

    async def fetch(self, query, *args):
        self.calls.append(("fetch", query, args))
        if "FROM sessions" in query:
            return [{"id": "s1", "user_id": "u1", "title": "t", "created_at": "c", "updated_at": "u"}]
        if "FROM marketing_campaigns" in query:
            return [{"id": 8, "tenant_id": "t1", "name": "Camp", "channel": "x", "objective": "obj", "status": "active", "owner_user_id": "u1", "budget": 1.0, "metadata_json": "{}", "created_at": "c", "updated_at": "u"}]
        if "FROM audit_logs" in query:
            return [{"id": 1, "user_id": "u1", "tenant_id": "t1", "action": "read", "resource": "/x", "ip_address": "1.1.1.1", "allowed": True, "timestamp": "ts"}]
        if "FROM coverage_tasks" in query:
            return [{"id": 3, "tenant_id": "t1", "requester_role": "coverage", "command": "pytest", "pytest_output": "ok", "status": "pending_review", "target_path": "core/db.py", "suggested_test_path": "tests/x.py", "review_payload_json": "{}", "created_at": "c", "updated_at": "u"}]
        if "FROM operation_checklists" in query:
            return [{"id": 5, "campaign_id": 7, "tenant_id": "t1", "title": "Ops", "items_json": "[]", "status": "pending", "owner_user_id": "", "created_at": "c", "updated_at": "u"}]
        if "FROM users u" in query:
            return [{"id": "u1", "username": "alice", "role": "user", "created_at": "c", "daily_token_limit": 9, "daily_request_limit": 3}]
        if "FROM messages" in query:
            return [{"id": 1, "session_id": "s1", "role": "assistant", "content": "hi", "tokens_used": 1, "created_at": "c"}]
        return [{"id": 1, "campaign_id": 7, "tenant_id": "t1", "asset_type": "post", "title": "t", "content": "c", "channel": "x", "metadata_json": "{}", "created_at": "c", "updated_at": "u"}]

    async def fetchval(self, query, *args):
        self.calls.append(("fetchval", query, args))
        return 1

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        if "FROM users WHERE username=$1" in query and "password_hash" not in query:
            return self.ensure_user_row
        if "FROM users WHERE id=$1" in query:
            return self.by_id_row
        if "password_hash" in query:
            return self.auth_row
        if "FROM sessions WHERE id=$1 AND user_id=$2" in query:
            return {"id": "s1", "user_id": "u1", "title": "t", "created_at": "c", "updated_at": "u"}
        if "FROM sessions WHERE id=$1" in query:
            return {"id": "s1", "user_id": "u1", "title": "t2", "created_at": "c", "updated_at": "u"}
        if "UPDATE marketing_campaigns" in query:
            return self.campaign_update_row
        if "INSERT INTO marketing_campaigns" in query:
            return {"id": 8, "tenant_id": "t1", "name": "New", "channel": "x", "objective": "obj", "status": "draft", "owner_user_id": "u1", "budget": 1.0, "metadata_json": "{}", "created_at": "c", "updated_at": "u"}
        if "INSERT INTO content_assets" in query:
            return {"id": 2, "campaign_id": 8, "tenant_id": "t1", "asset_type": "post", "title": "T", "content": "C", "channel": "x", "metadata_json": "{}", "created_at": "c", "updated_at": "u"}
        if "INSERT INTO operation_checklists" in query:
            return {"id": 5, "campaign_id": None, "tenant_id": "t1", "title": "Ops", "items_json": "[]", "status": "pending", "owner_user_id": "", "created_at": "c", "updated_at": "u"}
        if "INSERT INTO coverage_tasks" in query:
            return {"id": 10, "tenant_id": "t1", "requester_role": "coverage", "command": "pytest", "pytest_output": "ok", "status": "pending_review", "target_path": "core/db.py", "suggested_test_path": "", "review_payload_json": "{}", "created_at": "c", "updated_at": "u"}
        if "INSERT INTO coverage_findings" in query:
            return {"id": 11, "task_id": 10, "finding_type": "missing_test", "target_path": "core/db.py", "summary": "s", "severity": "medium", "details_json": "{}", "created_at": "c"}
        if "COALESCE(SUM(tokens_used)" in query:
            return {"total_tokens_used": 4, "total_api_requests": 2}
        if "SELECT daily_token_limit" in query:
            return {"daily_token_limit": 10, "daily_request_limit": 2}
        if "SELECT requests_used, tokens_used" in query:
            return {"requests_used": 2, "tokens_used": 11}
        if "SELECT id, role_name FROM prompt_registry" in query:
            return None
        return {"id": 1, "role_name": "system", "prompt_text": "x", "version": 1, "is_active": True, "created_at": "c", "updated_at": "u"}


def test_postgresql_core_branches(pg_db: Database):
    conn = _RichPgConn()
    pg_db._pg_pool = _FakePool(conn)

    u1 = run(pg_db.ensure_user("alice", role="admin"))
    assert u1.username == "alice"
    conn.ensure_user_row = {"id": "u1", "username": "alice", "role": "admin", "created_at": "c", "tenant_id": "t1"}
    u2 = run(pg_db.ensure_user("alice", role="admin"))
    assert u2.id == "u1"

    conn.auth_row = None
    assert run(pg_db.authenticate_user("alice", "pw")) is None
    conn.auth_row = {"id": "u1", "username": "alice", "password_hash": _hash_password("pw"), "role": "admin", "created_at": "c", "tenant_id": "t1"}
    assert run(pg_db.authenticate_user("alice", "pw")) is not None

    assert len(run(pg_db.list_sessions("u1"))) == 1
    assert run(pg_db.load_session("s1", user_id="u1")) is not None
    assert run(pg_db.load_session("s1")) is not None
    assert run(pg_db.update_session_title("s1", "new")) is False
    assert run(pg_db.delete_session("s1", user_id="u1")) is True
    assert run(pg_db.delete_session("s1")) is True

    conn.by_id_row = None
    assert run(pg_db._get_user_by_id("missing")) is None
    conn.by_id_row = {"id": "u1", "username": "alice", "role": "admin", "created_at": "c", "tenant_id": "t1"}
    assert run(pg_db._get_user_by_id("u1")) is not None

    run(pg_db.upsert_access_policy(user_id="u1", tenant_id="t1", resource_type="repo", action="read", effect="allow"))
    run(pg_db.record_audit_log(user_id="u1", tenant_id="t1", action="READ", resource="/x", ip_address="1.1.1.1", allowed=True))
    assert len(run(pg_db.list_audit_logs(limit=1))) == 1
    assert len(run(pg_db.list_audit_logs(user_id="u1", limit=1))) == 1

    assert run(pg_db.upsert_marketing_campaign(tenant_id="t1", name="New")).id == 8
    assert run(pg_db.upsert_marketing_campaign(tenant_id="t1", campaign_id=7, name="Updated")).id == 7
    conn.campaign_update_row = None
    with pytest.raises(ValueError):
        run(pg_db.upsert_marketing_campaign(tenant_id="t1", campaign_id=999, name="Missing"))
    assert len(run(pg_db.list_marketing_campaigns(tenant_id="t1", status="active", limit=1))) >= 1

    assert run(pg_db.add_content_asset(campaign_id=7, tenant_id="t1", asset_type="post", title="T", content="C")).id == 2
    assert len(run(pg_db.list_content_assets(tenant_id="t1", campaign_id=7, limit=1))) >= 1
    assert run(pg_db.add_operation_checklist(tenant_id="t1", title="Ops", items=[], campaign_id=None)).id == 5
    assert len(run(pg_db.list_operation_checklists(tenant_id="t1", campaign_id=7, limit=1))) >= 1

    task = run(pg_db.create_coverage_task(tenant_id="t1", command="pytest", pytest_output="ok"))
    assert task.id == 10
    finding = run(pg_db.add_coverage_finding(task_id=10, finding_type="missing_test", target_path="core/db.py", summary="s"))
    assert finding.id == 11
    assert len(run(pg_db.list_coverage_tasks(tenant_id="t1", status="pending_review", limit=1))) == 1

    run(pg_db.upsert_user_quota("u1", daily_token_limit=10, daily_request_limit=2))
    run(pg_db.record_provider_usage_daily("u1", "openai", tokens_used=11, requests_inc=2))
    status = run(pg_db.get_user_quota_status("u1", "openai"))
    assert status["token_limit_exceeded"] is True
    assert len(run(pg_db.list_users_with_quotas())) == 1
    stats = run(pg_db.get_admin_stats())
    assert stats["total_tokens_used"] == 4

    session = run(pg_db.create_session("u1", "Title"))
    msg = run(pg_db.add_message(session.id, "assistant", "hi", tokens_used=1))
    assert msg.id == 1
    assert len(run(pg_db.get_session_messages(session.id))) == 1
    replaced = run(pg_db.replace_session_messages(session.id, [{"content": "a"}, {"content": " "}, {"role": "user", "content": "b"}]))
    assert replaced == 2


def test_ensure_default_prompt_registry_branches(monkeypatch, sqlite_db: Database):
    class _BrokenLoader:
        def exec_module(self, module):
            module.SIDAR_SYSTEM_PROMPT = "sys prompt"

    class _BrokenSpec:
        loader = _BrokenLoader()

    monkeypatch.setattr("importlib.util.spec_from_file_location", lambda *args, **kwargs: _BrokenSpec())
    monkeypatch.setattr("importlib.util.module_from_spec", lambda spec: types.SimpleNamespace())
    monkeypatch.setattr(sqlite_db, "get_active_prompt", lambda role_name: asyncio.sleep(0, result=None))

    async def _raise(*args, **kwargs):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(sqlite_db, "upsert_prompt", _raise)
    run(sqlite_db.ensure_default_prompt_registry())


def test_ensure_user_and_token_fallback_paths(sqlite_db: Database):
    created = run(sqlite_db.ensure_user("new-user", role="admin"))
    loaded = run(sqlite_db.ensure_user("new-user", role="user"))
    assert created.id == loaded.id

    token = run(sqlite_db.create_auth_token("ghost-user", role="user", username="ghost", tenant_id="t1"))
    jwt_user = run(sqlite_db.get_user_by_token(token.token))
    assert jwt_user is not None
    assert jwt_user.id == "ghost-user"


@pytest.mark.parametrize(
    "fn,args",
    [
        ("add_content_asset", dict(campaign_id=1, asset_type="", title="t", content="c")),
        ("add_content_asset", dict(campaign_id=1, asset_type="post", title="", content="c")),
        ("add_operation_checklist", dict(title="", items=[])),
    ],
)
def test_validation_errors_for_campaign_related_methods(sqlite_db: Database, fn: str, args: dict):
    with pytest.raises(ValueError):
        run(getattr(sqlite_db, fn)(tenant_id="t1", **args))


def test_list_methods_limit_normalization(sqlite_db: Database):
    campaign = run(sqlite_db.upsert_marketing_campaign(tenant_id="t1", name="L1"))
    run(sqlite_db.add_content_asset(campaign_id=campaign.id, tenant_id="t1", asset_type="post", title="A", content="B"))
    run(sqlite_db.add_operation_checklist(tenant_id="t1", title="C", items=["x"]))
    run(sqlite_db.create_coverage_task(tenant_id="t1", command="pytest", pytest_output="ok"))

    assert len(run(sqlite_db.list_marketing_campaigns(tenant_id="t1", limit=0))) == 1
    assert len(run(sqlite_db.list_content_assets(tenant_id="t1", limit=0))) == 1
    assert len(run(sqlite_db.list_operation_checklists(tenant_id="t1", limit=0))) == 1
    assert len(run(sqlite_db.list_coverage_tasks(tenant_id="t1", limit=0))) == 1


def test_backend_and_sqlite_auxiliary_branches(tmp_path):
    cfg = DummyCfg(DATABASE_URL="sqlite:///relative.db", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    assert db._sqlite_path == tmp_path / "relative.db"
    db.database_url = "sqlite:///another-relative.db"
    db._configure_backend()
    assert db._sqlite_path == tmp_path / "another-relative.db"
    db.database_url = "plain-relative.db"
    db._configure_backend()
    assert db._sqlite_path == tmp_path / "plain-relative.db"

    run(db.connect())
    db._sqlite_lock = None
    assert run(db._run_sqlite_op(lambda: 7)) == 7
    assert db._sqlite_lock is not None

    run(db.init_schema())
    run(db.upsert_prompt("system", "p1", activate=True))
    assert len(run(db.list_prompts())) >= 1
    assert run(db.activate_prompt(999999)) is None
    assert run(db.delete_session("missing")) is False
    assert run(db.list_access_policies(user_id="nouser")) == []

    with pytest.raises(ValueError):
        run(db.upsert_marketing_campaign(tenant_id="t1", name=""))
    with pytest.raises(ValueError):
        run(db.upsert_marketing_campaign(tenant_id="t1", campaign_id=9999, name="missing"))
    with pytest.raises(ValueError):
        run(db.upsert_access_policy(user_id="u1", tenant_id="t1", resource_type="", action=""))
    assert run(db.check_access_policy(user_id="", tenant_id="t1", resource_type="repo", action="read")) is False
    assert run(db.check_access_policy(user_id="u1", tenant_id="t1", resource_type="repo", action="read")) is False

    run(db._ensure_schema_version_sqlite())
    run(db.close())


def test_postgresql_dispatch_and_query_optional_paths(pg_db: Database, monkeypatch: pytest.MonkeyPatch):
    conn = _RichPgConn()
    pg_db._pg_pool = _FakePool(conn)

    called: list[str] = []

    async def _mark(name):
        called.append(name)

    monkeypatch.setattr(pg_db, "_init_schema_postgresql", lambda: _mark("init"))
    monkeypatch.setattr(pg_db, "_ensure_access_control_schema_postgresql", lambda: _mark("ac"))
    monkeypatch.setattr(pg_db, "_ensure_audit_log_schema_postgresql", lambda: _mark("audit"))
    monkeypatch.setattr(pg_db, "_ensure_schema_version_postgresql", lambda: _mark("schema"))
    monkeypatch.setattr(pg_db, "ensure_default_prompt_registry", lambda: _mark("prompt"))
    run(pg_db.init_schema())
    assert called == ["init", "ac", "audit", "schema", "prompt"]

    # list/query branches without optional filters
    assert len(run(pg_db.list_marketing_campaigns(tenant_id="t1", status=None, limit=1))) >= 1
    assert len(run(pg_db.list_content_assets(tenant_id="t1", campaign_id=None, limit=1))) >= 1
    assert len(run(pg_db.list_operation_checklists(tenant_id="t1", campaign_id=None, limit=1))) >= 1
    assert len(run(pg_db.list_coverage_tasks(tenant_id="t1", status=None, limit=1))) >= 1
    assert run(pg_db.activate_prompt(12345)) is None

    original_fetchrow = conn.fetchrow

    async def _none_active_prompt(query, *args):
        if "WHERE role_name=$1 AND is_active=TRUE" in query:
            return None
        return await original_fetchrow(query, *args)

    conn.fetchrow = _none_active_prompt
    assert run(pg_db.get_active_prompt("system")) is None
    conn.fetchrow = original_fetchrow
    run(pg_db.upsert_prompt("system", "inactive", activate=False))
    assert not any(
        call[0] == "execute" and "UPDATE prompt_registry SET is_active=FALSE" in str(call[1])
        for call in conn.calls
    )

    original_fetch = conn.fetch

    async def _prompt_fetch(query, *args):
        if "FROM prompt_registry" in query:
            return [{"id": 1, "role_name": "system", "prompt_text": "x", "version": 1, "is_active": True, "created_at": "c", "updated_at": "u"}]
        return await original_fetch(query, *args)

    conn.fetch = _prompt_fetch
    assert len(run(pg_db.list_prompts("system"))) >= 1
    conn.fetch = original_fetch

    async def _none_session(query, *args):
        if "FROM sessions WHERE id=$1 AND user_id=$2" in query:
            return None
        return await original_fetchrow(query, *args)

    conn.fetchrow = _none_session
    assert run(pg_db.load_session("missing", user_id="u1")) is None
    conn.fetchrow = original_fetchrow


def test_postgresql_connect_and_default_prompt_guard_branches(pg_db: Database, monkeypatch: pytest.MonkeyPatch):
    class _DummyAsyncPG:
        class PoolError(Exception):
            pass

        @staticmethod
        async def create_pool(**kwargs):
            raise RuntimeError("generic failure")

    monkeypatch.setitem(sys.modules, "asyncpg", _DummyAsyncPG)
    with pytest.raises(RuntimeError):
        run(pg_db._connect_postgresql())

    monkeypatch.setattr("importlib.util.spec_from_file_location", lambda *args, **kwargs: None)
    monkeypatch.setattr(pg_db, "get_active_prompt", lambda *_a, **_k: asyncio.sleep(0, result=None))
    run(pg_db.ensure_default_prompt_registry())


def test_verify_and_get_user_by_token_invalid_paths(sqlite_db: Database):
    payload = {"sub": "u1", "role": "", "username": "x", "tenant_id": "default"}
    bad_token = jwt.encode(payload, sqlite_db.cfg.JWT_SECRET_KEY, algorithm=sqlite_db.cfg.JWT_ALGORITHM)
    assert sqlite_db.verify_auth_token(bad_token) is None

    invalid_sub_payload = {"sub": "", "role": "admin", "username": "x", "tenant_id": "default"}
    invalid_sub_token = jwt.encode(
        invalid_sub_payload,
        sqlite_db.cfg.JWT_SECRET_KEY,
        algorithm=sqlite_db.cfg.JWT_ALGORITHM,
    )
    assert sqlite_db.verify_auth_token(invalid_sub_token) is None

    assert run(sqlite_db.get_user_by_token("not-a-token")) is None


def test_access_control_schema_sqlite_adds_missing_tenant_column(tmp_path):
    cfg = DummyCfg(DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'ac.db'}", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    run(db.connect())
    assert db._sqlite_conn is not None
    run(
        db._run_sqlite_op(
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
    )
    run(db._ensure_access_control_schema_sqlite())
    cols = run(db._run_sqlite_op(lambda: db._sqlite_conn.execute("PRAGMA table_info(users)").fetchall()))
    assert "tenant_id" in {str(col[1]) for col in cols}
    run(db.close())


def test_schema_version_postgresql_short_circuit_and_delete_parse_fallback(pg_db: Database):
    class _SchemaConn(_RichPgConn):
        async def fetchval(self, query, *args):
            if "MAX(version)" in query:
                return pg_db.target_schema_version
            return await super().fetchval(query, *args)

        async def execute(self, query, *args):
            if "DELETE FROM sessions" in query:
                return "DELETE BAD"
            return await super().execute(query, *args)

        async def fetch(self, query, *args):
            if "FROM access_policies" in query:
                return [
                    {
                        "id": 1,
                        "user_id": "u1",
                        "tenant_id": "t1",
                        "resource_type": "repo",
                        "resource_id": "*",
                        "action": "read",
                        "effect": "allow",
                        "created_at": "c",
                        "updated_at": "u",
                    }
                ]
            return await super().fetch(query, *args)

    conn = _SchemaConn()
    pg_db._pg_pool = _FakePool(conn)
    run(pg_db._ensure_schema_version_postgresql())
    assert not any("baseline migration" in str(call[1]) for call in conn.calls if call[0] == "execute")

    assert run(pg_db.delete_session("s1")) is False
    assert len(run(pg_db.list_access_policies("u1", tenant_id="t1"))) == 1
    assert len(run(pg_db.list_access_policies("u1", tenant_id=""))) == 1


def test_list_operation_checklists_sqlite_campaign_filter_branch(sqlite_db: Database):
    campaign = run(sqlite_db.upsert_marketing_campaign(tenant_id="t1", name="Campaign for checklist"))
    run(sqlite_db.add_operation_checklist(tenant_id="t1", title="Ops", items=["x"], campaign_id=campaign.id))
    rows = run(sqlite_db.list_operation_checklists(tenant_id="t1", campaign_id=campaign.id, limit=10))
    assert len(rows) == 1
