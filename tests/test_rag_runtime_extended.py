import importlib.util
import json
import sys
import threading
import types
from pathlib import Path


def _load_rag_module(tmp_path: Path):
    cfg_mod = types.ModuleType("config")

    class _Cfg:
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 50
        RAG_CHUNK_OVERLAP = 10
        HF_TOKEN = ""
        HF_HUB_OFFLINE = False

    cfg_mod.Config = _Cfg
    prev = sys.modules.get("config")
    try:
        sys.modules["config"] = cfg_mod
        spec = importlib.util.spec_from_file_location("rag_runtime_ext", Path("core/rag.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        if prev is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = prev


def _new_store(mod, tmp_path: Path):
    monkey_cfg = types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=50, RAG_CHUNK_OVERLAP=10, HF_TOKEN="", HF_HUB_OFFLINE=False)
    DocumentStore = mod.DocumentStore
    old = DocumentStore._check_import
    try:
        DocumentStore._check_import = lambda self, _: False
        return DocumentStore(tmp_path / "rag_store", cfg=monkey_cfg)
    finally:
        DocumentStore._check_import = old


def test_embedding_function_gpu_fp16_and_exception_paths(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)

    # gpu mixed precision path
    ef_mod = types.ModuleType("chromadb.utils.embedding_functions")

    class _EF:
        def __call__(self, input):
            return [f"ok:{len(input)}"]

    ef_mod.SentenceTransformerEmbeddingFunction = lambda **kwargs: _EF()

    torch_mod = types.ModuleType("torch")
    torch_mod.cuda = types.SimpleNamespace(is_available=lambda: True)
    torch_mod.float16 = "fp16"

    class _Auto:
        def __enter__(self):
            return None

        def __exit__(self, *args):
            return False

    torch_mod.autocast = lambda **kwargs: _Auto()
    torch_amp = types.ModuleType("torch.amp")

    monkeypatch.setitem(sys.modules, "chromadb.utils.embedding_functions", ef_mod)
    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    monkeypatch.setitem(sys.modules, "torch.amp", torch_amp)

    ef = mod._build_embedding_function(use_gpu=True, gpu_device=1, mixed_precision=True)
    assert ef is not None

    # exception fallback path
    monkeypatch.delitem(sys.modules, "chromadb.utils.embedding_functions", raising=False)
    assert mod._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=False) is None


def test_env_import_and_load_index_error_paths(tmp_path):
    mod = _load_rag_module(tmp_path)
    store = _new_store(mod, tmp_path)

    store.cfg.HF_TOKEN = "tok"
    store.cfg.HF_HUB_OFFLINE = True
    store._apply_hf_runtime_env()
    assert "HF_HUB_OFFLINE" in __import__("os").environ
    assert "TRANSFORMERS_OFFLINE" in __import__("os").environ

    assert store._check_import("this_module_does_not_exist_xyz") is False

    # _load_index bad json warning path
    broken = store.store_dir / "index.json"
    broken.write_text("{bad", encoding="utf-8")
    store2 = mod.DocumentStore.__new__(mod.DocumentStore)
    store2.index_file = broken
    assert store2._load_index() == {}


def test_init_chroma_and_init_fts_migration_paths(tmp_path, monkeypatch):
    mod = _load_rag_module(tmp_path)

    # Prepare migration inputs for _init_fts lines 222-233
    sdir = tmp_path / "rag_mig"
    sdir.mkdir()
    idx = {"d1": {"session_id": "s1"}, "d2": {"session_id": "s1"}}
    (sdir / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    (sdir / "d1.txt").write_text("hello", encoding="utf-8")
    # d2.txt missing -> except pass path

    DocumentStore = mod.DocumentStore
    old = DocumentStore._check_import
    try:
        DocumentStore._check_import = lambda self, _: False
        st = DocumentStore(sdir, cfg=types.SimpleNamespace(RAG_TOP_K=3, RAG_CHUNK_SIZE=50, RAG_CHUNK_OVERLAP=10, HF_TOKEN="", HF_HUB_OFFLINE=False))
    finally:
        DocumentStore._check_import = old
    rows = st.fts_conn.execute("SELECT doc_id FROM bm25_index").fetchall()
    assert any(r["doc_id"] == "d1" for r in rows)

    # _init_chroma exception lines 198-200
    chroma_mod = types.ModuleType("chromadb")

    class _BrokenClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("boom")

    chroma_mod.PersistentClient = _BrokenClient
    monkeypatch.setitem(sys.modules, "chromadb", chroma_mod)

    st2 = mod.DocumentStore.__new__(mod.DocumentStore)
    st2.store_dir = tmp_path
    st2._use_gpu = False
    st2._gpu_device = 0
    st2._mixed_precision = False
    st2._chroma_available = True
    st2.cfg = types.SimpleNamespace(HF_TOKEN="", HF_HUB_OFFLINE=False)
    st2._apply_hf_runtime_env = lambda: None
    st2._init_chroma()
    assert st2._chroma_available is False


def test_document_and_search_error_and_fallback_paths(tmp_path):
    mod = _load_rag_module(tmp_path)
    st = _new_store(mod, tmp_path)

    # chunk/text helpers
    assert st._recursive_chunk_text("", size=10, overlap=2) == []
    assert st._recursive_chunk_text("abcdef", size=2, overlap=2)

    # add_document chroma exception lines 390-391
    class _BrokenCol:
        def delete(self, **kwargs):
            raise RuntimeError("chroma add fail")

    st._chroma_available = True
    st.collection = _BrokenCol()
    doc_id = st.add_document("T", "content", session_id="s1")
    assert doc_id

    # add_document_from_url exception lines 410-412
    httpx_mod = types.ModuleType("httpx")

    class _FailClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, _url):
            raise RuntimeError("network fail")

    httpx_mod.AsyncClient = _FailClient
    sys.modules["httpx"] = httpx_mod
    ok, msg = __import__("asyncio").run(st.add_document_from_url("https://example.invalid"))
    assert ok is False and "eklenemedi" in msg

    # add_document_from_file exception lines 429-431
    orig_resolve = Path.resolve
    Path.resolve = lambda self: (_ for _ in ()).throw(RuntimeError("resolve fail"))
    try:
        ok, msg = st.add_document_from_file("x.txt")
    finally:
        Path.resolve = orig_resolve
    assert ok is False and "Dosya eklenemedi" in msg

    # delete/get guards
    assert "bulunamadı" in st.delete_document("none")
    st._index[doc_id]["session_id"] = "other"
    assert "yetkiniz yok" in st.delete_document(doc_id, session_id="s1")
    assert st.get_document("none")[0] is False
    assert st.get_document(doc_id, session_id="s1")[0] is False

    # missing file branch in get_document
    st._index[doc_id]["session_id"] = "s1"
    f = st.store_dir / f"{doc_id}.txt"
    if f.exists():
        f.unlink()
    assert "dosyası eksik" in st.get_document(doc_id, session_id="s1")[1]

    # search mode guards and keyword fallback line 534
    st._index = {"a": {"session_id": "s1", "title": "A", "tags": [], "source": ""}}
    st._chroma_available = False
    assert "kullanılamıyor" in st.search("q", mode="vector", session_id="s1")[1]
    st._bm25_available = False
    assert "BM25 kullanılamıyor" in st.search("q", mode="bm25", session_id="s1")[1]
    st._bm25_available = False
    st._chroma_available = False
    st._keyword_search = lambda *args: (True, "kw")
    assert st.search("q", mode="auto", session_id="s1") == (True, "kw")


def test_chunk_text_none_argument_and_cfg_fallback(tmp_path):
    mod = _load_rag_module(tmp_path)
    st = _new_store(mod, tmp_path)

    # cfg'den fallback alınır
    out = st._chunk_text("a" * 120, chunk_size=None, chunk_overlap=None)
    assert isinstance(out, list) and out

    # cfg değerleri yoksa instance default'larına fallback
    st.cfg = types.SimpleNamespace()
    st._chunk_size = 30
    st._chunk_overlap = 5
    out2 = st._chunk_text("b" * 80, chunk_size=None, chunk_overlap=None)
    assert isinstance(out2, list) and out2


def test_low_level_fetch_and_format_status_paths(tmp_path):
    mod = _load_rag_module(tmp_path)
    st = _new_store(mod, tmp_path)

    # _fetch_chroma count exception path + _chroma_search
    class _Col:
        def count(self):
            raise RuntimeError("count fail")

        def query(self, **kwargs):
            return {"ids": [["c1"]], "documents": [["snip"]], "metadatas": [[{"parent_id": "p1", "title": "T", "source": "S"}] ]}

    st.collection = _Col()
    st._chroma_available = True
    ok, out = st._chroma_search("q", 1, "global")
    assert ok is True and "Vektör Arama" in out

    # bm25 cache no-op branches
    st._bm25_available = False
    st._update_bm25_cache_on_add("d", "x")
    st._update_bm25_cache_on_delete("d")

    # _fetch_bm25 unavailable / empty tokens / missing file
    assert st._fetch_bm25("q", 1, "global") == []
    st._bm25_available = True

    class _Conn:
        def execute(self, *_args):
            class _Cur:
                def fetchall(self):
                    return [{"doc_id": "d1", "score": -1.2}]

            return _Cur()

    st.fts_conn = _Conn()
    st._index = {"d1": {"title": "Doc", "source": "", "session_id": "global", "tags": []}}
    res = st._fetch_bm25('""', 1, "global")
    assert res == []
    res2 = st._fetch_bm25("python", 1, "global")
    assert res2 and res2[0]["id"] == "d1"

    # keyword path with missing files + format empty + snippet trim/fallback
    st._index = {"k1": {"title": "Title", "source": "", "session_id": "global", "tags": []}}
    ok2, text2 = st._keyword_search("hello", 1, "global")
    assert ok2 is False and "bulunamadı" in text2

    ok3, text3 = st._format_results_from_struct([{"id": "1", "title": "t", "source": "s", "snippet": "x" * 450, "score": 1}], "q", "M")
    assert ok3 is True and "..." in text3
    assert st._extract_snippet("abcdef", "zzz", window=3).endswith("...")

    st._index = {}
    assert "boş" in st.list_documents(session_id="global")
    st._chroma_available = False
    st._bm25_available = False
    assert "Anahtar Kelime" in st.status()
