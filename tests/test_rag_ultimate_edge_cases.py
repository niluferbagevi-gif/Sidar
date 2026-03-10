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

