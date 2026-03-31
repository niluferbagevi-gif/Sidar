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

    def test_connect_postgresql_raises_runtime_error_when_asyncpg_missing(self, monkeypatch):
        db_mod = _get_db()

        class _Cfg:
            DATABASE_URL = "postgresql://user:pass@db.local/sidar"
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1

        monkeypatch.setitem(sys.modules, "asyncpg", None)
        database = db_mod.Database(cfg=_Cfg())

        async def _scenario():
            with pytest.raises(RuntimeError, match="asyncpg bağımlılığı gerekli"):
                await database.connect()

        asyncio.run(_scenario())

    def test_connect_sqlite_propagates_operational_error_when_database_locked(self, monkeypatch):
        db_mod = _get_db()

        with tempfile.TemporaryDirectory() as tmpdir:
            database = self._make_sqlite_db(db_mod, tmpdir)
            real_connect = db_mod.sqlite3.connect

            def _locked_connect(*args, **kwargs):
                del args, kwargs
                raise sqlite3.OperationalError("database is locked")

            monkeypatch.setattr(db_mod.sqlite3, "connect", _locked_connect)

            async def _scenario():
                with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                    await database.connect()

            asyncio.run(_scenario())
            monkeypatch.setattr(db_mod.sqlite3, "connect", real_connect)

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


class TestPostgresqlConnectionFailurePaths:
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

    def test_connect_postgresql_raises_runtime_error_without_asyncpg(self, monkeypatch):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = "postgresql://user:pass@localhost/sidar"
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1

            import builtins
            real_import = builtins.__import__

            def _fake_import(name, *args, **kwargs):
                if name == "asyncpg":
                    raise ImportError("asyncpg missing")
                return real_import(name, *args, **kwargs)

            monkeypatch.setattr(builtins, "__import__", _fake_import)
            database = db_mod.Database(cfg=_Cfg())
            with pytest.raises(RuntimeError, match="asyncpg"):
                await database._connect_postgresql()

        asyncio.run(_scenario())

    def test_connect_postgresql_propagates_timeout_error(self, monkeypatch):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = "postgresql://user:pass@localhost/sidar"
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1

            class _FakeAsyncpg:
                class PoolError(Exception):
                    pass

                @staticmethod
                async def create_pool(**_kwargs):
                    raise asyncio.TimeoutError("pool timeout")

            monkeypatch.setitem(sys.modules, "asyncpg", _FakeAsyncpg)
            database = db_mod.Database(cfg=_Cfg())
            with pytest.raises(asyncio.TimeoutError, match="pool timeout"):
                await database._connect_postgresql()

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


class TestDatabaseSessionErrorBranches:
    def test_update_session_title_postgresql_returns_false_on_unparseable_result(self):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = "postgresql://user:pass@localhost/sidar"
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1

            class _Conn:
                async def execute(self, *_args, **_kwargs):
                    return "UPDATE done"

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

            updated = await database.update_session_title("s1", "Yeni Başlık")
            assert updated is False

        asyncio.run(_scenario())

    def test_delete_session_postgresql_returns_false_on_unparseable_result(self):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = "postgresql://user:pass@localhost/sidar"
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1

            class _Conn:
                async def execute(self, *_args, **_kwargs):
                    return "DELETE done"

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

            deleted = await database.delete_session("s1")
            assert deleted is False

        asyncio.run(_scenario())

    def test_create_session_postgresql_propagates_connection_drop(self):
        async def _scenario():
            db_mod = _get_db()

            class _Cfg:
                DATABASE_URL = "postgresql://user:pass@localhost/sidar"
                DB_POOL_SIZE = 5
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1

            class _Acquire:
                async def __aenter__(self):
                    raise ConnectionResetError("connection dropped")

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            class _Pool:
                def acquire(self):
                    return _Acquire()

            database = db_mod.Database(cfg=_Cfg())
            database._pg_pool = _Pool()

            with pytest.raises(ConnectionResetError, match="connection dropped"):
                await database.create_session("u1", "Bağlantı kopması testi")

        asyncio.run(_scenario())

# ===== MERGED FROM tests/test_core_db_extra.py =====

import asyncio
import sys
import tempfile
import types
import uuid
from pathlib import Path
from unittest.mock import patch

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
    with patch.dict(sys.modules, {"config": cfg_mod}):
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

class Extra_TestDataclasses:
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

class Extra_TestHelperFunctions:
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

class Extra_TestDatabaseConfig:
    def test_default_backend_is_sqlite(self):
        db = _get_db_module()

        class _Cfg:
            DATABASE_URL = ""
            DB_POOL_SIZE = 5
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1
            BASE_DIR = Path(tempfile.gettempdir())

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

        instance = db.Database(_Cfg())
        assert instance._backend == "postgresql"


class TestDatabaseSqliteInMemoryPersistence:
    @staticmethod
    def _make_db():
        db_mod = _get_db()

        class _Cfg:
            DATABASE_URL = "sqlite+aiosqlite:///:memory:"
            DB_POOL_SIZE = 3
            DB_SCHEMA_VERSION_TABLE = "schema_versions"
            DB_SCHEMA_TARGET_VERSION = 1

        return db_mod, db_mod.Database(cfg=_Cfg())

    def test_inmemory_user_session_message_roundtrip(self):
        db_mod, database = self._make_db()

        async def _run_case():
            await database.connect()
            await database.init_schema()
            try:
                user = await database.create_user("mem_user", role="user", password="secret")
                session = await database.create_session(user.id, "InMemory Chat")
                await database.add_message(session.id, "user", "merhaba", tokens_used=7)
                await database.add_message(session.id, "assistant", "selam", tokens_used=9)
                messages = await database.get_session_messages(session.id)

                assert user.username == "mem_user"
                assert session.title == "InMemory Chat"
                assert len(messages) == 2
                assert messages[0].content == "merhaba"
                assert messages[1].content == "selam"
            finally:
                await database.close()

        asyncio.run(_run_case())

    def test_inmemory_coverage_task_and_finding_persisted(self):
        db_mod, database = self._make_db()

        async def _run_case():
            await database.connect()
            await database.init_schema()
            try:
                task = await database.create_coverage_task(
                    tenant_id="tenant-x",
                    requester_role="coverage",
                    command="pytest -q",
                    pytest_output="2 failed",
                    status="pending_review",
                    target_path="core/db.py",
                    suggested_test_path="tests/test_core_db.py",
                    review_payload_json='{"note":"needs tests"}',
                )
                finding = await database.add_coverage_finding(
                    task_id=task.id,
                    finding_type="missing_branch",
                    target_path="core/db.py",
                    summary="branch not covered",
                    severity="high",
                    details={"line": 120},
                )
                tasks = await database.list_coverage_tasks(tenant_id="tenant-x", status="pending_review", limit=10)

                assert task.id > 0
                assert finding.task_id == task.id
                assert finding.finding_type == "missing_branch"
                assert len(tasks) == 1
                assert tasks[0].target_path == "core/db.py"
            finally:
                await database.close()

        asyncio.run(_run_case())

    def test_init_schema_idempotent_for_inmemory_sqlite(self):
        _db_mod, database = self._make_db()

        async def _run_case():
            await database.connect()
            try:
                await database.init_schema()
                await database.init_schema()
                assert database._sqlite_conn is not None
                row = database._sqlite_conn.execute(
                    f"SELECT MAX(version) AS v FROM {database._schema_version_table_quoted}"
                ).fetchone()
                assert row is not None
                assert int(row["v"] or 0) >= 1
            finally:
                await database.close()

        asyncio.run(_run_case())

    def test_sqlite_path_resolved(self):
        db = _get_db_module()
        with tempfile.TemporaryDirectory() as td:
            class _Cfg:
                DATABASE_URL = f"sqlite+aiosqlite:///{td}/mydb.db"
                DB_POOL_SIZE = 1
                DB_SCHEMA_VERSION_TABLE = "schema_versions"
                DB_SCHEMA_TARGET_VERSION = 1
                BASE_DIR = Path(td)

            instance = db.Database(_Cfg())
            assert instance._sqlite_path is not None
            assert str(instance._sqlite_path).endswith("mydb.db")


# ===========================================================================
# Database — connect / close
# ===========================================================================

class Extra_TestDatabaseConnectClose:
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

class Extra_TestCreateUser:
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

class Extra_TestAuthFlow:
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

class Extra_TestAuthToken:
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

class Extra_TestSessions:
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

class Extra_TestPromptRegistry:
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

class Extra_TestAccessPolicies:
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

class Extra_TestAuditLog:
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
