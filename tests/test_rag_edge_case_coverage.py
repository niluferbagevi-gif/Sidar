import importlib.util
import sys
import types
from pathlib import Path


def _load_rag_module(module_name: str = "rag_edge_under_test"):
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 80
        RAG_CHUNK_OVERLAP = 20
        RAG_VECTOR_BACKEND = "chroma"
        AI_PROVIDER = "openai"
        RAG_LOCAL_ENABLE_HYBRID = False
        HF_TOKEN = ""
        HF_HUB_OFFLINE = False
        DATABASE_URL = ""
        PGVECTOR_TABLE = "rag_embeddings"
        PGVECTOR_EMBEDDING_DIM = 384
        PGVECTOR_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

    cfg_mod.Config = _Cfg
    prev_cfg = sys.modules.get("config")
    sys.modules["config"] = cfg_mod
    try:
        spec = importlib.util.spec_from_file_location(module_name, Path("core/rag.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if prev_cfg is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev_cfg


def test_build_embedding_function_import_error_falls_back_to_none(monkeypatch):
    rag_mod = _load_rag_module("rag_edge_embedding")

    real_import = __import__

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("chromadb") or name == "torch":
            raise ImportError("missing for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _blocked_import)
    assert rag_mod._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True) is None


def test_pgvector_backend_missing_dependency_disables_engine(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_pgvector")
    DocumentStore = rag_mod.DocumentStore

    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=80,
        RAG_CHUNK_OVERLAP=20,
        RAG_VECTOR_BACKEND="pgvector",
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost/db",
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=384,
        PGVECTOR_EMBEDDING_MODEL="all-MiniLM-L6-v2",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
    )

    def _fake_check_import(self, module_name: str) -> bool:
        return module_name == "chromadb"

    monkeypatch.setattr(DocumentStore, "_check_import", _fake_check_import)
    store = DocumentStore(tmp_path / "rag_pgvector_missing", cfg=cfg)

    assert store._vector_backend == "pgvector"
    assert store._pgvector_available is False
    assert store._chroma_available is False


def test_recursive_chunk_text_handles_very_long_single_token(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_chunk")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(tmp_path / "rag_chunk", cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False))
    chunks = store._recursive_chunk_text("x" * 10_000, size=64, overlap=8)

    assert len(chunks) > 100
    assert all(len(chunk) <= 64 for chunk in chunks)


def test_fetch_pgvector_gracefully_handles_malformed_embedding_result(tmp_path, monkeypatch):
    rag_mod = _load_rag_module("rag_edge_pg_fetch")
    DocumentStore = rag_mod.DocumentStore
    monkeypatch.setattr(DocumentStore, "_check_import", lambda self, _: False)

    store = DocumentStore(tmp_path / "rag_pg_fetch", cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=64, RAG_CHUNK_OVERLAP=8, HF_TOKEN="", HF_HUB_OFFLINE=False))

    store._pgvector_available = True
    store.pg_engine = object()
    store._pgvector_embed_texts = lambda _texts: []

    assert store._fetch_pgvector("test", top_k=3, session_id="s1") == []