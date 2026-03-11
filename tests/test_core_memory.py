import asyncio
import importlib.util
from pathlib import Path


def _load_memory_module():
    spec = importlib.util.spec_from_file_location("sidar_core_memory", Path("core/memory.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_memory_sliding_window(tmp_path: Path):
    """Kayan pencere stratejisi son 1 turu korur ve özet bloklarını ekler."""
    mod = _load_memory_module()
    ConversationMemory = mod.ConversationMemory

    memory = ConversationMemory(file_path=tmp_path / "test_session.json", max_turns=50, keep_last=2)
    user = asyncio.run(memory.db.ensure_user("window_user", role="user"))
    memory.set_active_user(user.id, user.username)

    for i in range(1, 6):
        memory.add("user", f"Soru {i}")
        memory.add("assistant", f"Cevap {i}")

    assert len(memory.get_history()) == 10

    memory.apply_summary("Bu bir test özetidir.")
    turns = memory.get_history()

    assert len(turns) == 4
    assert "özeti istendi" in turns[0]["content"]
    assert "Bu bir test özetidir." in turns[1]["content"]
    assert turns[2]["content"] == "Soru 5"
    assert turns[3]["content"] == "Cevap 5"