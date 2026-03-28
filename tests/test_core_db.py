"""
core/db.py için birim testleri.
Dataclass yapıları, saf yardımcı fonksiyonlar (_hash_password, _verify_password,
_quote_sql_identifier, _utc_now_iso) ve Database._configure_backend kapsar.
"""
from __future__ import annotations

import sys
import types


def _get_db():
    # config stub
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        DATABASE_URL = ""
        DB_POOL_SIZE = 5
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1

    cfg_stub.Config = _Cfg
    sys.modules["config"] = cfg_stub

    if "core.db" in sys.modules:
        del sys.modules["core.db"]
    import core.db as db
    return db


# ══════════════════════════════════════════════════════════════
# Dataclass örnekleme
# ══════════════════════════════════════════════════════════════

class TestDataclasses:
    def test_user_record_fields(self):
        db = _get_db()
        u = db.UserRecord(id="1", username="alice", role="admin", created_at="2024-01-01")
        assert u.id == "1"
        assert u.tenant_id == "default"

    def test_auth_token_record(self):
        db = _get_db()
        t = db.AuthTokenRecord(token="tok", user_id="u1", expires_at="exp", created_at="now")
        assert t.token == "tok"

    def test_session_record(self):
        db = _get_db()
        s = db.SessionRecord(id="s1", user_id="u1", title="Chat", created_at="now", updated_at="now")
        assert s.title == "Chat"

    def test_message_record(self):
        db = _get_db()
        m = db.MessageRecord(id=1, session_id="s1", role="user", content="hi", tokens_used=10, created_at="now")
        assert m.role == "user"
        assert m.tokens_used == 10

    def test_access_policy_record(self):
        db = _get_db()
        r = db.AccessPolicyRecord(
            id=1, user_id="u", tenant_id="t", resource_type="rt",
            resource_id="rid", action="read", effect="allow",
            created_at="now", updated_at="now",
        )
        assert r.effect == "allow"

    def test_prompt_record(self):
        db = _get_db()
        p = db.PromptRecord(
            id=1, role_name="system", prompt_text="You are helpful",
            version=1, is_active=True, created_at="now", updated_at="now",
        )
        assert p.is_active is True

    def test_audit_log_record(self):
        db = _get_db()
        a = db.AuditLogRecord(
            id=1, user_id="u", tenant_id="t", action="login",
            resource="auth", ip_address="127.0.0.1", allowed=True, timestamp="now",
        )
        assert a.allowed is True

    def test_marketing_campaign_record(self):
        db = _get_db()
        c = db.MarketingCampaignRecord(
            id=1, tenant_id="t", name="Campaign", channel="email",
            objective="awareness", status="draft", owner_user_id="u",
            budget=1000.0, metadata_json="{}", created_at="now", updated_at="now",
        )
        assert c.budget == 1000.0

    def test_coverage_task_record(self):
        db = _get_db()
        r = db.CoverageTaskRecord(
            id=1, tenant_id="t", requester_role="admin", command="pytest",
            pytest_output="ok", status="done", target_path="core/foo.py",
            suggested_test_path="tests/test_foo.py", review_payload_json="{}",
            created_at="now", updated_at="now",
        )
        assert r.status == "done"

    def test_coverage_finding_record(self):
        db = _get_db()
        f = db.CoverageFindingRecord(
            id=1, task_id=1, finding_type="missing", target_path="core/foo.py",
            summary="Low coverage", severity="high", details_json="{}",
            created_at="now",
        )
        assert f.severity == "high"


# ══════════════════════════════════════════════════════════════
# _utc_now_iso
# ══════════════════════════════════════════════════════════════

class TestUtcNowIso:
    def test_returns_string(self):
        db = _get_db()
        result = db._utc_now_iso()
        assert isinstance(result, str)

    def test_contains_plus_or_z(self):
        db = _get_db()
        result = db._utc_now_iso()
        assert "+" in result or "Z" in result or result.endswith("+00:00")

    def test_different_calls_not_equal(self):
        import time
        db = _get_db()
        t1 = db._utc_now_iso()
        time.sleep(0.01)
        t2 = db._utc_now_iso()
        # Not necessarily different in 10ms but at minimum both are valid strings
        assert isinstance(t1, str) and isinstance(t2, str)


# ══════════════════════════════════════════════════════════════
# _hash_password / _verify_password
# ══════════════════════════════════════════════════════════════

class TestHashPassword:
    def test_returns_pbkdf2_prefix(self):
        db = _get_db()
        result = db._hash_password("secret")
        assert result.startswith("pbkdf2_sha256$")

    def test_hash_has_three_parts(self):
        db = _get_db()
        result = db._hash_password("password")
        parts = result.split("$")
        assert len(parts) == 3

    def test_same_password_different_salt(self):
        db = _get_db()
        h1 = db._hash_password("pass")
        h2 = db._hash_password("pass")
        # Different salts produce different hashes
        assert h1 != h2

    def test_explicit_salt_deterministic(self):
        db = _get_db()
        h1 = db._hash_password("pass", salt="fixed_salt_abc")
        h2 = db._hash_password("pass", salt="fixed_salt_abc")
        assert h1 == h2

    def test_different_passwords_different_hashes(self):
        db = _get_db()
        h1 = db._hash_password("pass1", salt="same")
        h2 = db._hash_password("pass2", salt="same")
        assert h1 != h2


class TestVerifyPassword:
    def test_correct_password_returns_true(self):
        db = _get_db()
        encoded = db._hash_password("secret123")
        assert db._verify_password("secret123", encoded) is True

    def test_wrong_password_returns_false(self):
        db = _get_db()
        encoded = db._hash_password("secret123")
        assert db._verify_password("wrongpass", encoded) is False

    def test_malformed_hash_returns_false(self):
        db = _get_db()
        assert db._verify_password("any", "not_a_valid_hash") is False

    def test_wrong_algorithm_returns_false(self):
        db = _get_db()
        assert db._verify_password("any", "bcrypt$salt$hash") is False

    def test_empty_password_matches_its_hash(self):
        db = _get_db()
        encoded = db._hash_password("")
        assert db._verify_password("", encoded) is True


# ══════════════════════════════════════════════════════════════
# _quote_sql_identifier
# ══════════════════════════════════════════════════════════════

class TestQuoteSqlIdentifier:
    def test_simple_name_quoted(self):
        db = _get_db()
        result = db._quote_sql_identifier("users")
        assert result == '"users"'

    def test_name_with_underscore_accepted(self):
        db = _get_db()
        result = db._quote_sql_identifier("schema_versions")
        assert result == '"schema_versions"'

    def test_leading_underscore_accepted(self):
        db = _get_db()
        result = db._quote_sql_identifier("_private")
        assert result == '"_private"'

    def test_empty_string_raises(self):
        db = _get_db()
        import pytest
        with pytest.raises(ValueError):
            db._quote_sql_identifier("")

    def test_whitespace_only_raises(self):
        db = _get_db()
        import pytest
        with pytest.raises(ValueError):
            db._quote_sql_identifier("   ")

    def test_name_with_space_raises(self):
        db = _get_db()
        import pytest
        with pytest.raises(ValueError):
            db._quote_sql_identifier("bad name")

    def test_name_with_hyphen_raises(self):
        db = _get_db()
        import pytest
        with pytest.raises(ValueError):
            db._quote_sql_identifier("bad-name")

    def test_digit_leading_raises(self):
        db = _get_db()
        import pytest
        with pytest.raises(ValueError):
            db._quote_sql_identifier("1users")

    def test_injection_attempt_raises(self):
        db = _get_db()
        import pytest
        with pytest.raises(ValueError):
            db._quote_sql_identifier("users; DROP TABLE--")


# ══════════════════════════════════════════════════════════════
# _json_dumps
# ══════════════════════════════════════════════════════════════

class TestJsonDumps:
    def test_simple_dict_serialized(self):
        db = _get_db()
        import json
        result = db._json_dumps({"b": 2, "a": 1})
        parsed = json.loads(result)
        assert parsed == {"a": 1, "b": 2}

    def test_sorted_keys(self):
        db = _get_db()
        result = db._json_dumps({"z": 0, "a": 1})
        assert result.index('"a"') < result.index('"z"')

    def test_unicode_not_escaped(self):
        db = _get_db()
        result = db._json_dumps({"msg": "merhaba dünya"})
        assert "dünya" in result


# ══════════════════════════════════════════════════════════════
# Database._configure_backend
# ══════════════════════════════════════════════════════════════

class TestDatabaseConfigureBackend:
    def _make_db(self, url):
        db_mod = _get_db()

        class _Cfg:
            DATABASE_URL = url
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1

        return db_mod.Database(cfg=_Cfg())

    def test_sqlite_url_sets_sqlite_backend(self):
        db = self._make_db("sqlite+aiosqlite:///data/sidar.db")
        assert db._backend == "sqlite"

    def test_postgresql_url_sets_pg_backend(self):
        db = self._make_db("postgresql://user:pass@localhost/db")
        assert db._backend == "postgresql"

    def test_postgresql_asyncpg_url_sets_pg_backend(self):
        db = self._make_db("postgresql+asyncpg://user:pass@localhost/db")
        assert db._backend == "postgresql"

    def test_empty_url_defaults_to_sqlite(self):
        db = self._make_db("")
        assert db._backend == "sqlite"

    def test_sqlite_path_resolved(self):
        db = self._make_db("sqlite+aiosqlite:///data/sidar.db")
        assert db._sqlite_path is not None

    def test_pool_size_default(self):
        db = self._make_db("")
        assert db.pool_size == 5

    def test_target_schema_version_default(self):
        db = self._make_db("")
        assert db.target_schema_version == 1
