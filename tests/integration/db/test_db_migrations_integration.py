import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from core.db import Database

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _touch_sqlite_database(db_url: str) -> None:
    """Open and dispose a synchronous SQLite engine in one worker thread."""
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SELECT 1")
    finally:
        engine.dispose()


def _sqlite_table_names(db_url: str) -> set[str]:
    """Inspect SQLite tables and dispose the engine before returning."""
    engine = create_engine(db_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alembic_migrations_up_and_down(tmp_path, monkeypatch):
    """Run alembic migrations end-to-end on a temporary SQLite database."""
    db_path = (tmp_path / "test_migration.db").resolve()
    db_url = f"sqlite:////{db_path.as_posix().lstrip('/')}"
    async_db_url = db_url.replace("sqlite://", "sqlite+aiosqlite://")

    monkeypatch.setenv("DATABASE_URL", async_db_url)

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", async_db_url)
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))

    # Alembic's env.py drives async engines with asyncio.run(...).  Execute the
    # blocking command in a worker thread so this pytest-asyncio test keeps its
    # loop clean and all sync SQLAlchemy engines are disposed on their owner
    # thread before control returns to the async test.
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    # Driver bağlantısını kesinleştirip dosya oluşturmayı fiziksel olarak tetikle.
    await asyncio.to_thread(_touch_sqlite_database, db_url)
    assert db_path.exists(), "SQLite database file should be created after upgrade."

    upgraded_tables = await asyncio.to_thread(_sqlite_table_names, db_url)

    assert "alembic_version" in upgraded_tables
    assert len(upgraded_tables) > 1, "Expected schema tables to exist after upgrade."

    await asyncio.to_thread(command.downgrade, alembic_cfg, "base")

    downgraded_tables = await asyncio.to_thread(_sqlite_table_names, db_url)

    # Alembic SQLite'da base downgrade sonrası yalnızca version tablosunu bırakabilir.
    assert downgraded_tables in (set(), {"alembic_version"})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_schema_version_migration_is_idempotent_under_concurrency(tmp_path):
    """Aynı SQLite şemasına eşzamanlı migration/version ensure çağrılarında bütünlüğü korur."""
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'concurrent_versions.db'}",
        BASE_DIR=str(tmp_path),
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=4,
        JWT_SECRET_KEY="test-secret-key-for-ci-testing-only!",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )
    db = Database(cfg)
    await db.connect()
    await db.init_schema()
    try:
        await asyncio.gather(*[db._ensure_schema_version_sqlite() for _ in range(16)])

        def _fetch_versions():
            assert db._sqlite_conn is not None
            rows = db._sqlite_conn.execute(
                "SELECT version FROM schema_versions ORDER BY version ASC"
            ).fetchall()
            return [int(row["version"]) for row in rows]

        versions = await db._run_sqlite_op(_fetch_versions)
        assert versions == [1, 2, 3, 4]
    finally:
        await db.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_user_sessions_and_messages_keep_integrity_under_concurrency(tmp_path):
    """Yüksek eşzamanlılıkta kullanıcı/oturum/mesaj ilişkilerinin bozulmadığını doğrular."""
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'concurrent_data.db'}",
        BASE_DIR=str(tmp_path),
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=2,
        JWT_SECRET_KEY="test-secret-key-for-ci-testing-only!",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )
    db = Database(cfg)
    await db.connect()
    await db.init_schema()
    users = 24
    messages_per_session = 10
    try:
        created_users = await asyncio.gather(
            *[
                db.create_user(f"u{idx}", tenant_id=f"tenant-{idx % 3}", password="pw")
                for idx in range(users)
            ]
        )
        sessions = await asyncio.gather(
            *[
                db.create_session(user.id, f"session-{idx}")
                for idx, user in enumerate(created_users)
            ]
        )

        await asyncio.gather(
            *[
                db.add_message(session.id, "user", f"msg-{k}", tokens_used=k)
                for session in sessions
                for k in range(messages_per_session)
            ]
        )

        session_messages = await asyncio.gather(
            *[db.get_session_messages(session.id) for session in sessions]
        )
        assert all(len(items) == messages_per_session for items in session_messages)
        assert all(
            [m.tokens_used for m in items] == list(range(messages_per_session))
            for items in session_messages
        )

        for session, user in zip(sessions[:6], created_users[:6], strict=True):
            assert await db.load_session(session.id, user_id=user.id) is not None
            assert await db.load_session(session.id, user_id="wrong-user") is None

        def _integrity_check():
            assert db._sqlite_conn is not None
            integrity = db._sqlite_conn.execute("PRAGMA integrity_check").fetchone()
            orphan_messages = db._sqlite_conn.execute(
                """
                SELECT COUNT(*) AS orphan_count
                FROM messages m
                LEFT JOIN sessions s ON s.id = m.session_id
                WHERE s.id IS NULL
                """
            ).fetchone()
            return str(integrity[0] if integrity else ""), int(
                orphan_messages[0] if orphan_messages else 0
            )

        integrity_result, orphan_count = await db._run_sqlite_op(_integrity_check)
        assert integrity_result.lower() == "ok"
        assert orphan_count == 0
    finally:
        await db.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_db_facade_session_metrics_and_audit_modules_interoperate(sqlite_db: Database):
    """Extracted session, metrics and audit helpers keep the core.db facade coherent."""
    user = await sqlite_db.create_user(
        "facade-integration-user",
        password="pw",
        tenant_id="tenant-integration",
    )
    session = await sqlite_db.create_session(user.id, "Refactor guard")
    await sqlite_db.add_message(session.id, "user", "hello", tokens_used=3)
    await sqlite_db.replace_session_messages(
        session.id,
        [
            {"role": "user", "content": "rewritten", "tokens_used": 5},
            {"role": "assistant", "content": "ack", "tokens_used": 7},
        ],
    )

    await sqlite_db.upsert_user_quota(user.id, daily_token_limit=12, daily_request_limit=2)
    await sqlite_db.record_provider_usage_daily(user.id, "OpenAI", tokens_used=5, requests_inc=1)
    await sqlite_db.record_provider_usage_daily(user.id, "openai", tokens_used=7, requests_inc=1)
    await sqlite_db.record_audit_log(
        user_id=user.id,
        tenant_id="tenant-integration",
        action="SESSION_UPDATE",
        resource=session.id,
        ip_address="127.0.0.1",
        allowed=True,
    )

    sessions = await sqlite_db.list_sessions(user.id)
    messages = await sqlite_db.get_session_messages(session.id)
    quota = await sqlite_db.get_user_quota_status(user.id, "openai")
    audit_logs = await sqlite_db.list_audit_logs(user_id=user.id, limit=5)

    assert [item.id for item in sessions] == [session.id]
    assert [(item.role, item.content, item.tokens_used) for item in messages] == [
        ("user", "rewritten", 0),
        ("assistant", "ack", 0),
    ]
    assert quota["tokens_used"] == 12
    assert quota["requests_used"] == 2
    assert quota["token_limit_exceeded"] is True
    assert quota["request_limit_exceeded"] is True
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "session_update"
    assert audit_logs[0].resource == session.id


def _packaged_alembic_config(database_url: str) -> Config:
    """Build an Alembic config that exercises packaged sidar_assets migrations."""
    from sidar_assets.paths import migrations_path

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)
    alembic_cfg.set_main_option("script_location", str(migrations_path()))
    return alembic_cfg


@pytest.mark.integration
def test_packaged_alembic_head_preserves_seed_data_and_downgrades_to_base(tmp_path, monkeypatch):
    """Packaged migrations keep baseline data valid while moving to head and back to base."""
    db_path = (tmp_path / "packaged_seeded_roundtrip.db").resolve()
    db_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    alembic_cfg = _packaged_alembic_config(db_url)

    command.upgrade(alembic_cfg, "0001_baseline_schema")
    engine = create_engine(db_url)
    user_id = "11111111-1111-1111-1111-111111111111"
    session_id = "22222222-2222-2222-2222-222222222222"
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                INSERT INTO users (id, username, password_hash, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, "seed-user", "hash", "admin", "2026-05-12 00:00:00"),
            )
            conn.exec_driver_sql(
                """
                INSERT INTO sessions (id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    "seed-session",
                    "2026-05-12 00:01:00",
                    "2026-05-12 00:01:00",
                ),
            )
            conn.exec_driver_sql(
                """
                INSERT INTO messages (id, session_id, role, content, tokens_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (1, session_id, "user", "hello", 7, "2026-05-12 00:02:00"),
            )
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")

    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        assert {
            "users",
            "sessions",
            "messages",
            "prompt_registry",
            "audit_logs",
            "marketing_campaigns",
            "access_policies",
        }.issubset(table_names)
        assert "tenant_id" in {column["name"] for column in inspector.get_columns("users")}
        assert "idx_access_policies_user_tenant" in {
            index["name"] for index in inspector.get_indexes("access_policies")
        }

        with engine.begin() as conn:
            user_row = (
                conn.exec_driver_sql(
                    "SELECT username, role, tenant_id FROM users WHERE id = ?", (user_id,)
                )
                .mappings()
                .one()
            )
            assert dict(user_row) == {
                "username": "seed-user",
                "role": "admin",
                "tenant_id": "default",
            }
            message_row = (
                conn.exec_driver_sql(
                    "SELECT content, tokens_used FROM messages WHERE session_id = ?", (session_id,)
                )
                .mappings()
                .one()
            )
            assert dict(message_row) == {"content": "hello", "tokens_used": 7}
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM prompt_registry").scalar_one() >= 1
            conn.exec_driver_sql(
                """
                INSERT INTO access_policies (
                    id, user_id, tenant_id, resource_type, resource_id, action, effect, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    1,
                    user_id,
                    "default",
                    "session",
                    session_id,
                    "read",
                    "allow",
                    "2026-05-12 00:03:00",
                    "2026-05-12 00:03:00",
                ),
            )
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "base")

    engine = create_engine(db_url)
    try:
        downgraded_tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert downgraded_tables in (set(), {"alembic_version"})


@pytest.mark.integration
def test_packaged_alembic_stepwise_downgrade_removes_revision_objects(tmp_path, monkeypatch):
    """Packaged migrations can roll back one revision at a time without orphaned tables/columns."""
    db_path = (tmp_path / "packaged_stepwise_rollback.db").resolve()
    db_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    alembic_cfg = _packaged_alembic_config(db_url)

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        head_tables = set(inspector.get_table_names())
        assert "access_policies" in head_tables
        assert "tenant_id" in {column["name"] for column in inspector.get_columns("users")}
        assert {
            "marketing_campaigns",
            "content_assets",
            "operation_checklists",
            "coverage_tasks",
            "coverage_findings",
            "audit_logs",
            "prompt_registry",
        }.issubset(head_tables)
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "0005_pgvector_hnsw_index")
    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        downgraded_tables = set(inspector.get_table_names())
        assert "access_policies" not in downgraded_tables
        assert "tenant_id" not in {column["name"] for column in inspector.get_columns("users")}
        assert "marketing_campaigns" in downgraded_tables
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "0003_audit_trail")
    engine = create_engine(db_url)
    try:
        downgraded_tables = set(inspect(engine).get_table_names())
        assert {
            "marketing_campaigns",
            "content_assets",
            "operation_checklists",
            "coverage_tasks",
            "coverage_findings",
        }.isdisjoint(downgraded_tables)
        assert "audit_logs" in downgraded_tables
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "0002_prompt_registry")
    engine = create_engine(db_url)
    try:
        downgraded_tables = set(inspect(engine).get_table_names())
        assert "audit_logs" not in downgraded_tables
        assert "prompt_registry" in downgraded_tables
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "0001_baseline_schema")
    engine = create_engine(db_url)
    try:
        downgraded_tables = set(inspect(engine).get_table_names())
        assert "prompt_registry" not in downgraded_tables
        assert "users" in downgraded_tables
        assert "sessions" in downgraded_tables
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "base")
    engine = create_engine(db_url)
    try:
        downgraded_tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert downgraded_tables in (set(), {"alembic_version"})


@pytest.mark.integration
def test_packaged_alembic_head_base_cycle_is_repeatable(tmp_path, monkeypatch):
    """Repeated packaged upgrade-head/downgrade-base cycles do not leave conflicting objects."""
    db_path = (tmp_path / "packaged_repeatable_roundtrip.db").resolve()
    db_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SIDAR_ENV", raising=False)
    alembic_cfg = _packaged_alembic_config(db_url)

    expected_head_tables = {
        "users",
        "auth_tokens",
        "user_quotas",
        "provider_usage_daily",
        "sessions",
        "messages",
        "schema_versions",
        "prompt_registry",
        "audit_logs",
        "marketing_campaigns",
        "content_assets",
        "operation_checklists",
        "coverage_tasks",
        "coverage_findings",
        "access_policies",
        "alembic_version",
    }

    for _ in range(2):
        command.upgrade(alembic_cfg, "head")
        engine = create_engine(db_url)
        try:
            table_names = set(inspect(engine).get_table_names())
            assert expected_head_tables.issubset(table_names)
        finally:
            engine.dispose()

        command.downgrade(alembic_cfg, "base")
        engine = create_engine(db_url)
        try:
            table_names = set(inspect(engine).get_table_names())
            assert table_names in (set(), {"alembic_version"})
        finally:
            engine.dispose()
