import sys
import types

from tests.test_rag_edge_case_coverage import _load_rag_module
from tests.test_rag_runtime_extended import _new_store


def test_init_chroma_disables_backend_when_embedding_model_init_raises(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_chroma_embed_init_fail")
    DocumentStore = rag_mod.DocumentStore
    errors = []

    class _Client:
        def get_or_create_collection(self, **_kwargs):
            return object()

    chromadb_mod = types.SimpleNamespace(PersistentClient=lambda path: _Client())

    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="chroma",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
    )

    monkeypatch.setitem(sys.modules, "chromadb", chromadb_mod)
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, module_name: module_name == "chromadb")
    monkeypatch.setattr(rag_mod, "_build_embedding_function", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("embed init failed")))
    monkeypatch.setattr(rag_mod.logger, "error", lambda msg, *args: errors.append(msg % args if args else msg))

    store = DocumentStore(tmp_path / "rag_chroma_embed_init_fail", cfg=cfg)

    assert store._chroma_available is False
    assert any("ChromaDB başlatma hatası" in msg and "embed init failed" in msg for msg in errors)


def test_fetch_chroma_returns_empty_when_vector_db_has_no_ids(tmp_path):
    rag_mod = _load_rag_module("rag_chroma_empty_ids")
    store = _new_store(rag_mod, tmp_path)

    class _Collection:
        def count(self):
            return 0

        def query(self, **_kwargs):
            return {"ids": [[]], "documents": [[]], "metadatas": [[]]}

    store.collection = _Collection()

    assert store._fetch_chroma("needle", top_k=2, session_id="s1") == []


def test_fetch_chroma_uses_id_and_defaults_when_metadata_is_missing(tmp_path):
    rag_mod = _load_rag_module("rag_chroma_missing_metadata")
    store = _new_store(rag_mod, tmp_path)
    seen = {}

    class _Collection:
        def count(self):
            return 2

        def query(self, **kwargs):
            seen.update(kwargs)
            return {
                "ids": [["chunk-1", "chunk-2"]],
                "documents": [["alpha", "beta"]],
            }

    store.collection = _Collection()

    out = store._fetch_chroma("needle", top_k=2, session_id="session-42")

    assert seen["where"] == {"session_id": "session-42"}
    assert out == [
        {"id": "chunk-1", "title": "?", "source": "", "snippet": "alpha", "score": 1.0},
        {"id": "chunk-2", "title": "?", "source": "", "snippet": "beta", "score": 1.0},
    ]


def test_fetch_chroma_tolerates_invalid_metadata_entries_and_preserves_filter(tmp_path):
    rag_mod = _load_rag_module("rag_chroma_invalid_metadata")
    store = _new_store(rag_mod, tmp_path)
    seen = {}

    class _Collection:
        def count(self):
            return 3

        def query(self, **kwargs):
            seen.update(kwargs)
            return {
                "ids": [["chunk-a", "chunk-b", "chunk-c"]],
                "documents": [["alpha", None, "gamma"]],
                "metadatas": [[None, "bad-meta", {"title": "Doc C", "source": None}]],
            }

    store.collection = _Collection()

    out = store._fetch_chroma("needle", top_k=3, session_id="sess-invalid")

    assert seen["where"] == {"session_id": "sess-invalid"}
    assert [item["id"] for item in out] == ["chunk-a", "chunk-b", "chunk-c"]
    assert out[0]["title"] == "?"
    assert out[1]["title"] == "?"
    assert out[1]["snippet"] == ""
    assert out[2]["title"] == "Doc C"
    assert out[2]["source"] == ""
