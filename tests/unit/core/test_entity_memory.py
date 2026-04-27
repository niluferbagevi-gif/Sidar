import asyncio
import types
from pathlib import Path
from typing import Any

import pytest

from core import entity_memory as em_module
from core.entity_memory import WELL_KNOWN_KEYS, EntityMemory, get_entity_memory

requires_sqlalchemy = pytest.mark.skipif(
    not em_module._SA_AVAILABLE, reason="sqlalchemy async extras not available in runtime"
)


@pytest.fixture
def sqlite_db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'entity_memory_test.db'}"


@pytest.fixture(autouse=True)
def reset_singleton():
    em_module._instance = None
    yield
    em_module._instance = None


@requires_sqlalchemy
def test_initialize_and_crud_happy_path(sqlite_db_url: str):
    async def scenario():
        em = EntityMemory(database_url=sqlite_db_url)
        await em.initialize()

        assert await em.upsert("u1", "coding_style", "functional", {"source": "chat"}) is True
        assert await em.get("u1", "coding_style") == "functional"

        # upsert should update existing key
        assert await em.upsert("u1", "coding_style", "oop") is True
        assert await em.get("u1", "coding_style") == "oop"

        # profile and users list
        assert await em.upsert("u1", "preferred_language", "Python") is True
        profile = await em.get_profile("u1")
        assert profile["coding_style"] == "oop"
        assert profile["preferred_language"] == "Python"
        assert await em.list_users() == ["u1"]

        # delete single key and whole user
        assert await em.delete("u1", "coding_style") is True
        assert await em.get("u1", "coding_style") is None
        deleted_rows = await em.delete_user("u1")
        assert deleted_rows == 1
        assert await em.get_profile("u1") == {}

        await em.close()

    asyncio.run(scenario())


def test_validation_and_disabled_behavior(sqlite_db_url: str):
    async def scenario():
        disabled = EntityMemory(
            database_url=sqlite_db_url, config=types.SimpleNamespace(ENABLE_ENTITY_MEMORY=False)
        )

        # disabled instance should no-op
        await disabled.initialize()
        assert disabled.enabled is False
        assert await disabled.upsert("u", "k", "v") is False
        assert await disabled.get("u", "k") is None
        assert await disabled.get_profile("u") == {}
        assert await disabled.list_users() == []
        assert await disabled.delete("u", "k") is False
        assert await disabled.delete_user("u") == 0
        assert await disabled.purge_expired() == 0

        # enabled but invalid inputs should be rejected
        em = EntityMemory(database_url=sqlite_db_url)
        await em.initialize()
        assert await em.upsert("", "k", "v") is False
        assert await em.upsert("u", "", "v") is False
        await em.close()

    asyncio.run(scenario())


@requires_sqlalchemy
def test_eviction_when_max_per_user_reached(sqlite_db_url: str):
    async def scenario():
        em = EntityMemory(database_url=sqlite_db_url, max_per_user=2)
        await em.initialize()

        assert await em.upsert("u1", "k1", "v1") is True
        assert await em.upsert("u1", "k2", "v2") is True
        # inserting third key should evict oldest updated_at (k1)
        assert await em.upsert("u1", "k3", "v3") is True

        profile = await em.get_profile("u1")
        assert set(profile.keys()) == {"k2", "k3"}
        assert await em.get("u1", "k1") is None

        await em.close()

    asyncio.run(scenario())


@requires_sqlalchemy
def test_purge_expired_and_ttl_zero(sqlite_db_url: str):
    async def scenario():
        em = EntityMemory(database_url=sqlite_db_url, ttl_days=1)
        await em.initialize()
        assert await em.upsert("u1", "k1", "v1") is True
        assert await em.upsert("u1", "k2", "v2") is True

        # force one row to be old
        async with em._engine.begin() as conn:
            await conn.execute(
                em_module.sql_text(
                    "UPDATE entity_memory SET updated_at = updated_at - 3 * 86400 WHERE key = 'k1'"
                )
            )

        removed = await em.purge_expired()
        assert removed == 1
        assert await em.get("u1", "k1") is None
        assert await em.get("u1", "k2") == "v2"
        await em.close()

        # ttl_days <= 0 means purge disabled
        em_no_ttl = EntityMemory(database_url=sqlite_db_url, ttl_days=0)
        await em_no_ttl.initialize()
        assert await em_no_ttl.upsert("u2", "k", "v") is True
        assert await em_no_ttl.purge_expired() == 0
        await em_no_ttl.close()

    asyncio.run(scenario())


def test_well_known_keys_and_singleton_creation(monkeypatch):
    assert "coding_style" in WELL_KNOWN_KEYS
    assert "preferred_language" in WELL_KNOWN_KEYS

    fake_cfg = types.SimpleNamespace(DATABASE_URL="sqlite+aiosqlite:///tmp/sidar_entity.db")
    # config module is imported lazily in get_entity_memory()
    monkeypatch.setattr("config.Config", lambda: fake_cfg)

    first = get_entity_memory()
    second = get_entity_memory()

    assert isinstance(first, EntityMemory)
    assert first is second
    assert first._db_url == fake_cfg.DATABASE_URL


def test_initialize_when_sqlalchemy_unavailable_and_close_without_engine(
    monkeypatch, sqlite_db_url: str
):
    async def scenario():
        monkeypatch.setattr(em_module, "_SA_AVAILABLE", False)
        em = EntityMemory(database_url=sqlite_db_url)
        await em.initialize()
        assert em._engine is None
        await em.close()  # no-op branch when engine is missing

    asyncio.run(scenario())


@requires_sqlalchemy
def test_purge_expired_returns_zero_when_nothing_to_delete(sqlite_db_url: str):
    async def scenario():
        em = EntityMemory(database_url=sqlite_db_url, ttl_days=30)
        await em.initialize()
        assert await em.upsert("u1", "k1", "v1") is True
        removed = await em.purge_expired()
        assert removed == 0
        await em.close()

    asyncio.run(scenario())


@requires_sqlalchemy
def test_entity_memory_ttl_and_corrupted_record_recovery(
    sqlite_db_url: str,
    fake_redis: Any,
    frozen_time,
):
    async def scenario():
        # Ortak fake_redis fixture'ının hazır olduğunu doğrula (dış bağımlılık izolasyonu).
        assert await fake_redis.ping() is True

        em = EntityMemory(database_url=sqlite_db_url, ttl_days=1)
        await em.initialize()
        assert await em.upsert("u-ttl", "coding_style", "functional") is True

        # metadata alanını boz; okuma patlamadan kurtarılmalı.
        async with em._engine.begin() as conn:
            await conn.execute(
                em_module.sql_text(
                    "UPDATE entity_memory SET metadata = '{bad-json' "
                    "WHERE user_id = 'u-ttl' AND key = 'coding_style'"
                )
            )

        profile = await em.get_profile("u-ttl")
        assert profile["coding_style"] == "functional"

        # frozen_time ile 2 gün ileri sarıp TTL temizliği doğrula.
        frozen_time.move_to("2026-04-03 12:00:00")
        removed = await em.purge_expired()
        assert removed == 1
        assert await em.get("u-ttl", "coding_style") is None
        await em.close()

    asyncio.run(scenario())


@requires_sqlalchemy
def test_get_survives_corrupted_metadata_row(sqlite_db_url: str):
    async def scenario():
        em = EntityMemory(database_url=sqlite_db_url)
        await em.initialize()
        assert await em.upsert("u-corrupt", "preferred_language", "Python") is True

        async with em._engine.begin() as conn:
            await conn.execute(
                em_module.sql_text(
                    "UPDATE entity_memory SET metadata = 'not-json' "
                    "WHERE user_id = 'u-corrupt' AND key = 'preferred_language'"
                )
            )

        assert await em.get("u-corrupt", "preferred_language") == "Python"
        await em.close()

    asyncio.run(scenario())
