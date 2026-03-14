# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

from tests.test_rag_runtime_extended import _load_rag_module, _new_store


def test_recursive_chunk_text_handles_separatorless_large_text(tmp_path):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    huge = "A" * 2000
    chunks = store._recursive_chunk_text(huge, size=128, overlap=16)

    assert chunks
    assert all(len(c) <= 128 for c in chunks)
    assert "".join(chunks).startswith("A" * 128)


def test_recursive_chunk_text_applies_overlap_when_next_part_exceeds_limit(tmp_path):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    chunks = store._recursive_chunk_text("hello def world", size=10, overlap=2)

    assert chunks == ["hello def", "ef world"]


def test_recursive_chunk_text_small_text_hits_inner_early_return(tmp_path):
    """Metin zaten size'dan küçükse _split içindeki erken-dönüş (satır 276) çalışmalı."""
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    result = store._recursive_chunk_text("kısa metin", size=200, overlap=0)

    assert result == ["kısa metin"]


def test_recursive_chunk_text_zero_size_hits_force_split(tmp_path):
    """size=0 verilince ayırıcılar tükenir ve zorla bölme (satır 280-281) tetiklenir."""
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    result = store._recursive_chunk_text("ab", size=0, overlap=0)

    assert result
    assert all(isinstance(c, str) for c in result)