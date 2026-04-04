from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import types

import pytest

def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("jwt"):
    jwt_stub = types.ModuleType("jwt")

    class _JwtError(Exception):
        pass

    jwt_stub.PyJWTError = _JwtError
    jwt_stub.decode = lambda *_args, **_kwargs: {}
    jwt_stub.encode = lambda *_args, **_kwargs: "token"
    sys.modules["jwt"] = jwt_stub

from core.db import Database


def _cfg(tmp_path: Path, name: str = "phase3.db") -> SimpleNamespace:
    return SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / name}",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=2,
        JWT_TTL_DAYS=7,
    )


def _run(coro):
    return asyncio.run(coro)


def test_prompt_registry_lifecycle_and_activation(tmp_path: Path) -> None:
    db = Database(_cfg(tmp_path, "prompt.db"))
    _run(db.connect())
    _run(db.init_schema())

    with pytest.raises(ValueError):
        _run(db.upsert_prompt("", ""))

    _run(db.upsert_prompt("system", "v1"))
    second = _run(db.upsert_prompt("system", "v2", activate=False))

    active_before = _run(db.get_active_prompt("system"))
    assert active_before is not None and active_before.is_active is True

    activated = _run(db.activate_prompt(second.id))
    assert activated is not None and activated.id == second.id and activated.prompt_text == "v2" and activated.is_active is True

    rows = _run(db.list_prompts("system"))
    assert len(rows) >= 3
    assert _run(db.activate_prompt(-1)) is None

    _run(db.close())


def test_access_policy_and_audit_log_paths(tmp_path: Path) -> None:
    db = Database(_cfg(tmp_path, "policy.db"))
    _run(db.connect())
    _run(db.init_schema())

    user = _run(db.create_user("policy-user", tenant_id="tenant-a"))

    with pytest.raises(ValueError):
        _run(db.upsert_access_policy(user_id=user.id, resource_type="", action="read"))
    with pytest.raises(ValueError):
        _run(db.upsert_access_policy(user_id=user.id, resource_type="repo", action="read", effect="maybe"))

    _run(
        db.upsert_access_policy(
            user_id=user.id,
            tenant_id="default",
            resource_type="repo",
            resource_id="*",
            action="read",
            effect="allow",
        )
    )
    _run(
        db.upsert_access_policy(
            user_id=user.id,
            tenant_id="tenant-a",
            resource_type="repo",
            resource_id="project-x",
            action="read",
            effect="deny",
        )
    )

    assert (
        _run(
            db.check_access_policy(
                user_id=user.id,
                tenant_id="tenant-a",
                resource_type="repo",
                resource_id="project-x",
                action="read",
            )
        )
        is False
    )
    assert (
        _run(
            db.check_access_policy(
                user_id=user.id,
                tenant_id="tenant-b",
                resource_type="repo",
                resource_id="anything",
                action="read",
            )
        )
        is True
    )

    with pytest.raises(ValueError):
        _run(db.record_audit_log(action="", resource="repo", ip_address="127.0.0.1", allowed=True))

    _run(
        db.record_audit_log(
            user_id=user.id,
            tenant_id="tenant-a",
            action="READ",
            resource="repo/project-x",
            ip_address="",
            allowed=False,
        )
    )
    logs = _run(db.list_audit_logs(user_id=user.id, limit=5))
    assert len(logs) == 1
    assert logs[0].allowed is False
    assert logs[0].ip_address == "unknown"

    _run(db.close())


def test_marketing_content_and_checklist_paths(tmp_path: Path) -> None:
    db = Database(_cfg(tmp_path, "marketing.db"))
    _run(db.connect())
    _run(db.init_schema())

    with pytest.raises(ValueError):
        _run(db.upsert_marketing_campaign(tenant_id="default", name=""))

    campaign = _run(
        db.upsert_marketing_campaign(
            tenant_id="tenant-a",
            name="Launch",
            channel="Email",
            status="ACTIVE",
            metadata={"priority": "high"},
        )
    )
    updated = _run(
        db.upsert_marketing_campaign(
            tenant_id="tenant-a",
            campaign_id=campaign.id,
            name="Launch v2",
            status="PAUSED",
        )
    )
    assert updated.name == "Launch v2"

    with pytest.raises(ValueError):
        _run(db.add_content_asset(campaign_id=campaign.id, tenant_id="tenant-a", asset_type="", title="x", content="y"))

    asset = _run(
        db.add_content_asset(
            campaign_id=campaign.id,
            tenant_id="tenant-a",
            asset_type="post",
            title="Teaser",
            content="Hello",
            metadata={"lang": "tr"},
        )
    )
    assets = _run(db.list_content_assets(tenant_id="tenant-a", campaign_id=campaign.id))
    assert [a.id for a in assets] == [asset.id]

    with pytest.raises(ValueError):
        _run(db.add_operation_checklist(tenant_id="tenant-a", title="", items=[]))

    checklist = _run(
        db.add_operation_checklist(
            tenant_id="tenant-a",
            campaign_id=campaign.id,
            title="Go-live",
            items=[" qa ", "", {"owner": "ops", "": "skip"}],
        )
    )
    parsed = json.loads(checklist.items_json)
    assert parsed == ["qa", {"owner": "ops"}]

    lists = _run(db.list_operation_checklists(tenant_id="tenant-a", campaign_id=campaign.id))
    assert len(lists) == 1

    _run(db.close())


def test_coverage_task_finding_quota_and_stats_paths(tmp_path: Path) -> None:
    db = Database(_cfg(tmp_path, "coverage.db"))
    _run(db.connect())
    _run(db.init_schema())

    user = _run(db.create_user("quota-user"))

    with pytest.raises(ValueError):
        _run(db.create_coverage_task(command="", pytest_output="x"))

    task = _run(
        db.create_coverage_task(
            tenant_id="tenant-c",
            requester_role="coverage",
            command="pytest -q",
            pytest_output="FAIL",
            status="pending_review",
            target_path="core/db.py",
            suggested_test_path="tests/core/test_db_phase3_paths.py",
        )
    )

    with pytest.raises(ValueError):
        _run(db.add_coverage_finding(task_id=task.id, finding_type="", target_path="a", summary="b"))

    finding = _run(
        db.add_coverage_finding(
            task_id=task.id,
            finding_type="missing-test",
            target_path="core/db.py",
            summary="branch not covered",
            details={"line": 42},
        )
    )
    assert finding.task_id == task.id

    tasks = _run(db.list_coverage_tasks(tenant_id="tenant-c", status="pending_review", limit=1))
    assert len(tasks) == 1 and tasks[0].id == task.id

    _run(db.upsert_user_quota(user.id, daily_token_limit=-5, daily_request_limit=2))
    _run(db.record_provider_usage_daily(user.id, "OpenAI", tokens_used=100, requests_inc=1))
    status = _run(db.get_user_quota_status(user.id, "openai"))
    assert status["daily_token_limit"] == 0
    assert status["daily_request_limit"] == 2
    assert status["request_limit_exceeded"] is False

    users = _run(db.list_users_with_quotas())
    assert any(u["id"] == user.id for u in users)

    admin = _run(db.get_admin_stats())
    assert admin["total_users"] >= 1
    assert admin["total_tokens_used"] >= 100

    _run(db.close())


def test_session_crud_and_replace_messages_paths(tmp_path: Path) -> None:
    db = Database(_cfg(tmp_path, "sessions.db"))
    _run(db.connect())
    _run(db.init_schema())

    user = _run(db.create_user("session-user"))
    other = _run(db.create_user("session-other"))

    session = _run(db.create_session(user.id, "Initial"))
    assert _run(db.update_session_title(session.id, "Updated")) is True
    assert _run(db.update_session_title("missing", "Nope")) is False

    _run(db.add_message(session.id, "user", "hello", tokens_used=-9))
    replaced = _run(
        db.replace_session_messages(
            session.id,
            [{"role": " user ", "content": "a"}, {"role": "assistant", "content": "  "}, {"content": "b"}],
        )
    )
    assert replaced == 2

    messages = _run(db.get_session_messages(session.id))
    assert [m.content for m in messages] == ["a", "b"]
    assert messages[1].role == "assistant"

    loaded = _run(db.load_session(session.id, user_id=user.id))
    assert loaded is not None
    assert _run(db.load_session(session.id, user_id=other.id)) is None

    own_sessions = _run(db.list_sessions(user.id))
    assert len(own_sessions) == 1

    assert _run(db.delete_session(session.id, user_id=other.id)) is False
    assert _run(db.delete_session(session.id, user_id=user.id)) is True

    _run(db.close())
