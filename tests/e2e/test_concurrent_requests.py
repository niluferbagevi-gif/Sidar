"""E2E concurrency coverage for request-like database pressure."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.db import Database


@pytest.mark.asyncio
async def test_concurrent_session_writes_do_not_exhaust_single_sqlite_pool(tmp_path) -> None:
    cfg = SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{(tmp_path / 'concurrent.db').as_posix()}",
        BASE_DIR=str(tmp_path),
        DB_POOL_SIZE=1,
        DB_POOL_MIN_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET_KEY="test-secret-key-for-ci-testing-only!",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=1,
    )
    db = Database(cfg)
    await db.connect()
    await db.init_schema()
    user = await db.create_user("concurrent_user")

    async def _write_turn(index: int) -> str:
        session = await db.create_session(user.id, f"Turn {index}")
        await db.add_message(session.id, "user", f"prompt-{index}")
        await db.add_message(session.id, "assistant", f"reply-{index}")
        messages = await db.get_session_messages(session.id)
        assert [message.content for message in messages] == [f"prompt-{index}", f"reply-{index}"]
        return session.id

    try:
        session_ids = await asyncio.wait_for(
            asyncio.gather(*[_write_turn(index) for index in range(24)]),
            timeout=5,
        )
        sessions = await db.list_sessions(user.id)
    finally:
        await db.close()

    assert len(set(session_ids)) == 24
    assert len(sessions) == 24
