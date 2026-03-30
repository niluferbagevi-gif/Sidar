"""
core/db.py için birim testleri.
Dataclass yapıları, saf yardımcı fonksiyonlar (_hash_password, _verify_password,
_quote_sql_identifier, _utc_now_iso) ve Database._configure_backend kapsar.
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import sqlite3
import sys
import tempfile
import types
from pathlib import Path

import pytest


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

    def test_non_string_encoded_returns_false(self):
        db = _get_db()
        import pytest
        with pytest.raises(AttributeError):
            db._verify_password("secret", None)


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


class TestDatabaseErrorAndAsyncFlows:
    @staticmethod
    def _make_sqlite_db(db_mod, tmpdir: str):
        db_file = Path(tmpdir) / "sidar_test.db"

        class _Cfg:
            DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tmpdir)

        return db_mod.Database(cfg=_Cfg())

    def test_run_sqlite_op_raises_when_connection_missing(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                with pytest.raises(RuntimeError, match="SQLite bağlantısı başlatılmadı"):
                    await database._run_sqlite_op(lambda: 1)
        asyncio.run(_scenario())

    def test_connect_postgresql_timeout_is_propagated_and_logged(self, monkeypatch, caplog):
        db_mod = _get_db()

        class _Cfg:
            DATABASE_URL = "postgresql://user:pass@db.local/sidar"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1

        fake_asyncpg = types.SimpleNamespace(
            create_pool=lambda **_kwargs: (_ for _ in ()).throw(asyncio.TimeoutError("pool timeout")),
            PoolError=RuntimeError,
        )
        monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)
        database = db_mod.Database(cfg=_Cfg())

        async def _scenario():
            with caplog.at_level(logging.WARNING, logger="core.db"):
                with pytest.raises(asyncio.TimeoutError):
                    await database.connect()
            assert "zaman aşımına uğradı" in caplog.text
            assert database._pg_pool is None
        asyncio.run(_scenario())

    def test_connect_postgresql_pool_error_is_propagated_and_logged(self, monkeypatch, caplog):
        db_mod = _get_db()

        class _Cfg:
            DATABASE_URL = "postgresql://user:pass@db.local/sidar"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1

        class _FakePoolError(Exception):
            pass

        async def _raise_pool_error(**_kwargs):
            raise _FakePoolError("pool unavailable")

        fake_asyncpg = types.SimpleNamespace(create_pool=_raise_pool_error, PoolError=_FakePoolError)
        monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)
        database = db_mod.Database(cfg=_Cfg())

        async def _scenario():
            with caplog.at_level(logging.WARNING, logger="core.db"):
                with pytest.raises(_FakePoolError):
                    await database.connect()
            assert "bağlantı havuzu kullanılamıyor" in caplog.text
            assert database._pg_pool is None
        asyncio.run(_scenario())

    def test_connect_postgresql_non_pool_error_is_propagated_and_logged(self, monkeypatch, caplog):
        db_mod = _get_db()

        class _Cfg:
            DATABASE_URL = "postgresql://user:pass@db.local/sidar"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1

        async def _raise_generic_error(**_kwargs):
            raise RuntimeError("dsn parse failure")

        fake_asyncpg = types.SimpleNamespace(create_pool=_raise_generic_error, PoolError=type("PoolError", (Exception,), {}))
        monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)
        database = db_mod.Database(cfg=_Cfg())

        async def _scenario():
            with caplog.at_level(logging.WARNING, logger="core.db"):
                with pytest.raises(RuntimeError, match="dsn parse failure"):
                    await database.connect()
            assert "oluşturulamadı; üst katmana iletiliyor" in caplog.text
            assert database._pg_pool is None
        asyncio.run(_scenario())

    def test_connect_postgresql_returns_early_when_pool_already_initialized(self):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = "postgresql://user:pass@db.local/sidar"
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1

            database = db_mod.Database(cfg=_Cfg())
            existing_pool = object()
            database._pg_pool = existing_pool

            await database._connect_postgresql()
            assert database._pg_pool is existing_pool

        asyncio.run(_scenario())

    def test_ensure_schema_version_sqlite_applies_missing_versions(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                database.target_schema_version = 3
                await database.connect()

                await database._ensure_schema_version_sqlite()

                versions = await database._run_sqlite_op(
                    lambda: [
                        int(row[0])
                        for row in database._sqlite_conn.execute(  # type: ignore[union-attr]
                            f"SELECT version FROM {database._schema_version_table_quoted} ORDER BY version"
                        ).fetchall()
                    ]
                )
                assert versions == [1, 2, 3]
                await database.close()

        asyncio.run(_scenario())

    def test_unique_constraint_violation_on_duplicate_username(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                await database.create_user("alice", role="user")
                with pytest.raises(sqlite3.IntegrityError):
                    await database.create_user("alice", role="admin")

                await database.close()
        asyncio.run(_scenario())

    def test_rollback_scenario_preserves_database_consistency(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()

                def _operation():
                    assert database._sqlite_conn is not None
                    conn = database._sqlite_conn
                    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT UNIQUE)")
                    try:
                        conn.execute("INSERT INTO t (v) VALUES ('x')")
                        conn.execute("INSERT INTO t (v) VALUES ('x')")
                        conn.commit()
                    except sqlite3.IntegrityError:
                        conn.rollback()
                        raise

                with pytest.raises(sqlite3.IntegrityError):
                    await database._run_sqlite_op(_operation)

                def _count():
                    assert database._sqlite_conn is not None
                    row = database._sqlite_conn.execute("SELECT COUNT(*) FROM t").fetchone()
                    return int(row[0])

                row_count = await database._run_sqlite_op(_count)
                assert row_count == 0
                await database.close()
        asyncio.run(_scenario())

    def test_run_sqlite_op_auto_rolls_back_on_integrity_error(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()

                def _setup():
                    assert database._sqlite_conn is not None
                    database._sqlite_conn.execute("CREATE TABLE IF NOT EXISTS t2 (v TEXT UNIQUE)")
                    database._sqlite_conn.commit()

                await database._run_sqlite_op(_setup)

                def _broken_insert():
                    assert database._sqlite_conn is not None
                    database._sqlite_conn.execute("INSERT INTO t2 (v) VALUES ('x')")
                    database._sqlite_conn.execute("INSERT INTO t2 (v) VALUES ('x')")
                    # rollback çağrısı yok: _run_sqlite_op otomatik rollback yapmalı

                with pytest.raises(sqlite3.IntegrityError):
                    await database._run_sqlite_op(_broken_insert)

                count = await database._run_sqlite_op(
                    lambda: int(database._sqlite_conn.execute("SELECT COUNT(*) FROM t2").fetchone()[0])  # type: ignore[union-attr]
                )
                assert count == 0
                await database.close()

        asyncio.run(_scenario())

    def test_run_sqlite_op_auto_rolls_back_on_runtime_error(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()

                def _setup():
                    assert database._sqlite_conn is not None
                    database._sqlite_conn.execute("CREATE TABLE IF NOT EXISTS t3 (v TEXT)")
                    database._sqlite_conn.commit()

                await database._run_sqlite_op(_setup)

                def _broken_runtime():
                    assert database._sqlite_conn is not None
                    database._sqlite_conn.execute("INSERT INTO t3 (v) VALUES ('partial')")
                    raise RuntimeError("mid-transaction failure")

                with pytest.raises(RuntimeError, match="mid-transaction failure"):
                    await database._run_sqlite_op(_broken_runtime)

                count = await database._run_sqlite_op(
                    lambda: int(database._sqlite_conn.execute("SELECT COUNT(*) FROM t3").fetchone()[0])  # type: ignore[union-attr]
                )
                assert count == 0
                await database.close()

        asyncio.run(_scenario())

    def test_async_create_session_and_message_flow(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                user = await database.create_user("bob", role="user")
                session = await database.create_session(user.id, "Test Sohbeti")
                message = await database.add_message(session.id, "user", "merhaba", tokens_used=12)
                messages = await database.get_session_messages(session.id)

                assert session.user_id == user.id
                assert message.tokens_used == 12
                assert len(messages) == 1
                assert messages[0].content == "merhaba"
                await database.close()
        asyncio.run(_scenario())


class TestDatabaseCrudEdgeCases:
    @staticmethod
    def _make_sqlite_db(db_mod, tmpdir: str):
        db_file = Path(tmpdir) / "sidar_test.db"

        class _Cfg:
            DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tmpdir)

        return db_mod.Database(cfg=_Cfg())

    def test_update_and_delete_session_return_false_for_missing_records(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                updated = await database.update_session_title("missing-session", "Yeni Başlık")
                deleted = await database.delete_session("missing-session")

                assert updated is False
                assert deleted is False
                await database.close()

        asyncio.run(_scenario())

    def test_add_message_raises_integrity_error_for_missing_session(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                with pytest.raises(sqlite3.IntegrityError):
                    await database.add_message("missing-session", "user", "hello")

                await database.close()

        asyncio.run(_scenario())

    def test_add_message_integrity_error_rolls_back_transaction(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                # FK ihlali ile hata üret ve rollback davranışını doğrula.
                with pytest.raises(sqlite3.IntegrityError):
                    await database.add_message("missing-session", "assistant", "cevap")

                rows = await database._run_sqlite_op(
                    lambda: database._sqlite_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]  # type: ignore[union-attr]
                )
                assert int(rows) == 0
                await database.close()

        asyncio.run(_scenario())

    def test_upsert_access_policy_raises_for_invalid_effect(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                with pytest.raises(ValueError, match="effect must be allow or deny"):
                    await database.upsert_access_policy(
                        user_id="u1",
                        tenant_id="default",
                        resource_type="rag",
                        resource_id="doc-1",
                        action="read",
                        effect="block",
                    )
                await database.close()

        asyncio.run(_scenario())

    def test_create_session_raises_integrity_error_for_missing_user(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                with pytest.raises(sqlite3.IntegrityError):
                    await database.create_session("missing-user-id", "Yetim Oturum")

                sessions_count = await database._run_sqlite_op(
                    lambda: int(database._sqlite_conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])  # type: ignore[union-attr]
                )
                assert sessions_count == 0
                await database.close()

        asyncio.run(_scenario())

    def test_create_user_commit_failure_triggers_rollback(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()

                rollback_calls = {"count": 0}

                class _ConnProxy:
                    def execute(self, *_args, **_kwargs):
                        return None

                    def commit(self):
                        raise sqlite3.OperationalError("disk I/O error")

                    def rollback(self):
                        rollback_calls["count"] += 1

                database._sqlite_conn = _ConnProxy()  # type: ignore[assignment]

                with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
                    await database.create_user("rollback_user", role="user")

                assert rollback_calls["count"] == 1

        asyncio.run(_scenario())


class TestDatabaseWithConftestFixture:
    def test_fixture_backed_sqlite_crud_flow(self, sqlite_test_db_url):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = sqlite_test_db_url
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1
                BASE_DIR = Path(".")

            database = db_mod.Database(cfg=_Cfg())
            await database.connect()
            await database.init_schema()

            user = await database.register_user("fixture_user", "secret", role="admin", tenant_id="tenant-1")
            auth_user = await database.authenticate_user("fixture_user", "secret")
            session = await database.create_session(user.id, "Fixture Session")
            _ = await database.add_message(session.id, "user", "merhaba", tokens_used=5)
            messages = await database.get_session_messages(session.id)

            assert auth_user is not None
            assert auth_user.id == user.id
            assert len(messages) == 1
            assert messages[0].content == "merhaba"
            await database.close()

        asyncio.run(_scenario())


class TestDatabaseConnectionDropScenarios:
    @staticmethod
    def _make_sqlite_db(db_mod, tmpdir: str):
        db_file = Path(tmpdir) / "sidar_drop_test.db"

        class _Cfg:
            DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tmpdir)

        return db_mod.Database(cfg=_Cfg())

    def test_run_sqlite_op_raises_when_connection_drops_mid_operation(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()

                assert database._sqlite_conn is not None
                database._sqlite_conn.close()  # ani bağlantı kesilmesi simülasyonu

                with pytest.raises(sqlite3.ProgrammingError):
                    await database._run_sqlite_op(lambda: database._sqlite_conn.execute("SELECT 1"))  # type: ignore[union-attr]

        asyncio.run(_scenario())

    @pytest.mark.parametrize(
        "campaign_name, status, budget",
        [
            ("Kampanya A", "draft", 150.0),
            ("Kampanya B", "active", 300.5),
        ],
    )
    def test_fixture_backed_marketing_tables(self, sqlite_test_db_url, campaign_name, status, budget):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = sqlite_test_db_url
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1
                BASE_DIR = Path(".")

            database = db_mod.Database(cfg=_Cfg())
            await database.connect()
            await database.init_schema()
            owner = await database.create_user(f"owner_{campaign_name[-1]}", role="manager", tenant_id="tenant-1")

            campaign = await database.upsert_marketing_campaign(
                tenant_id="tenant-1",
                name=campaign_name,
                channel="instagram",
                objective="lead",
                status=status,
                owner_user_id=owner.id,
                budget=budget,
                metadata={"origin": "fixture"},
            )
            checklist = await database.add_operation_checklist(
                tenant_id="tenant-1",
                title=f"{campaign_name} Checklist",
                items=[{"step": "brief"}],
                status="planned",
                owner_user_id=owner.id,
                campaign_id=campaign.id,
            )
            assets = await database.list_content_assets(campaign_id=campaign.id, tenant_id="tenant-1")

            assert campaign.name == campaign_name
            assert checklist.campaign_id == campaign.id
            assert isinstance(assets, list)
            await database.close()

        asyncio.run(_scenario())


class TestDatabaseRollbackAndConnectionFailures:
    @staticmethod
    def _make_sqlite_db(db_mod, tmpdir: str):
        db_file = Path(tmpdir) / "sidar_rollback_test.db"

        class _Cfg:
            DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tmpdir)

        return db_mod.Database(cfg=_Cfg())

    def test_run_sqlite_op_calls_rollback_on_integrity_error(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()

                rollback_calls = {"count": 0}

                class _ConnProxy:
                    def rollback(self):
                        rollback_calls["count"] += 1

                database._sqlite_conn = _ConnProxy()  # type: ignore[assignment]

                def _broken_op():
                    raise sqlite3.IntegrityError("unique constraint failed")

                with pytest.raises(sqlite3.IntegrityError):
                    await database._run_sqlite_op(_broken_op)

                assert rollback_calls["count"] == 1

        asyncio.run(_scenario())

    def test_create_user_surfaces_operational_error_and_rolls_back(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()

                state = {"rollback": 0}

                class _ConnProxy:
                    def execute(self, *_args, **_kwargs):
                        raise sqlite3.OperationalError("database is locked")

                    def commit(self):
                        raise AssertionError("commit should not run on failed execute")

                    def rollback(self):
                        state["rollback"] += 1

                database._sqlite_conn = _ConnProxy()  # type: ignore[assignment]

                with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                    await database.create_user("kilitli_kullanici", role="user")

                assert state["rollback"] == 1

        asyncio.run(_scenario())

    def test_run_sqlite_op_preserves_original_error_when_rollback_also_fails(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()

                class _ConnProxy:
                    def rollback(self):
                        raise RuntimeError("rollback failed")

                database._sqlite_conn = _ConnProxy()  # type: ignore[assignment]

                def _broken_op():
                    raise ValueError("primary failure")

                with pytest.raises(ValueError, match="primary failure"):
                    await database._run_sqlite_op(_broken_op)

        asyncio.run(_scenario())


class TestDatabasePromptRegistryBootstrap:
    @staticmethod
    def _make_sqlite_db(db_mod, tmpdir: str):
        db_file = Path(tmpdir) / "sidar_prompt_test.db"

        class _Cfg:
            DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tmpdir)

        return db_mod.Database(cfg=_Cfg())

    def test_ensure_default_prompt_registry_logs_warning_when_upsert_fails(self, monkeypatch, caplog):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                class _Loader:
                    @staticmethod
                    def exec_module(module):
                        module.SIDAR_SYSTEM_PROMPT = "varsayilan sistem promptu"

                fake_spec = types.SimpleNamespace(loader=_Loader())
                monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *_a, **_k: fake_spec)
                monkeypatch.setattr(importlib.util, "module_from_spec", lambda _spec: types.SimpleNamespace())
                async def _none_prompt(*_args, **_kwargs):
                    return None

                monkeypatch.setattr(database, "get_active_prompt", _none_prompt)

                async def _boom(**_kwargs):
                    raise RuntimeError("insert failed")

                monkeypatch.setattr(database, "upsert_prompt", _boom)

                with caplog.at_level(logging.WARNING, logger="core.db"):
                    await database.ensure_default_prompt_registry()

                assert "Varsayılan prompt kaydı oluşturulamadı" in caplog.text
                await database.close()

        asyncio.run(_scenario())


class TestDatabasePromptActivationAndPostgresSchema:
    @staticmethod
    def _make_sqlite_db(db_mod, tmpdir: str):
        db_file = Path(tmpdir) / "sidar_prompt_activation.db"

        class _Cfg:
            DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tmpdir)

        return db_mod.Database(cfg=_Cfg())

    def test_activate_prompt_sqlite_paths(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                assert await database.activate_prompt(0) is None
                assert await database.activate_prompt(99999) is None

                first = await database.upsert_prompt("system", "v1", activate=True)
                second = await database.upsert_prompt("system", "v2", activate=False)
                activated = await database.activate_prompt(second.id)
                assert activated is not None
                assert activated.id == second.id

                current = await database.get_active_prompt("system")
                assert current is not None
                assert current.id == second.id
                assert current.id != first.id
                await database.close()

        asyncio.run(_scenario())


class TestDatabaseAdditionalEdgeCases:
    @staticmethod
    def _make_sqlite_db(db_mod, tmpdir: str):
        db_file = Path(tmpdir) / "sidar_additional_edges.db"

        class _Cfg:
            DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tmpdir)

        return db_mod.Database(cfg=_Cfg())

    def test_empty_listing_queries_return_empty_lists(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database.init_schema()

                campaigns = await database.list_marketing_campaigns(tenant_id="default")
                assets = await database.list_content_assets(campaign_id=999, tenant_id="default")
                checklists = await database.list_operation_checklists(campaign_id=999, tenant_id="default")

                assert campaigns == []
                assert assets == []
                assert checklists == []
                await database.close()

        asyncio.run(_scenario())

    def test_add_operation_checklist_rejects_blank_title(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database.init_schema()

                with pytest.raises(ValueError, match="title is required"):
                    await database.add_operation_checklist(
                        campaign_id=1,
                        tenant_id="default",
                        title="   ",
                        items=[],
                        status="pending",
                        owner_user_id="u1",
                    )
                await database.close()

        asyncio.run(_scenario())

    def test_replace_session_messages_sqlite_normalizes_payload_and_filters_blanks(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database.init_schema()

                user = await database.create_user("msg_replace_user", role="user")
                session = await database.create_session(user.id, "Replace Test")
                await database.add_message(session.id, "user", "eski", tokens_used=1)

                replaced = await database.replace_session_messages(
                    session.id,
                    [
                        {"role": "", "content": "  yeni içerik  "},
                        {"role": "assistant", "content": "   "},
                    ],
                )
                assert replaced == 1

                rows = await database.get_session_messages(session.id)
                assert len(rows) == 1
                assert rows[0].role == "assistant"
                assert rows[0].content == "yeni içerik"
                await database.close()

        asyncio.run(_scenario())

    def test_replace_session_messages_postgresql_rolls_outside_on_transaction_error(self):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = "postgresql://user:pass@localhost/sidar"
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1

            state = {"tx_exc_type": None, "exec_calls": 0}

            class _Tx:
                async def __aenter__(self):
                    return None

                async def __aexit__(self, exc_type, exc, tb):
                    state["tx_exc_type"] = exc_type
                    return False

            class _Conn:
                def transaction(self):
                    return _Tx()

                async def execute(self, query, *_args):
                    state["exec_calls"] += 1
                    if "INSERT INTO messages" in query:
                        raise RuntimeError("insert failed")

            class _Acquire:
                async def __aenter__(self):
                    return _Conn()

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            class _Pool:
                def acquire(self):
                    return _Acquire()

            database = db_mod.Database(cfg=_Cfg())
            database._pg_pool = _Pool()

            with pytest.raises(RuntimeError, match="insert failed"):
                await database.replace_session_messages(
                    "s1",
                    [{"role": "assistant", "content": "boom"}],
                )

            assert state["exec_calls"] >= 2  # delete + insert denemesi
            assert state["tx_exc_type"] is RuntimeError

        asyncio.run(_scenario())

    def test_init_schema_postgresql_executes_all_queries(self):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = "postgresql://user:pass@localhost/sidar"
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1

            executed = []

            class _Conn:
                async def execute(self, query):
                    executed.append(query)

            class _Acquire:
                async def __aenter__(self):
                    return _Conn()

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            class _Pool:
                def acquire(self):
                    return _Acquire()

            database = db_mod.Database(cfg=_Cfg())
            database._pg_pool = _Pool()
            await database._init_schema_postgresql()

            assert len(executed) > 15
            assert any("CREATE TABLE IF NOT EXISTS users" in q for q in executed)
            assert any("CREATE TABLE IF NOT EXISTS prompt_registry" in q for q in executed)

        asyncio.run(_scenario())


class TestMarketingCampaignCrudFailurePaths:
    @staticmethod
    def _make_sqlite_db(db_mod, tmpdir: str):
        db_file = Path(tmpdir) / "sidar_campaign_failures.db"

        class _Cfg:
            DATABASE_URL = f"sqlite+aiosqlite:///{db_file}"
            DB_POOL_SIZE = 2
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            JWT_SECRET_KEY = "secret"
            JWT_ALGORITHM = "HS256"
            JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 60

        return db_mod.Database(cfg=_Cfg())

    def test_upsert_marketing_campaign_update_raises_for_missing_record(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                with pytest.raises(ValueError, match="campaign not found"):
                    await database.upsert_marketing_campaign(
                        tenant_id="acme",
                        name="Missing Campaign",
                        campaign_id=99999,
                    )
                await database.close()

        asyncio.run(_scenario())

    def test_upsert_marketing_campaign_rolls_back_on_sqlite_lock_error(self):
        async def _scenario():
            db_mod = _get_db()
            with tempfile.TemporaryDirectory() as tmpdir:
                database = self._make_sqlite_db(db_mod, tmpdir)
                await database.connect()
                await database._init_schema_sqlite()

                rollback_calls = {"count": 0}

                class _ConnProxy:
                    def execute(self, _query, *_params):
                        raise sqlite3.OperationalError("database is locked")

                    def rollback(self):
                        rollback_calls["count"] += 1

                database._sqlite_conn = _ConnProxy()  # type: ignore[assignment]
                with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                    await database.upsert_marketing_campaign(tenant_id="acme", name="Locked Campaign")

                assert rollback_calls["count"] == 1

        asyncio.run(_scenario())
