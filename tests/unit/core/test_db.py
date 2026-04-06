from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
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
