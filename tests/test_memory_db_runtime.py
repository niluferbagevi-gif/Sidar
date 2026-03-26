import asyncio
from pathlib import Path

from core.memory import ConversationMemory


def test_memory_bootstraps_default_admin_and_binds_sessions(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    asyncio.run(mem.initialize())
    user = asyncio.run(mem.db.ensure_user("default_user", role="user"))
    asyncio.run(mem.set_active_user(user.id, user.username))

    assert mem.active_user_id
    assert mem.active_session_id

    asyncio.run(mem.add("user", "merhaba"))
    asyncio.run(mem.add("assistant", "selam"))

    history = asyncio.run(mem.get_history())
    assert len(history) >= 2
    assert history[-1]["content"] == "selam"


def test_memory_async_session_methods_work(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=10)

    async def _run():
        await mem.initialize()
        user = await mem.db.ensure_user("runtime_user", role="user")
        await mem.set_active_user(user.id, user.username)
        sid = await mem.create_session("DB Session")
        await mem.add("user", "u1")
        await mem.add("assistant", "a1")
        ok = await mem.load_session(sid)
        sessions = await mem.get_all_sessions()
        return ok, sessions, await mem.get_history()

    ok, sessions, hist = asyncio.run(_run())
    assert ok is True
    assert any(s["id"] for s in sessions)
    assert len(hist) == 2

def test_memory_large_history_retrieval_performance(tmp_path: Path):
    mem = ConversationMemory(file_path=tmp_path / "memory.json", max_turns=6000)
    asyncio.run(mem.initialize())
    user = asyncio.run(mem.db.ensure_user("perf_user", role="user"))
    asyncio.run(mem.set_active_user(user.id, user.username))

    for i in range(1200):
        asyncio.run(mem.add("user", f"u-{i}"))
        asyncio.run(mem.add("assistant", f"a-{i}"))

    import time
    start = time.monotonic()
    hist = asyncio.run(mem.get_history())
    elapsed = time.monotonic() - start

    assert len(hist) >= 2400
    assert elapsed < 2.0