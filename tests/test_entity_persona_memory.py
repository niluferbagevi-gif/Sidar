"""Testler: Entity/Persona Memory (Özellik 6)"""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import MagicMock


def _run(coro):
    """Async coroutine'i senkron olarak çalıştır."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── EntityMemory birim testleri ────────────────────────────────────────────

from core.entity_memory import EntityMemory, WELL_KNOWN_KEYS, get_entity_memory


class TestEntityMemoryDisabled:
    """ENABLE_ENTITY_MEMORY=False olduğunda tüm işlemler sessizce NOP olmalı."""

    def setup_method(self):
        cfg = MagicMock()
        cfg.ENABLE_ENTITY_MEMORY = False
        cfg.ENTITY_MEMORY_TTL_DAYS = 90
        cfg.ENTITY_MEMORY_MAX_PER_USER = 100
        self.em = EntityMemory(config=cfg)

    def test_not_initialized(self):
        assert self.em._engine is None

    def test_initialize_noop(self):
        _run(self.em.initialize())
        assert self.em._engine is None

    def test_upsert_returns_false(self):
        result = _run(self.em.upsert("u1", "coding_style", "functional"))
        assert result is False

    def test_get_returns_none(self):
        result = _run(self.em.get("u1", "coding_style"))
        assert result is None

    def test_get_profile_returns_empty(self):
        result = _run(self.em.get_profile("u1"))
        assert result == {}

    def test_list_users_returns_empty(self):
        result = _run(self.em.list_users())
        assert result == []

    def test_delete_returns_false(self):
        result = _run(self.em.delete("u1", "coding_style"))
        assert result is False

    def test_delete_user_returns_zero(self):
        result = _run(self.em.delete_user("u1"))
        assert result == 0

    def test_purge_expired_returns_zero(self):
        result = _run(self.em.purge_expired())
        assert result == 0


def _make_sqlite_em(tmp_path, max_per_user=100):
    db_path = tmp_path / "test_entity.db"
    cfg = MagicMock()
    cfg.ENABLE_ENTITY_MEMORY = True
    cfg.ENTITY_MEMORY_TTL_DAYS = 30
    cfg.ENTITY_MEMORY_MAX_PER_USER = max_per_user
    em = EntityMemory(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        config=cfg,
    )
    return em


def _try_init(em):
    """Başlatmayı dene; sqlalchemy/aiosqlite yoksa False döner (skip sinyali)."""
    try:
        _run(em.initialize())
    except (ImportError, Exception) as e:
        if "aiosqlite" in str(e) or "sqlalchemy" in str(e) or "No module" in str(e):
            return False
        raise
    # Engine oluştu mu kontrol et (kütüphane eksikse engine=None kalır)
    return em._engine is not None


class TestEntityMemoryWithSQLite:
    """sqlite+aiosqlite ile tam entegrasyon testi."""

    def test_initialize_creates_table(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        assert em._engine is not None
        _run(em.close())

    def test_upsert_and_get_roundtrip(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(em.upsert("user1", "coding_style", "functional"))
        result = _run(em.get("user1", "coding_style"))
        assert result == "functional"
        _run(em.close())

    def test_upsert_updates_existing(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(em.upsert("user1", "verbosity", "concise"))
        _run(em.upsert("user1", "verbosity", "detailed"))
        result = _run(em.get("user1", "verbosity"))
        assert result == "detailed"
        _run(em.close())

    def test_get_returns_none_for_missing_key(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        result = _run(em.get("user1", "nonexistent_key"))
        assert result is None
        _run(em.close())

    def test_get_profile_returns_all_keys(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(em.upsert("user2", "coding_style", "OOP"))
        _run(em.upsert("user2", "preferred_language", "Python"))
        profile = _run(em.get_profile("user2"))
        assert profile.get("coding_style") == "OOP"
        assert profile.get("preferred_language") == "Python"
        _run(em.close())

    def test_get_profile_isolates_users(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(em.upsert("alice", "coding_style", "functional"))
        _run(em.upsert("bob", "coding_style", "OOP"))
        alice_profile = _run(em.get_profile("alice"))
        bob_profile = _run(em.get_profile("bob"))
        assert alice_profile.get("coding_style") == "functional"
        assert bob_profile.get("coding_style") == "OOP"
        _run(em.close())

    def test_delete_removes_key(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(em.upsert("user3", "verbosity", "medium"))
        deleted = _run(em.delete("user3", "verbosity"))
        assert deleted is True
        result = _run(em.get("user3", "verbosity"))
        assert result is None
        _run(em.close())

    def test_delete_user_removes_all(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(em.upsert("user4", "coding_style", "OOP"))
        _run(em.upsert("user4", "verbosity", "detailed"))
        count = _run(em.delete_user("user4"))
        assert count == 2
        profile = _run(em.get_profile("user4"))
        assert profile == {}
        _run(em.close())

    def test_list_users(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(em.upsert("alice", "coding_style", "functional"))
        _run(em.upsert("bob", "verbosity", "concise"))
        users = _run(em.list_users())
        assert "alice" in users
        assert "bob" in users
        _run(em.close())

    def test_max_per_user_eviction(self, tmp_path):
        em = _make_sqlite_em(tmp_path, max_per_user=5)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        keys = [f"key_{i}" for i in range(6)]
        for k in keys:
            _run(em.upsert("eviction_user", k, f"val_{k}"))
        profile = _run(em.get_profile("eviction_user"))
        assert len(profile) <= 5, f"Eviction çalışmadı: {len(profile)} anahtar var"
        _run(em.close())

    def test_purge_expired_removes_old(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        try:
            from sqlalchemy import text as sql_text
        except ImportError:
            pytest.skip("sqlalchemy kurulu değil")
        import time
        old_time = time.time() - (100 * 86400)  # 100 gün önce
        async def _insert():
            async with em._engine.begin() as conn:
                await conn.execute(
                    sql_text(
                        "INSERT INTO entity_memory (user_id, key, value, metadata, created_at, updated_at)"
                        " VALUES ('old_user', 'old_key', 'old_val', '{}', :t, :t)"
                    ),
                    {"t": old_time},
                )
        _run(_insert())
        removed = _run(em.purge_expired())
        assert removed >= 1
        _run(em.close())

    def test_purge_no_op_when_ttl_zero(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        em.ttl_days = 0
        result = _run(em.purge_expired())
        assert result == 0
        _run(em.close())

    def test_close_disposes_engine(self, tmp_path):
        em = _make_sqlite_em(tmp_path)
        if not _try_init(em):
            pytest.skip("aiosqlite/sqlalchemy kurulu değil")
        _run(em.close())
        assert em._engine is None


# ─── Well-known keys sabitleri ───────────────────────────────────────────────

class TestWellKnownKeys:
    def test_well_known_keys_is_frozenset(self):
        assert isinstance(WELL_KNOWN_KEYS, frozenset)

    def test_expected_keys_present(self):
        assert "coding_style" in WELL_KNOWN_KEYS
        assert "preferred_language" in WELL_KNOWN_KEYS
        assert "verbosity" in WELL_KNOWN_KEYS
        assert "framework_pref" in WELL_KNOWN_KEYS


# ─── Singleton get_entity_memory ────────────────────────────────────────────

def test_get_entity_memory_returns_instance():
    import core.entity_memory as em_mod
    original = em_mod._instance
    em_mod._instance = None
    try:
        instance = get_entity_memory()
        assert isinstance(instance, EntityMemory)
        instance2 = get_entity_memory()
        assert instance is instance2
    finally:
        em_mod._instance = original
