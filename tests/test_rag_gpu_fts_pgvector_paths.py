import importlib.util
import json
import sys
import types
from pathlib import Path


def _load_rag_module():
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 120
        RAG_CHUNK_OVERLAP = 20
        HF_TOKEN = ""
        HF_HUB_OFFLINE = False

    cfg_mod.Config = _Cfg
    prev = sys.modules.get("config")
    try:
        sys.modules["config"] = cfg_mod
        spec = importlib.util.spec_from_file_location("rag_gpu_fts_pg", Path("core/rag.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        if prev is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev


def test_build_embedding_function_uses_fp16_autocast_on_cuda(monkeypatch):
    mod = _load_rag_module()

    ef_mod = types.ModuleType("chromadb.utils.embedding_functions")
    captured = {}

    class _EF:
        def __call__(self, inputs):
            return [f"ok:{len(inputs)}"]

    def _factory(**kwargs):
        captured["device"] = kwargs.get("device")
        return _EF()

    ef_mod.SentenceTransformerEmbeddingFunction = _factory

    torch_mod = types.ModuleType("torch")
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: True)
    torch_mod.float16 = "fp16"
    torch_mod.amp = types.ModuleType("torch.amp")

    auto_state = {"entered": 0}

    class _Auto:
        def __enter__(self):
            auto_state["entered"] += 1
            return None

        def __exit__(self, *args):
            return False

    torch_mod.autocast = lambda **kwargs: _Auto()

    monkeypatch.setitem(sys.modules, "chromadb.utils.embedding_functions", ef_mod)
    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    monkeypatch.setitem(sys.modules, "torch.amp", torch_mod.amp)

    ef = mod._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True)
    assert ef is not None
    assert captured["device"] == "cuda:0"
    assert ef.__call__(["a", "b"]) == ["ok:2"]
    assert auto_state["entered"] == 1


def test_build_embedding_function_falls_back_to_cpu_when_cuda_unavailable(monkeypatch):
    mod = _load_rag_module()

    ef_mod = types.ModuleType("chromadb.utils.embedding_functions")
    captured = {}

    class _EF:
        def __call__(self, inputs):
            return ["cpu"]

    def _factory(**kwargs):
        captured["device"] = kwargs.get("device")
        return _EF()

    ef_mod.SentenceTransformerEmbeddingFunction = _factory

    torch_mod = types.ModuleType("torch")
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch_mod.float16 = "fp16"

    auto_state = {"entered": 0}

    class _Auto:
        def __enter__(self):
            auto_state["entered"] += 1
            return None

        def __exit__(self, *args):
            return False

    torch_mod.autocast = lambda **kwargs: _Auto()

    monkeypatch.setitem(sys.modules, "chromadb.utils.embedding_functions", ef_mod)
    monkeypatch.setitem(sys.modules, "torch", torch_mod)

    ef = mod._build_embedding_function(use_gpu=True, gpu_device=1, mixed_precision=True)
    assert ef is not None
    assert captured["device"] == "cpu"
    assert ef(["x"]) == ["cpu"]
    assert auto_state["entered"] == 0


def test_init_fts_migrates_existing_docs_and_uses_unicode61_tokenizer(tmp_path):
    mod = _load_rag_module()
    store_dir = tmp_path / "rag_fts"
    store_dir.mkdir()

    idx = {"d1": {"session_id": "s1", "title": "T1", "source": "src"}}
    (store_dir / "index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    (store_dir / "d1.txt").write_text("İstanbul'da çığ riski", encoding="utf-8")

    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=80,
        RAG_CHUNK_OVERLAP=10,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
    )

    old = mod.DocumentStore._check_import
    try:
        mod.DocumentStore._check_import = lambda self, _: False
        st = mod.DocumentStore(store_dir, cfg=cfg)
    finally:
        mod.DocumentStore._check_import = old

    sql = st.fts_conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='bm25_index'"
    ).fetchone()[0]
    assert "unicode61" in sql

    rows = st.fts_conn.execute("SELECT doc_id, content FROM bm25_index").fetchall()
    assert any(r["doc_id"] == "d1" for r in rows)

    results = st._fetch_bm25("Istanbul cig", top_k=3, session_id="s1")
    assert any(r["id"] == "d1" for r in results)


def test_pgvector_backend_disables_chroma_and_initializes_pgvector_path(tmp_path):
    mod = _load_rag_module()
    called = {"chroma": 0, "pg": 0}

    def _fake_chroma(self):
        called["chroma"] += 1

    def _fake_pg(self):
        called["pg"] += 1

    old_check = mod.DocumentStore._check_import
    old_init_chroma = mod.DocumentStore._init_chroma
    old_init_pg = mod.DocumentStore._init_pgvector
    try:
        mod.DocumentStore._check_import = lambda self, name: name == "chromadb"
        mod.DocumentStore._init_chroma = _fake_chroma
        mod.DocumentStore._init_pgvector = _fake_pg

        cfg = types.SimpleNamespace(
            RAG_TOP_K=3,
            RAG_CHUNK_SIZE=64,
            RAG_CHUNK_OVERLAP=8,
            HF_TOKEN="",
            HF_HUB_OFFLINE=False,
            RAG_VECTOR_BACKEND="pgvector",
            DATABASE_URL="postgresql://u:p@localhost:5432/db",
            PGVECTOR_TABLE="rag_embeddings",
            PGVECTOR_EMBEDDING_DIM=384,
            PGVECTOR_EMBEDDING_MODEL="all-MiniLM-L6-v2",
        )
        st = mod.DocumentStore(tmp_path / "rag_pg", cfg=cfg)
    finally:
        mod.DocumentStore._check_import = old_check
        mod.DocumentStore._init_chroma = old_init_chroma
        mod.DocumentStore._init_pgvector = old_init_pg

    assert st._vector_backend == "pgvector"
    assert st._chroma_available is False
    assert called["pg"] == 1
    assert called["chroma"] == 0
