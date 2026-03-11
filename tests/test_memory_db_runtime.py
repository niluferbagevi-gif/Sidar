import asyncio
from pathlib import Path

from core.memory import ConversationMemory


def test_memory_bootstraps_default_admin_and_binds_sessions(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    assert mem.active_user_id
    assert mem.active_session_id

    mem.add("user", "merhaba")
    mem.add("assistant", "selam")

    history = mem.get_history()
    assert len(history) >= 2
    assert history[-1]["content"] == "selam"


def test_memory_async_session_methods_work(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    async def _run():
        sid = await mem.acreate_session("DB Session")
        await mem.aadd("user", "u1")
        await mem.aadd("assistant", "a1")
        ok = await mem.aload_session(sid)
        sessions = await mem.aget_all_sessions()
        return ok, sessions, await mem.aget_history()

    ok, sessions, hist = asyncio.run(_run())
    assert ok is True
    assert any(s["id"] for s in sessions)
    assert len(hist) == 2
