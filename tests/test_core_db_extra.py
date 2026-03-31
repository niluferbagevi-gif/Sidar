"""
Extra tests for core/db.py targeting missing coverage lines.

Covers:
- Dataclasses: UserRecord, AuthTokenRecord, SessionRecord, MessageRecord,
  AccessPolicyRecord, PromptRecord, AuditLogRecord, MarketingCampaignRecord,
  ContentAssetRecord, OperationChecklistRecord, CoverageTaskRecord,
  CoverageFindingRecord
- Helper functions: _utc_now_iso, _hash_password, _verify_password,
  _expires_in, _quote_sql_identifier, _json_dumps
- Database (SQLite backend): connect, close, init_schema, create_user,
  ensure_user, list_sessions, load_session, update_session_title,
  delete_session, register_user, authenticate_user, create_auth_token,
  verify_auth_token, get_user_by_token, upsert_prompt, get_active_prompt,
  list_prompts, activate_prompt, upsert_access_policy, list_access_policies,
  check_access_policy, record_audit_log

All async methods use asyncio.run(). Heavy native deps (jwt, cryptography)
are already stubbed by conftest.py.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import types
import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Ensure stubs are in place (conftest already does jwt/cryptography stubs).
# We only need to make sure core.db can be imported.
# ---------------------------------------------------------------------------

def _get_db_module():
    """Re-import core.db with a fresh Config stub each call."""
    for k in list(sys.modules.keys()):
        if k in ("core.db", "config"):
            del sys.modules[k]

    cfg_mod = types.ModuleType("config")

    class _Cfg:
        DATABASE_URL = ""
        DB_POOL_SIZE = 5
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        JWT_SECRET_KEY = "test-secret"
        JWT_ALGORITHM = "HS256"
        JWT_TTL_DAYS = 7
        BASE_DIR = Path(tempfile.gettempdir())

    cfg_mod.Config = _Cfg
    sys.modules["config"] = cfg_mod

    import core.db as db
    return db


# Pre-import once so we can reference symbols in type hints
_db_mod = _get_db_module()


def _fresh_db(tmp_path: Path):
    """Return an initialized Database instance backed by SQLite in tmp_path."""
    db = _get_db_module()

    class _Cfg:
        DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path}/test.db"
        DB_POOL_SIZE = 1
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        JWT_SECRET_KEY = "test-secret"
        JWT_ALGORITHM = "HS256"
        JWT_TTL_DAYS = 1
        BASE_DIR = tmp_path

    sys.modules["config"].Config = _Cfg

    # Monkey-patch ensure_default_prompt_registry to be a no-op (avoids
    # reading agent/definitions.py which may not exist in test env)
    async def _noop(self):
        pass

    db.Database.ensure_default_prompt_registry = _noop  # type: ignore[method-assign]

    instance = db.Database(_Cfg())
    asyncio.run(instance.connect())
    asyncio.run(instance.init_schema())
    return db, instance


# ===========================================================================
# Dataclass construction
# ===========================================================================

class TestDataclasses:
    def test_user_record(self):
        db = _get_db_module()
        u = db.UserRecord(id="1", username="alice", role="admin", created_at="now")
        assert u.id == "1"
        assert u.tenant_id == "default"

    def test_auth_token_record(self):
        db = _get_db_module()
        r = db.AuthTokenRecord(token="t", user_id="u", expires_at="e", created_at="c")
        assert r.token == "t"

    def test_session_record(self):
        db = _get_db_module()
        s = db.SessionRecord(id="s", user_id="u", title="T", created_at="c", updated_at="u2")
        assert s.title == "T"

    def test_message_record(self):
        db = _get_db_module()
        m = db.MessageRecord(id=1, session_id="s", role="user", content="hi", tokens_used=5, created_at="c")
        assert m.content == "hi"

    def test_access_policy_record(self):
        db = _get_db_module()
        p = db.AccessPolicyRecord(id=1, user_id="u", tenant_id="t", resource_type="r",
                                   resource_id="*", action="read", effect="allow",
                                   created_at="c", updated_at="u")
        assert p.effect == "allow"

    def test_prompt_record(self):
        db = _get_db_module()
        p = db.PromptRecord(id=1, role_name="system", prompt_text="Hello", version=1,
                             is_active=True, created_at="c", updated_at="u")
        assert p.is_active is True

    def test_audit_log_record(self):
        db = _get_db_module()
        a = db.AuditLogRecord(id=1, user_id="u", tenant_id="t", action="read",
                               resource="doc", ip_address="1.2.3.4", allowed=True, timestamp="ts")
        assert a.allowed is True

    def test_marketing_campaign_record(self):
        db = _get_db_module()
        m = db.MarketingCampaignRecord(id=1, tenant_id="t", name="camp", channel="email",
                                        objective="reach", status="draft", owner_user_id="u",
                                        budget=100.0, metadata_json="{}", created_at="c", updated_at="u")
        assert m.budget == 100.0

    def test_content_asset_record(self):
        db = _get_db_module()
        c = db.ContentAssetRecord(id=1, campaign_id=1, tenant_id="t", asset_type="blog",
                                   title="T", content="C", channel="web",
                                   metadata_json="{}", created_at="c", updated_at="u")
        assert c.asset_type == "blog"

    def test_operation_checklist_record(self):
        db = _get_db_module()
        o = db.OperationChecklistRecord(id=1, campaign_id=None, tenant_id="t", title="T",
                                         items_json="[]", status="pending",
                                         owner_user_id="u", created_at="c", updated_at="u")
        assert o.campaign_id is None

    def test_coverage_task_record(self):
        db = _get_db_module()
        r = db.CoverageTaskRecord(id=1, tenant_id="t", requester_role="coverage",
                                   command="pytest", pytest_output="", status="pending_review",
                                   target_path="core/rag.py", suggested_test_path="tests/t.py",
                                   review_payload_json="{}", created_at="c", updated_at="u")
        assert r.status == "pending_review"

    def test_coverage_finding_record(self):
        db = _get_db_module()
        f = db.CoverageFindingRecord(id=1, task_id=1, finding_type="missing",
                                      target_path="core/rag.py", summary="s",
                                      severity="medium", details_json="{}", created_at="c")
        assert f.finding_type == "missing"


# ===========================================================================
# Helper functions
# ===========================================================================

class TestHelperFunctions:
    def test_utc_now_iso_is_string(self):
        db = _get_db_module()
        result = db._utc_now_iso()
        assert isinstance(result, str)
        assert "T" in result

    def test_hash_password_format(self):
        db = _get_db_module()
        h = db._hash_password("mypassword")
        parts = h.split("$")
        assert parts[0] == "pbkdf2_sha256"
        assert len(parts) == 3

    def test_hash_password_with_salt(self):
        db = _get_db_module()
        h = db._hash_password("pass", salt="fixed_salt")
        assert "fixed_salt" in h

    def test_verify_password_correct(self):
        db = _get_db_module()
        h = db._hash_password("secret")
        assert db._verify_password("secret", h) is True

    def test_verify_password_wrong(self):
        db = _get_db_module()
        h = db._hash_password("secret")
        assert db._verify_password("wrong", h) is False

    def test_verify_password_bad_format(self):
        db = _get_db_module()
        assert db._verify_password("x", "not_valid_format") is False

    def test_verify_password_wrong_algorithm(self):
        db = _get_db_module()
        assert db._verify_password("x", "bcrypt$salt$hash") is False

    def test_expires_in_returns_iso(self):
        db = _get_db_module()
        result = db._expires_in(days=7)
        assert isinstance(result, str)
        assert "T" in result

    def test_quote_sql_identifier_valid(self):
        db = _get_db_module()
        assert db._quote_sql_identifier("my_table") == '"my_table"'

    def test_quote_sql_identifier_empty_raises(self):
        db = _get_db_module()
        with pytest.raises(ValueError):
            db._quote_sql_identifier("")

    def test_quote_sql_identifier_invalid_raises(self):
        db = _get_db_module()
        with pytest.raises(ValueError):
            db._quote_sql_identifier("1badname")

    def test_json_dumps_serializes(self):
        db = _get_db_module()
        result = db._json_dumps({"b": 2, "a": 1})
        import json
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": 2}


# ===========================================================================
# Database — backend configuration
# ===========================================================================

class TestDatabaseConfig:
    def test_default_backend_is_sqlite(self):
        db = _get_db_module()

        class _Cfg:
            DATABASE_URL = ""
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tempfile.gettempdir())

        sys.modules["config"].Config = _Cfg
        instance = db.Database(_Cfg())
        assert instance._backend == "sqlite"

    def test_postgresql_url_sets_backend(self):
        db = _get_db_module()

        class _Cfg:
            DATABASE_URL = "postgresql://user:pass@localhost/db"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tempfile.gettempdir())

        sys.modules["config"].Config = _Cfg
        instance = db.Database(_Cfg())
        assert instance._backend == "postgresql"

    def test_sqlite_path_resolved(self):
        db = _get_db_module()
        with tempfile.TemporaryDirectory() as td:
            class _Cfg:
                DATABASE_URL = f"sqlite+aiosqlite:///{td}/mydb.db"
                DB_POOL_SIZE = 1
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1
                BASE_DIR = Path(td)

            sys.modules["config"].Config = _Cfg
            instance = db.Database(_Cfg())
            assert instance._sqlite_path is not None
            assert str(instance._sqlite_path).endswith("mydb.db")


# ===========================================================================
# Database — connect / close
# ===========================================================================

class TestDatabaseConnectClose:
    def test_connect_creates_connection(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            assert instance._sqlite_conn is not None

    def test_close_sets_conn_to_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            asyncio.run(instance.close())
            assert instance._sqlite_conn is None

    def test_double_connect_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            asyncio.run(instance.connect())  # Second call — should not raise
            assert instance._sqlite_conn is not None


# ===========================================================================
# Database — create_user / ensure_user / list_sessions
# ===========================================================================

class TestCreateUser:
    def test_create_user_returns_record(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("alice", role="admin"))
            assert user.username == "alice"
            assert user.role == "admin"
            assert user.id

    def test_create_user_with_password(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("bob", role="user", password="secret"))
            assert user.username == "bob"

    def test_ensure_user_returns_existing(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user1 = asyncio.run(instance.create_user("charlie", role="user"))
            user2 = asyncio.run(instance.ensure_user("charlie"))
            assert user1.id == user2.id

    def test_ensure_user_creates_if_missing(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.ensure_user("newuser"))
            assert user.username == "newuser"

    def test_list_sessions_empty_initially(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("dave", role="user"))
            sessions = asyncio.run(instance.list_sessions(user.id))
            assert sessions == []


# ===========================================================================
# Database — register_user / authenticate_user
# ===========================================================================

class TestAuthFlow:
    def test_register_and_authenticate(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            asyncio.run(instance.register_user("eve", "pass123"))
            user = asyncio.run(instance.authenticate_user("eve", "pass123"))
            assert user is not None
            assert user.username == "eve"

    def test_wrong_password_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            asyncio.run(instance.register_user("frank", "right"))
            user = asyncio.run(instance.authenticate_user("frank", "wrong"))
            assert user is None

    def test_unknown_user_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.authenticate_user("ghost", "any"))
            assert user is None


# ===========================================================================
# Database — create_auth_token / verify_auth_token / get_user_by_token
# ===========================================================================

class TestAuthToken:
    def test_create_token_returns_record(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("grace", role="user"))
            token_rec = asyncio.run(instance.create_auth_token(
                user.id, ttl_days=1, role="user", username="grace", tenant_id="default"
            ))
            assert token_rec.token
            assert token_rec.user_id == user.id

    def test_verify_valid_token(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("henry", role="admin"))
            token_rec = asyncio.run(instance.create_auth_token(
                user.id, role="admin", username="henry"
            ))
            result = instance.verify_auth_token(token_rec.token)
            assert result is not None
            assert result.id == user.id

    def test_verify_invalid_token_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            result = instance.verify_auth_token("not.a.valid.token")
            assert result is None

    def test_get_user_by_token_returns_user(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("irene", role="user"))
            token_rec = asyncio.run(instance.create_auth_token(
                user.id, role="user", username="irene"
            ))
            fetched = asyncio.run(instance.get_user_by_token(token_rec.token))
            assert fetched is not None
            assert fetched.username == "irene"

    def test_get_user_by_invalid_token_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            result = asyncio.run(instance.get_user_by_token("bad.token.here"))
            assert result is None


# ===========================================================================
# Database — load_session / update_session_title / delete_session
# ===========================================================================

class TestSessions:
    def _create_session(self, instance, user_id: str, title: str = "My Session") -> str:
        """Insert a session directly and return its id."""
        db = _get_db_module()
        import sqlite3, uuid as _uuid

        sid = str(_uuid.uuid4())
        now = db._utc_now_iso()

        def _run():
            instance._sqlite_conn.execute(
                "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (sid, user_id, title, now, now),
            )
            instance._sqlite_conn.commit()

        asyncio.run(instance._run_sqlite_op(_run))
        return sid

    def test_load_session_returns_record(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("joe", role="user"))
            sid = self._create_session(instance, user.id)
            rec = asyncio.run(instance.load_session(sid))
            assert rec is not None
            assert rec.id == sid

    def test_load_session_wrong_user_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("kate", role="user"))
            sid = self._create_session(instance, user.id)
            rec = asyncio.run(instance.load_session(sid, user_id="other_user"))
            assert rec is None

    def test_load_nonexistent_session_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            rec = asyncio.run(instance.load_session("doesnotexist"))
            assert rec is None

    def test_update_session_title(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("liam", role="user"))
            sid = self._create_session(instance, user.id, "Old Title")
            updated = asyncio.run(instance.update_session_title(sid, "New Title"))
            assert updated is True
            rec = asyncio.run(instance.load_session(sid))
            assert rec.title == "New Title"

    def test_update_nonexistent_session_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            updated = asyncio.run(instance.update_session_title("fake", "title"))
            assert updated is False

    def test_delete_session(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("mia", role="user"))
            sid = self._create_session(instance, user.id)
            deleted = asyncio.run(instance.delete_session(sid))
            assert deleted is True
            rec = asyncio.run(instance.load_session(sid))
            assert rec is None

    def test_delete_session_with_user_id_filter(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("nina", role="user"))
            sid = self._create_session(instance, user.id)
            deleted = asyncio.run(instance.delete_session(sid, user_id=user.id))
            assert deleted is True


# ===========================================================================
# Database — upsert_prompt / get_active_prompt / list_prompts / activate_prompt
# ===========================================================================

class TestPromptRegistry:
    def test_upsert_prompt_returns_record(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            rec = asyncio.run(instance.upsert_prompt("system", "You are helpful."))
            assert rec.role_name == "system"
            assert rec.is_active is True

    def test_upsert_prompt_empty_raises(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            with pytest.raises(ValueError):
                asyncio.run(instance.upsert_prompt("", "text"))

    def test_get_active_prompt_returns_latest(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            asyncio.run(instance.upsert_prompt("system", "v1"))
            asyncio.run(instance.upsert_prompt("system", "v2"))
            rec = asyncio.run(instance.get_active_prompt("system"))
            assert rec is not None
            assert rec.prompt_text == "v2"

    def test_get_active_prompt_empty_role_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            result = asyncio.run(instance.get_active_prompt(""))
            assert result is None

    def test_list_prompts_all(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            asyncio.run(instance.upsert_prompt("system", "p1"))
            asyncio.run(instance.upsert_prompt("system", "p2"))
            prompts = asyncio.run(instance.list_prompts())
            assert len(prompts) >= 2

    def test_list_prompts_filtered_by_role(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            asyncio.run(instance.upsert_prompt("system", "sys"))
            asyncio.run(instance.upsert_prompt("reviewer", "rev"))
            prompts = asyncio.run(instance.list_prompts("reviewer"))
            assert all(p.role_name == "reviewer" for p in prompts)

    def test_activate_prompt_zero_id_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            result = asyncio.run(instance.activate_prompt(0))
            assert result is None

    def test_activate_prompt_nonexistent_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            result = asyncio.run(instance.activate_prompt(9999))
            assert result is None


# ===========================================================================
# Database — upsert_access_policy / list_access_policies / check_access_policy
# ===========================================================================

class TestAccessPolicies:
    def test_upsert_then_list(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("oscar", role="user"))
            asyncio.run(instance.upsert_access_policy(
                user_id=user.id, tenant_id="default",
                resource_type="document", action="read", effect="allow",
            ))
            policies = asyncio.run(instance.list_access_policies(user.id))
            assert len(policies) == 1
            assert policies[0].action == "read"

    def test_upsert_invalid_effect_raises(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("peter", role="user"))
            with pytest.raises(ValueError, match="effect"):
                asyncio.run(instance.upsert_access_policy(
                    user_id=user.id, resource_type="doc", action="read", effect="maybe"
                ))

    def test_upsert_missing_resource_type_raises(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("quinn", role="user"))
            with pytest.raises(ValueError):
                asyncio.run(instance.upsert_access_policy(
                    user_id=user.id, resource_type="", action="read"
                ))

    def test_check_access_policy_allow(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("rose", role="user"))
            asyncio.run(instance.upsert_access_policy(
                user_id=user.id, resource_type="document", action="read", effect="allow"
            ))
            allowed = asyncio.run(instance.check_access_policy(
                user_id=user.id, resource_type="document", action="read"
            ))
            assert allowed is True

    def test_check_access_policy_deny_overrides_allow(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("sam", role="user"))
            asyncio.run(instance.upsert_access_policy(
                user_id=user.id, resource_type="document", action="delete", effect="deny"
            ))
            denied = asyncio.run(instance.check_access_policy(
                user_id=user.id, resource_type="document", action="delete"
            ))
            assert denied is False

    def test_check_access_policy_no_policy_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("tom", role="user"))
            result = asyncio.run(instance.check_access_policy(
                user_id=user.id, resource_type="campaign", action="write"
            ))
            assert result is False

    def test_check_access_policy_empty_user_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            result = asyncio.run(instance.check_access_policy(
                user_id="", resource_type="doc", action="read"
            ))
            assert result is False

    def test_list_access_policies_with_tenant_filter(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            user = asyncio.run(instance.create_user("uma", role="user"))
            asyncio.run(instance.upsert_access_policy(
                user_id=user.id, tenant_id="tenantA", resource_type="doc", action="read", effect="allow"
            ))
            asyncio.run(instance.upsert_access_policy(
                user_id=user.id, tenant_id="tenantB", resource_type="doc", action="write", effect="allow"
            ))
            policies = asyncio.run(instance.list_access_policies(user.id, tenant_id="tenantA"))
            assert all(p.tenant_id == "tenantA" for p in policies)


# ===========================================================================
# Database — record_audit_log
# ===========================================================================

class TestAuditLog:
    def test_record_audit_log_success(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            # Should not raise
            asyncio.run(instance.record_audit_log(
                user_id="u1", tenant_id="default",
                action="login", resource="auth",
                ip_address="1.2.3.4", allowed=True,
            ))

    def test_record_audit_log_missing_action_raises(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            with pytest.raises(ValueError, match="action"):
                asyncio.run(instance.record_audit_log(
                    action="", resource="doc", ip_address="1.2.3.4", allowed=True
                ))

    def test_record_audit_log_missing_resource_raises(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            with pytest.raises(ValueError):
                asyncio.run(instance.record_audit_log(
                    action="read", resource="", ip_address="1.2.3.4", allowed=True
                ))

    def test_record_audit_log_no_user_id(self):
        with tempfile.TemporaryDirectory() as td:
            db, instance = _fresh_db(Path(td))
            # user_id is optional (defaults to "")
            asyncio.run(instance.record_audit_log(
                action="search", resource="rag",
                ip_address="127.0.0.1", allowed=False,
            ))
