from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("jwt")

from core.db import Database


@pytest.fixture
async def db(tmp_path: Path):
    cfg = SimpleNamespace(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        BASE_DIR=tmp_path,
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
    )
    database = Database(cfg=cfg)
    database._sqlite_path = Path(":memory:")
    await database.connect()
    await database.init_schema()
    try:
        yield database
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_db_crud_sessions_and_messages(db: Database):
    user = await db.create_user("alice", password="secret123")
    session = await db.create_session(user.id, "İlk Oturum")

    await db.add_message(session.id, "user", "Merhaba", tokens_used=3)
    await db.add_message(session.id, "assistant", "Selam", tokens_used=2)

    sessions = await db.list_sessions(user.id)
    assert len(sessions) == 1
    assert sessions[0].title == "İlk Oturum"

    loaded = await db.load_session(session.id, user.id)
    assert loaded is not None

    messages = await db.get_session_messages(session.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "Merhaba"


@pytest.mark.asyncio
async def test_db_rolls_back_after_sqlite_error(db: Database):
    def _failing_txn() -> None:
        assert db._sqlite_conn is not None
        now = "2026-01-01T00:00:00+00:00"
        db._sqlite_conn.execute(
            "INSERT INTO users (id, username, role, tenant_id, created_at) VALUES (?, ?, ?, ?, ?)",
            ("u1", "temp_user", "user", "default", now),
        )
        # UNIQUE ihlali ile hata üret
        db._sqlite_conn.execute(
            "INSERT INTO users (id, username, role, tenant_id, created_at) VALUES (?, ?, ?, ?, ?)",
            ("u2", "temp_user", "user", "default", now),
        )

    with pytest.raises(Exception):
        await db._run_sqlite_op(_failing_txn)

    # Rollback sonrası bağlantı kullanılabilir ve önceki satır kalıcı olmamalı.
    users = await db.list_users_with_quotas()
    usernames = {row["username"] for row in users}
    assert "temp_user" not in usernames

    created = await db.create_user("after_rollback", password="safe-password")
    assert created.username == "after_rollback"
