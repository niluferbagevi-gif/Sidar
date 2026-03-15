import types
from pathlib import Path

from tests.test_rag_runtime_extended import _load_rag_module, _new_store


def test_build_embedding_function_fp16_autocast_wrapper_executes(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)

    ef_mod = types.ModuleType("chromadb.utils.embedding_functions")

    class _EF:
        def __call__(self, input):
            return [f"embed:{len(input)}"]

    ef_mod.SentenceTransformerEmbeddingFunction = lambda **kwargs: _EF()

    entered = {"autocast": 0}

    class _Auto:
        def __enter__(self):
            entered["autocast"] += 1
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    torch_mod = types.ModuleType("torch")
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: True)
    torch_mod.float16 = "fp16"
    torch_mod.autocast = lambda **kwargs: _Auto()

    monkeypatch.setitem(__import__("sys").modules, "chromadb.utils.embedding_functions", ef_mod)
    monkeypatch.setitem(__import__("sys").modules, "torch", torch_mod)
    monkeypatch.setitem(__import__("sys").modules, "torch.amp", types.ModuleType("torch.amp"))

    ef = mod._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True)
    assert ef is not None

    # Wrapper'ın gerçekten çalışması için __call__ doğrudan çağrılır.
    out = ef.__call__(["a", "b"])
    assert out == ["embed:2"]
    assert entered["autocast"] == 1


def test_delete_document_returns_already_deleted_when_removed_in_lock(tmp_path):
    mod = _load_rag_module(tmp_path)

    st = mod.DocumentStore.__new__(mod.DocumentStore)
    doc_id = "d-race"
    st._index = {doc_id: {"title": "Race", "session_id": "global"}}

    class _RaceLock:
        def __enter__(self_inner):
            st._index.pop(doc_id, None)
            return None

        def __exit__(self_inner, exc_type, exc, tb):
            return False

    st._write_lock = _RaceLock()

    msg = st.delete_document(doc_id)
    assert "zaten silinmiş" in msg


def test_keyword_search_missing_file_in_result_phase_sets_empty_content(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)
    st = _new_store(mod, tmp_path)

    st._index = {"k1": {"title": "Title", "source": "", "session_id": "global", "tags": []}}
    target = st.store_dir / "k1.txt"

    original_read_text = Path.read_text
    calls = {"target": 0}

    def _patched_read_text(self, *args, **kwargs):
        if self == target:
            calls["target"] += 1
            if calls["target"] == 1:
                return "hello world"
            raise FileNotFoundError("deleted between ranking and formatting")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)

    ok, text = st._keyword_search("hello", 1, "global")
    assert ok is True
    assert "[RAG Arama: hello]" in text
