from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sqlite3
import sys
import types
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import jwt
import pytest

import core.db as core_db
from core.db import (
    Database,
    _expires_in,
    _hash_password,
    _json_dumps,
    _new_entity_id,
    _parse_asyncpg_affected_rows,
    _parse_iso_datetime,
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
    JWT_SECRET_KEY: str = "test-secret-key-32-bytes-minimum!!"
    JWT_ALGORITHM: str = "HS256"
    JWT_TTL_DAYS: int = 3
    SQLITE_MAX_CONCURRENT_OPS: int = 4


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
async def test_init_schema_postgresql_propagates_mid_migration_disconnect(tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    db._backend = "postgresql"
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg
    fake_pg.conn.execute.side_effect = [
        None,
        None,
        ConnectionError("database connection lost during migration"),
    ]

    with pytest.raises(ConnectionError, match="migration"):
        await db._init_schema_postgresql()

    assert fake_pg.conn.execute.await_count == 3


@pytest.mark.asyncio
async def test_ensure_default_prompt_registry_postgres_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
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
    _, iteration_text, _, _ = hashed.split("$", 3)
    assert int(iteration_text) >= 600000
    assert _verify_password("abc123", hashed)
    assert not _verify_password("wrong", hashed)
    assert not _verify_password("abc123", "invalid")
    assert not _verify_password("abc123", "sha1$salt$deadbeef")

    assert _quote_sql_identifier("schema_versions") == '"schema_versions"'
    assert _json_dumps({"b": 1, "a": 2}) == '{"a": 2, "b": 1}'


def test_verify_password_accepts_legacy_120k_hash_format() -> None:
    salt = "legacysalt"
    digest = hashlib.pbkdf2_hmac("sha256", b"abc123", salt.encode("utf-8"), 120000).hex()
    encoded = f"pbkdf2_sha256${salt}${digest}"
    assert _verify_password("abc123", encoded)
    assert not _verify_password("wrong", encoded)


def test_verify_password_rejects_unknown_algorithm_and_invalid_iterations() -> None:
    assert _verify_password("abc123", "unknown_algo$600000$salt$deadbeef") is False
    assert _verify_password("abc123", "pbkdf2_sha256$not-a-number$salt$deadbeef") is False


@pytest.mark.parametrize(
    ("command_tag", "expected"),
    [
        ("UPDATE 1", 1),
        ("DELETE 0", 0),
        ("INSERT 0 15", 15),
        ("", 0),
        (None, 0),
        ("UNKNOWN", 0),
    ],
)
def test_parse_asyncpg_affected_rows(command_tag, expected: int) -> None:
    assert _parse_asyncpg_affected_rows(command_tag) == expected


def test_new_entity_id_returns_valid_uuid() -> None:
    generated = _new_entity_id()
    parsed = uuid.UUID(generated)
    assert str(parsed) == generated


def test_new_entity_id_prefers_builtin_uuid7(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeUUID7:
        def __call__(self):
            return uuid.UUID("00000000-0000-7000-8000-000000000001")

    monkeypatch.setattr(uuid, "uuid7", _FakeUUID7(), raising=False)
    assert _new_entity_id() == "00000000-0000-7000-8000-000000000001"


def test_new_entity_id_uses_uuid6_fallback_when_builtin_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(uuid, "uuid7", raising=False)

    fake_uuid6 = types.ModuleType("uuid6")
    fake_uuid6.uuid7 = lambda: uuid.UUID("00000000-0000-7000-8000-000000000002")
    monkeypatch.setitem(sys.modules, "uuid6", fake_uuid6)

    assert _new_entity_id() == "00000000-0000-7000-8000-000000000002"


def test_new_entity_id_falls_back_to_uuid4_when_uuid7_not_callable_and_uuid6_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(uuid, "uuid7", "not-callable", raising=False)
    monkeypatch.setitem(sys.modules, "uuid6", None)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("00000000-0000-4000-8000-000000000111"))

    assert _new_entity_id() == "00000000-0000-4000-8000-000000000111"


def test_parse_asyncpg_affected_rows_returns_zero_for_invalid_match_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeMatch:
        def group(self, _index: int) -> str:
            return "not-a-number"

    class _FakeRegex:
        def search(self, _text: str):
            return _FakeMatch()

    monkeypatch.setattr("core.db._ASYNCPG_COMMAND_TAG_COUNT_RE", _FakeRegex())
    assert _parse_asyncpg_affected_rows("UPDATE 3") == 0


@pytest.mark.parametrize("identifier", ["", "1abc", "bad-name", "bad space"])
def test_quote_sql_identifier_rejects_invalid(identifier: str) -> None:
    with pytest.raises(ValueError, match="SQL identifier cannot be empty|Invalid SQL identifier"):
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
async def test_bulk_message_write_and_multi_session_fetch(sqlite_db: Database) -> None:
    user = await sqlite_db.create_user("bulk-user", password="pw")
    first = await sqlite_db.create_session(user.id, "first")
    second = await sqlite_db.create_session(user.id, "second")

    inserted = await sqlite_db.add_messages_bulk(
        [
            {"session_id": first.id, "role": "user", "content": "f-1", "tokens_used": 1},
            {"session_id": first.id, "role": "assistant", "content": "f-2", "tokens_used": 2},
            {"session_id": second.id, "role": "user", "content": "s-1", "tokens_used": 3},
            {"session_id": "", "role": "user", "content": "ignore-me", "tokens_used": 4},
        ]
    )
    assert inserted == 3

    grouped = await sqlite_db.get_messages_for_sessions([first.id, second.id])
    assert [m.content for m in grouped[first.id]] == ["f-1", "f-2"]
    assert [m.tokens_used for m in grouped[first.id]] == [1, 2]
    assert [m.content for m in grouped[second.id]] == ["s-1"]
    assert [m.tokens_used for m in grouped[second.id]] == [3]


@pytest.mark.asyncio
async def test_bulk_and_grouped_messages_empty_inputs_return_empty(sqlite_db: Database) -> None:
    assert await sqlite_db.add_messages_bulk([]) == 0
    assert await sqlite_db.get_messages_for_sessions(["", "   "]) == {}


@pytest.mark.asyncio
async def test_sqlite_connection_uses_wal_mode(sqlite_db: Database) -> None:
    assert sqlite_db._sqlite_conn is not None

    def _run() -> str:
        assert sqlite_db._sqlite_conn is not None
        row = sqlite_db._sqlite_conn.execute("PRAGMA journal_mode;").fetchone()
        assert row is not None
        return str(row[0]).lower()

    mode = await sqlite_db._run_sqlite_op(_run)
    assert mode == "wal"


@pytest.mark.asyncio
async def test_messages_session_index_exists_in_sqlite_schema(sqlite_db: Database) -> None:
    assert sqlite_db._sqlite_conn is not None

    def _run() -> list[str]:
        assert sqlite_db._sqlite_conn is not None
        rows = sqlite_db._sqlite_conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='index' AND tbl_name='messages'
            """
        ).fetchall()
        return [str(r["name"]) for r in rows]

    index_names = await sqlite_db._run_sqlite_op(_run)
    assert "idx_messages_session_id" in index_names


@pytest.mark.asyncio
async def test_create_duplicate_user_raises_integrity_error(sqlite_db: Database) -> None:
    await sqlite_db.create_user("unique_user", password="pw")
    with pytest.raises(sqlite3.IntegrityError):
        await sqlite_db.create_user("unique_user", password="pw2")


@pytest.mark.asyncio
async def test_prompt_registry_flow(sqlite_db: Database) -> None:
    with pytest.raises(ValueError, match="role_name ve prompt_text boş olamaz"):
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

    with pytest.raises(ValueError, match="effect must be allow or deny"):
        await sqlite_db.upsert_access_policy(
            user_id=user.id, resource_type="repo", action="write", effect="maybe"
        )


@pytest.mark.asyncio
async def test_run_sqlite_op_rolls_back_on_failure(sqlite_db: Database) -> None:
    user = await sqlite_db.create_user("rollback", password="pw")

    def _failing_op() -> None:
        assert sqlite_db._sqlite_conn is not None
        # Database._sqlite_conn, sqlite3.Connection olduğundan execute senkrondur.
        # Cursor döndüğünü doğrulayarak "await edilmemiş coroutine" riskini engelleriz.
        cursor = sqlite_db._sqlite_conn.execute(
            "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("s1", user.id, "t", _utc_now_iso(), _utc_now_iso()),
        )
        assert isinstance(cursor, sqlite3.Cursor)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await sqlite_db._run_sqlite_op(_failing_op)

    assert await sqlite_db.load_session("s1") is None


@pytest.mark.asyncio
async def test_jwt_token_flow_prefers_db_user(sqlite_db: Database) -> None:
    user = await sqlite_db.create_user(
        "jwt-user", role="admin", password="pw", tenant_id="tenant-a"
    )
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
async def test_fetch_message_rows_by_session_ids_returns_empty_for_blank_input(
    sqlite_db: Database,
) -> None:
    assert await sqlite_db._fetch_message_rows_by_session_ids([]) == []
    assert await sqlite_db._fetch_message_rows_by_session_ids(["", "   "]) == []


@pytest.mark.asyncio
async def test_run_sqlite_op_raises_runtime_error_when_rollback_also_fails(
    sqlite_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _BrokenConn:
        def rollback(self) -> None:
            raise sqlite3.OperationalError("rollback failed")

    monkeypatch.setattr(sqlite_db, "_sqlite_conn", _BrokenConn())

    def _failing_op() -> None:
        raise ValueError("write failed")

    with pytest.raises(RuntimeError, match="SQLite işlemi ve rollback başarısız oldu"):
        await sqlite_db._run_sqlite_op(_failing_op)


@pytest.mark.asyncio
async def test_run_sqlite_op_retries_when_database_is_locked(sqlite_db: Database) -> None:
    attempts = {"count": 0}

    def _flaky_operation() -> int:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return 42

    result = await sqlite_db._run_sqlite_op(_flaky_operation)
    assert result == 42
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_run_sqlite_op_raises_after_max_retries_for_locked_database(
    sqlite_db: Database,
) -> None:
    attempts = {"count": 0}

    def _always_locked() -> int:
        attempts["count"] += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        await sqlite_db._run_sqlite_op(_always_locked)

    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_run_sqlite_op_re_raises_non_lock_operational_error(sqlite_db: Database) -> None:
    def _op() -> int:
        raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        await sqlite_db._run_sqlite_op(_op)


@pytest.mark.asyncio
async def test_run_sqlite_op_covers_empty_retry_range_exit(
    sqlite_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core_db, "range", lambda *_args, **_kwargs: [], raising=False)
    with pytest.raises(sqlite3.OperationalError, match="deneme sınırına ulaştı"):
        await sqlite_db._run_sqlite_op(lambda: 99)


@pytest.mark.asyncio
async def test_run_sqlite_op_initializes_write_lock_and_keeps_reads_unlocked(tmp_path) -> None:
    cfg = DummyCfg(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'sidar_lock.db'}",
        BASE_DIR=str(tmp_path),
        SQLITE_MAX_CONCURRENT_OPS=2,
    )
    db = Database(cfg)
    await db.connect()

    assert db._sqlite_lock is None
    assert await db._run_sqlite_op(lambda: "ok", write=False) == "ok"
    assert db._sqlite_lock is not None
    assert isinstance(db._sqlite_lock, asyncio.Lock)
    await db.close()


@pytest.mark.asyncio
async def test_transaction_sqlite_edge_branches(sqlite_db: Database, tmp_path) -> None:
    db = Database(
        DummyCfg(
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'tx-no-conn.db'}", BASE_DIR=str(tmp_path)
        )
    )
    db._backend = "sqlite"
    db._sqlite_conn = None
    with pytest.raises(RuntimeError, match="SQLite bağlantısı başlatılmadı"):
        async with db.transaction():
            pass

    sqlite_db._sqlite_lock = None
    async with sqlite_db.transaction():
        pass
    assert isinstance(sqlite_db._sqlite_lock, asyncio.Lock)

    class _ForeignLoopLock:
        def __init__(self) -> None:
            self._loop = object()

    sqlite_db._sqlite_lock = _ForeignLoopLock()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="tx failure"):
        async with sqlite_db.transaction():
            raise RuntimeError("tx failure")
    assert isinstance(sqlite_db._sqlite_lock, asyncio.Lock)


@pytest.mark.asyncio
async def test_transaction_sqlite_rolls_back_on_operational_error(tmp_path) -> None:
    db = Database(
        DummyCfg(
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'tx-rollback.db'}",
            BASE_DIR=str(tmp_path),
        )
    )
    db._backend = "sqlite"

    class _Conn:
        def __init__(self) -> None:
            self.begin_calls = 0
            self.rollback_calls = 0
            self.commit_calls = 0

        def execute(self, sql: str):
            if sql == "BEGIN":
                self.begin_calls += 1
            return None

        def rollback(self) -> None:
            self.rollback_calls += 1

        def commit(self) -> None:
            self.commit_calls += 1

    conn = _Conn()
    db._sqlite_conn = conn
    db._sqlite_write_lock = asyncio.Lock()

    with pytest.raises(sqlite3.OperationalError, match="forced tx error"):
        async with db.transaction():
            raise sqlite3.OperationalError("forced tx error")

    assert conn.begin_calls == 1
    assert conn.rollback_calls == 1
    assert conn.commit_calls == 0


@pytest.mark.asyncio
async def test_transaction_postgresql_supports_awaitable_transaction_factory(tmp_path) -> None:
    db = Database(
        DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR=str(tmp_path))
    )
    fake_pg = FakePgAdapter()
    db._backend = "postgresql"
    db._pg_pool = fake_pg

    class _Tx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _tx_factory():
        return _Tx()

    fake_pg.conn.transaction = _tx_factory
    async with db.transaction() as conn:
        assert conn is fake_pg.conn


@pytest.mark.asyncio
async def test_transaction_postgresql_supports_sync_transaction_factory(tmp_path) -> None:
    db = Database(
        DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR=str(tmp_path))
    )
    fake_pg = FakePgAdapter()
    db._backend = "postgresql"
    db._pg_pool = fake_pg

    class _Tx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_pg.conn.transaction = lambda: _Tx()
    async with db.transaction() as conn:
        assert conn is fake_pg.conn


@pytest.mark.asyncio
async def test_ensure_default_prompt_registry_branches(
    monkeypatch: pytest.MonkeyPatch, sqlite_db: Database
) -> None:
    class _BrokenLoader:
        def exec_module(self, module):
            module.SIDAR_SYSTEM_PROMPT = "sys prompt"

    class _BrokenSpec:
        loader = _BrokenLoader()

    monkeypatch.setattr(
        "importlib.util.spec_from_file_location", lambda *args, **kwargs: _BrokenSpec()
    )
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
    bad_token = jwt.encode(
        payload, sqlite_db.cfg.JWT_SECRET_KEY, algorithm=sqlite_db.cfg.JWT_ALGORITHM
    )
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
    cols = await db._run_sqlite_op(
        lambda: db._sqlite_conn.execute("PRAGMA table_info(users)").fetchall()
    )
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
    updated = await sqlite_db.upsert_marketing_campaign(
        campaign_id=campaign.id, tenant_id="t1", name="Launch 2", status="ACTIVE"
    )
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

    task = await sqlite_db.create_coverage_task(
        tenant_id="t1", command="pytest", pytest_output="ok", target_path="core/db.py"
    )
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
        [
            {
                "id": 1,
                "session_id": "s1",
                "role": "assistant",
                "content": "hi",
                "tokens_used": 1,
                "created_at": "c",
            }
        ],
    ]
    fake_pg.conn.fetchrow.return_value = {
        "id": "s1",
        "user_id": "u1",
        "title": "t",
        "created_at": "c",
        "updated_at": "u",
    }
    fake_pg.conn.execute.side_effect = ["UPDATE 1", "DELETE 1", "DELETE BAD"]

    sessions = await db.list_sessions("u1")
    assert len(sessions) == 1
    assert await db.update_session_title("s1", "updated") is True
    assert await db.delete_session("s1") is True
    assert await db.delete_session("s1") is False

    messages = await db.get_session_messages("s1")
    assert len(messages) == 1


@pytest.mark.asyncio
async def test_postgresql_bulk_and_grouped_message_paths() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    inserted = await db.add_messages_bulk(
        [
            {"session_id": "s1", "role": "user", "content": "one", "tokens_used": 2},
            {"session_id": "s2", "role": "assistant", "content": "two", "tokens_used": 4},
            {"session_id": " ", "role": "user", "content": "skip"},
        ]
    )
    assert inserted == 2
    assert fake_pg.conn.executemany.await_count == 1
    exec_args = fake_pg.conn.executemany.await_args
    assert exec_args is not None
    rows = exec_args.args[1]
    assert len(rows) == 2

    fake_pg.conn.fetch.return_value = [
        {
            "id": 1,
            "session_id": "s1",
            "role": "user",
            "content": "one",
            "tokens_used": 2,
            "created_at": "c1",
        },
        {
            "id": 2,
            "session_id": "s2",
            "role": "assistant",
            "content": "two",
            "tokens_used": 4,
            "created_at": "c2",
        },
    ]
    grouped = await db.get_messages_for_sessions(["s1", "s2"])
    assert [m.content for m in grouped["s1"]] == ["one"]
    assert [m.content for m in grouped["s2"]] == ["two"]
    assert fake_pg.conn.fetch.await_count == 1
    fetch_args = fake_pg.conn.fetch.await_args
    assert fetch_args is not None
    assert "ORDER BY session_id ASC, created_at ASC, id ASC" in fetch_args.args[0]

    assert await db.get_messages_for_sessions(["", "   "]) == {}


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

    ensured = await sqlite_db.ensure_user_id(
        "fixed-id", username="fixed-name", role="reviewer", tenant_id="tenant-z"
    )
    assert ensured.id == "fixed-id"
    assert ensured.tenant_id == "tenant-z"

    same = await sqlite_db.ensure_user_id("fixed-id")
    assert same.username == "fixed-name"


@pytest.mark.asyncio
async def test_marketing_and_content_listing_filters_and_validations(sqlite_db: Database) -> None:
    with pytest.raises(ValueError, match="campaign name is required"):
        await sqlite_db.upsert_marketing_campaign(name="")

    c1 = await sqlite_db.upsert_marketing_campaign(tenant_id="tenant-1", name="C1", status="DRAFT")
    c2 = await sqlite_db.upsert_marketing_campaign(tenant_id="tenant-1", name="C2", status="ACTIVE")
    _ = c2

    active = await sqlite_db.list_marketing_campaigns(
        tenant_id="tenant-1", status="active", limit=1
    )
    assert len(active) == 1
    assert active[0].status == "active"

    with pytest.raises(ValueError, match="asset_type, title and content are required"):
        await sqlite_db.add_content_asset(
            campaign_id=c1.id, tenant_id="tenant-1", asset_type="", title="x", content="y"
        )

    a1 = await sqlite_db.add_content_asset(
        campaign_id=c1.id, tenant_id="tenant-1", asset_type="post", title="T1", content="Body"
    )
    _a2 = await sqlite_db.add_content_asset(
        campaign_id=c1.id, tenant_id="tenant-1", asset_type="post", title="T2", content="Body"
    )

    all_assets = await sqlite_db.list_content_assets(tenant_id="tenant-1", limit=10)
    by_campaign = await sqlite_db.list_content_assets(
        tenant_id="tenant-1", campaign_id=c1.id, limit=10
    )
    assert len(by_campaign) == len(all_assets) == 2
    assert by_campaign[0].campaign_id == a1.campaign_id


@pytest.mark.asyncio
async def test_operation_checklist_and_coverage_management(sqlite_db: Database) -> None:
    with pytest.raises(ValueError, match="title is required"):
        await sqlite_db.add_operation_checklist(tenant_id="t1", title="", items=[])

    checklist = await sqlite_db.add_operation_checklist(
        tenant_id="t1",
        title="Ops",
        items=["one", {"step": "two"}, {"": "drop"}, "   "],
        status="PENDING",
    )
    checklists = await sqlite_db.list_operation_checklists(tenant_id="t1", limit=5)
    assert checklists[0].id == checklist.id

    with pytest.raises(ValueError, match="command is required"):
        await sqlite_db.create_coverage_task(tenant_id="t1", command="", pytest_output="x")

    task = await sqlite_db.create_coverage_task(
        tenant_id="t1",
        command="pytest -q",
        pytest_output="ok",
        status="IN_PROGRESS",
        review_payload_json='{"score":1}',
    )
    assert task.status == "IN_PROGRESS"

    with pytest.raises(ValueError, match="finding_type and summary are required"):
        await sqlite_db.add_coverage_finding(
            task_id=task.id, finding_type="", target_path="a", summary="b"
        )

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

    with pytest.raises(ValueError, match="action and resource are required"):
        await sqlite_db.record_audit_log(
            action="", resource="repo", ip_address="127.0.0.1", allowed=True
        )

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

    async def mock_fetchrow_router(query, *args, **kwargs):
        if "marketing_campaigns" in query:
            return campaign_row
        if "content_assets" in query:
            return asset_row
        if "operation_checklists" in query:
            return checklist_row
        if "coverage_tasks" in query:
            return task_row
        if "coverage_findings" in query:
            return finding_row
        return None

    async def mock_fetch_router(query, *args, **kwargs):
        if "FROM marketing_campaigns" in query:
            return [campaign_row]
        if "FROM content_assets" in query:
            return [asset_row]
        if "FROM operation_checklists" in query:
            return [checklist_row]
        if "FROM coverage_tasks" in query:
            return [task_row]
        return []

    fake_pg.conn.fetchrow = AsyncMock(side_effect=mock_fetchrow_router)
    fake_pg.conn.fetch = AsyncMock(side_effect=mock_fetch_router)

    created = await db.upsert_marketing_campaign(tenant_id="t1", name="Launch", status="ACTIVE")
    assert created.id == 10
    updated = await db.upsert_marketing_campaign(campaign_id=10, tenant_id="t1", name="Launch2")
    assert updated.name == "Launch"

    campaigns = await db.list_marketing_campaigns(tenant_id="t1", status="active", limit=5)
    assert campaigns and campaigns[0].id == 10

    asset = await db.add_content_asset(
        campaign_id=10, tenant_id="t1", asset_type="post", title="hello", content="world"
    )
    assert asset.id == 20
    assets = await db.list_content_assets(tenant_id="t1", campaign_id=10, limit=3)
    assert assets and assets[0].campaign_id == 10

    checklist = await db.add_operation_checklist(
        tenant_id="t1", title="ops", items=["a"], campaign_id=10
    )
    assert checklist.id == 30
    checklists = await db.list_operation_checklists(tenant_id="t1", campaign_id=10, limit=3)
    assert checklists and checklists[0].id == 30

    task = await db.create_coverage_task(tenant_id="t1", command="pytest", pytest_output="ok")
    assert task.id == 40
    finding = await db.add_coverage_finding(
        task_id=40, finding_type="missing_test", target_path="core/db.py", summary="line missed"
    )
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
    fake_pg.conn.fetch = AsyncMock(
        return_value=[
            {
                "id": "u1",
                "username": "john",
                "role": "user",
                "created_at": "c",
                "daily_token_limit": 100,
                "daily_request_limit": 5,
            }
        ]
    )

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
    replaced = await db.replace_session_messages(
        "s1", [{"content": "x"}, {"role": "user", "content": "y"}]
    )
    assert replaced == 2


@pytest.mark.asyncio
async def test_replace_session_messages_postgresql_supports_awaitable_transaction_factory(
    tmp_path,
) -> None:
    db = Database(
        DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR=str(tmp_path))
    )
    fake_pg = FakePgAdapter()
    db._backend = "postgresql"
    db._pg_pool = fake_pg

    class _Tx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _tx_factory():
        return _Tx()

    fake_pg.conn.transaction = _tx_factory
    replaced = await db.replace_session_messages(
        "s-awaitable", [{"role": "user", "content": "hello"}]
    )
    assert replaced == 1


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


def test_sqlite_triple_slash_url_branch(tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL=f"sqlite:///{tmp_path / 'triple.db'}", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    assert db._backend == "sqlite"
    assert db._sqlite_path == tmp_path / "triple.db"


def test_sqlite_plain_path_url_branch(tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL="plain_relative.db", BASE_DIR=str(tmp_path))
    db = Database(cfg)
    assert db._backend == "sqlite"
    assert db._sqlite_path == tmp_path / "plain_relative.db"


@pytest.mark.asyncio
async def test_connect_postgresql_branch_matrix(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cfg = DummyCfg(DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", BASE_DIR=str(tmp_path))

    already_connected = Database(cfg)
    already_connected._pg_pool = object()
    await already_connected._connect_postgresql()

    missing_dep = Database(cfg)
    monkeypatch.delitem(sys.modules, "asyncpg", raising=False)
    monkeypatch.setitem(sys.modules, "asyncpg", None)
    with pytest.raises(RuntimeError, match="asyncpg"):
        await missing_dep._connect_postgresql()

    class _AsyncpgStub:
        class PoolError(Exception):
            pass

    timeout_db = Database(cfg)

    async def _raise_timeout(**_kwargs):
        raise TimeoutError("pool timeout")

    monkeypatch.setitem(
        sys.modules,
        "asyncpg",
        types.SimpleNamespace(create_pool=_raise_timeout, PoolError=_AsyncpgStub.PoolError),
    )
    with pytest.raises(TimeoutError):
        await timeout_db._connect_postgresql()

    pool_error_db = Database(cfg)

    async def _raise_pool(**_kwargs):
        raise _AsyncpgStub.PoolError("pool is down")

    monkeypatch.setitem(
        sys.modules,
        "asyncpg",
        types.SimpleNamespace(create_pool=_raise_pool, PoolError=_AsyncpgStub.PoolError),
    )
    with pytest.raises(_AsyncpgStub.PoolError):
        await pool_error_db._connect_postgresql()

    generic_db = Database(cfg)

    async def _raise_generic(**_kwargs):
        raise RuntimeError("connection failed")

    monkeypatch.setitem(
        sys.modules,
        "asyncpg",
        types.SimpleNamespace(create_pool=_raise_generic, PoolError=_AsyncpgStub.PoolError),
    )
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


@pytest.mark.asyncio
async def test_postgresql_prompt_activation_and_upsert_edges() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    # empty role short-circuit
    assert await db.get_active_prompt("") is None

    # get_active_prompt: missing row path then success path
    fake_pg.conn.fetchrow = AsyncMock(
        side_effect=[
            None,
            {
                "id": 1,
                "role_name": "system",
                "prompt_text": "p",
                "version": 2,
                "is_active": True,
                "created_at": "c",
                "updated_at": "u",
            },
        ]
    )
    assert await db.get_active_prompt("system") is None
    active = await db.get_active_prompt("system")
    assert active is not None
    assert active.version == 2

    # upsert_prompt postgresql path
    fake_pg.conn.fetchval = AsyncMock(return_value=2)
    fake_pg.conn.fetchrow = AsyncMock(
        return_value={
            "id": 3,
            "role_name": "system",
            "prompt_text": "p3",
            "version": 3,
            "is_active": False,
            "created_at": "c",
            "updated_at": "u",
        }
    )
    inserted = await db.upsert_prompt("system", "p3", activate=False)
    assert inserted.id == 3

    # invalid id short-circuit
    assert await db.activate_prompt(0) is None

    # not found branch
    fake_pg.conn.fetchrow = AsyncMock(return_value=None)
    assert await db.activate_prompt(1000) is None

    # success branch
    fake_pg.conn.fetchrow = AsyncMock(return_value={"id": 4, "role_name": "system"})

    async def _fake_get_active(role_name: str):
        return PromptRecord(
            id=4,
            role_name=role_name,
            prompt_text="x",
            version=4,
            is_active=True,
            created_at="c",
            updated_at="u",
        )

    from core.db import PromptRecord

    db.get_active_prompt = _fake_get_active  # type: ignore[method-assign]
    activated = await db.activate_prompt(4)
    assert activated is not None
    assert activated.id == 4


@pytest.mark.asyncio
async def test_postgresql_user_and_session_branches() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    # ensure_user existing path
    fake_pg.conn.fetchrow = AsyncMock(
        return_value={
            "id": "u1",
            "username": "john",
            "role": "admin",
            "created_at": "c",
            "tenant_id": "t1",
        }
    )
    existing = await db.ensure_user("john", role="user")
    assert existing.role == "admin"

    # ensure_user create path
    fake_pg.conn.fetchrow = AsyncMock(return_value=None)
    created = await db.ensure_user("new-user", role="reviewer")
    assert created.username == "new-user"

    # create_user postgresql branch
    created2 = await db.create_user("post-user", role="analyst", password="pw", tenant_id="t2")
    assert created2.tenant_id == "t2"

    # authenticate branches: missing, wrong password, and success
    hashed = _hash_password("pw")
    fake_pg.conn.fetchrow = AsyncMock(
        side_effect=[
            None,
            {
                "id": "u2",
                "username": "x",
                "password_hash": hashed,
                "role": "user",
                "created_at": "c",
                "tenant_id": "t",
            },
            {
                "id": "u2",
                "username": "x",
                "password_hash": hashed,
                "role": "user",
                "created_at": "c",
                "tenant_id": "t",
            },
        ]
    )
    assert await db.authenticate_user("x", "pw") is None
    assert await db.authenticate_user("x", "wrong") is None
    ok = await db.authenticate_user("x", "pw")
    assert ok is not None

    # _get_user_by_id none and success
    fake_pg.conn.fetchrow = AsyncMock(
        side_effect=[
            None,
            {
                "id": "u3",
                "username": "y",
                "role": "user",
                "created_at": "c",
                "tenant_id": "default",
            },
        ]
    )
    assert await db._get_user_by_id("u3") is None
    got = await db._get_user_by_id("u3")
    assert got is not None

    # load_session with user filter, without user filter, and missing
    fake_pg.conn.fetchrow = AsyncMock(
        side_effect=[
            {"id": "s1", "user_id": "u1", "title": "t", "created_at": "c", "updated_at": "u"},
            {"id": "s2", "user_id": "u1", "title": "t2", "created_at": "c", "updated_at": "u"},
            None,
        ]
    )
    assert (await db.load_session("s1", user_id="u1")) is not None
    assert (await db.load_session("s2")) is not None
    assert (await db.load_session("s3")) is None

    # update/delete parse-failure fallback branches
    fake_pg.conn.execute = AsyncMock(side_effect=["UPDATED", object(), object()])
    assert await db.update_session_title("s1", "n") is False
    assert await db.delete_session("s1", user_id="u1") is False
    assert await db.delete_session("s1") is False


@pytest.mark.asyncio
async def test_postgresql_policy_audit_and_listing_branches() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    # connect routing branch
    await db.connect()

    # access-policy early false / no match
    assert (
        await db.check_access_policy(user_id="", tenant_id="t", resource_type="repo", action="read")
        is False
    )
    assert (
        await db.check_access_policy(
            user_id="u1", tenant_id="t", resource_type="repo", action="read", resource_id="x"
        )
        is False
    )

    await db.upsert_access_policy(
        user_id="u1",
        tenant_id="default",
        resource_type="repo",
        action="read",
        resource_id="*",
        effect="allow",
    )
    rows = [
        {
            "id": 1,
            "user_id": "u1",
            "tenant_id": "default",
            "resource_type": "repo",
            "resource_id": "*",
            "action": "read",
            "effect": "allow",
            "created_at": "c",
            "updated_at": "u",
        }
    ]
    user_logs_rows = [
        {
            "id": 1,
            "user_id": "u1",
            "tenant_id": "default",
            "action": "read",
            "resource": "repo/1",
            "ip_address": "127.0.0.1",
            "allowed": True,
            "timestamp": "c",
        }
    ]
    all_logs_rows = [
        {
            "id": 2,
            "user_id": "u2",
            "tenant_id": "default",
            "action": "write",
            "resource": "repo/2",
            "ip_address": "10.0.0.2",
            "allowed": False,
            "timestamp": "c",
        }
    ]

    async def _fake_fetch(query: str, *args):
        if "FROM access_policies" in query:
            return rows
        if "WHERE user_id=$1 ORDER BY timestamp DESC LIMIT $2" in query:
            return user_logs_rows
        return all_logs_rows

    fake_pg.conn.fetch = AsyncMock(side_effect=_fake_fetch)

    listed_default = await db.list_access_policies("u1")
    listed_tenant = await db.list_access_policies("u1", tenant_id="default")
    assert listed_default and listed_tenant

    assert (
        await db.check_access_policy(
            user_id="u1", tenant_id="any", resource_type="repo", action="read", resource_id="x"
        )
        is True
    )

    await db.record_audit_log(
        user_id="u1",
        tenant_id="default",
        action="read",
        resource="repo/1",
        ip_address="127.0.0.1",
        allowed=True,
    )
    user_logs = await db.list_audit_logs(user_id="u1", limit=2)
    all_logs = await db.list_audit_logs(limit=2)
    assert len(user_logs) == 1
    assert len(all_logs) == 1


@pytest.mark.asyncio
async def test_postgresql_timestamp_writes_use_datetime_instances() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    fake_pg.conn.fetchval = AsyncMock(return_value=0)
    fake_pg.conn.fetchrow = AsyncMock(
        side_effect=[
            {
                "id": 1,
                "role_name": "system",
                "prompt_text": "p",
                "version": 1,
                "is_active": True,
                "created_at": "c",
                "updated_at": "u",
            },
            {
                "id": 10,
                "tenant_id": "t1",
                "name": "Launch",
                "channel": "",
                "objective": "",
                "status": "active",
                "owner_user_id": "",
                "budget": 0.0,
                "metadata_json": "{}",
                "created_at": "c",
                "updated_at": "u",
            },
            {
                "id": 11,
                "campaign_id": 10,
                "tenant_id": "t1",
                "asset_type": "post",
                "title": "hello",
                "content": "world",
                "channel": "",
                "metadata_json": "{}",
                "created_at": "c",
                "updated_at": "u",
            },
            {
                "id": 12,
                "campaign_id": 10,
                "tenant_id": "t1",
                "title": "ops",
                "items_json": "[]",
                "status": "pending",
                "owner_user_id": "",
                "created_at": "c",
                "updated_at": "u",
            },
            {
                "id": 13,
                "tenant_id": "t1",
                "requester_role": "coverage",
                "command": "pytest",
                "pytest_output": "ok",
                "status": "pending_review",
                "target_path": "",
                "suggested_test_path": "",
                "review_payload_json": "{}",
                "created_at": "c",
                "updated_at": "u",
            },
            {
                "id": 14,
                "task_id": 13,
                "finding_type": "missing_test",
                "target_path": "core/db.py",
                "summary": "line missed",
                "severity": "medium",
                "details_json": "{}",
                "created_at": "c",
            },
        ]
    )

    await db.upsert_prompt("system", "p", activate=True)
    await db.upsert_access_policy(
        user_id="u1", tenant_id="default", resource_type="repo", action="read", effect="allow"
    )
    await db.record_audit_log(
        user_id="u1",
        tenant_id="default",
        action="read",
        resource="repo/1",
        ip_address="127.0.0.1",
        allowed=True,
    )
    await db.upsert_marketing_campaign(tenant_id="t1", name="Launch", status="ACTIVE")
    await db.add_content_asset(
        campaign_id=10, tenant_id="t1", asset_type="post", title="hello", content="world"
    )
    await db.add_operation_checklist(tenant_id="t1", title="ops", items=["a"], campaign_id=10)
    await db.create_coverage_task(tenant_id="t1", command="pytest", pytest_output="ok")
    await db.add_coverage_finding(
        task_id=13, finding_type="missing_test", target_path="core/db.py", summary="line missed"
    )
    await db.create_user("pg-user", role="user", password="pw")

    datetime_args = []
    for call in fake_pg.conn.execute.await_args_list:
        datetime_args.extend([arg for arg in call.args[1:] if isinstance(arg, datetime)])
    for call in fake_pg.conn.fetchrow.await_args_list:
        datetime_args.extend([arg for arg in call.args[1:] if isinstance(arg, datetime)])

    assert datetime_args


@pytest.mark.asyncio
async def test_postgresql_listing_without_optional_filters() -> None:
    db = Database(DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR="."))
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    campaign_row = {
        "id": 1,
        "tenant_id": "t",
        "name": "n",
        "channel": "",
        "objective": "",
        "status": "active",
        "owner_user_id": "",
        "budget": 0.0,
        "metadata_json": "{}",
        "created_at": "c",
        "updated_at": "u",
    }
    asset_row = {
        "id": 2,
        "campaign_id": 1,
        "tenant_id": "t",
        "asset_type": "post",
        "title": "ttl",
        "content": "c",
        "channel": "",
        "metadata_json": "{}",
        "created_at": "c",
        "updated_at": "u",
    }
    checklist_row = {
        "id": 3,
        "campaign_id": 1,
        "tenant_id": "t",
        "title": "ops",
        "items_json": "[]",
        "status": "pending",
        "owner_user_id": "",
        "created_at": "c",
        "updated_at": "u",
    }
    task_row = {
        "id": 4,
        "tenant_id": "t",
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

    fake_pg.conn.fetch = AsyncMock(
        side_effect=[[campaign_row], [asset_row], [checklist_row], [task_row]]
    )
    fake_pg.conn.fetchrow = AsyncMock(return_value=None)

    campaigns = await db.list_marketing_campaigns(tenant_id="t", limit=2)
    assets = await db.list_content_assets(tenant_id="t", limit=2)
    checklists = await db.list_operation_checklists(tenant_id="t", limit=2)
    tasks = await db.list_coverage_tasks(tenant_id="t", limit=2)

    assert campaigns and assets and checklists and tasks

    with pytest.raises(ValueError, match="campaign not found"):
        await db.upsert_marketing_campaign(campaign_id=999, tenant_id="t", name="missing")


@pytest.mark.asyncio
async def test_sqlite_branches_for_prompt_policy_and_listings(sqlite_db: Database) -> None:
    # list_prompts without filter (901-908)
    await sqlite_db.upsert_prompt("system", "v1", activate=True)
    prompts = await sqlite_db.list_prompts()
    assert prompts

    # activate_prompt missing id -> None (1096, 1111)
    assert await sqlite_db.activate_prompt(999_999) is None

    # _run_sqlite_op lock initialization branch (282)
    sqlite_db._sqlite_lock = None
    result = await sqlite_db._run_sqlite_op(lambda: 42)
    assert result == 42

    user = await sqlite_db.create_user("list-policy-user", password="pw")
    await sqlite_db.upsert_access_policy(
        user_id=user.id,
        tenant_id="default",
        resource_type="repo",
        action="read",
        effect="allow",
    )
    # no tenant filter branch (1606)
    policies = await sqlite_db.list_access_policies(user.id)
    assert policies and policies[0].tenant_id == "default"

    with pytest.raises(ValueError, match="resource_type and action are required"):
        await sqlite_db.upsert_access_policy(
            user_id=user.id, tenant_id="default", resource_type="", action="read"
        )

    campaign = await sqlite_db.upsert_marketing_campaign(tenant_id="tenant-l", name="Campaign A")
    # no status branch (2046)
    listed_campaigns = await sqlite_db.list_marketing_campaigns(tenant_id="tenant-l")
    assert listed_campaigns and listed_campaigns[0].id == campaign.id

    checklist = await sqlite_db.add_operation_checklist(
        campaign_id=campaign.id, tenant_id="tenant-l", title="Ops", items=["a", "b"]
    )
    # campaign_id is not None branch (2373)
    checklists = await sqlite_db.list_operation_checklists(
        tenant_id="tenant-l", campaign_id=campaign.id
    )
    assert checklists and checklists[0].id == checklist.id

    await sqlite_db.create_coverage_task(tenant_id="tenant-l", command="pytest", pytest_output="ok")
    # no status branch (2644)
    tasks = await sqlite_db.list_coverage_tasks(tenant_id="tenant-l")
    assert tasks


@pytest.mark.asyncio
async def test_run_sqlite_op_recreates_lock_when_bound_to_different_loop(
    sqlite_db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    class _ForeignLoopLock:
        def __init__(self) -> None:
            self._loop = object()

    sqlite_db._sqlite_lock = _ForeignLoopLock()  # type: ignore[assignment]

    with caplog.at_level("WARNING"):
        result = await sqlite_db._run_sqlite_op(lambda: 7)

    assert result == 7
    assert isinstance(sqlite_db._sqlite_lock, asyncio.Lock)
    assert "kilidi farklı event loop'a bağlı" in caplog.text


@pytest.mark.asyncio
async def test_postgresql_and_schema_version_edge_branches(tmp_path) -> None:
    db = Database(
        DummyCfg(DATABASE_URL="postgresql://user:pw@localhost:5432/sidar", BASE_DIR=str(tmp_path))
    )
    fake_pg = FakePgAdapter()
    db._pg_pool = fake_pg

    # ensure_default_prompt_registry when no loader/default prompt (845->850, 852)
    class _SpecNoLoader:
        loader = None

    import importlib.util as _importlib_util

    original_spec = _importlib_util.spec_from_file_location
    _importlib_util.spec_from_file_location = lambda *_args, **_kwargs: _SpecNoLoader()  # type: ignore[assignment]
    try:
        await db.ensure_default_prompt_registry()
    finally:
        _importlib_util.spec_from_file_location = original_spec  # type: ignore[assignment]

    fake_pg.conn.fetchval = AsyncMock(return_value=0)
    fake_pg.conn.fetchrow = AsyncMock(
        return_value={
            "id": 10,
            "role_name": "system",
            "prompt_text": "new",
            "version": 1,
            "is_active": True,
            "created_at": "c",
            "updated_at": "u",
        }
    )
    await db.upsert_prompt("system", "new", activate=True)  # activate=True branch (998)

    # schema-version helper (1138-1149)
    await db._ensure_schema_version_postgresql()
    assert fake_pg.conn.execute.await_count >= 2

    # ensure_user_id postgres insert path (1461-1472)
    async def _none_user(_user_id: str):
        return None

    db._get_user_by_id = _none_user  # type: ignore[method-assign]
    created = await db.ensure_user_id(
        "uid-postgres", username="u-post", role="reviewer", tenant_id="t-post"
    )
    assert created.id == "uid-postgres"

    # current >= target branch (1147)
    fake_pg.conn.fetchval = AsyncMock(return_value=999)
    await db._ensure_schema_version_postgresql()


@pytest.mark.asyncio
async def test_sqlite_remaining_edge_branches(tmp_path) -> None:
    cfg = DummyCfg(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'edges.db'}",
        BASE_DIR=str(tmp_path),
        DB_SCHEMA_TARGET_VERSION=1,
    )
    db = Database(cfg)
    await db.connect()
    await db.init_schema()

    # sqlite schema version current>=target branch (1127)
    await db._ensure_schema_version_sqlite()

    # register_user wrapper (1383) + authenticate none/wrong branches (1411, 1413)
    plain = await db.ensure_user("no-password")
    assert await db.authenticate_user(plain.username, "pw") is None
    await db.register_user("with-password", "pw")
    assert await db.authenticate_user("with-password", "wrong") is None

    # sqlite delete_session without user_id branch (1345)
    s = await db.create_session(plain.id, "tmp")
    assert await db.delete_session(s.id) is True

    # sqlite campaign update missing row branch (1987)
    with pytest.raises(ValueError, match="campaign not found"):
        await db.upsert_marketing_campaign(campaign_id=999_999, tenant_id="t", name="x")
    await db.close()


def test_parse_iso_datetime_assumes_utc_for_naive_input() -> None:
    parsed = _parse_iso_datetime("2026-01-02T03:04:05")
    assert parsed.tzinfo == UTC
    assert parsed.isoformat() == "2026-01-02T03:04:05+00:00"


def test_new_entity_id_falls_back_to_uuid4_when_uuid7_and_uuid6_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(uuid, "uuid7", raising=False)
    monkeypatch.setitem(sys.modules, "uuid6", None)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID("00000000-0000-4000-8000-000000000099"))

    assert _new_entity_id() == "00000000-0000-4000-8000-000000000099"


def test_expires_in_uses_default_days_when_no_argument() -> None:
    now = datetime.now(UTC)
    expiry = datetime.fromisoformat(_expires_in())
    assert timedelta(days=6, hours=23, minutes=59) < (expiry - now) < timedelta(days=7, minutes=1)


@pytest.mark.asyncio
async def test_get_user_by_token_returns_jwt_user_when_db_lookup_missing(
    sqlite_db: Database,
) -> None:
    token = await sqlite_db.create_auth_token(
        user_id="missing-user",
        role="analyst",
        username="jwt-only",
        tenant_id="tenant-z",
        ttl_days=1,
    )

    resolved = await sqlite_db.get_user_by_token(token.token)
    assert resolved is not None
    assert resolved.id == "missing-user"
    assert resolved.username == "jwt-only"
    assert resolved.role == "analyst"
    assert resolved.tenant_id == "tenant-z"
