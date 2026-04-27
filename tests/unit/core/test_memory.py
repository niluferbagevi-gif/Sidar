import asyncio
import sys
import types
from pathlib import Path

import pytest

# core.db imports jwt at module import time in test env
sys.modules.setdefault("jwt", types.SimpleNamespace())

from core import memory as memory_module
from core.memory import ConversationMemory, MemoryAuthError, get_config


class FakeDB:
    def __init__(self, cfg=None):
        self.cfg = cfg
        self.connected = 0
        self.inited = 0
        self.sessions = {}
        self.messages = {}
        self.user_sessions = {}
        self.users_with_quotas = []
        self._seq = 0

    async def connect(self):
        self.connected += 1

    async def init_schema(self):
        self.inited += 1

    async def list_sessions(self, user_id):
        ids = self.user_sessions.get(user_id, [])
        return [self.sessions[sid] for sid in ids if sid in self.sessions]

    async def get_session_messages(self, session_id):
        return list(self.messages.get(session_id, []))

    async def create_session(self, user_id, title):
        self._seq += 1
        sid = f"s{self._seq}"
        row = types.SimpleNamespace(
            id=sid, user_id=user_id, title=title, updated_at="2024-01-01T00:00:00Z"
        )
        self.sessions[sid] = row
        self.messages.setdefault(sid, [])
        self.user_sessions.setdefault(user_id, []).insert(0, sid)
        return row

    async def load_session(self, session_id, user_id):
        row = self.sessions.get(session_id)
        if row and row.user_id == user_id:
            return row
        return None

    async def delete_session(self, session_id, user_id):
        row = self.sessions.get(session_id)
        if not row or row.user_id != user_id:
            return False
        self.sessions.pop(session_id, None)
        self.messages.pop(session_id, None)
        if user_id in self.user_sessions:
            self.user_sessions[user_id] = [
                sid for sid in self.user_sessions[user_id] if sid != session_id
            ]
        return True

    async def update_session_title(self, session_id, new_title):
        if session_id in self.sessions:
            self.sessions[session_id].title = new_title

    async def add_message(self, session_id, role, content, tokens_used=0):
        self.messages.setdefault(session_id, []).append(
            types.SimpleNamespace(
                role=role,
                content=content,
                created_at="2024-01-01T00:00:00Z",
                tokens_used=tokens_used,
            )
        )

    async def replace_session_messages(self, session_id, compact_turns):
        self.messages[session_id] = [
            types.SimpleNamespace(
                role=i["role"],
                content=i["content"],
                created_at="2024-01-01T00:00:00Z",
                tokens_used=0,
            )
            for i in compact_turns
        ]
        return len(compact_turns)

    async def list_users_with_quotas(self):
        return list(self.users_with_quotas)


@pytest.fixture
def mem(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(memory_module, "Database", FakeDB)
    m = ConversationMemory(base_dir=tmp_path, max_turns=2, keep_last=1)
    return m


def test_fake_db_delete_and_update_noop_branches() -> None:
    db = FakeDB()

    async def scenario() -> None:
        row = await db.create_session("u1", "ilk")
        db.user_sessions.pop("u1")
        assert await db.delete_session(row.id, "u1") is True

        await db.update_session_title("missing", "noop")

    asyncio.run(scenario())


def test_get_config_variants(monkeypatch):
    cfg = types.SimpleNamespace(DATABASE_URL="sqlite+aiosqlite:///x.db")
    monkeypatch.setattr(memory_module, "_config_get_config", lambda: cfg)
    assert get_config() is cfg

    monkeypatch.setattr(memory_module, "_config_get_config", None)
    fallback = get_config()
    assert isinstance(fallback, memory_module.Config)


def test_init_path_and_database_url_resolution(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(memory_module, "Database", FakeDB)

    m1 = ConversationMemory(base_dir=tmp_path)
    assert m1.sessions_dir == tmp_path / "sessions"
    assert "sidar_memory.db" in m1.cfg.DATABASE_URL

    file_path = tmp_path / "legacy" / "memory.json"
    m2 = ConversationMemory(file_path=file_path, database_url="sqlite+aiosqlite:///data/sidar.db")
    assert m2.cfg.BASE_DIR == file_path.parent
    assert "sidar_memory.db" in m2.cfg.DATABASE_URL


def test_init_replaces_placeholder_sqlite_database_url_from_config(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(memory_module, "Database", FakeDB)
    monkeypatch.setattr(
        memory_module, "get_config", lambda: types.SimpleNamespace(DATABASE_URL="sqlite:///x")
    )

    mem = ConversationMemory(base_dir=tmp_path)
    assert "sidar_memory.db" in mem.cfg.DATABASE_URL


def test_user_required_and_repr_len(mem):
    assert "session=None" in repr(mem)
    assert len(mem) == 0
    with pytest.raises(MemoryAuthError):
        mem._require_active_user()


def test_sync_api_helpers(mem):
    mem._turns = [{"role": "user", "content": "merhaba"}]
    assert mem.get_messages_for_llm() == [{"role": "user", "content": "merhaba"}]

    mem.set_last_file("a.py")
    assert mem.get_last_file() == "a.py"

    assert isinstance(mem._estimate_tokens(), int)
    assert mem.needs_summarization() is False


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_estimate_tokens_with_tiktoken(monkeypatch, mem):
    class Enc:
        @staticmethod
        def encode(text):
            return [1] * len(text)

    fake_tiktoken = types.SimpleNamespace(get_encoding=lambda _: Enc())
    monkeypatch.setitem(sys.modules, "tiktoken", fake_tiktoken)

    mem._turns = [{"role": "u", "content": "abc"}, {"role": "a", "content": "de"}]
    assert mem._estimate_tokens() == 5


def test_async_main_flows(mem):
    async def scenario():
        await mem.initialize()
        assert mem.db.connected == 1
        assert mem.db.inited == 1

        await mem.set_active_user("u1", "alice")
        assert mem.active_user_id == "u1"
        assert mem.active_username == "alice"
        assert mem.active_session_id is not None

        sid = mem.active_session_id
        await mem.add("user", "ilk")
        await mem.add("assistant", "yanit")
        await mem.add("user", "ucuncu")

        hist = await mem.get_history()
        assert len(hist) == 3
        assert len(mem._turns) <= 4  # max_turns*2

        hist_last = await mem.get_history(1)
        assert hist_last[0]["content"] == "ucuncu"

        sessions = await mem.get_all_sessions()
        assert sessions and sessions[0]["message_count"] >= 3

        await mem.update_title("Guncel")
        assert mem.active_title == "Guncel"

        loaded = await mem.load_session(sid)
        assert loaded is True

        missing = await mem.load_session("nope")
        assert missing is False

        ok = await mem.delete_session(sid)
        assert ok is True
        assert mem.active_session_id is not None

        not_ok = await mem.delete_session("404")
        assert not_ok is False

    asyncio.run(scenario())


def test_apply_summary_and_clear(mem):
    async def scenario():
        await mem.initialize()
        await mem.set_active_user("u1")
        await mem.add("user", "m1")
        await mem.add("assistant", "m2")
        await mem.add("user", "m3")

        await mem.apply_summary("kisa ozet")
        assert mem._turns[1]["content"].startswith("[KONUŞMA ÖZETİ]")
        assert any(
            m.content == "kisa ozet" or "KONUŞMA ÖZETİ" in m.content
            for m in mem.db.messages[mem.active_session_id]
        )

        old_sid = mem.active_session_id
        await mem.clear()
        assert mem.get_last_file() is None
        assert mem.active_session_id != old_sid
        assert await mem.get_history() == []

    asyncio.run(scenario())


def test_compaction_and_nightly(mem):
    async def scenario():
        await mem.initialize()
        await mem.set_active_user("u1")
        sid = mem.active_session_id

        for i in range(13):
            await mem.add("user" if i % 2 == 0 else "assistant", f"msg {i} /api/test.py")

        skipped = await mem.compact_session(user_id="u1", session_id=sid, min_messages=99)
        assert skipped["status"] == "skipped"

        compacted = await mem.compact_session(
            user_id="u1", session_id=sid, keep_last=2, min_messages=3
        )
        assert compacted["status"] == "compacted"
        assert compacted["messages_after"] >= 2

        missing = await mem.compact_session(user_id="u1", session_id="none", min_messages=1)
        assert missing["status"] == "missing"

        # second user/session so nightly skip+compact branches run
        await mem.set_active_user("u2")
        sid2 = mem.active_session_id
        for i in range(5):
            await mem.add("user", f"u2-{i}")

        mem.db.users_with_quotas = [{"id": "u1"}, {"id": "u2"}]
        report = await mem.run_nightly_consolidation(keep_recent_sessions=0, min_messages=3)
        assert report["status"] == "completed"
        assert sid2 in report["session_ids"]

        async def boom():
            raise RuntimeError("db fail")

        mem.db.list_users_with_quotas = boom
        mem.active_user_id = "u3"
        fallback = await mem.run_nightly_consolidation(keep_recent_sessions=1, min_messages=100)
        assert fallback["users_scanned"] >= 1

    asyncio.run(scenario())


def test_static_helpers_and_noop_methods(mem):
    assert ConversationMemory._parse_iso_ts("2024-01-01T00:00:00Z") > 0
    assert ConversationMemory._parse_iso_ts("x") == 0.0

    summary = ConversationMemory._build_compaction_summary(
        "Baslik",
        [
            types.SimpleNamespace(role="user", content="kod: app.py"),
            types.SimpleNamespace(role="assistant", content="```print(1)```"),
        ],
    )
    assert "Oturum başlığı" in summary
    assert "Kod/araç referansı" in summary

    assert ConversationMemory._safe_ts("bad") > 0
    mem._dirty = True
    mem.force_save()
    assert mem._dirty is False
    mem._save(force=True)
    assert mem._cleanup_broken_files() is None


def test_del_swallows_exceptions(mem, monkeypatch):
    monkeypatch.setattr(mem, "force_save", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    mem.__del__()


def test_constructor_defaults_and_ensure_initialized_lock(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(memory_module, "Database", FakeDB)
    monkeypatch.chdir(tmp_path)
    cfg = types.SimpleNamespace(DATABASE_URL="", BASE_DIR=str(tmp_path))
    monkeypatch.setattr(memory_module, "get_config", lambda: cfg)

    mem = ConversationMemory()
    assert mem.sessions_dir == Path.cwd() / "data" / "sessions"
    assert "sidar_memory.db" in mem.cfg.DATABASE_URL

    asyncio.run(mem._ensure_initialized())
    assert mem._initialized is True
    assert mem._init_lock is not None


def test_async_branches_for_existing_session_and_noop_paths(mem):
    async def scenario():
        await mem.initialize()
        await mem.set_active_user("u1")
        first_sid = mem.active_session_id
        await mem.create_session("ikinci")
        second_sid = mem.active_session_id
        # delete active session while another session exists -> load_session branch
        assert await mem.delete_session(second_sid) is True
        assert mem.active_session_id == first_sid

        # update_title early-return when no active session id
        mem.active_session_id = None
        await mem.update_title("noop")

        # add() creates session when missing
        await mem.add("user", "auto-create")
        assert mem.active_session_id is not None

        # set_active_user with existing sessions path
        sid_before = mem.active_session_id
        await mem.set_active_user("u1", "alice")
        assert mem.active_session_id == sid_before

        # apply_summary / clear early-return branches (sid/uid missing)
        mem.active_session_id = None
        mem.active_user_id = None
        await mem.apply_summary("s")
        await mem.clear()

    asyncio.run(scenario())


def test_estimate_tokens_importerror_and_misc_branches(monkeypatch, mem):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("no tiktoken")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    assert __import__("json").__name__ == "json"
    mem._turns = [{"role": "u", "content": "x" * 35}]
    assert mem._estimate_tokens() == 10

    summary = ConversationMemory._build_compaction_summary(
        "Baslik",
        [
            types.SimpleNamespace(role="assistant", content=""),
            types.SimpleNamespace(role="assistant", content="yanit"),
        ],
    )
    assert "Öne çıkan kullanıcı istekleri" not in summary
    assert "Öne çıkan SİDAR çıktıları" in summary

    # _save(force=False) no-op branch
    mem._dirty = True
    mem._save(force=False)
    assert mem._dirty is True


def test_nightly_consolidation_skip_and_non_compacted_report(mem):
    async def scenario():
        await mem.initialize()
        await mem.set_active_user("u1")
        for i in range(5):
            await mem.add("user", f"m-{i}")

        mem.db.users_with_quotas = [{"id": "u1"}]
        report = await mem.run_nightly_consolidation(keep_recent_sessions=1, min_messages=99)
        assert report["status"] == "completed"
        assert report["sessions_compacted"] == 0

    asyncio.run(scenario())


def test_ensure_initialized_with_existing_lock_and_inner_already_initialized(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setattr(memory_module, "Database", FakeDB)
    mem = ConversationMemory(base_dir=tmp_path)
    mem._initialized = False
    mem._init_lock = asyncio.Lock()

    async def scenario():
        await mem._ensure_initialized()  # _init_lock zaten var -> 107->109 false branch
        assert mem._initialized is True

        class FlipLock:
            async def __aenter__(self):
                mem._initialized = True
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        mem._initialized = False
        mem._init_lock = FlipLock()
        await mem._ensure_initialized()  # lock içinde _initialized=True -> 110->exit
        assert mem._initialized is True

    asyncio.run(scenario())


def test_delete_non_active_session_and_nightly_skipped_report_branch(mem):
    async def scenario():
        await mem.initialize()
        await mem.set_active_user("u1")
        sid1 = mem.active_session_id
        sid2 = await mem.create_session("ikinci")
        # active session sid2 iken sid1 silinir -> active_session_id koşulu false
        assert await mem.delete_session(sid1) is True
        assert mem.active_session_id == sid2

        # report compacted değil (skipped) -> 399->390 false branch
        for i in range(5):
            await mem.add("user", f"s-{i}")
        mem.db.users_with_quotas = [{"id": "u1"}]
        report = await mem.run_nightly_consolidation(keep_recent_sessions=0, min_messages=99)
        assert report["sessions_compacted"] == 0
        assert report["reports"] and report["reports"][0]["status"] == "skipped"

    asyncio.run(scenario())
