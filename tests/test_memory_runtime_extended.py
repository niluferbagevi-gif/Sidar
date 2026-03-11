import asyncio
from unittest.mock import patch

import pytest

from core.memory import ConversationMemory, MemoryAuthError


def _activate_user(mem: ConversationMemory, username: str = "tester") -> None:
    user = asyncio.run(mem.db.ensure_user(username, role="user"))
    mem.set_active_user(user.id, user.username)


def test_memory_requires_user_context_before_stateful_ops(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    with pytest.raises(MemoryAuthError):
        mem.add("user", "merhaba")

    with pytest.raises(MemoryAuthError):
        mem.get_all_sessions()


def test_memory_set_active_user_creates_session_and_persists_messages(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)
    _activate_user(mem, "alice")

    assert mem.active_user_id
    assert mem.active_session_id

    mem.add("user", "u1")
    mem.add("assistant", "a1")

    hist = mem.get_history()
    assert len(hist) == 2
    assert hist[-1]["content"] == "a1"


def test_memory_async_roundtrip_load_and_delete(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    async def _run():
        user = await mem.db.ensure_user("bob", role="user")
        await mem.aset_active_user(user.id, user.username)
        sid = await mem.acreate_session("deneme")
        await mem.aadd("user", "x")
        await mem.aadd("assistant", "y")
        ok = await mem.aload_session(sid)
        deleted = await mem.adelete_session(sid)
        return ok, deleted, await mem.aget_all_sessions()

    ok, deleted, sessions = asyncio.run(_run())
    assert ok is True
    assert deleted is True
    assert isinstance(sessions, list)


def test_apply_summary_keeps_last_turns(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=50, keep_last=2)
    _activate_user(mem, "charlie")

    for i in range(1, 5):
        mem.add("user", f"Soru {i}")
        mem.add("assistant", f"Cevap {i}")

    mem.apply_summary("özet metni")
    turns = mem.get_history()

    assert len(turns) == 4
    assert "özeti" in turns[0]["content"].lower()
    assert "özet metni" in turns[1]["content"]
    assert turns[2]["content"] == "Soru 4"
    assert turns[3]["content"] == "Cevap 4"


def test_clear_recreates_active_session(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)
    _activate_user(mem, "dora")

    first_session = mem.active_session_id
    mem.add("user", "deneme")
    mem.clear()

    assert mem.active_session_id
    assert mem.active_session_id != first_session
    assert mem.get_history() == []


def test_cleanup_broken_files_is_noop_in_db_mode(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)
    _activate_user(mem, "eve")

    broken = mem.sessions_dir / "legacy.json.broken"
    broken.write_text("{}", encoding="utf-8")

    mem._cleanup_broken_files(max_age_days=0, max_files=0)
    assert broken.exists()


def test_memory_delete_last_session_creates_new_session(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    async def _run():
        user = await mem.db.ensure_user("frank", role="user")
        await mem.aset_active_user(user.id, user.username)
        last_session_id = mem.active_session_id

        deleted = await mem.adelete_session(last_session_id)
        sessions = await mem.aget_all_sessions()
        return last_session_id, deleted, sessions

    last_session_id, deleted, sessions = asyncio.run(_run())
    assert deleted is True
    assert mem.active_session_id is not None
    assert mem.active_session_id != last_session_id
    assert mem.active_title == "Yeni Sohbet"
    assert len(sessions) == 1


def test_memory_del_calls_force_save_and_swallows_exceptions(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    mem.__del__()

    with patch.object(mem, "force_save", side_effect=Exception("save-fail")):
        mem.__del__()

def test_estimate_tokens_importerror_fallback(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)
    content = "Bu bir test mesajıdır ve token fallback hesabı çalışmalıdır."
    mem._turns = [{"role": "user", "content": content}]

    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("simulated missing tiktoken")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_fake_import):
        token_count = mem._estimate_tokens()

    assert token_count == int(len(content) / 3.5)
