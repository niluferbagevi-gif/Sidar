from __future__ import annotations

import json
import sqlite3
import types
from dataclasses import dataclass
from datetime import datetime

import jwt
import pytest

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
