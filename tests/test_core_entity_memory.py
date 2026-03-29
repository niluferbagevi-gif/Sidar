"""
core/entity_memory.py için birim testleri.
EntityMemory (disabled path + SQLite integration) ve
WELL_KNOWN_KEYS sabitini kapsar.
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import patch


def _get_em():
    if "core.entity_memory" in sys.modules:
        del sys.modules["core.entity_memory"]
    import core.entity_memory as em
    em._instance = None
    return em


def _run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════
# WELL_KNOWN_KEYS sabiti
# ══════════════════════════════════════════════════════════════

class TestWellKnownKeys:
    def test_coding_style_in_keys(self):
        em = _get_em()
        assert "coding_style" in em.WELL_KNOWN_KEYS

    def test_preferred_language_in_keys(self):
        em = _get_em()
        assert "preferred_language" in em.WELL_KNOWN_KEYS

    def test_is_frozenset(self):
        em = _get_em()
        assert isinstance(em.WELL_KNOWN_KEYS, frozenset)


# ══════════════════════════════════════════════════════════════
# EntityMemory — init
# ══════════════════════════════════════════════════════════════

class TestEntityMemoryInit:
    def test_default_ttl(self):
        em = _get_em()
        instance = em.EntityMemory()
        assert instance.ttl_days == 90

    def test_custom_ttl(self):
        em = _get_em()
        instance = em.EntityMemory(ttl_days=30)
        assert instance.ttl_days == 30

    def test_default_max_per_user(self):
        em = _get_em()
        instance = em.EntityMemory()
        assert instance.max_per_user == 100

    def test_custom_max_per_user(self):
        em = _get_em()
        instance = em.EntityMemory(max_per_user=50)
        assert instance.max_per_user == 50

    def test_enabled_default_true(self):
        em = _get_em()
        instance = em.EntityMemory()
        assert instance.enabled is True

    def test_config_overrides_ttl(self):
        em = _get_em()

        class _Cfg:
            ENTITY_MEMORY_TTL_DAYS = 7
            ENTITY_MEMORY_MAX_PER_USER = 10
            ENABLE_ENTITY_MEMORY = True

        instance = em.EntityMemory(config=_Cfg())
        assert instance.ttl_days == 7
        assert instance.max_per_user == 10

    def test_explicit_ttl_overrides_config(self):
        em = _get_em()

        class _Cfg:
            ENTITY_MEMORY_TTL_DAYS = 7
            ENTITY_MEMORY_MAX_PER_USER = 10
            ENABLE_ENTITY_MEMORY = True

        instance = em.EntityMemory(config=_Cfg(), ttl_days=99)
        assert instance.ttl_days == 99

    def test_disabled_via_config(self):
        em = _get_em()

        class _Cfg:
            ENTITY_MEMORY_TTL_DAYS = 90
            ENTITY_MEMORY_MAX_PER_USER = 100
            ENABLE_ENTITY_MEMORY = False

        instance = em.EntityMemory(config=_Cfg())
        assert instance.enabled is False


# ══════════════════════════════════════════════════════════════
# EntityMemory — disabled path (no DB calls)
# ══════════════════════════════════════════════════════════════

class TestEntityMemoryDisabled:
    def setup_method(self):
        em = _get_em()

        class _Cfg:
            ENTITY_MEMORY_TTL_DAYS = 90
            ENTITY_MEMORY_MAX_PER_USER = 100
            ENABLE_ENTITY_MEMORY = False

        self.em_instance = em.EntityMemory(config=_Cfg())

    def test_initialize_noop_when_disabled(self):
        _run(self.em_instance.initialize())
        assert self.em_instance._engine is None

    def test_upsert_returns_false_when_disabled(self):
        result = _run(self.em_instance.upsert("u1", "key", "val"))
        assert result is False

    def test_get_returns_none_when_disabled(self):
        result = _run(self.em_instance.get("u1", "key"))
        assert result is None

    def test_get_profile_returns_empty_when_disabled(self):
        result = _run(self.em_instance.get_profile("u1"))
        assert result == {}

    def test_list_users_returns_empty_when_disabled(self):
        result = _run(self.em_instance.list_users())
        assert result == []

    def test_delete_returns_false_when_disabled(self):
        result = _run(self.em_instance.delete("u1", "key"))
        assert result is False

    def test_delete_user_returns_zero_when_disabled(self):
        result = _run(self.em_instance.delete_user("u1"))
        assert result == 0

    def test_purge_expired_returns_zero_when_disabled(self):
        result = _run(self.em_instance.purge_expired())
        assert result == 0

    def test_close_noop_when_no_engine(self):
        _run(self.em_instance.close())  # should not raise


# ══════════════════════════════════════════════════════════════
# EntityMemory — no engine path (enabled=True but no init)
# ══════════════════════════════════════════════════════════════

class TestEntityMemoryNoEngine:
    def setup_method(self):
        em = _get_em()
        self.em_instance = em.EntityMemory()
        # enabled=True but _engine=None (not initialized)

    def test_upsert_returns_false_without_engine(self):
        result = _run(self.em_instance.upsert("u1", "key", "val"))
        assert result is False

    def test_get_returns_none_without_engine(self):
        result = _run(self.em_instance.get("u1", "key"))
        assert result is None

    def test_get_profile_returns_empty_without_engine(self):
        result = _run(self.em_instance.get_profile("u1"))
        assert result == {}

    def test_purge_expired_returns_zero_when_ttl_zero(self):
        em = _get_em()
        instance = em.EntityMemory(ttl_days=0)
        result = _run(instance.purge_expired())
        assert result == 0


class TestGetEntityMemorySingleton:
    def setup_method(self):
        em = _get_em()
        em._instance = None
        self.em = em

    def test_uses_given_config_and_returns_singleton(self):
        cfg = types.SimpleNamespace(
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            ENTITY_MEMORY_TTL_DAYS=5,
            ENTITY_MEMORY_MAX_PER_USER=12,
            ENABLE_ENTITY_MEMORY=True,
        )
        first = self.em.get_entity_memory(config=cfg)
        second = self.em.get_entity_memory(config=cfg)
        assert first is second
        assert first._db_url == "sqlite+aiosqlite:///:memory:"
        assert first.ttl_days == 5
        assert first.max_per_user == 12

    def test_without_config_uses_config_module_default(self):
        fake_config_module = types.ModuleType("config")

        class _Cfg:
            DATABASE_URL = "sqlite+aiosqlite:///tmp/sidar-test.db"
            ENTITY_MEMORY_TTL_DAYS = 90
            ENTITY_MEMORY_MAX_PER_USER = 100
            ENABLE_ENTITY_MEMORY = True

        fake_config_module.Config = _Cfg

        with patch.dict(sys.modules, {"config": fake_config_module}):
            instance = self.em.get_entity_memory()

        assert instance._db_url == "sqlite+aiosqlite:///tmp/sidar-test.db"


# ══════════════════════════════════════════════════════════════
# EntityMemory — SQLite integration (if sqlalchemy available)
# ══════════════════════════════════════════════════════════════

try:
    import sqlalchemy  # noqa: F401
    import aiosqlite  # noqa: F401
    _SA_AVAILABLE = True
except ImportError:
    _SA_AVAILABLE = False

import pytest


@pytest.mark.skipif(not _SA_AVAILABLE, reason="sqlalchemy+aiosqlite required")
class TestEntityMemorySQLite:
    def _make(self, **kwargs):
        em = _get_em()
        return em.EntityMemory(
            database_url="sqlite+aiosqlite:///:memory:",
            **kwargs,
        )

    def test_initialize_creates_table(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            assert instance._engine is not None
            await instance.close()
        asyncio.run(_test())

    def test_upsert_and_get(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            ok = await instance.upsert("u1", "coding_style", "functional")
            assert ok is True
            val = await instance.get("u1", "coding_style")
            assert val == "functional"
            await instance.close()
        asyncio.run(_test())

    def test_upsert_updates_existing(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            await instance.upsert("u1", "lang", "Python")
            await instance.upsert("u1", "lang", "TypeScript")
            val = await instance.get("u1", "lang")
            assert val == "TypeScript"
            await instance.close()
        asyncio.run(_test())

    def test_upsert_empty_user_id_returns_false(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            ok = await instance.upsert("", "key", "val")
            assert ok is False
            await instance.close()
        asyncio.run(_test())

    def test_upsert_empty_key_returns_false(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            ok = await instance.upsert("u1", "", "val")
            assert ok is False
            await instance.close()
        asyncio.run(_test())

    def test_get_nonexistent_returns_none(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            val = await instance.get("u1", "nonexistent")
            assert val is None
            await instance.close()
        asyncio.run(_test())

    def test_get_profile_returns_all_keys(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            await instance.upsert("u1", "lang", "Python")
            await instance.upsert("u1", "style", "OOP")
            profile = await instance.get_profile("u1")
            assert profile["lang"] == "Python"
            assert profile["style"] == "OOP"
            await instance.close()
        asyncio.run(_test())

    def test_list_users(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            await instance.upsert("alice", "k", "v")
            await instance.upsert("bob", "k", "v")
            users = await instance.list_users()
            assert "alice" in users
            assert "bob" in users
            await instance.close()
        asyncio.run(_test())

    def test_delete_removes_key(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            await instance.upsert("u1", "lang", "Python")
            ok = await instance.delete("u1", "lang")
            assert ok is True
            val = await instance.get("u1", "lang")
            assert val is None
            await instance.close()
        asyncio.run(_test())

    def test_delete_user_removes_all(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            await instance.upsert("u1", "lang", "Python")
            await instance.upsert("u1", "style", "OOP")
            count = await instance.delete_user("u1")
            assert count == 2
            await instance.close()
        asyncio.run(_test())

    def test_purge_expired_removes_old_records(self):
        import sqlalchemy as sa_mod
        async def _test():
            instance = self._make(ttl_days=1)
            await instance.initialize()
            await instance.upsert("u1", "old", "value")
            async with instance._engine.begin() as conn:
                await conn.execute(
                    sa_mod.text("UPDATE entity_memory SET updated_at = 0 WHERE user_id = 'u1'")
                )
            removed = await instance.purge_expired()
            assert removed >= 1
            await instance.close()
        asyncio.run(_test())

    def test_close_disposes_engine(self):
        async def _test():
            instance = self._make()
            await instance.initialize()
            await instance.close()
            assert instance._engine is None
        asyncio.run(_test())
