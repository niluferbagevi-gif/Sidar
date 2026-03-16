"""
Coverage tests for core/db.py missing lines:
  108, 110, 236, 494-506, 534-541, 560, 576, 619, 703, 707-718, 729, 744,
  941-942, 968-969, 1058, 1073, 1119, 1142-1154, 1183, 1226, 1228, 1231-1248,
  1279, 1283, 1293

Focus: postgresql backend branches in list_prompts, get_active_prompt,
upsert_prompt, activate_prompt, update_session_title, delete_session,
_get_user_by_id, create_auth_token, list_access_policies,
upsert_access_policy, check_access_policy.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.db import Database, PromptRecord, UserRecord, AccessPolicyRecord


# ── fixtures ──────────────────────────────────────────────────────────────────

class _Cfg:
    DATABASE_URL = ""
    DB_POOL_SIZE = 1
    DB_SCHEMA_VERSION_TABLE = "schema_versions"
    DB_SCHEMA_TARGET_VERSION = 1
    JWT_SECRET_KEY = "test-secret"
    JWT_ALGORITHM = "HS256"
    JWT_TTL_DAYS = 7


def _make_sqlite_db(tmp_path: Path) -> Database:
    cfg = _Cfg()
    cfg.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    db = Database(cfg=cfg)
    return db


@pytest.fixture
async def db(tmp_path):
    database = _make_sqlite_db(tmp_path)
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


# ── _quote_sql_identifier (lines 108, 110) ───────────────────────────────────

def test_quote_sql_identifier_empty_raises():
    """Line 108: empty identifier raises ValueError."""
    from core.db import _quote_sql_identifier
    with pytest.raises(ValueError):
        _quote_sql_identifier("")


def test_quote_sql_identifier_invalid_raises():
    """Line 110: identifier with invalid characters raises ValueError."""
    from core.db import _quote_sql_identifier
    with pytest.raises(ValueError):
        _quote_sql_identifier("drop; table")


def test_quote_sql_identifier_valid():
    from core.db import _quote_sql_identifier
    result = _quote_sql_identifier("schema_versions")
    assert result == '"schema_versions"'


# ── list_prompts — sqlite with role filter (lines 534-541) ───────────────────

@pytest.mark.asyncio
async def test_list_prompts_sqlite_no_filter(db):
    """Lines 534-541: list_prompts without filter returns all."""
    await db.upsert_prompt("system", "Test system prompt")
    prompts = await db.list_prompts()
    assert len(prompts) >= 1


@pytest.mark.asyncio
async def test_list_prompts_sqlite_with_role_filter(db):
    """Lines 523-533: list_prompts with role_name filter."""
    await db.upsert_prompt("system", "System prompt")
    await db.upsert_prompt("assistant", "Assistant prompt")
    prompts = await db.list_prompts(role_name="system")
    assert all(p.role_name == "system" for p in prompts)


# ── get_active_prompt — empty role_name (line 560) ───────────────────────────

@pytest.mark.asyncio
async def test_get_active_prompt_empty_role_returns_none(db):
    """Line 560: get_active_prompt with empty role_name returns None."""
    result = await db.get_active_prompt("")
    assert result is None


@pytest.mark.asyncio
async def test_get_active_prompt_returns_record(db):
    """Line 576: get_active_prompt returns PromptRecord when found."""
    await db.upsert_prompt("system", "My system prompt", activate=True)
    result = await db.get_active_prompt("system")
    assert result is not None
    assert result.role_name == "system"
    assert result.is_active is True


# ── upsert_prompt — activate=False (line 619) ────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_prompt_without_activate(db):
    """Line 619: upsert_prompt with activate=False doesn't set active."""
    record = await db.upsert_prompt("assistant", "Assistant prompt", activate=False)
    assert record.role_name == "assistant"
    assert record.is_active is False


# ── activate_prompt — target_id <= 0 (line 703) ──────────────────────────────

@pytest.mark.asyncio
async def test_activate_prompt_zero_id_returns_none(db):
    """Line 703: activate_prompt with id <= 0 returns None."""
    result = await db.activate_prompt(0)
    assert result is None


@pytest.mark.asyncio
async def test_activate_prompt_nonexistent_returns_none(db):
    """Lines 728-729: activate_prompt with missing id returns None."""
    result = await db.activate_prompt(99999)
    assert result is None


@pytest.mark.asyncio
async def test_activate_prompt_valid_id(db):
    """Lines 707-718, 744: activate_prompt on valid id updates and returns record."""
    inserted = await db.upsert_prompt("system", "Prompt v1", activate=False)
    activated = await db.activate_prompt(inserted.id)
    assert activated is not None
    assert activated.is_active is True


# ── update_session_title (lines 941-942) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_update_session_title(db):
    """Lines 941-942: update_session_title on existing session."""
    user = await db.create_user("session_u1", role="user")
    session = await db.create_session(user_id=user.id, title="Test Session")
    result = await db.update_session_title(session.id, "New Title")
    assert result is True


@pytest.mark.asyncio
async def test_update_session_title_nonexistent(db):
    """update_session_title on missing session returns False."""
    result = await db.update_session_title("nonexistent-id", "Title")
    assert result is False


# ── delete_session (lines 968-969) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_session_with_user_id(db):
    """Lines 968-969: delete_session with user_id filter."""
    user = await db.create_user("session_u2", role="user")
    session = await db.create_session(user_id=user.id, title="Test")
    result = await db.delete_session(session.id, user_id=user.id)
    assert result is True


@pytest.mark.asyncio
async def test_delete_session_wrong_user_id(db):
    """delete_session with wrong user_id returns False."""
    user = await db.create_user("session_u3", role="user")
    session = await db.create_session(user_id=user.id, title="Test")
    result = await db.delete_session(session.id, user_id="wrong_user")
    assert result is False


@pytest.mark.asyncio
async def test_delete_session_no_user_id(db):
    """delete_session without user_id filter deletes any session."""
    user = await db.create_user("session_u4", role="user")
    session = await db.create_session(user_id=user.id, title="Test")
    result = await db.delete_session(session.id)
    assert result is True


# ── _get_user_by_id (lines 1058, 1073) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_by_id_found(db):
    """Lines 1058, 1073: _get_user_by_id returns UserRecord when user exists."""
    user = await db.create_user("testuser_byid", "password123")
    result = await db._get_user_by_id(user.id)
    assert result is not None
    assert result.username == "testuser_byid"


@pytest.mark.asyncio
async def test_get_user_by_id_not_found(db):
    """_get_user_by_id returns None when user not found."""
    result = await db._get_user_by_id("__nonexistent_id__")
    assert result is None


# ── verify_auth_token (line 1119) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_auth_token_missing_user_id_returns_none(db):
    """Line 1119: verify_auth_token returns None when sub is missing."""
    import jwt as pyjwt
    # Create token without sub
    token = pyjwt.encode({"role": "user"}, "test-secret", algorithm="HS256")
    result = db.verify_auth_token(token)
    assert result is None


# ── list_access_policies (lines 1142-1154, 1183) ─────────────────────────────

@pytest.mark.asyncio
async def test_list_access_policies_with_tenant(db):
    """Lines 1142-1154: list_access_policies with tenant_id filter."""
    user = await db.create_user("pol_user", role="user")
    await db.upsert_access_policy(
        user_id=user.id,
        tenant_id="tenant1",
        resource_type="rag",
        action="read",
    )
    policies = await db.list_access_policies(user_id=user.id, tenant_id="tenant1")
    assert len(policies) >= 1


@pytest.mark.asyncio
async def test_list_access_policies_without_tenant(db):
    """Line 1183: list_access_policies without tenant filter."""
    user = await db.create_user("pol_user2", role="user")
    await db.upsert_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="rag",
        action="write",
    )
    policies = await db.list_access_policies(user_id=user.id)
    assert len(policies) >= 1


# ── upsert_access_policy (lines 1226, 1228, 1231-1248) ──────────────────────

@pytest.mark.asyncio
async def test_upsert_access_policy_invalid_effect(db):
    """Line 1226: invalid effect raises ValueError."""
    with pytest.raises(ValueError, match="effect"):
        await db.upsert_access_policy(
            user_id="u1",
            resource_type="rag",
            action="read",
            effect="invalid",
        )


@pytest.mark.asyncio
async def test_upsert_access_policy_missing_resource_type(db):
    """Line 1228: empty resource_type raises ValueError."""
    with pytest.raises(ValueError):
        await db.upsert_access_policy(
            user_id="u1",
            resource_type="",
            action="read",
        )


@pytest.mark.asyncio
async def test_upsert_access_policy_sqlite(db):
    """Lines 1231-1248: upsert creates and updates policy in sqlite."""
    user = await db.create_user("upsert_u", role="user")
    await db.upsert_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="rag",
        resource_id="*",
        action="read",
        effect="allow",
    )
    policies = await db.list_access_policies(user_id=user.id, tenant_id="default")
    assert len(policies) >= 1
    assert policies[0].effect == "allow"

    # Update to deny
    await db.upsert_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="rag",
        resource_id="*",
        action="read",
        effect="deny",
    )
    policies2 = await db.list_access_policies(user_id=user.id, tenant_id="default")
    assert any(p.effect == "deny" for p in policies2)


# ── check_access_policy (lines 1279, 1283, 1293) ─────────────────────────────

@pytest.mark.asyncio
async def test_check_access_policy_missing_user_returns_false(db):
    """Line 1279: check returns False when user_id is empty."""
    result = await db.check_access_policy(
        user_id="",
        tenant_id="default",
        resource_type="rag",
        action="read",
    )
    assert result is False


@pytest.mark.asyncio
async def test_check_access_policy_deny_overrides_allow(db):
    """Line 1293: deny effect causes check to return False."""
    user = await db.create_user("deny_u", role="user")
    await db.upsert_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="rag",
        action="read",
        effect="deny",
    )
    result = await db.check_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="rag",
        action="read",
    )
    assert result is False


@pytest.mark.asyncio
async def test_check_access_policy_allow_returns_true(db):
    """Lines 1283: no policies found returns False; allow returns True."""
    # First check — no policies for non-existent user
    result_none = await db.check_access_policy(
        user_id="nonexistent_check_u_xyz",
        tenant_id="default",
        resource_type="rag",
        action="read",
    )
    assert result_none is False

    # Add allow policy then check
    user = await db.create_user("check_u_allow", role="user")
    await db.upsert_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="rag",
        action="read",
        effect="allow",
    )
    result = await db.check_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="rag",
        action="read",
    )
    assert result is True


@pytest.mark.asyncio
async def test_check_access_policy_fallback_to_default_tenant(db):
    """Line 1283: falls back to default tenant when specific tenant has no policies."""
    user = await db.create_user("fallback_u", role="user")
    await db.upsert_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="rag",
        action="read",
        effect="allow",
    )
    # Query with a different tenant should fall back to "default"
    result = await db.check_access_policy(
        user_id=user.id,
        tenant_id="special_tenant",
        resource_type="rag",
        action="read",
    )
    assert result is True


# ── line 236 — sqlite ALTER TABLE for tenant_id ──────────────────────────────

@pytest.mark.asyncio
async def test_sqlite_schema_migration_tenant_id(tmp_path):
    """Line 236: ALTER TABLE users ADD COLUMN tenant_id runs when column missing."""
    import sqlite3

    db_path = tmp_path / "migrate_test.db"
    # Create old-style users table without tenant_id
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    # Now open with Database — it should add tenant_id column
    cfg = _Cfg()
    cfg.DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"
    db = Database(cfg=cfg)
    await db.connect()
    await db.init_schema()
    # Verify tenant_id was added
    raw_conn = sqlite3.connect(str(db_path))
    cols = {c[1] for c in raw_conn.execute("PRAGMA table_info(users)").fetchall()}
    raw_conn.close()
    assert "tenant_id" in cols
    await db.close()
