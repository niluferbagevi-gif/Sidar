# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

import asyncio
from pathlib import Path

from core.memory import ConversationMemory


def test_memory_bootstraps_default_admin_and_binds_sessions(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    user = asyncio.run(mem.db.ensure_user("default_user", role="user"))
    mem.set_active_user(user.id, user.username)

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
        user = await mem.db.ensure_user("runtime_user", role="user")
        await mem.aset_active_user(user.id, user.username)
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

def test_memory_large_history_retrieval_performance(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=6000)
    user = asyncio.run(mem.db.ensure_user("perf_user", role="user"))
    mem.set_active_user(user.id, user.username)

    for i in range(1200):
        mem.add("user", f"u-{i}")
        mem.add("assistant", f"a-{i}")

    import time
    start = time.monotonic()
    hist = mem.get_history()
    elapsed = time.monotonic() - start

    assert len(hist) >= 2400
    assert elapsed < 2.0