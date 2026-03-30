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
