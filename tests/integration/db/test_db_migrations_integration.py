import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from core.db import Database

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_alembic_migrations_up_and_down(tmp_path, monkeypatch):
    """Run alembic migrations end-to-end on a temporary SQLite database."""
    db_path = (tmp_path / "test_migration.db").resolve()
    db_url = f"sqlite:////{db_path.as_posix().lstrip('/')}"
    async_db_url = db_url.replace("sqlite://", "sqlite+aiosqlite://")

    monkeypatch.setenv("DATABASE_URL", async_db_url)

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", async_db_url)
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))

    command.upgrade(alembic_cfg, "head")
    # Driver bağlantısını kesinleştirip dosya oluşturmayı fiziksel olarak tetikle.
    bootstrap_engine = create_engine(db_url)
    try:
        with bootstrap_engine.begin() as conn:
            conn.exec_driver_sql("SELECT 1")
    finally:
        bootstrap_engine.dispose()
    assert db_path.exists(), "SQLite database file should be created after upgrade."

    engine = create_engine(db_url)
    try:
        upgraded_tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "alembic_version" in upgraded_tables
    assert len(upgraded_tables) > 1, "Expected schema tables to exist after upgrade."

    command.downgrade(alembic_cfg, "base")

    downgraded_engine = create_engine(db_url)
    try:
        downgraded_tables = set(inspect(downgraded_engine).get_table_names())
    finally:
        downgraded_engine.dispose()

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
