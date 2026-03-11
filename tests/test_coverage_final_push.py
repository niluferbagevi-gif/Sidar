"""
Final coverage push — hedef: %95 barajını aşmak.

Bu dosya şu alanlardaki eksik satırları kapatır:
  - core/db.py           : sqlite:/// prefix, relative path, double-connect guards, load_session without user_id
  - managers/system_health.py : render_llm_metrics_prometheus with by_provider and by_user
  - core/memory.py       : elif DATABASE_URL endswith data/sidar.db, run_sync error, _safe_ts exception, __del__ exception
"""
import asyncio
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# core/db.py — eksik satırlar: 113-114, 118-119, 126, 131, 472
# ─────────────────────────────────────────────────────────────────────────────

class _SimpleCfg:
    def __init__(self, url: str, base_dir=None):
        self.DATABASE_URL = url
        self.DB_POOL_SIZE = 1
        self.DB_SCHEMA_VERSION_TABLE = "schema_versions"
        self.DB_SCHEMA_TARGET_VERSION = 1
        if base_dir is not None:
            self.BASE_DIR = base_dir


def test_db_sqlite_plain_prefix_is_accepted(tmp_path: Path):
    """Line 113-114: sqlite:/// prefix (without +aiosqlite) should be parsed correctly."""
    from core.db import Database

    db_file = tmp_path / "plain.db"
    cfg = _SimpleCfg(f"sqlite:///{db_file.as_posix()}")
    db = Database(cfg=cfg)
    assert db._sqlite_path == db_file


def test_db_relative_sqlite_path_resolves_against_base_dir(tmp_path: Path):
    """Lines 118-119: relative sqlite path should be resolved against BASE_DIR."""
    from core.db import Database

    cfg = _SimpleCfg("sqlite+aiosqlite:///relative/test.db", base_dir=tmp_path)
    db = Database(cfg=cfg)
    assert db._sqlite_path == tmp_path / "relative" / "test.db"


def test_db_connect_sqlite_second_call_is_noop(tmp_path: Path):
    """Line 131: second call to _connect_sqlite returns early without reopening."""
    from core.db import Database

    db_file = tmp_path / "noop.db"
    cfg = _SimpleCfg(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    db = Database(cfg=cfg)

    async def _run():
        await db.connect()
        first_conn = db._sqlite_conn
        # Second connect should hit the early-return guard (line 131)
        await db.connect()
        assert db._sqlite_conn is first_conn
        await db.close()

    asyncio.run(_run())


def test_db_load_session_without_user_id(tmp_path: Path):
    """Line 472: load_session with user_id=None takes the else branch."""
    from core.db import Database

    db_file = tmp_path / "load.db"
    cfg = _SimpleCfg(f"sqlite+aiosqlite:///{db_file.as_posix()}")

    async def _run():
        db = Database(cfg=cfg)
        await db.connect()
        await db.init_schema()

        user = await db.register_user("load_user", "pw")
        sess = await db.create_session(user.id, "my session")

        # load without user_id → else branch (line 472)
        loaded = await db.load_session(sess.id)
        assert loaded is not None
        assert loaded.title == "my session"

        # non-existent session returns None
        missing = await db.load_session("does-not-exist")
        assert missing is None

        await db.close()

    asyncio.run(_run())


def test_db_connect_postgresql_returns_early_if_pool_exists():
    """Line 146: _connect_postgresql returns early when pool is already set."""
    from core.db import Database

    cfg = _SimpleCfg("postgresql://user:pw@localhost/test")
    db = Database(cfg=cfg)
    # Inject a fake pool so the early-return guard fires
    fake_pool = MagicMock()
    db._pg_pool = fake_pool

    async def _run():
        # Should return immediately without calling asyncpg (line 146)
        await db._connect_postgresql()
        assert db._pg_pool is fake_pool  # unchanged

    asyncio.run(_run())


def test_db_connect_dispatches_to_postgresql_path():
    """Line 126: connect() returns early after calling _connect_postgresql."""
    from core.db import Database

    cfg = _SimpleCfg("postgresql://user:pw@localhost/test")
    db = Database(cfg=cfg)

    called = []

    async def _fake_pg():
        called.append(True)

    db._connect_postgresql = _fake_pg  # type: ignore[assignment]

    async def _run():
        await db.connect()
        assert called == [True]

    asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# managers/system_health.py — eksik satırlar: 30-63 (render_llm_metrics_prometheus)
# ─────────────────────────────────────────────────────────────────────────────

def test_render_llm_metrics_prometheus_with_by_provider_and_by_user():
    """Lines 30-63: render_llm_metrics_prometheus populates by_provider and by_user rows."""
    from managers.system_health import render_llm_metrics_prometheus

    snapshot = {
        "totals": {
            "calls": 10,
            "cost_usd": 0.05,
            "total_tokens": 1500,
            "failures": 2,
        },
        "by_provider": {
            "ollama": {
                "calls": 7,
                "cost_usd": 0.0,
                "total_tokens": 1000,
                "failures": 0,
                "latency_ms_avg": 120.5,
            },
            "openai": {
                "calls": 3,
                "cost_usd": 0.05,
                "total_tokens": 500,
                "failures": 2,
                "latency_ms_avg": 350.0,
            },
        },
        "by_user": {
            "user_abc": {
                "calls": 6,
                "cost_usd": 0.02,
                "total_tokens": 800,
            },
            "user_xyz": {
                "calls": 4,
                "cost_usd": 0.03,
                "total_tokens": 700,
            },
        },
    }

    result = render_llm_metrics_prometheus(snapshot)

    assert "sidar_llm_calls_total 10" in result
    assert 'sidar_llm_calls_total{provider="ollama"} 7' in result
    assert 'sidar_llm_calls_total{provider="openai"} 3' in result
    assert 'sidar_llm_latency_ms_avg{provider="ollama"} 120.5' in result
    assert 'sidar_llm_user_calls_total{user_id="user_abc"} 6' in result
    assert 'sidar_llm_user_cost_total_usd{user_id="user_xyz"}' in result
    assert result.endswith("\n")


def test_render_llm_metrics_prometheus_empty_snapshot():
    """render_llm_metrics_prometheus handles None / empty snapshot gracefully."""
    from managers.system_health import render_llm_metrics_prometheus

    result = render_llm_metrics_prometheus(None)  # type: ignore[arg-type]
    assert "sidar_llm_calls_total 0" in result

    result2 = render_llm_metrics_prometheus({})
    assert "sidar_llm_calls_total 0" in result2


# ─────────────────────────────────────────────────────────────────────────────
# core/memory.py — eksik satırlar: 39, 87, 162, 170, 176, 291-292, 303-304, 309-310
# ─────────────────────────────────────────────────────────────────────────────

def test_memory_db_url_empty_branch_assigns_local_path(tmp_path: Path):
    """Line 39: ConversationMemory assigns sidar_memory.db when DATABASE_URL is empty."""
    from core.memory import ConversationMemory

    mem_file = tmp_path / "sessions" / "memory.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)

    class _EmptyCfg:
        DATABASE_URL = ""
        DB_POOL_SIZE = 1
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        BASE_DIR = tmp_path

    with patch("core.memory.Config", return_value=_EmptyCfg()):
        mem = ConversationMemory(file_path=mem_file)
        # After __init__, empty URL should be set to local sidar_memory.db
        assert "sidar_memory.db" in mem.cfg.DATABASE_URL


def test_memory_db_url_elif_branch_endswith_sidar_db(tmp_path: Path):
    """Line 40-41: ConversationMemory reassigns DATABASE_URL when it ends with 'data/sidar.db'."""
    from core.memory import ConversationMemory

    mem_file = tmp_path / "sessions" / "memory.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)

    class _SidarDbCfg:
        DATABASE_URL = "sqlite+aiosqlite:///data/sidar.db"
        DB_POOL_SIZE = 1
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        BASE_DIR = tmp_path

    with patch("core.memory.Config", return_value=_SidarDbCfg()):
        mem = ConversationMemory(file_path=mem_file)
        # After __init__, URL must be remapped to use the local sidar_memory.db
        assert "sidar_memory.db" in mem.cfg.DATABASE_URL


def test_memory_run_coro_sync_propagates_thread_exception(tmp_path: Path):
    """Line 86-87: _run_coro_sync re-raises box error from worker thread when in event loop."""
    from core.memory import ConversationMemory
    import pytest

    mem_file = tmp_path / "sessions" / "memory.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)
    mem = ConversationMemory(file_path=mem_file)

    # Simulate the box["error"] path by directly injecting an error and calling raise logic
    # We test _run_coro_sync being called inside an event loop (thread path)
    async def _run_in_loop():
        async def _boom():
            raise ValueError("thread-boom")

        # We're inside a running loop so _run_coro_sync goes through the thread path
        with pytest.raises(ValueError, match="thread-boom"):
            mem._run_coro_sync(_boom())

    asyncio.run(_run_in_loop())


def test_memory_aupdate_title_noop_without_session(tmp_path: Path):
    """Line 162: aupdate_title returns early when there is no active_session_id."""
    from core.memory import ConversationMemory

    mem_file = tmp_path / "sessions" / "mem.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)
    mem = ConversationMemory(file_path=mem_file)
    mem.active_session_id = None

    # Should return without error (line 162 early return)
    asyncio.run(mem.aupdate_title("new title"))


def test_memory_aadd_creates_session_when_no_active_session(tmp_path: Path):
    """Line 170: aadd auto-creates a session when active_session_id is not set."""
    from core.memory import ConversationMemory

    mem_file = tmp_path / "sessions" / "add.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)
    mem = ConversationMemory(file_path=mem_file)

    async def _run():
        await mem.db.connect()
        await mem.db.init_schema()
        user = await mem.db.register_user("aadd_user", "pw")
        mem.active_user_id = user.id
        mem.active_username = "aadd_user"
        # No active session — aadd should create one (line 170)
        mem.active_session_id = None
        await mem.aadd("user", "hello world")
        assert mem.active_session_id is not None
        await mem.db.close()

    asyncio.run(_run())


def test_memory_turns_trimmed_when_exceeds_double_max(tmp_path: Path):
    """Line 176: excess turns are trimmed to max_turns*2 window."""
    from core.memory import ConversationMemory

    mem_file = tmp_path / "sessions" / "trim.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)
    mem = ConversationMemory(file_path=mem_file, max_turns=3)

    async def _run():
        await mem.db.connect()
        await mem.db.init_schema()
        user = await mem.db.register_user("trim_user", "pw")
        mem.active_user_id = user.id
        mem.active_username = "trim_user"
        await mem.acreate_session("trim session")

        # Add more than max_turns*2 = 6 messages to trigger trim (line 176)
        for i in range(8):
            await mem.aadd("user", f"msg {i}")

        history = await mem.aget_history()
        assert len(history) <= mem.max_turns * 2
        await mem.db.close()

    asyncio.run(_run())


def test_memory_save_with_force_calls_force_save(tmp_path: Path):
    """Lines 291-292: _save(force=True) delegates to force_save()."""
    from core.memory import ConversationMemory

    mem_file = tmp_path / "sessions" / "save.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)
    mem = ConversationMemory(file_path=mem_file)

    called = []
    original_force_save = mem.force_save
    mem.force_save = lambda: called.append(True)  # type: ignore[method-assign]

    mem._save(force=True)
    assert called == [True]
    mem._save(force=False)
    # No additional call for force=False
    assert called == [True]


def test_memory_safe_ts_exception_returns_current_time(tmp_path: Path):
    """Lines 303-304: _safe_ts returns time.time() on parse exception."""
    import time
    from core.memory import ConversationMemory

    before = time.time()
    result = ConversationMemory._safe_ts("not-a-valid-timestamp")
    after = time.time()
    assert before <= result <= after


def test_memory_del_swallows_exception(tmp_path: Path):
    """Lines 309-310: __del__ swallows exceptions from force_save."""
    from core.memory import ConversationMemory

    mem_file = tmp_path / "sessions" / "del.json"
    mem_file.parent.mkdir(parents=True, exist_ok=True)
    mem = ConversationMemory(file_path=mem_file)
    mem.force_save = lambda: (_ for _ in ()).throw(RuntimeError("del error"))  # type: ignore[method-assign]

    # __del__ must not raise
    mem.__del__()
