from pathlib import Path
import importlib.util


def _load_memory_module():
    spec = importlib.util.spec_from_file_location("sidar_core_memory", Path("core/memory.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_memory_sliding_window(tmp_path: Path):
    """Kayan pencere stratejisi son 2 turu korur ve özet bloklarını ekler."""
    mod = _load_memory_module()
    ConversationMemory = mod.ConversationMemory

    mem_file = tmp_path / "test_session.json"
    memory = ConversationMemory(file_path=mem_file, max_turns=50, keep_last=2)

    for i in range(1, 6):
        memory.add("user", f"Soru {i}")
        memory.add("assistant", f"Cevap {i}")

    assert len(memory.get_history()) == 10, "Başlangıçta 10 mesaj olmalı."

    memory.apply_summary("Bu bir test özetidir.")
    turns = memory.get_history()

    assert len(turns) == 4, f"Özet sonrası mesaj sayısı 4 olmalı, {len(turns)} bulundu."
    assert "özeti istendi" in turns[0]["content"]
    assert "Bu bir test özetidir." in turns[1]["content"]
    assert turns[2]["content"] == "Soru 5"
    assert turns[3]["content"] == "Cevap 5"