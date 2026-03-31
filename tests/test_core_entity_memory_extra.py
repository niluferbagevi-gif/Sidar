"""
Extra tests for core/entity_memory.py targeting missing coverage lines.

Missing lines targeted:
  25-26: sqlalchemy import block
  105-111: initialize() body when enabled + SA available
  127-165: upsert() full logic including eviction
  175-185: get() body
  191-200: get_profile() body
  206-210: list_users() body
  220-227: delete() body
  233-238: delete_user() body
  248-257: purge_expired() body
  262-263: close() body

Uses sys.modules stubbing for ALL heavy deps.
Uses asyncio.run() for async tests (NO @pytest.mark.asyncio).
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Install stubs BEFORE importing entity_memory
# ---------------------------------------------------------------------------

def _install_stubs():
    """Stub all heavy deps so entity_memory can be imported cleanly."""

    # pydantic stub
    if "pydantic" not in sys.modules:
        pyd = types.ModuleType("pydantic")
        pyd.BaseModel = type("BaseModel", (), {})  # type: ignore[attr-defined]
        sys.modules["pydantic"] = pyd

    # redis stubs
    for mod_name in ("redis", "redis.asyncio", "redis.exceptions"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # chromadb stubs
    for mod_name in ("chromadb", "chromadb.utils", "chromadb.utils.embedding_functions"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # sqlalchemy stubs — we need to stub BEFORE the module-level try/except runs,
    # so we remove the cached entity_memory module and re-import with our mocks.
    # We'll handle sqlalchemy by injecting _SA_AVAILABLE manually after import.


_install_stubs()

# Remove cached module so we get a fresh import with stubs in place
for _k in list(sys.modules.keys()):
    if _k in ("core.entity_memory",):
        del sys.modules[_k]

import core.entity_memory as em_mod  # noqa: E402


def _fresh_entity_memory_module():
    """Return a freshly imported core.entity_memory module."""
    _install_stubs()
    sys.modules.pop("core.entity_memory", None)
    return importlib.import_module("core.entity_memory")


# ---------------------------------------------------------------------------
# Async DB mock helpers
# ---------------------------------------------------------------------------

def _make_mock_conn(scalar_value=0, fetchone_value=None, fetchall_value=None, rowcount=1):
    """Build a mock async connection context manager."""
    conn = MagicMock()

    # execute returns an awaitable result object
    result = MagicMock()
    result.scalar = MagicMock(return_value=scalar_value)
    result.fetchone = MagicMock(return_value=fetchone_value)
    result.fetchall = MagicMock(return_value=fetchall_value or [])
    result.rowcount = rowcount

    conn.execute = AsyncMock(return_value=result)
    return conn, result


def _make_mock_engine(scalar_value=0, fetchone_value=None, fetchall_value=None, rowcount=1):
    """Build a mock engine with begin() and connect() context managers."""
    engine = MagicMock()
    engine.dispose = AsyncMock()

    conn, result = _make_mock_conn(scalar_value, fetchone_value, fetchall_value, rowcount)

    async def _fake_begin():
        return conn

    async def _fake_connect():
        return conn

    # async context managers
    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=conn)
    begin_cm.__aexit__ = AsyncMock(return_value=False)

    connect_cm = MagicMock()
    connect_cm.__aenter__ = AsyncMock(return_value=conn)
    connect_cm.__aexit__ = AsyncMock(return_value=False)

    engine.begin = MagicMock(return_value=begin_cm)
    engine.connect = MagicMock(return_value=connect_cm)

    return engine, conn, result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeConfig:
    ENABLE_ENTITY_MEMORY = True
    ENTITY_MEMORY_TTL_DAYS = 30
    ENTITY_MEMORY_MAX_PER_USER = 50


class _FakeConfigDisabled:
    ENABLE_ENTITY_MEMORY = False
    ENTITY_MEMORY_TTL_DAYS = 30
    ENTITY_MEMORY_MAX_PER_USER = 50


# ===========================================================================
# TESTS
# ===========================================================================

# --- EntityMemory.__init__ ---

def test_init_defaults():
    """EntityMemory initialises with default values when no config given."""
    obj = em_mod.EntityMemory()
    assert obj._db_url == "sqlite+aiosqlite:///data/sidar.db"
    assert obj._engine is None
    assert obj.ttl_days == 90
    assert obj.max_per_user == 100
    assert obj.enabled is True


def test_init_with_config():
    """Config values override defaults."""
    obj = em_mod.EntityMemory(config=_FakeConfig())
    assert obj.ttl_days == 30
    assert obj.max_per_user == 50
    assert obj.enabled is True


def test_init_with_config_disabled():
    """ENABLE_ENTITY_MEMORY=False disables the instance."""
    obj = em_mod.EntityMemory(config=_FakeConfigDisabled())
    assert obj.enabled is False


def test_init_explicit_ttl_overrides_config():
    """Explicit ttl_days parameter wins over config."""
    obj = em_mod.EntityMemory(config=_FakeConfig(), ttl_days=7)
    assert obj.ttl_days == 7


def test_init_explicit_max_overrides_config():
    """Explicit max_per_user parameter wins over config."""
    obj = em_mod.EntityMemory(config=_FakeConfig(), max_per_user=5)
    assert obj.max_per_user == 5


def test_init_none_ttl_uses_config():
    """ttl_days=None falls back to config."""
    obj = em_mod.EntityMemory(config=_FakeConfig(), ttl_days=None)
    assert obj.ttl_days == 30


def test_init_none_max_uses_config():
    """max_per_user=None falls back to config."""
    obj = em_mod.EntityMemory(config=_FakeConfig(), max_per_user=None)
    assert obj.max_per_user == 50


# --- initialize() ---

def test_initialize_disabled_returns_early():
    """initialize() returns immediately when disabled."""
    obj = em_mod.EntityMemory(config=_FakeConfigDisabled())
    asyncio.run(obj.initialize())  # Should not raise
    assert obj._engine is None


def test_initialize_sa_not_available_returns_early():
    """initialize() logs warning and returns when SA not available."""
    obj = em_mod.EntityMemory()
    original = em_mod._SA_AVAILABLE
    try:
        em_mod._SA_AVAILABLE = False
        asyncio.run(obj.initialize())
        assert obj._engine is None
    finally:
        em_mod._SA_AVAILABLE = original


def test_initialize_creates_engine_and_tables():
    """initialize() creates engine and executes DDL statements (lines 105-111)."""
    obj = em_mod.EntityMemory()

    engine, conn, _ = _make_mock_engine()

    mock_create = MagicMock(return_value=engine)
    mock_sql_text = MagicMock(side_effect=lambda s: s)

    with patch.object(em_mod, "_SA_AVAILABLE", True), \
         patch.object(em_mod, "create_async_engine", mock_create, create=True), \
         patch.object(em_mod, "sql_text", mock_sql_text, create=True):
        asyncio.run(obj.initialize())

    assert obj._engine is engine
    # DDL has 2 statements (CREATE TABLE + CREATE INDEX)
    assert conn.execute.call_count >= 2


# --- upsert() ---

def test_upsert_disabled_returns_false():
    """upsert() returns False when disabled."""
    obj = em_mod.EntityMemory(config=_FakeConfigDisabled())
    result = asyncio.run(obj.upsert("u1", "key", "val"))
    assert result is False


def test_upsert_no_engine_returns_false():
    """upsert() returns False when engine not initialised."""
    obj = em_mod.EntityMemory()
    result = asyncio.run(obj.upsert("u1", "key", "val"))
    assert result is False


def test_upsert_empty_user_id_returns_false():
    """upsert() returns False for empty user_id."""
    obj = em_mod.EntityMemory()
    engine, _, _ = _make_mock_engine()
    obj._engine = engine
    result = asyncio.run(obj.upsert("", "key", "val"))
    assert result is False


def test_upsert_empty_key_returns_false():
    """upsert() returns False for empty key."""
    obj = em_mod.EntityMemory()
    engine, _, _ = _make_mock_engine()
    obj._engine = engine
    result = asyncio.run(obj.upsert("u1", "", "val"))
    assert result is False


def test_upsert_whitespace_stripped_empty_returns_false():
    """upsert() strips whitespace and returns False for blank strings."""
    obj = em_mod.EntityMemory()
    engine, _, _ = _make_mock_engine()
    obj._engine = engine
    result = asyncio.run(obj.upsert("   ", "  ", "val"))
    assert result is False


def test_upsert_normal_success():
    """upsert() executes insert/update SQL and returns True (lines 127-165)."""
    obj = em_mod.EntityMemory()
    # count < max_per_user (0 < 100)
    engine, conn, result = _make_mock_engine(scalar_value=0)
    obj._engine = engine
    with patch.object(em_mod, "_SA_AVAILABLE", True), \
         patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        ret = asyncio.run(obj.upsert("u1", "coding_style", "functional"))
    assert ret is True
    # Should execute: count query + upsert = 2 calls
    assert conn.execute.call_count == 2


def test_upsert_with_metadata():
    """upsert() accepts metadata dict and serialises it."""
    obj = em_mod.EntityMemory()
    engine, conn, _ = _make_mock_engine(scalar_value=0)
    obj._engine = engine
    with patch.object(em_mod, "_SA_AVAILABLE", True), \
         patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        ret = asyncio.run(obj.upsert("u1", "key", "val", metadata={"source": "test"}))
    assert ret is True


def test_upsert_triggers_eviction_when_at_max():
    """upsert() deletes oldest entry when count >= max_per_user (eviction lines 142-151)."""
    obj = em_mod.EntityMemory(max_per_user=2)
    # count = 2 >= max_per_user = 2 → triggers eviction
    engine, conn, _ = _make_mock_engine(scalar_value=2)
    obj._engine = engine
    with patch.object(em_mod, "_SA_AVAILABLE", True), \
         patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        ret = asyncio.run(obj.upsert("u1", "key", "val"))
    assert ret is True
    # count query + DELETE (eviction) + upsert = 3 calls
    assert conn.execute.call_count == 3


# --- get() ---

def test_get_disabled_returns_none():
    """get() returns None when disabled."""
    obj = em_mod.EntityMemory(config=_FakeConfigDisabled())
    result = asyncio.run(obj.get("u1", "key"))
    assert result is None


def test_get_no_engine_returns_none():
    """get() returns None when no engine."""
    obj = em_mod.EntityMemory()
    result = asyncio.run(obj.get("u1", "key"))
    assert result is None


def test_get_returns_value_when_found():
    """get() returns the string value from the DB row (lines 175-185)."""
    obj = em_mod.EntityMemory()
    engine, conn, _ = _make_mock_engine(fetchone_value=("functional",))
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.get("u1", "coding_style"))
    assert result == "functional"


def test_get_returns_none_when_not_found():
    """get() returns None when query returns no row."""
    obj = em_mod.EntityMemory()
    engine, conn, _ = _make_mock_engine(fetchone_value=None)
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.get("u1", "coding_style"))
    assert result is None


# --- get_profile() ---

def test_get_profile_disabled_returns_empty():
    """get_profile() returns {} when disabled."""
    obj = em_mod.EntityMemory(config=_FakeConfigDisabled())
    result = asyncio.run(obj.get_profile("u1"))
    assert result == {}


def test_get_profile_no_engine_returns_empty():
    """get_profile() returns {} when no engine."""
    obj = em_mod.EntityMemory()
    result = asyncio.run(obj.get_profile("u1"))
    assert result == {}


def test_get_profile_returns_dict(capsys):
    """get_profile() returns {key: value} dict from DB rows (lines 191-200)."""
    obj = em_mod.EntityMemory()
    rows = [("coding_style", "functional"), ("verbosity", "concise")]
    engine, conn, _ = _make_mock_engine(fetchall_value=rows)
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.get_profile("u1"))
    assert result == {"coding_style": "functional", "verbosity": "concise"}


def test_get_profile_empty_user_returns_empty_dict():
    """get_profile() returns {} for user with no entries."""
    obj = em_mod.EntityMemory()
    engine, conn, _ = _make_mock_engine(fetchall_value=[])
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.get_profile("nobody"))
    assert result == {}


# --- list_users() ---

def test_list_users_disabled_returns_empty():
    """list_users() returns [] when disabled."""
    obj = em_mod.EntityMemory(config=_FakeConfigDisabled())
    result = asyncio.run(obj.list_users())
    assert result == []


def test_list_users_no_engine_returns_empty():
    """list_users() returns [] when no engine."""
    obj = em_mod.EntityMemory()
    result = asyncio.run(obj.list_users())
    assert result == []


def test_list_users_returns_list(capsys):
    """list_users() returns list of user_ids (lines 206-210)."""
    obj = em_mod.EntityMemory()
    rows = [("alice",), ("bob",)]
    engine, conn, _ = _make_mock_engine(fetchall_value=rows)
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.list_users())
    assert result == ["alice", "bob"]


# --- delete() ---

def test_delete_disabled_returns_false():
    """delete() returns False when disabled."""
    obj = em_mod.EntityMemory(config=_FakeConfigDisabled())
    result = asyncio.run(obj.delete("u1", "key"))
    assert result is False


def test_delete_no_engine_returns_false():
    """delete() returns False when no engine."""
    obj = em_mod.EntityMemory()
    result = asyncio.run(obj.delete("u1", "key"))
    assert result is False


def test_delete_returns_true_when_row_deleted():
    """delete() returns True when a row was removed (lines 220-227)."""
    obj = em_mod.EntityMemory()
    engine, conn, _ = _make_mock_engine(rowcount=1)
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.delete("u1", "coding_style"))
    assert result is True


def test_delete_returns_false_when_no_row():
    """delete() returns False when no row matched."""
    obj = em_mod.EntityMemory()
    engine, conn, _ = _make_mock_engine(rowcount=0)
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.delete("u1", "missing_key"))
    assert result is False


# --- delete_user() ---

def test_delete_user_disabled_returns_zero():
    """delete_user() returns 0 when disabled."""
    obj = em_mod.EntityMemory(config=_FakeConfigDisabled())
    result = asyncio.run(obj.delete_user("u1"))
    assert result == 0


def test_delete_user_no_engine_returns_zero():
    """delete_user() returns 0 when no engine."""
    obj = em_mod.EntityMemory()
    result = asyncio.run(obj.delete_user("u1"))
    assert result == 0


def test_delete_user_returns_count(capsys):
    """delete_user() returns number of rows deleted (lines 233-238)."""
    obj = em_mod.EntityMemory()
    engine, conn, _ = _make_mock_engine(rowcount=3)
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.delete_user("u1"))
    assert result == 3


# --- purge_expired() ---

def test_purge_expired_disabled_returns_zero():
    """purge_expired() returns 0 when disabled."""
    obj = em_mod.EntityMemory(config=_FakeConfigDisabled())
    result = asyncio.run(obj.purge_expired())
    assert result == 0


def test_purge_expired_no_engine_returns_zero():
    """purge_expired() returns 0 when no engine."""
    obj = em_mod.EntityMemory()
    result = asyncio.run(obj.purge_expired())
    assert result == 0


def test_purge_expired_ttl_zero_returns_zero():
    """purge_expired() returns 0 when ttl_days=0 (disabled TTL)."""
    obj = em_mod.EntityMemory(ttl_days=0)
    engine, conn, _ = _make_mock_engine(rowcount=5)
    obj._engine = engine
    result = asyncio.run(obj.purge_expired())
    assert result == 0


def test_purge_expired_deletes_old_rows():
    """purge_expired() executes DELETE and returns rowcount (lines 248-257)."""
    obj = em_mod.EntityMemory(ttl_days=30)
    engine, conn, _ = _make_mock_engine(rowcount=4)
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.purge_expired())
    assert result == 4
    conn.execute.assert_called_once()


def test_purge_expired_returns_zero_when_nothing_deleted():
    """purge_expired() returns 0 when no rows are expired."""
    obj = em_mod.EntityMemory(ttl_days=30)
    engine, conn, _ = _make_mock_engine(rowcount=0)
    obj._engine = engine
    with patch.object(em_mod, "sql_text", MagicMock(side_effect=lambda s: s), create=True):
        result = asyncio.run(obj.purge_expired())
    assert result == 0


# --- close() ---

def test_close_disposes_engine():
    """close() calls dispose() on the engine and sets it to None (lines 262-263)."""
    obj = em_mod.EntityMemory()
    engine, _, _ = _make_mock_engine()
    obj._engine = engine
    asyncio.run(obj.close())
    engine.dispose.assert_called_once()
    assert obj._engine is None


def test_close_no_engine_is_noop():
    """close() is a no-op when engine is None."""
    obj = em_mod.EntityMemory()
    asyncio.run(obj.close())  # Should not raise
    assert obj._engine is None


# --- WELL_KNOWN_KEYS ---

def test_well_known_keys_contains_expected():
    """WELL_KNOWN_KEYS contains expected persona keys."""
    assert "coding_style" in em_mod.WELL_KNOWN_KEYS
    assert "preferred_language" in em_mod.WELL_KNOWN_KEYS
    assert "verbosity" in em_mod.WELL_KNOWN_KEYS


# --- get_entity_memory() singleton ---

def test_get_entity_memory_returns_instance():
    """get_entity_memory() returns an EntityMemory instance (uses singleton)."""
    class _Cfg:
        DATABASE_URL = "sqlite+aiosqlite:///data/test.db"
        ENABLE_ENTITY_MEMORY = True
        ENTITY_MEMORY_TTL_DAYS = 90
        ENTITY_MEMORY_MAX_PER_USER = 100

    local_em = _fresh_entity_memory_module()
    old_instance = local_em._instance
    try:
        local_em._instance = None
        instance = local_em.get_entity_memory(config=_Cfg())
        assert isinstance(instance, local_em.EntityMemory)
    finally:
        local_em._instance = old_instance


def test_get_entity_memory_reuses_singleton():
    """get_entity_memory() returns the same instance on repeated calls."""
    local_em = _fresh_entity_memory_module()
    old_instance = local_em._instance
    try:
        sentinel = local_em.EntityMemory()
        local_em._instance = sentinel
        result = local_em.get_entity_memory()
        assert result is sentinel
    finally:
        local_em._instance = old_instance
