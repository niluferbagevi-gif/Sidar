"""
core/memory.py için birim testleri.
ConversationMemory constructor, _require_active_user, MemoryAuthError kapsar.
DB çağrıları gerektiren entegrasyon testleri stub'lanır.
"""
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _get_memory():
    # config stub
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        DATABASE_URL = ""
        DB_POOL_SIZE = 5
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        BASE_DIR = None

    def _get_config():
        return _Cfg()

    cfg_stub.Config = _Cfg
    cfg_stub.get_config = _get_config
    sys.modules["config"] = cfg_stub

    for mod in ("core.db", "core.memory"):
        if mod in sys.modules:
            del sys.modules[mod]

    import core.memory as memory
    return memory


def _make_memory(**kwargs):
    memory = _get_memory()
    with tempfile.TemporaryDirectory() as tmpdir:
        m = memory.ConversationMemory(base_dir=Path(tmpdir), **kwargs)
    return m


# ══════════════════════════════════════════════════════════════
# MemoryAuthError
# ══════════════════════════════════════════════════════════════

class TestMemoryAuthError:
    def test_is_permission_error(self):
        memory = _get_memory()
        err = memory.MemoryAuthError("test")
        assert isinstance(err, PermissionError)

    def test_message_preserved(self):
        memory = _get_memory()
        err = memory.MemoryAuthError("need auth")
        assert "need auth" in str(err)


# ══════════════════════════════════════════════════════════════
# ConversationMemory — constructor
# ══════════════════════════════════════════════════════════════

class TestConversationMemoryInit:
    def _make(self, **kwargs):
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            m = memory.ConversationMemory(base_dir=Path(tmpdir), **kwargs)
        return m

    def test_default_max_turns(self):
        m = self._make()
        assert m.max_turns == 20

    def test_custom_max_turns(self):
        m = self._make(max_turns=5)
        assert m.max_turns == 5

    def test_default_keep_last(self):
        m = self._make()
        assert m.keep_last == 4

    def test_custom_keep_last(self):
        m = self._make(keep_last=10)
        assert m.keep_last == 10

    def test_active_user_id_none_initially(self):
        m = self._make()
        assert m.active_user_id is None

    def test_active_session_id_none_initially(self):
        m = self._make()
        assert m.active_session_id is None

    def test_turns_empty_initially(self):
        m = self._make()
        assert m._turns == []

    def test_not_initialized_initially(self):
        m = self._make()
        assert m._initialized is False

    def test_sessions_dir_created(self):
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "sub"
            m = memory.ConversationMemory(base_dir=base)
            assert m.sessions_dir.exists()

    def test_file_path_compat(self):
        """Legacy file_path parametresi hâlâ destekleniyor."""
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "data" / "memory.db"
            m = memory.ConversationMemory(file_path=fp)
            # sessions_dir parent'ı file_path parent'ının altında olmalı
            assert m.sessions_dir is not None

    def test_sqlite_url_when_no_url_provided(self):
        m = self._make()
        assert "sqlite" in m.db.database_url.lower()

    def test_database_url_override(self):
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            url = f"sqlite+aiosqlite:///{tmpdir}/custom.db"
            m = memory.ConversationMemory(
                base_dir=Path(tmpdir),
                database_url=url,
            )
            assert "custom.db" in m.db.database_url


# ══════════════════════════════════════════════════════════════
# ConversationMemory._require_active_user
# ══════════════════════════════════════════════════════════════

class TestRequireActiveUser:
    def _make(self):
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            return memory.ConversationMemory(base_dir=Path(tmpdir)), memory

    def test_raises_when_no_user(self):
        m, memory = self._make()
        import pytest
        with pytest.raises(memory.MemoryAuthError):
            m._require_active_user()

    def test_returns_user_id_when_set(self):
        m, _ = self._make()
        m.active_user_id = "user123"
        result = m._require_active_user()
        assert result == "user123"

    def test_raises_with_empty_string(self):
        m, memory = self._make()
        m.active_user_id = ""
        import pytest
        with pytest.raises(memory.MemoryAuthError):
            m._require_active_user()

    def test_raises_after_reset(self):
        m, memory = self._make()
        m.active_user_id = "user123"
        m.active_user_id = None
        import pytest
        with pytest.raises(memory.MemoryAuthError):
            m._require_active_user()


# ══════════════════════════════════════════════════════════════
# ConversationMemory.get_config
# ══════════════════════════════════════════════════════════════

class TestGetConfig:
    def test_get_config_returns_config_instance(self):
        memory = _get_memory()
        cfg = memory.get_config()
        assert cfg is not None

    def test_get_config_callable(self):
        memory = _get_memory()
        assert callable(memory.get_config)


# ══════════════════════════════════════════════════════════════
# ConversationMemory — stub DB path (no real DB calls)
# ══════════════════════════════════════════════════════════════

class TestMemoryWithStubDb:
    """DB çağrıları stub'lanan async davranış testleri."""

    def _make_with_stub_db(self):
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            m = memory.ConversationMemory(base_dir=Path(tmpdir))

        # Stub out DB
        m.db = MagicMock()
        m.db.connect = AsyncMock()
        m.db.init_schema = AsyncMock()
        m.db.list_sessions = AsyncMock(return_value=[])
        m.db.create_session = AsyncMock(return_value=MagicMock(id="sid1", title="Test"))
        m.db.get_session_messages = AsyncMock(return_value=[])
        m.db.add_message = AsyncMock()
        m.db.load_session = AsyncMock(return_value=None)
        m.db.delete_session = AsyncMock(return_value=True)
        m.db.update_session_title = AsyncMock()
        return m, memory

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_initialize_calls_connect_and_init_schema(self):
        m, _ = self._make_with_stub_db()
        self._run(m.initialize())
        m.db.connect.assert_called_once()
        m.db.init_schema.assert_called_once()

    def test_initialize_sets_initialized_flag(self):
        m, _ = self._make_with_stub_db()
        self._run(m.initialize())
        assert m._initialized is True

    def test_initialize_clears_active_user(self):
        m, _ = self._make_with_stub_db()
        m.active_user_id = "old_user"
        self._run(m.initialize())
        assert m.active_user_id is None

    def test_get_all_sessions_requires_user(self):
        m, memory = self._make_with_stub_db()
        self._run(m.initialize())
        import pytest
        with pytest.raises(memory.MemoryAuthError):
            self._run(m.get_all_sessions())

    def test_get_all_sessions_calls_list_sessions(self):
        m, _ = self._make_with_stub_db()
        self._run(m.initialize())
        m.active_user_id = "u1"
        result = self._run(m.get_all_sessions())
        assert result == []
        m.db.list_sessions.assert_called_once_with("u1")

    def test_create_session_requires_user(self):
        m, memory = self._make_with_stub_db()
        self._run(m.initialize())
        import pytest
        with pytest.raises(memory.MemoryAuthError):
            self._run(m.create_session())

    def test_create_session_returns_id(self):
        m, _ = self._make_with_stub_db()
        self._run(m.initialize())
        m.active_user_id = "u1"
        sid = self._run(m.create_session("My Chat"))
        assert sid == "sid1"
        assert m.active_session_id == "sid1"

    def test_add_requires_user(self):
        m, memory = self._make_with_stub_db()
        self._run(m.initialize())
        import pytest
        with pytest.raises(memory.MemoryAuthError):
            self._run(m.add("user", "hello"))

    def test_add_appends_to_turns(self):
        m, _ = self._make_with_stub_db()
        self._run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid1"
        self._run(m.add("user", "hello"))
        assert len(m._turns) == 1
        assert m._turns[0]["role"] == "user"
        assert m._turns[0]["content"] == "hello"

    def test_update_title_no_session_noop(self):
        m, _ = self._make_with_stub_db()
        self._run(m.initialize())
        m.active_user_id = "u1"
        # No active session — should not raise
        self._run(m.update_title("New Title"))
        m.db.update_session_title.assert_not_called()

    def test_update_title_calls_db(self):
        m, _ = self._make_with_stub_db()
        self._run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid1"
        self._run(m.update_title("New Title"))
        m.db.update_session_title.assert_called_once_with("sid1", "New Title")


class TestMemoryCompactionAndMultimodalLikeHistoryEdges:
    def _make_with_stub_db(self):
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            m = memory.ConversationMemory(base_dir=Path(tmpdir))

        m.db = MagicMock()
        m.db.connect = AsyncMock()
        m.db.init_schema = AsyncMock()
        m.db.list_sessions = AsyncMock(return_value=[])
        m.db.create_session = AsyncMock(return_value=MagicMock(id="sid1", title="Test"))
        m.db.get_session_messages = AsyncMock(return_value=[])
        m.db.load_session = AsyncMock(return_value=None)
        m.db.replace_session_messages = AsyncMock(return_value=0)
        return m, memory

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_build_compaction_summary_counts_code_and_link_references(self):
        m, _ = self._make_with_stub_db()
        messages = [
            types.SimpleNamespace(role="user", content="YouTube videosunu analiz et: https://youtu.be/dQw4w9WgXcQ"),
            types.SimpleNamespace(role="assistant", content="`main.py` içinde /api/posts endpointine bakacağım."),
            types.SimpleNamespace(role="assistant", content="```python\nprint('ok')\n```"),
        ]
        summary = m._build_compaction_summary("Sosyal Medya", messages)
        assert "Toplam mesaj: 3" in summary
        assert "Kod/araç referansı görülen mesaj sayısı: 2" in summary
        assert "Öne çıkan kullanıcı istekleri" in summary

    def test_compact_session_skips_when_message_threshold_not_met(self):
        m, _ = self._make_with_stub_db()
        self._run(m.initialize())
        m.db.load_session = AsyncMock(return_value=types.SimpleNamespace(id="sid9", title="Kısa Oturum"))
        m.db.get_session_messages = AsyncMock(
            return_value=[types.SimpleNamespace(role="user", content="kısa", created_at="2026-01-01T00:00:00+00:00")]
        )

        result = self._run(m.compact_session(user_id="u1", session_id="sid9", min_messages=5))
        assert result["status"] == "skipped"
        assert result["reason"] == "message_threshold"

    def test_compact_session_keeps_recent_messages_and_updates_active_turns(self):
        m, _ = self._make_with_stub_db()
        self._run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid42"
        m.db.load_session = AsyncMock(return_value=types.SimpleNamespace(id="sid42", title="Analiz Oturumu"))
        m.db.get_session_messages = AsyncMock(
            return_value=[
                types.SimpleNamespace(role="user", content="1. mesaj", created_at="2026-01-01T00:00:00+00:00"),
                types.SimpleNamespace(role="assistant", content="2. mesaj", created_at="2026-01-01T00:01:00+00:00"),
                types.SimpleNamespace(role="user", content="3. mesaj", created_at="2026-01-01T00:02:00+00:00"),
            ]
        )
        m.db.replace_session_messages = AsyncMock(return_value=4)

        result = self._run(
            m.compact_session(user_id="u1", session_id="sid42", keep_last=1, min_messages=2)
        )
        assert result["status"] == "compacted"
        assert result["messages_after"] == 4
        payload = m.db.replace_session_messages.await_args.args[1]
        assert payload[0]["content"].startswith("[GECE DÖNGÜSÜ]")
        assert payload[-1]["content"] == "3. mesaj"
        assert len(m._turns) == 3


class TestMemoryParametricParsing:
    @pytest.mark.parametrize(
        "raw_value, should_be_positive",
        [
            ("2026-01-01T00:00:00+00:00", True),
            ("2026-01-01T00:00:00Z", True),
            ("invalid-date", False),
            (None, False),
        ],
    )
    def test_parse_iso_ts_handles_multiple_input_types(self, raw_value, should_be_positive):
        memory = _get_memory()
        parsed = memory.ConversationMemory._parse_iso_ts(raw_value)  # type: ignore[arg-type]
        assert (parsed > 0) is should_be_positive


class TestMemoryNightlyConsolidationExceptionPaths:
    def _make_with_stub_db(self):
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            m = memory.ConversationMemory(base_dir=Path(tmpdir))

        m.db = MagicMock()
        m.db.connect = AsyncMock()
        m.db.init_schema = AsyncMock()
        m.db.list_users_with_quotas = AsyncMock(side_effect=RuntimeError("quota source down"))
        m.db.list_sessions = AsyncMock(return_value=[])
        return m

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_run_nightly_consolidation_falls_back_to_active_user_when_user_listing_fails(self):
        m = self._make_with_stub_db()
        self._run(m.initialize())
        m.active_user_id = "u-active"

        result = self._run(m.run_nightly_consolidation(keep_recent_sessions=1, min_messages=5))

        assert result["status"] == "completed"
        assert result["users_scanned"] == 1
        m.db.list_sessions.assert_called_once_with("u-active")

# ===== MERGED FROM tests/test_core_memory_extra.py =====

import asyncio
import sys
import tempfile
import time
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _get_memory():
    """Fresh import of core.memory with stubbed config and core.db."""
    cfg_stub = types.ModuleType("config")

    class _Cfg:
        DATABASE_URL = ""
        DB_POOL_SIZE = 5
        DB_SCHEMA_VERSION_TABLE = "schema_versions"
        DB_SCHEMA_TARGET_VERSION = 1
        BASE_DIR = None

    def _get_config():
        return _Cfg()

    cfg_stub.Config = _Cfg
    cfg_stub.get_config = _get_config
    sys.modules["config"] = cfg_stub

    for mod in ("core.db", "core.memory"):
        if mod in sys.modules:
            del sys.modules[mod]

    import core.memory as memory
    return memory


def _make_memory_obj(memory_mod, **kwargs):
    """Return a ConversationMemory with stub DB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        m = memory_mod.ConversationMemory(base_dir=Path(tmpdir), **kwargs)
    m.db = MagicMock()
    m.db.connect = AsyncMock()
    m.db.init_schema = AsyncMock()
    m.db.list_sessions = AsyncMock(return_value=[])
    m.db.create_session = AsyncMock(return_value=MagicMock(id="sid1", title="Yeni Sohbet"))
    m.db.get_session_messages = AsyncMock(return_value=[])
    m.db.add_message = AsyncMock()
    m.db.load_session = AsyncMock(return_value=None)
    m.db.delete_session = AsyncMock(return_value=True)
    m.db.update_session_title = AsyncMock()
    m.db.replace_session_messages = AsyncMock(return_value=3)
    m.db.list_users_with_quotas = AsyncMock(return_value=[])
    return m


# ===========================================================================
# Constructor edge cases (lines 52, 70)
# ===========================================================================

class Extra_TestConstructorEdgeCases:
    def test_no_base_dir_no_file_path_uses_cwd_data(self):
        memory = _get_memory()
        # No base_dir and no file_path → resolved_base_dir = Path.cwd() / "data"
        m = memory.ConversationMemory()
        expected = Path.cwd() / "data" / "sessions"
        assert m.sessions_dir == expected

    def test_database_url_ending_with_sidar_db_is_remapped(self):
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            m = memory.ConversationMemory(
                base_dir=Path(tmpdir),
                database_url="sqlite+aiosqlite:///data/sidar.db",
            )
        # Should be remapped to sidar_memory.db
        assert "sidar_memory.db" in m.db.database_url

    def test_explicit_database_url_not_sidar_db_unchanged(self):
        memory = _get_memory()
        with tempfile.TemporaryDirectory() as tmpdir:
            custom = f"sqlite+aiosqlite:///{tmpdir}/custom.db"
            m = memory.ConversationMemory(base_dir=Path(tmpdir), database_url=custom)
        assert "custom.db" in m.db.database_url


# ===========================================================================
# _ensure_initialized (lines 107-111)
# ===========================================================================

class Extra_TestEnsureInitialized:
    def test_ensure_initialized_runs_initialize_once(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        assert m._initialized is False
        _run(m._ensure_initialized())
        assert m._initialized is True
        m.db.connect.assert_called_once()

    def test_ensure_initialized_does_not_reinitialize(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m._ensure_initialized())
        _run(m._ensure_initialized())
        # connect should still be called only once
        m.db.connect.assert_called_once()

    def test_ensure_initialized_creates_init_lock_when_none(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        assert m._init_lock is None
        _run(m._ensure_initialized())
        assert m._init_lock is not None


# ===========================================================================
# load_session (lines 140-161)
# ===========================================================================

class Extra_TestLoadSession:
    def test_load_session_returns_false_when_not_found(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.db.load_session = AsyncMock(return_value=None)
        result = _run(m.load_session("nonexistent"))
        assert result is False

    def test_load_session_success_populates_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"

        fake_session = MagicMock(id="sid99", title="Chat 99")
        fake_msg = MagicMock(
            role="user",
            content="hello",
            tokens_used=5,
            created_at="2026-01-01T00:00:00+00:00",
        )
        m.db.load_session = AsyncMock(return_value=fake_session)
        m.db.get_session_messages = AsyncMock(return_value=[fake_msg])

        result = _run(m.load_session("sid99"))
        assert result is True
        assert m.active_session_id == "sid99"
        assert m.active_title == "Chat 99"
        assert len(m._turns) == 1
        assert m._turns[0]["role"] == "user"
        assert m._turns[0]["content"] == "hello"

    def test_load_session_safe_ts_handles_invalid_date(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"

        fake_session = MagicMock(id="sidX", title="X")
        fake_msg = MagicMock(
            role="assistant",
            content="resp",
            tokens_used=0,
            created_at="not-a-date",  # invalid → _safe_ts returns time.time()
        )
        m.db.load_session = AsyncMock(return_value=fake_session)
        m.db.get_session_messages = AsyncMock(return_value=[fake_msg])

        result = _run(m.load_session("sidX"))
        assert result is True
        assert m._turns[0]["timestamp"] > 0


# ===========================================================================
# delete_session (lines 164-176)
# ===========================================================================

class Extra_TestDeleteSession:
    def test_delete_session_returns_false_when_db_returns_false(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.db.delete_session = AsyncMock(return_value=False)
        result = _run(m.delete_session("sid_gone"))
        assert result is False

    def test_delete_session_loads_remaining_session_when_active(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid_del"
        m.db.delete_session = AsyncMock(return_value=True)

        remaining = MagicMock(id="sid_other", title="Other")
        m.db.list_sessions = AsyncMock(return_value=[remaining])
        m.db.load_session = AsyncMock(return_value=remaining)
        m.db.get_session_messages = AsyncMock(return_value=[])

        result = _run(m.delete_session("sid_del"))
        assert result is True

    def test_delete_session_creates_new_session_when_none_remaining(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid_last"
        m.db.delete_session = AsyncMock(return_value=True)
        m.db.list_sessions = AsyncMock(return_value=[])

        result = _run(m.delete_session("sid_last"))
        assert result is True
        m.db.create_session.assert_called()

    def test_delete_session_not_active_session_no_redirect(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid_A"
        m.db.delete_session = AsyncMock(return_value=True)

        result = _run(m.delete_session("sid_B"))  # different session
        assert result is True
        m.db.list_sessions.assert_not_called()


# ===========================================================================
# add (lines 190, 196)
# ===========================================================================

class Extra_TestAdd:
    def test_add_auto_creates_session_when_none(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        assert m.active_session_id is None

        _run(m.add("user", "hello"))
        m.db.create_session.assert_called()
        assert len(m._turns) == 1

    def test_add_trims_turns_when_exceeds_max(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid1"
        m.max_turns = 2  # threshold: 2 * 2 = 4

        # Add 5 turns — should be trimmed to 4 on the 5th add
        for i in range(5):
            _run(m.add("user", f"msg{i}"))

        assert len(m._turns) == 4  # trimmed to max_turns * 2


# ===========================================================================
# get_history (lines 201-204)
# ===========================================================================

class Extra_TestGetHistory:
    def test_get_history_all_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid1"
        _run(m.add("user", "a"))
        _run(m.add("assistant", "b"))

        result = _run(m.get_history())
        assert len(result) == 2

    def test_get_history_n_last(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid1"
        for i in range(5):
            _run(m.add("user", f"msg{i}"))

        result = _run(m.get_history(n_last=2))
        assert len(result) == 2
        assert result[-1]["content"] == "msg4"


# ===========================================================================
# set_active_user (lines 207-214)
# ===========================================================================

class Extra_TestSetActiveUser:
    def test_set_active_user_with_existing_sessions(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())

        existing = MagicMock(id="sid_existing", title="Existing")
        m.db.list_sessions = AsyncMock(return_value=[existing])
        m.db.load_session = AsyncMock(return_value=existing)
        m.db.get_session_messages = AsyncMock(return_value=[])

        _run(m.set_active_user("u42", username="alice"))
        assert m.active_user_id == "u42"
        assert m.active_username == "alice"
        m.db.load_session.assert_called_with("sid_existing", "u42")

    def test_set_active_user_creates_session_when_none(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.db.list_sessions = AsyncMock(return_value=[])

        _run(m.set_active_user("u7"))
        assert m.active_user_id == "u7"
        m.db.create_session.assert_called()


# ===========================================================================
# get_messages_for_llm (lines 221-222)
# ===========================================================================

class Extra_TestGetMessagesForLlm:
    def test_returns_role_and_content_dicts(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "s1"
        _run(m.add("user", "hi"))
        _run(m.add("assistant", "hello"))

        result = m.get_messages_for_llm()
        assert result == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

    def test_returns_empty_list_when_no_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        assert m.get_messages_for_llm() == []


# ===========================================================================
# set_last_file / get_last_file (lines 225-231)
# ===========================================================================

class Extra_TestLastFile:
    def test_set_and_get_last_file(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m.set_last_file("/path/to/file.py")
        assert m.get_last_file() == "/path/to/file.py"
        assert m._dirty is True

    def test_get_last_file_returns_none_initially(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        assert m.get_last_file() is None


# ===========================================================================
# _estimate_tokens (lines 234-240)
# ===========================================================================

class Extra_TestEstimateTokens:
    def test_estimate_without_tiktoken(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m._turns = [{"role": "user", "content": "hello world"}]
        # tiktoken is not installed in test env → fallback to len/3.5
        result = m._estimate_tokens()
        assert isinstance(result, int)
        assert result > 0

    def test_estimate_empty_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m._turns = []
        result = m._estimate_tokens()
        assert result == 0

    def test_estimate_uses_tiktoken_when_available(self, monkeypatch):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m._turns = [{"role": "user", "content": "abc"}, {"role": "assistant", "content": "def"}]

        class _Enc:
            def encode(self, text):
                return list(text)

        class _Tiktoken:
            @staticmethod
            def get_encoding(_name):
                return _Enc()

        monkeypatch.setitem(sys.modules, "tiktoken", _Tiktoken)
        assert m._estimate_tokens() == len("abcdef")


# ===========================================================================
# needs_summarization (lines 243-246)
# ===========================================================================

class Extra_TestNeedsSummarization:
    def test_needs_summarization_false_when_few_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m.max_turns = 20
        m._turns = [{"role": "user", "content": "hi"}]
        assert m.needs_summarization() is False

    def test_needs_summarization_true_when_many_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m.max_turns = 2  # threshold: 2*2*0.8 = 3.2 → 3
        m._turns = [{"role": "user", "content": "x"}] * 4
        assert m.needs_summarization() is True

    def test_needs_summarization_true_when_many_tokens(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m.max_turns = 20
        # Create enough text to exceed 6000 token estimate
        long_content = "word " * 7000  # ~7000 words → ~7000/3.5*3.5 = 7000 tokens
        m._turns = [{"role": "user", "content": long_content}]
        assert m.needs_summarization() is True


# ===========================================================================
# apply_summary (lines 249-267)
# ===========================================================================

class Extra_TestApplySummary:
    def test_apply_summary_replaces_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid1"
        m.active_title = "Chat"
        m._turns = [
            {"role": "user", "content": "old1", "timestamp": time.time()},
            {"role": "assistant", "content": "old2", "timestamp": time.time()},
        ]
        m.db.delete_session = AsyncMock(return_value=True)

        _run(m.apply_summary("This is a summary."))

        assert any("KONUŞMA ÖZETİ" in t.get("content", "") for t in m._turns)

    def test_apply_summary_no_session_no_db_calls(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = None
        m.active_session_id = None
        m._turns = []

        _run(m.apply_summary("Summary without session."))
        m.db.delete_session.assert_not_called()

    def test_apply_summary_keeps_last_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid1"
        m.keep_last = 1
        m._turns = [
            {"role": "user", "content": "first", "timestamp": time.time()},
            {"role": "assistant", "content": "last", "timestamp": time.time()},
        ]
        m.db.delete_session = AsyncMock(return_value=True)

        _run(m.apply_summary("Summary"))
        # The last 1 turn should be kept plus 2 summary turns
        assert len(m._turns) >= 2
        contents = [t["content"] for t in m._turns]
        assert "last" in contents


# ===========================================================================
# clear (lines 270-278)
# ===========================================================================

class Extra_TestClear:
    def test_clear_empties_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid1"
        m._turns = [{"role": "user", "content": "data"}]

        _run(m.clear())
        assert m._turns == []

    def test_clear_no_session_no_db_calls(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_session_id = None

        _run(m.clear())
        m.db.delete_session.assert_not_called()

    def test_clear_with_session_calls_delete_and_create(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "sid1"
        m.active_title = "MyCHAT"

        _run(m.clear())
        m.db.delete_session.assert_called_with("sid1", "u1")
        m.db.create_session.assert_called()


# ===========================================================================
# _build_compaction_summary (lines 288-316)
# ===========================================================================

class Extra_TestBuildCompactionSummary:
    def test_basic_summary_with_user_and_assistant(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        messages = [
            types.SimpleNamespace(role="user", content="What is 2+2?"),
            types.SimpleNamespace(role="assistant", content="It's 4."),
        ]
        summary = m._build_compaction_summary("Test Session", messages)
        assert "Test Session" in summary
        assert "Toplam mesaj: 2" in summary
        assert "What is 2+2?" in summary
        assert "It's 4." in summary

    def test_summary_counts_code_references(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        messages = [
            types.SimpleNamespace(role="user", content="```python\ncode here\n```"),
            types.SimpleNamespace(role="assistant", content="I see the .py file and /api/endpoint"),
        ]
        summary = m._build_compaction_summary("Code Chat", messages)
        assert "Kod/araç referansı görülen mesaj sayısı: 2" in summary

    def test_summary_empty_messages(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        summary = m._build_compaction_summary("Empty", [])
        assert "Toplam mesaj: 0" in summary

    def test_summary_skips_empty_content(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        messages = [
            types.SimpleNamespace(role="user", content=""),
            types.SimpleNamespace(role="assistant", content="Valid response."),
        ]
        summary = m._build_compaction_summary("Test", messages)
        # Should still work; empty content is skipped
        assert "Toplam mesaj: 2" in summary


# ===========================================================================
# compact_session (lines 320-367)
# ===========================================================================

class Extra_TestCompactSession:
    def test_compact_session_missing_session(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.db.load_session = AsyncMock(return_value=None)

        result = _run(m.compact_session(user_id="u1", session_id="sid_missing"))
        assert result["status"] == "missing"

    def test_compact_session_skipped_few_messages(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())

        m.db.load_session = AsyncMock(return_value=MagicMock(id="s1", title="Short"))
        m.db.get_session_messages = AsyncMock(return_value=[
            MagicMock(role="user", content="hi", created_at="2026-01-01T00:00:00+00:00")
        ])

        result = _run(m.compact_session(user_id="u1", session_id="s1", min_messages=5))
        assert result["status"] == "skipped"
        assert result["reason"] == "message_threshold"

    def test_compact_session_keep_last_zero(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())

        fake_session = MagicMock(id="s2", title="Full")
        msgs = [
            MagicMock(role="user", content=f"msg{i}", created_at="2026-01-01T00:00:00+00:00")
            for i in range(5)
        ]
        m.db.load_session = AsyncMock(return_value=fake_session)
        m.db.get_session_messages = AsyncMock(return_value=msgs)

        result = _run(m.compact_session(user_id="u1", session_id="s2", keep_last=0, min_messages=2))
        assert result["status"] == "compacted"
        # With keep_last=0, only the 2 summary turns
        written_args = m.db.replace_session_messages.await_args.args[1]
        assert len(written_args) == 2

    def test_compact_session_updates_active_turns_when_active(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.active_user_id = "u1"
        m.active_session_id = "s3"

        fake_session = MagicMock(id="s3", title="Active Session")
        msgs = [
            MagicMock(role="user", content=f"msg{i}", created_at="2026-01-01T00:00:00+00:00")
            for i in range(3)
        ]
        m.db.load_session = AsyncMock(return_value=fake_session)
        m.db.get_session_messages = AsyncMock(return_value=msgs)

        result = _run(m.compact_session(user_id="u1", session_id="s3", min_messages=2))
        assert result["status"] == "compacted"
        assert len(m._turns) > 0  # active turns were updated


# ===========================================================================
# run_nightly_consolidation (lines 369-409)
# ===========================================================================

class Extra_TestRunNightlyConsolidation:
    def test_nightly_consolidation_exception_in_list_users(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.db.list_users_with_quotas = AsyncMock(side_effect=RuntimeError("DB down"))
        m.active_user_id = None

        result = _run(m.run_nightly_consolidation())
        assert result["status"] == "completed"
        assert result["users_scanned"] == 0

    def test_nightly_consolidation_appends_active_user(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.db.list_users_with_quotas = AsyncMock(return_value=[])
        m.active_user_id = "active_user"
        m.db.list_sessions = AsyncMock(return_value=[])

        result = _run(m.run_nightly_consolidation())
        assert result["users_scanned"] == 1

    def test_nightly_consolidation_skips_recent_sessions(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.db.list_users_with_quotas = AsyncMock(return_value=[{"id": "u1"}])
        m.active_user_id = None

        sessions = [
            MagicMock(id=f"sid{i}", title=f"Session {i}") for i in range(3)
        ]
        m.db.list_sessions = AsyncMock(return_value=sessions)
        m.db.load_session = AsyncMock(return_value=None)  # compact will return missing

        result = _run(m.run_nightly_consolidation(keep_recent_sessions=2))
        # Only 1 session (index 2) should be attempted (the older one)
        assert len(result["reports"]) == 1

    def test_nightly_consolidation_reports_compacted(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        _run(m.initialize())
        m.db.list_users_with_quotas = AsyncMock(return_value=[{"id": "u1"}])
        m.active_user_id = None

        sessions = [MagicMock(id="sid_old", title="Old Session")]
        m.db.list_sessions = AsyncMock(return_value=sessions)

        fake_session = MagicMock(id="sid_old", title="Old Session")
        msgs = [
            MagicMock(role="user", content=f"m{i}", created_at="2026-01-01T00:00:00+00:00")
            for i in range(5)
        ]
        m.db.load_session = AsyncMock(return_value=fake_session)
        m.db.get_session_messages = AsyncMock(return_value=msgs)

        result = _run(m.run_nightly_consolidation(keep_recent_sessions=0, min_messages=3))
        assert result["sessions_compacted"] >= 1


# ===========================================================================
# force_save, _save, _cleanup_broken_files (lines 411-422)
# ===========================================================================

class Extra_TestSaveAndCleanup:
    def test_force_save_clears_dirty(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m._dirty = True
        m.force_save()
        assert m._dirty is False

    def test_save_with_force_calls_force_save(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m._dirty = True
        m._save(force=True)
        assert m._dirty is False

    def test_save_without_force_noop(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m._dirty = True
        m._save(force=False)
        assert m._dirty is True  # unchanged

    def test_cleanup_broken_files_noop(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        # Should return None and not raise
        result = m._cleanup_broken_files()
        assert result is None


# ===========================================================================
# _safe_ts (lines 426-430)
# ===========================================================================

class Extra_TestSafeTs:
    def test_safe_ts_valid_iso(self):
        memory = _get_memory()
        ts = memory.ConversationMemory._safe_ts("2026-01-01T00:00:00+00:00")
        assert ts > 0

    def test_safe_ts_invalid_returns_current_time(self):
        memory = _get_memory()
        before = time.time()
        ts = memory.ConversationMemory._safe_ts("not-a-date")
        after = time.time()
        assert before <= ts <= after + 1

    def test_safe_ts_z_suffix(self):
        memory = _get_memory()
        ts = memory.ConversationMemory._safe_ts("2026-06-15T12:30:00Z")
        assert ts > 0


# ===========================================================================
# __del__, __len__, __repr__ (lines 432-443)
# ===========================================================================

class Extra_TestDunderMethods:
    def test_len_returns_turn_count(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m._turns = [{"role": "user", "content": "x"}] * 3
        assert len(m) == 3

    def test_len_empty(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        assert len(m) == 0

    def test_repr_contains_session_and_turns(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m.active_session_id = "test_session"
        m._turns = [{"role": "user", "content": "hi"}]
        r = repr(m)
        assert "test_session" in r
        assert "1" in r

    def test_del_calls_force_save(self):
        memory = _get_memory()
        m = _make_memory_obj(memory)
        m._dirty = True
        m.__del__()  # should not raise
        assert m._dirty is False


# ===========================================================================
# _parse_iso_ts static method
# ===========================================================================

class Extra_TestParseIsoTs:
    def test_valid_iso_returns_positive(self):
        memory = _get_memory()
        ts = memory.ConversationMemory._parse_iso_ts("2026-01-01T00:00:00+00:00")
        assert ts > 0

    def test_z_suffix_handled(self):
        memory = _get_memory()
        ts = memory.ConversationMemory._parse_iso_ts("2026-06-15T10:00:00Z")
        assert ts > 0

    def test_invalid_returns_zero(self):
        memory = _get_memory()
        ts = memory.ConversationMemory._parse_iso_ts("garbage")
        assert ts == 0.0

    def test_none_returns_zero(self):
        memory = _get_memory()
        ts = memory.ConversationMemory._parse_iso_ts(None)
        assert ts == 0.0
