import asyncio
from unittest.mock import patch

import pytest

from core.memory import ConversationMemory, MemoryAuthError


def _activate_user(mem: ConversationMemory, username: str = "tester") -> None:
    asyncio.run(mem.initialize())
    user = asyncio.run(mem.db.ensure_user(username, role="user"))
    asyncio.run(mem.set_active_user(user.id, user.username))


def test_memory_requires_user_context_before_stateful_ops(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    with pytest.raises(MemoryAuthError):
        asyncio.run(mem.add("user", "merhaba"))

    with pytest.raises(MemoryAuthError):
        asyncio.run(mem.get_all_sessions())


def test_memory_set_active_user_creates_session_and_persists_messages(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)
    _activate_user(mem, "alice")

    assert mem.active_user_id
    assert mem.active_session_id
    
    asyncio.run(mem.add("user", "merhaba"))
    asyncio.run(mem.add("assistant", "selam"))
    asyncio.run(mem.add("user", "u1"))
    asyncio.run(mem.add("assistant", "a1"))

    hist = asyncio.run(mem.get_history())
    assert len(hist) == 4
    assert hist[-1]["content"] == "a1"


def test_memory_async_roundtrip_load_and_delete(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    async def _run():
        await mem.initialize()
        user = await mem.db.ensure_user("bob", role="user")
        await mem.set_active_user(user.id, user.username)
        sid = await mem.create_session("deneme")
        await mem.add("user", "x")
        await mem.add("assistant", "y")
        ok = await mem.load_session(sid)
        deleted = await mem.delete_session(sid)
        return ok, deleted, await mem.get_all_sessions()

    ok, deleted, sessions = asyncio.run(_run())
    assert ok is True
    assert deleted is True
    assert isinstance(sessions, list)


def test_apply_summary_keeps_last_turns(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=50, keep_last=2)
    _activate_user(mem, "charlie")

    for i in range(1, 5):
        asyncio.run(mem.add("user", f"Soru {i}"))
        asyncio.run(mem.add("assistant", f"Cevap {i}"))

    asyncio.run(mem.apply_summary("özet metni"))
    turns = asyncio.run(mem.get_history())

    assert len(turns) == 4
    assert "özeti" in turns[0]["content"].lower()
    assert "özet metni" in turns[1]["content"]
    assert turns[2]["content"] == "Soru 4"
    assert turns[3]["content"] == "Cevap 4"


def test_clear_recreates_active_session(tmp_path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)
    _activate_user(mem, "dora")

    first_session = mem.active_session_id
    asyncio.run(mem.add("user", "deneme"))
    asyncio.run(mem.clear())

    assert mem.active_session_id
    assert mem.active_session_id != first_session
    assert asyncio.run(mem.get_history()) == []


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
        await mem.initialize()
        user = await mem.db.ensure_user("frank", role="user")
        await mem.set_active_user(user.id, user.username)
        last_session_id = mem.active_session_id

        deleted = await mem.delete_session(last_session_id)
        sessions = await mem.get_all_sessions()
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
