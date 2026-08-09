"""E2E coverage for PostgreSQL outage degraded SQLite fallback and recovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.db import Database


class _RecoveredPool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_postgres_down_uses_sqlite_degraded_mode_then_reconnects_to_recovered_pool(
    tmp_path,
) -> None:
    fallback_url = f"sqlite+aiosqlite:///{(tmp_path / 'degraded.db').as_posix()}"
    cfg = SimpleNamespace(
        DATABASE_URL="postgresql+asyncpg://sidar:secret@127.0.0.1:5432/sidar",
        DB_DEGRADED_SQLITE_URL=fallback_url,
        DB_DEGRADED_MODE_ON_POSTGRES_FAILURE=True,
        BASE_DIR=str(tmp_path),
        DB_POOL_SIZE=2,
        DB_POOL_MIN_SIZE=1,
        DB_STATEMENT_CACHE_SIZE=0,
        DB_MAX_CACHED_STATEMENT_LIFETIME=0,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        SIDAR_AUTO_MIGRATE=True,
        JWT_SECRET_KEY="test-secret-key-for-ci-testing-only!",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=1,
    )

    async def _postgres_down_factory(**_kwargs):
        raise TimeoutError("postgres down")

    degraded = Database(cfg, pg_pool_factory=_postgres_down_factory)
    await degraded.connect()
    await degraded.init_schema()
    user = await degraded.create_user("failover_user")
    session = await degraded.create_session(user.id, "fallback session")
    await degraded.add_message(session.id, "user", "stored during outage")

    assert degraded.degraded_mode is True
    assert degraded.database_url == fallback_url
    assert cfg.DATABASE_URL == fallback_url
    assert (await degraded.get_session_messages(session.id))[0].content == "stored during outage"
    await degraded.close()

    recovered_pool = _RecoveredPool()

    async def _postgres_recovered_factory(**kwargs):
        assert kwargs["max_size"] == 2
        return recovered_pool

    cfg.DATABASE_URL = "postgresql+asyncpg://sidar:secret@127.0.0.1:5432/sidar"
    recovered = Database(cfg, pg_pool_factory=_postgres_recovered_factory)
    await recovered.connect()
    await recovered.close()

    assert recovered.degraded_mode is False
    assert recovered._backend == "postgresql"
    assert recovered_pool.closed is True
