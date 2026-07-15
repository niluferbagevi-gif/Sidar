from __future__ import annotations

import ast
import builtins
import contextlib
import importlib
import json
import os
import sys
import threading
import types
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.asyncio

import core.rag as rag


@pytest.fixture(autouse=True)
def _clear_embedding_function_cache() -> Iterator[None]:
    """Keep monkeypatched embedding factories isolated between RAG tests."""

    rag._build_embedding_function_cached.cache_clear()
    rag._DOCUMENT_STORE_SINGLETONS.clear()
    yield
    rag._build_embedding_function_cached.cache_clear()
    rag._DOCUMENT_STORE_SINGLETONS.clear()


def _make_store_stub(tmp_path: Path) -> rag.DocumentStore:
    store = rag.DocumentStore.__new__(rag.DocumentStore)
    store.cfg = SimpleNamespace(RAG_CHUNK_SIZE=12, RAG_CHUNK_OVERLAP=3)
    store._chunk_size = 12
    store._chunk_overlap = 3
    store.store_dir = tmp_path
    store.index_file = tmp_path / "index.json"
    store._index = {}
    # DocumentStore invariant fields normally created by __init__. Keep this
    # __new__-based stub aligned when pgvector/backend attributes are added.
    # Tests can cover pgvector branches without starting real vector backends.
    store.pg_engine = None
    store._pgvector_available = False
    store._pg_embedding_model = None
    store._pg_table = "rag_embeddings"
    store._pg_embedding_dim = 384
    store._pg_embedding_model_name = "all-MiniLM-L6-v2"
    store._graph_index = rag.GraphIndex(tmp_path)
    return store


async def test_graph_index_basic_node_edge_operations(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    graph.add_node("a.py", node_type="file")
    graph.add_node("b.py", node_type="file")
    graph.add_edge("a.py", "b.py", kind="imports")

    assert graph.neighbors("a.py") == ["b.py"]
    assert graph.reverse_neighbors("b.py") == ["a.py"]
    assert graph.edge_kinds[("a.py", "b.py")] == {"imports"}

    graph.clear()
    assert graph.nodes == {}
    assert graph.edges == {}


async def test_graph_index_normalizers_and_extract_str_literal(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    nested = tmp_path / "src" / "api.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("print('x')", encoding="utf-8")

    assert rag.GraphIndex._normalize_node_id(tmp_path, nested) == "src/api.py"
    assert rag.GraphIndex._endpoint_node_id("get", "health") == "endpoint:GET /health"

    assert graph._extract_str_literal(ast.parse("'abc'").body[0].value) == "abc"
    assert graph._extract_str_literal(ast.parse("123").body[0].value) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/api/users", "/api/users"),
        ("https://localhost:8080/v1/x", "/v1/x"),
        ("http://127.0.0.1:9000", "/"),
        ("users", None),
        ("https://example.com/api", None),
        ("/api/{id}", None),
    ],
)
async def test_graph_index_normalize_endpoint_path(
    tmp_path: Path, raw: str, expected: str | None
) -> None:
    graph = rag.GraphIndex(tmp_path)

    assert graph._normalize_endpoint_path(raw) == expected


async def test_graph_index_python_and_script_import_candidates(tmp_path: Path) -> None:
    root = tmp_path
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("", encoding="utf-8")
    current = pkg / "caller.py"
    current.write_text("", encoding="utf-8")

    py_candidates = rag.GraphIndex._python_import_candidates(current, "mod", 0, root)
    assert (pkg / "mod.py").resolve() in py_candidates

    js_file = pkg / "util.js"
    js_file.write_text("", encoding="utf-8")
    script_candidates = rag.GraphIndex._script_import_candidates(current, "./util", root)
    assert js_file.resolve() in script_candidates


async def test_graph_index_parse_python_source_extracts_deps_defs_calls(tmp_path: Path) -> None:
    root = tmp_path
    app_file = root / "app.py"
    dep = root / "dep.py"
    dep.write_text("", encoding="utf-8")
    app_file.write_text("", encoding="utf-8")

    content = """
import dep

@app.get('/health')
def health():
    return {'ok': True}

def call_it():
    requests.get('/api/ping')
    client.router.get('/ignored')
    client.api.get('/api/pong')
    build_client().get('/api/factory')
"""
    graph = rag.GraphIndex(root)
    deps, defs, calls = graph._parse_python_source(app_file, content)

    assert dep.resolve() in deps
    assert defs[0]["endpoint_id"] == "endpoint:GET /health"
    ids = {call["endpoint_id"] for call in calls}
    assert "endpoint:GET /api/ping" in ids
    assert "endpoint:GET /api/pong" in ids
    assert "endpoint:GET /api/factory" in ids
    assert "endpoint:GET /ignored" not in ids


async def test_graph_index_parse_python_source_handles_syntax_error(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    deps, defs, calls = graph._parse_python_source(tmp_path / "bad.py", "def broken(:\n")

    assert deps == [] and defs == [] and calls == []


async def test_graph_index_extract_script_calls_deduplicates(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    content = """
fetch('/api/items', { method: 'POST' })
fetch('/api/items', { method: 'POST' })
new WebSocket('ws://localhost/ws/stream')
"""

    calls = graph._extract_script_endpoint_calls(content)

    ids = {c["endpoint_id"] for c in calls}
    assert "endpoint:POST /api/items" in ids
    assert "endpoint:WS /ws/stream" in ids
    assert len(calls) == 2


async def test_graph_index_endpoint_call_skip_branches_are_explicit(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    src = """
def call_it():
    requests.get()
    requests.post('relative-path')
    requests.put('/ok')
"""

    _deps, defs, calls = graph._parse_python_source(tmp_path / "client.py", src)

    assert defs == []
    assert calls == [
        {
            "endpoint_id": "endpoint:PUT /ok",
            "method": "PUT",
            "path": "/ok",
        }
    ]


async def test_graph_index_script_endpoint_call_skip_branches_are_explicit(
    tmp_path: Path,
) -> None:
    graph = rag.GraphIndex(tmp_path)

    calls = graph._extract_script_endpoint_calls(
        """
fetch('https://example.com/api/remote')
fetch('/api/local')
new WebSocket('https://example.com/ws/remote')
new WebSocket('/ws/local')
new WebSocket('/ws/local')
"""
    )

    assert calls == [
        {
            "endpoint_id": "endpoint:GET /api/local",
            "method": "GET",
            "path": "/api/local",
        },
        {
            "endpoint_id": "endpoint:WS /ws/local",
            "method": "WS",
            "path": "/ws/local",
        },
    ]


async def test_document_store_add_document_from_file_empty_and_explicit_title(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    captured: dict[str, object] = {}

    def _fake_add(title: str, content: str, source: str, tags: list[str], session_id: str) -> str:
        captured.update(
            title=title,
            content=content,
            source=source,
            tags=tags,
            session_id=session_id,
        )
        return "doc-explicit-title"

    store._add_document_sync = _fake_add  # type: ignore[method-assign]

    empty = tmp_path / "empty.md"
    empty.write_text("   \n", encoding="utf-8")
    ok, message = store.add_document_from_file(str(empty), session_id="s-empty")
    assert ok is False
    assert "Dosya boş" in message

    non_empty = tmp_path / "notes.md"
    non_empty.write_text("body", encoding="utf-8")
    ok, message = store.add_document_from_file(
        str(non_empty), title="Explicit title", tags=["t"], session_id="s-explicit"
    )

    assert ok is True
    assert "doc-explicit-title" in message
    assert captured == {
        "title": "Explicit title",
        "content": "body",
        "source": f"file://{non_empty.resolve()}",
        "tags": ["t"],
        "session_id": "s-explicit",
    }


async def test_graph_index_rebuild_resolve_search_and_impact(tmp_path: Path) -> None:
    root = tmp_path
    (root / "dep.py").write_text("", encoding="utf-8")
    (root / "api.py").write_text(
        "import dep\n@app.get('/health')\ndef health():\n    return 'ok'\nrequests.get('/health')\n",
        encoding="utf-8",
    )
    (root / "caller.js").write_text("fetch('/health')", encoding="utf-8")

    graph = rag.GraphIndex(root)
    summary = graph.rebuild()

    assert summary["nodes"] >= 4
    assert summary["edges"] >= 3
    assert graph.resolve_node_id("API.PY") == "api.py"
    assert graph.resolve_node_id("health") == "endpoint:GET /health"

    path = graph.explain_dependency_path("caller.js", "dep.py")
    assert path == ["caller.js", "endpoint:GET /health", "api.py", "dep.py"]

    impact = graph.impact_analysis("dep.py", max_depth=5)
    assert impact["risk_level"] == "high"
    assert "api.py" in impact["review_targets"]

    related = graph.search_related("api health", top_k=3)
    assert related and related[0]["score"] >= 1


async def test_graph_index_collect_bfs_and_extract_dependencies_non_python(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    adjacency = {"a": {"b", "c"}, "b": {"d"}, "c": set(), "d": set()}

    assert graph._collect_bfs("a", adjacency, max_depth=2) == {"b": 1, "c": 1, "d": 2}
    assert graph._collect_bfs("x", adjacency, max_depth=2) == {}

    file_path = tmp_path / "ui.js"
    dep = tmp_path / "mod.js"
    dep.write_text("", encoding="utf-8")
    content = "import './mod'; fetch('/ok')"
    deps, defs, calls = graph._extract_dependencies(file_path, content)
    assert dep.resolve() in deps
    assert defs == []
    assert calls[0]["path"] == "/ok"


async def test_graph_index_circular(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    graph.add_node("a.py", node_type="file")
    graph.add_node("b.py", node_type="file")
    graph.add_node("c.py", node_type="file")
    graph.add_edge("a.py", "b.py", kind="imports")
    graph.add_edge("b.py", "a.py", kind="imports")
    graph.add_edge("b.py", "c.py", kind="imports")

    assert graph.explain_dependency_path("a.py", "a.py") == ["a.py"]
    assert graph.explain_dependency_path("a.py", "b.py") == ["a.py", "b.py"]
    assert graph.explain_dependency_path("a.py", "c.py") == ["a.py", "b.py", "c.py"]
    assert graph.explain_dependency_path("c.py", "a.py") == []


async def test_graph_index_deep_dependency_path(tmp_path: Path) -> None:
    graph = rag.GraphIndex(tmp_path)
    for node in ("entry.py", "service.py", "repo.py", "client.py", "adapter.py"):
        graph.add_node(node, node_type="file")
    graph.add_edge("entry.py", "service.py", kind="imports")
    graph.add_edge("service.py", "repo.py", kind="imports")
    graph.add_edge("repo.py", "client.py", kind="imports")
    graph.add_edge("client.py", "adapter.py", kind="imports")

    assert graph.explain_dependency_path("entry.py", "adapter.py") == [
        "entry.py",
        "service.py",
        "repo.py",
        "client.py",
        "adapter.py",
    ]


async def test_embed_texts_for_semantic_cache_empty() -> None:
    assert rag.embed_texts_for_semantic_cache([]) == []


async def test_document_store_accepts_injected_embedding_function_builder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    injected_builder = object()
    captured: dict[str, object] = {}
    store = rag.DocumentStore.__new__(rag.DocumentStore)
    store._embedding_function_builder = injected_builder

    def _fake_init_chroma(_store, *, build_embedding_function):
        captured["store"] = _store
        captured["builder"] = build_embedding_function

    monkeypatch.setattr(rag.chroma_backend, "init_chroma", _fake_init_chroma)

    rag.DocumentStore._init_chroma(store)

    assert captured == {"store": store, "builder": injected_builder}


async def test_shared_document_store_keys_custom_embedding_builders(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        RAG_VECTOR_BACKEND="chroma",
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=1000,
        RAG_CHUNK_OVERLAP=200,
        USE_GPU=False,
        GPU_DEVICE=0,
        GPU_MIXED_PRECISION=False,
    )

    def builder_one(**_kwargs):
        return "one"

    def builder_two(**_kwargs):
        return "two"

    store_one = rag.get_shared_document_store(
        store_dir=tmp_path / "shared",
        cfg=cfg,
        initialize_vector=False,
        embedding_function_builder=builder_one,
    )
    store_two = rag.get_shared_document_store(
        store_dir=tmp_path / "shared",
        cfg=cfg,
        initialize_vector=False,
        embedding_function_builder=builder_two,
    )

    assert store_one is not store_two
    assert store_one._embedding_function_builder is builder_one
    assert store_two._embedding_function_builder is builder_two


async def test_shared_document_store_reuses_cached_store_for_same_key(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        RAG_VECTOR_BACKEND="chroma",
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=1000,
        RAG_CHUNK_OVERLAP=200,
        USE_GPU=False,
        GPU_DEVICE=0,
        GPU_MIXED_PRECISION=False,
    )

    store_one = rag.get_shared_document_store(
        store_dir=tmp_path / "shared",
        cfg=cfg,
        initialize_vector=False,
    )
    store_two = rag.get_shared_document_store(
        store_dir=tmp_path / "shared",
        cfg=cfg,
        initialize_vector=False,
    )

    assert store_one is store_two


async def test_public_build_embedding_function_delegates_to_internal_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rag, "_build_embedding_function", lambda **kwargs: kwargs)

    assert rag.build_embedding_function(
        use_gpu=True, gpu_device=2, mixed_precision=True, cfg="cfg"
    ) == {
        "use_gpu": True,
        "gpu_device": 2,
        "mixed_precision": True,
        "cfg": "cfg",
    }


async def test_build_embedding_function_uses_explicit_cpu_without_gpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setenv("TRANSFORMERS_CACHE", str(tmp_path / "transformers"))

    class _EF:
        def __init__(self, model_name: str, device: str, local_files_only: bool) -> None:
            self.model_name = model_name
            self.device = device
            self.local_files_only = local_files_only

    monkeypatch.setitem(
        sys.modules,
        "chromadb.utils.embedding_functions",
        SimpleNamespace(SentenceTransformerEmbeddingFunction=_EF),
    )

    ef = rag._build_embedding_function(use_gpu=False, gpu_device=3)

    assert ef is not None
    assert ef.model_name == "all-MiniLM-L6-v2"
    assert ef.device == "cpu"
    assert ef.local_files_only is False


async def test_document_store_helper_methods(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)

    assert (
        rag.DocumentStore._normalize_pg_url("postgresql+asyncpg://u:p@h/db")
        == "postgresql://u:p@h/db"
    )
    assert (
        rag.DocumentStore._format_vector_for_sql([0.1, 2, 3.333333333])
        == "[0.10000000,2.00000000,3.33333333]"
    )

    chunks = store._recursive_chunk_text("class A\ndef x():\n    pass\n" * 4, size=20, overlap=5)
    assert chunks
    assert max(len(c) for c in chunks) >= 20

    assert store._chunk_text("abcdef", chunk_size=0) == []
    chunked = store._chunk_text("abcdefghijklmno", chunk_size=5, chunk_overlap=-2)
    assert chunked


async def test_document_store_validate_url_safe_accepts_and_blocks() -> None:
    rag.DocumentStore._validate_url_safe("https://example.com/resource")

    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("ftp://example.com/a")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://127.0.0.1/a")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("https://localhost/a")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://10.0.0.8/admin")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://172.16.5.4/internal")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://192.168.1.10/debug")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://169.254.10.10/meta")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://[::1]/loopback")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://[fd00::1]/private-v6")


async def test_document_store_validate_url_safe_resolves_dns_to_public_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _public_getaddrinfo(*_args, **_kwargs):
        return [(rag.socket.AF_INET, rag.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(rag.socket, "getaddrinfo", _public_getaddrinfo)

    rag.DocumentStore._validate_url_safe("https://public.example/resource", resolve_dns=True)


async def test_document_store_validate_url_safe_handles_invalid_and_unresolved_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert rag.DocumentStore._is_public_ip_address("not-an-ip") is False

    def _raise_gaierror(*_args, **_kwargs):
        raise rag.socket.gaierror("no dns")

    monkeypatch.setattr(rag.socket, "getaddrinfo", _raise_gaierror)
    with pytest.raises(ValueError, match="Hostname çözümlenemedi"):
        rag.DocumentStore._validate_url_safe("https://missing.example", resolve_dns=True)

    monkeypatch.setattr(rag.socket, "getaddrinfo", lambda *_args, **_kwargs: [])
    with pytest.raises(ValueError, match="Hostname çözümlenemedi"):
        rag.DocumentStore._validate_url_safe("https://empty.example", resolve_dns=True)


async def test_document_store_validate_url_safe_blocks_dns_private_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _private_getaddrinfo(*_args, **_kwargs):
        return [(rag.socket.AF_INET, rag.socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]

    monkeypatch.setattr(rag.socket, "getaddrinfo", _private_getaddrinfo)

    with pytest.raises(ValueError, match="public olmayan"):
        rag.DocumentStore._validate_url_safe("http://metadata-proxy.example", resolve_dns=True)


async def test_document_store_add_url_blocks_redirect_to_private_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    add_calls: list[tuple[str, str, str]] = []

    async def _add_document(title: str, content: str, source: str, *_args, **_kwargs) -> str:
        add_calls.append((title, content, source))
        return "doc-1"

    store.add_document = _add_document  # type: ignore[method-assign]

    def _getaddrinfo(host: str, port: int, *_args, **_kwargs):
        if host == "public.example":
            return [(rag.socket.AF_INET, rag.socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        if host == "169.254.169.254":
            return [(rag.socket.AF_INET, rag.socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]
        raise AssertionError(f"unexpected host: {host}")

    monkeypatch.setattr(rag.socket, "getaddrinfo", _getaddrinfo)

    class _Response:
        def __init__(self, url: str, status_code: int, *, location: str = "", text: str = ""):
            self.url = url
            self.status_code = status_code
            self.headers = {"Location": location} if location else {}
            self.text = text

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class _AsyncClient:
        def __init__(self, **_kwargs):
            self.calls: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str):
            self.calls.append(url)
            return _Response(url, 302, location="http://169.254.169.254/latest/meta-data")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)

    ok, message = await store.add_document_from_url("https://public.example/start")

    assert ok is False
    assert "İç ağ" in message or "Engellenen hostname" in message
    assert add_calls == []


async def test_document_store_index_get_delete_and_status(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)

    class _DummyLock:
        def __enter__(self) -> _DummyLock:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    store._write_lock = _DummyLock()
    store._save_index = lambda: None
    store._update_bm25_cache_on_delete = lambda _doc_id: None
    store._chroma_available = False
    store.collection = None
    store._pgvector_available = False
    store._bm25_available = True
    store._vector_backend = "chroma"
    store._use_gpu = False
    store._gpu_device = 0
    store._graph_rag_enabled = False

    doc_id = "abc123"
    (tmp_path / f"{doc_id}.txt").write_text("body", encoding="utf-8")
    store._index[doc_id] = {
        "title": "Doc",
        "source": "src",
        "session_id": "s1",
        "size": 4,
        "tags": ["t"],
    }

    docs = store.get_index_info(session_id="s1")
    assert docs[0]["id"] == doc_id
    assert store.doc_count == 1

    ok, text = store.get_document(doc_id, session_id="s1")
    assert ok is True
    assert "Doc" in text

    denied_ok, denied = store.get_document(doc_id, session_id="s2")
    assert denied_ok is False
    assert "yetkiniz yok" in denied

    result = store.delete_document(doc_id, session_id="s1")
    assert "Belge silindi" in result
    assert store.doc_count == 0
    assert "BM25" in store.status()


async def test_document_store_clean_html_with_bleach(monkeypatch: pytest.MonkeyPatch) -> None:
    html = "<script>alert(1)</script><p>Hello&nbsp; <b>World</b></p>"

    class _FakeBleach:
        @staticmethod
        def clean(_html: str, **_: object) -> str:
            return "<ignored>Clean Text</ignored>"

    monkeypatch.setattr(rag, "_bleach", _FakeBleach)
    assert rag.DocumentStore._clean_html(html) == "<ignored>Clean Text</ignored>"


async def test_document_store_scoped_hf_runtime_env_sets_expected_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _make_store_stub(Path("/tmp"))
    store.cfg = SimpleNamespace(HF_TOKEN="abc-token", HF_HUB_OFFLINE=True)

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    with store._scoped_hf_runtime_env():
        assert os.environ["HF_TOKEN"] == "abc-token"
        assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "abc-token"
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"

    assert "HF_TOKEN" not in os.environ
    assert "HUGGING_FACE_HUB_TOKEN" not in os.environ
    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ


async def test_document_store_apply_hf_runtime_env_does_not_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _make_store_stub(Path("/tmp"))
    store.cfg = SimpleNamespace(HF_TOKEN="abc-token", HF_HUB_OFFLINE=True)

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    store._apply_hf_runtime_env()

    assert "HF_TOKEN" not in os.environ
    assert "HUGGING_FACE_HUB_TOKEN" not in os.environ
    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ


async def test_document_store_scoped_hf_runtime_env_restores_existing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _make_store_stub(Path("/tmp"))
    store.cfg = SimpleNamespace(HF_TOKEN="new-token", HF_HUB_OFFLINE=True)

    monkeypatch.setenv("HF_TOKEN", "old-token")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "old-hub-token")
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")

    with store._scoped_hf_runtime_env():
        assert os.environ["HF_TOKEN"] == "new-token"
        assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "new-token"
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"

    assert os.environ["HF_TOKEN"] == "old-token"
    assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "old-hub-token"
    assert os.environ["HF_HUB_OFFLINE"] == "0"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "0"


async def test_document_store_apply_hf_runtime_env_uses_local_cache_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(HF_TOKEN="", HF_HUB_OFFLINE="false", HF_USE_LOCAL_CACHE_ONLY=True)
    store._pg_embedding_model_name = "custom/model"

    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    with store._scoped_hf_runtime_env():
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"

    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ


async def test_document_store_apply_hf_runtime_env_auto_offline_when_model_cache_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = tmp_path / "hf"
    (cache_root / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(cache_root))
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_CACHE", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(HF_TOKEN="", HF_HUB_OFFLINE=False, HF_USE_LOCAL_CACHE_ONLY=False)

    with store._scoped_hf_runtime_env():
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"

    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ


async def test_document_store_add_document_from_file_validation_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    captured: dict[str, object] = {}

    def _fake_add(title: str, content: str, source: str, tags: list[str], session_id: str) -> str:
        captured["title"] = title
        captured["content"] = content
        captured["source"] = source
        captured["tags"] = tags
        captured["session_id"] = session_id
        return "doc-file-1"

    store._add_document_sync = _fake_add  # type: ignore[method-assign]

    bad = tmp_path / "payload.bin"
    bad.write_bytes(b"\x00\x01")
    ok, msg = store.add_document_from_file(str(bad), session_id="s-file")
    assert ok is False
    assert "Desteklenmeyen dosya türü" in msg

    good = tmp_path / "notes.md"
    good.write_text("hello world", encoding="utf-8")
    ok, msg = store.add_document_from_file(str(good), tags=["alpha"], session_id="s-file")
    assert ok is True
    assert "[doc-file-1]" in msg
    assert captured["title"] == "notes.md"
    assert captured["source"] == f"file://{good.resolve()}"
    assert captured["tags"] == ["alpha"]


async def test_document_store_graph_helpers_and_projection_and_plan(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_root_dir = tmp_path
    store._graph_ready = True
    store._chroma_available = False
    store.collection = None
    store._pgvector_available = False
    store._vector_backend = "bm25"
    store._index = {
        "d1": {"title": "Doc1", "source": "s1", "session_id": "s1"},
        "d2": {"title": "Doc2", "source": "s2", "session_id": "s2"},
    }
    graph = rag.GraphIndex(tmp_path)
    graph.add_node("a.py", node_type="file")
    graph.add_node("endpoint:GET /h", node_type="endpoint")
    graph.add_edge("a.py", "endpoint:GET /h", kind="calls_endpoint")
    store._graph_index = graph

    ok, msg = store.search_graph("", top_k=3)
    assert ok is False
    assert "boş sorgu" in msg

    ok, msg = store.search_graph("a.py", top_k=2)
    assert ok is True
    assert "[GraphRAG: a.py]" in msg

    proj = store.build_knowledge_graph_projection(
        session_id="s1", include_code_graph=True, limit=20
    )
    node_ids = {n.id for n in proj["nodes"]}
    assert "doc:d1" in node_ids
    assert "doc:d2" not in node_ids
    assert any(e.source == "code:a.py" for e in proj["edges"])

    plan = store.build_graphrag_search_plan("hello", session_id="s1", top_k=2)
    assert plan.query == "hello"
    assert plan.vector_backend == "bm25"
    assert plan.broker_topics[0].startswith("sidar.swarm.researcher.")


async def test_document_store_search_sync_mode_routing(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.default_top_k = 3
    store.cfg = SimpleNamespace(RAG_TOP_K=3)
    store._index = {"d1": {"session_id": "s1", "title": "t"}}
    store._bm25_available = True
    store._pgvector_available = False
    store._chroma_available = False
    store.collection = None
    store._vector_backend = "bm25"
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False

    store._bm25_search = lambda q, k, s: (True, f"bm25:{q}:{k}:{s}")  # type: ignore[method-assign]
    store._keyword_search = lambda q, k, s: (True, f"kw:{q}:{k}:{s}")  # type: ignore[method-assign]
    store._rrf_search = lambda q, k, s: (True, f"rrf:{q}:{k}:{s}")  # type: ignore[method-assign]
    store.search_graph = lambda q, k: (True, f"graph:{q}:{k}")  # type: ignore[method-assign]

    ok, result = store._search_sync("q", mode="graph", session_id="s1")
    assert ok is True and result.startswith("graph:")

    ok, result = store._search_sync("q", mode="vector", session_id="s1")
    assert ok is False
    assert "Vektör arama kullanılamıyor" in result

    ok, result = store._search_sync("q", mode="bm25", session_id="s1")
    assert ok is True and result.startswith("bm25:")

    ok, result = store._search_sync("q", mode="keyword", session_id="s1")
    assert ok is True and result.startswith("kw:")

    ok, result = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is True and result.startswith("bm25:")


async def test_document_store_consolidate_session_documents(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {
        "a": {
            "session_id": "s1",
            "title": "A",
            "preview": "old-a",
            "access_count": 0,
            "created_at": 1,
            "last_accessed_at": 1,
            "tags": [],
        },
        "b": {
            "session_id": "s1",
            "title": "B",
            "preview": "old-b",
            "access_count": 0,
            "created_at": 2,
            "last_accessed_at": 2,
            "tags": [],
        },
        "c": {
            "session_id": "s1",
            "title": "C",
            "preview": "keep",
            "access_count": 2,
            "created_at": 3,
            "last_accessed_at": 3,
            "tags": [],
        },
        "digest_old": {
            "session_id": "s1",
            "title": "Digest",
            "preview": "prev",
            "access_count": 0,
            "created_at": 4,
            "last_accessed_at": 4,
            "tags": ["memory-summary"],
            "source": "memory://nightly-digest/2026",
        },
    }
    deleted: list[str] = []
    store.delete_document = lambda doc_id, _session_id="s1": deleted.append(doc_id) or "ok"  # type: ignore[method-assign]
    store._add_document_sync = lambda **kwargs: "digest-new"  # type: ignore[method-assign]

    summary = store.consolidate_session_documents("s1", keep_recent_docs=1)

    assert summary["status"] == "completed"
    assert summary["removed_docs"] >= 1
    assert summary["summary_doc_id"] == "digest-new"
    assert "digest_old" in deleted


async def test_document_store_graph_disabled_and_dispatch_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = False
    store._graph_ready = False
    store._index = {"d1": {"session_id": "s1", "title": "Doc"}}

    ok, msg = store.rebuild_graph_index()
    assert ok is False and "devre dışı" in msg

    ok, msg = store.search_graph("anything")
    assert ok is False and "devre dışı" in msg

    ok, msg = store.explain_dependency_path("a.py", "b.py")
    assert ok is False and "devre dışı" in msg

    ok, msg = store.graph_impact_details("x")
    assert ok is False and "devre dışı" in msg


async def test_document_store_graph_query_dispatch_and_empty_impact_target(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_ready = True
    store._index = {"d1": {"session_id": "s1", "title": "Doc"}}
    store._graph_index = rag.GraphIndex(tmp_path)
    store._graph_index.add_node("a.py", node_type="file")
    store._graph_index.add_node("b.py", node_type="file")
    store._graph_index.add_edge("a.py", "b.py", kind="imports")

    ok, msg = store.search_graph("a.py -> b.py", top_k=3)
    assert ok is True
    assert "[GraphRAG Path]" in msg

    ok, msg = store.search_graph("impact: ")
    assert ok is False
    assert "hedef belirtilmedi" in msg


async def test_document_store_build_graphrag_search_plan_with_pgvector_candidates(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_ready = True
    store._graph_index = rag.GraphIndex(tmp_path)
    store._graph_index.add_node("file.py", node_type="file")
    store._index = {"d1": {"session_id": "s1", "title": "Doc1", "source": "src1"}}
    store._pgvector_available = True
    store._chroma_available = False
    store.collection = None
    store._vector_backend = "bm25"
    store._fetch_pgvector = lambda _q, _k, _s: [  # type: ignore[method-assign]
        {"doc_id": "d1"},
        {"doc_id": "d2"},
    ]

    plan = store.build_graphrag_search_plan("query", session_id="s1", top_k=1)

    assert plan.vector_backend == "pgvector"
    assert plan.vector_candidates == ["d1"]
    assert any(topic.endswith(".rag_search") for topic in plan.broker_topics)


async def test_document_store_rrf_and_formatting_and_snippet_behaviors(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {"d1": {"session_id": "s1", "title": "Title 1", "source": "src://1"}}
    store._pgvector_available = True
    store._fetch_pgvector = lambda _q, _k, _s: [  # type: ignore[method-assign]
        {"id": "d1", "title": "Title 1", "source": "src://1", "snippet": "a" * 500, "score": 0.9}
    ]
    store._fetch_bm25 = lambda _q, _k, _s: []  # type: ignore[method-assign]

    ok, text = store._rrf_search("query", 1, "s1")
    assert ok is True
    assert "Hibrit RRF (pgvector + BM25)" in text
    assert "..." in text

    snippet = rag.DocumentStore._extract_snippet("x" * 20, "missing", window=10)
    assert snippet == "xxxxxxxxxx..."


async def test_document_store_list_documents_and_touch_and_missing_file(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._save_index = lambda: None
    store._index = {
        "d1": {
            "session_id": "s1",
            "title": "Doc 1",
            "source": "src://1",
            "size": 2048,
            "tags": ["alpha"],
            "access_count": 0,
        },
    }

    listing = store.list_documents(session_id="s1")
    assert "[Belge Deposu — 1 belge]" in listing
    assert "Doc 1" in listing and "2.0 KB" in listing

    ok, msg = store.get_document("d1", session_id="s1")
    assert ok is False
    assert "dosyası eksik" in msg

    store._touch_document("d1")
    assert store._index["d1"]["access_count"] == 1


async def test_document_store_format_extract_and_consolidate_skip_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)

    ok, text = store._format_results_from_struct([], "q", source_name="BM25")
    assert ok is False
    assert "ilgili sonuç bulunamadı" in text

    snippet = rag.DocumentStore._extract_snippet("start middle keyword end", "keyword", window=8)
    assert "keyword" in snippet

    store._index = {"d1": {"session_id": "s1", "title": "Only"}}
    summary = store.consolidate_session_documents("s1", keep_recent_docs=2)
    assert summary["status"] == "skipped"

    store._index = {
        "d1": {
            "session_id": "s1",
            "title": "Pinned",
            "tags": ["pinned"],
            "access_count": 0,
            "created_at": 1,
            "last_accessed_at": 1,
        },
        "d2": {
            "session_id": "s1",
            "title": "Read",
            "tags": [],
            "access_count": 3,
            "created_at": 2,
            "last_accessed_at": 2,
        },
    }
    summary = store.consolidate_session_documents("s1", keep_recent_docs=1)
    assert summary["status"] == "skipped"


async def test_document_store_search_sync_fallback_chain_and_graph_not_found(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "A"}}
    store._bm25_available = True
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()
    store._is_local_llm_provider = False
    store._local_hybrid_enabled = True
    store._rrf_search = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("rrf"))  # type: ignore[method-assign]
    store._pgvector_search = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("pg"))  # type: ignore[method-assign]
    store._chroma_search = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("chroma"))  # type: ignore[method-assign]
    store._bm25_search = lambda q, k, s: (True, f"bm25:{q}:{k}:{s}")  # type: ignore[method-assign]

    ok, result = store._search_sync("needle", mode="auto", session_id="s1")
    assert ok is True
    assert result.startswith("bm25:needle")

    graph_store = _make_store_stub(tmp_path)
    graph_store._graph_rag_enabled = True
    graph_store._graph_ready = True
    graph_store._graph_index = rag.GraphIndex(tmp_path)

    ok, result = graph_store.search_graph("unknown-module", top_k=2)
    assert ok is False
    assert "ilgili modül bulunamadı" in result


async def test_document_store_search_sync_preferred_chroma_fallbacks_to_rrf(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "A"}}
    store._bm25_available = True
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()
    store._vector_backend = "chroma"
    store._is_local_llm_provider = False
    store._local_hybrid_enabled = True
    store._chroma_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("preferred-chroma"))  # type: ignore[method-assign]
    store._rrf_search = lambda q, k, s: (True, f"rrf:{q}:{k}:{s}")  # type: ignore[method-assign]

    ok, result = store._search_sync("needle", mode="auto", session_id="s1")
    assert ok is True
    assert result == "rrf:needle:2:s1"


async def test_document_store_search_sync_empty_session_and_analyze_graph_impact(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {}

    ok, msg = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is False
    assert "belge deposu boş" in msg

    graph_store = _make_store_stub(tmp_path)
    graph_store._graph_rag_enabled = True
    graph_store._graph_ready = True
    graph_store._graph_index = rag.GraphIndex(tmp_path)
    graph_store._graph_index.add_node("a.py", node_type="file")
    graph_store._graph_index.add_node("b.py", node_type="file")
    graph_store._graph_index.add_edge("a.py", "b.py", kind="imports")

    ok, text = graph_store.analyze_graph_impact("a.py")
    assert ok is True
    assert "[GraphRAG Impact] a.py" in text


async def test_embed_texts_for_semantic_cache_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setenv("TRANSFORMERS_CACHE", str(tmp_path / "transformers"))

    class _Vec:
        def tolist(self) -> list[list[float]]:
            return [[0.1, 0.2]]

    seen: dict[str, object] = {}

    class _ST:
        def __init__(self, _name: str, *, device: str, local_files_only: bool) -> None:
            seen["device"] = device
            seen["local_files_only"] = local_files_only
            seen["hf_progress"] = os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS")
            seen["transformers_verbosity"] = os.environ.get("TRANSFORMERS_VERBOSITY")

        def encode(self, _texts: list[str], normalize_embeddings: bool = True) -> _Vec:
            assert normalize_embeddings is True
            return _Vec()

    monkeypatch.setitem(
        __import__("sys").modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_ST)
    )
    cfg = SimpleNamespace(
        PGVECTOR_EMBEDDING_MODEL="mini",
        USE_GPU="false",
        GPU_DEVICE=1,
    )
    assert rag.embed_texts_for_semantic_cache(["hello"], cfg=cfg) == [[0.1, 0.2]]
    assert seen["device"] == "cpu"
    assert seen["local_files_only"] is False
    assert seen["hf_progress"] == "1"
    assert seen["transformers_verbosity"] == "error"

    cfg.USE_GPU = "true"
    cfg.HF_USE_LOCAL_CACHE_ONLY = True
    assert rag.embed_texts_for_semantic_cache(["hello"], cfg=cfg) == [[0.1, 0.2]]
    assert seen["device"] == "cuda:1"
    assert seen["local_files_only"] is True

    class _BrokenST:
        def __init__(self, _name: str, **_kwargs: object) -> None:
            raise RuntimeError("boom")

    monkeypatch.setitem(
        __import__("sys").modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=_BrokenST),
    )
    assert rag.embed_texts_for_semantic_cache(["hello"], cfg=cfg) == []


async def test_build_embedding_function_gpu_success_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Cuda:
        enabled = False

        @staticmethod
        def is_available() -> bool:
            return _Cuda.enabled

    class _Torch:
        cuda = _Cuda()
        float16 = "fp16"

        @staticmethod
        def autocast(device_type: str, dtype: str):
            class _Ctx:
                def __enter__(self) -> None:
                    return None

                def __exit__(self, *_args: object) -> None:
                    return None

            assert device_type == "cuda"
            assert dtype == "fp16"
            return _Ctx()

    class _EF:
        def __init__(self, model_name: str, device: str, local_files_only: bool) -> None:
            self.model_name = model_name
            self.device = device
            self.local_files_only = local_files_only

        def __call__(self, _input: list[str]) -> list[list[float]]:
            return [[1.0]]

    monkeypatch.setitem(__import__("sys").modules, "torch", _Torch)
    monkeypatch.setitem(
        __import__("sys").modules,
        "chromadb.utils.embedding_functions",
        SimpleNamespace(SentenceTransformerEmbeddingFunction=_EF),
    )

    ef = rag._build_embedding_function(use_gpu=True, gpu_device=1, mixed_precision=True)
    assert ef is not None
    assert ef(["chunk"]) == [[1.0]]

    _Cuda.enabled = True
    ef_cuda = rag._build_embedding_function(use_gpu=True, gpu_device=1, mixed_precision=True)
    assert ef_cuda is not None
    assert ef_cuda(["chunk"]) == [[1.0]]

    # Instance-level __call__ monkeypatching does not intercept special method
    # lookup for callables, so the test explicitly exercises our autocast stub.
    with _Torch.autocast(device_type="cuda", dtype="fp16"):
        pass

    cached_cpu_ef = rag._build_embedding_function(use_gpu=False)
    assert isinstance(cached_cpu_ef, _EF)

    class _BrokenEF:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("factory unavailable")

    monkeypatch.setitem(
        __import__("sys").modules,
        "chromadb.utils.embedding_functions",
        SimpleNamespace(SentenceTransformerEmbeddingFunction=_BrokenEF),
    )
    assert rag._build_embedding_function(use_gpu=True) is None


async def test_build_embedding_function_import_module_and_missing_autocast_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Cuda:
        @staticmethod
        def is_available() -> bool:
            return True

    class _TorchNoAutocast:
        cuda = _Cuda()

    class _EF:
        def __init__(self, model_name: str, device: str, local_files_only: bool) -> None:
            self.model_name = model_name
            self.device = device
            self.local_files_only = local_files_only

    fake_embedding_module = SimpleNamespace(SentenceTransformerEmbeddingFunction=_EF)
    monkeypatch.delitem(sys.modules, "chromadb.utils.embedding_functions", raising=False)
    monkeypatch.setattr(rag.importlib, "import_module", lambda name: fake_embedding_module)
    monkeypatch.setitem(sys.modules, "torch", _TorchNoAutocast)

    caplog.set_level("WARNING")
    ef = rag._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True)
    assert ef is not None
    assert ef.device == "cuda:0"
    assert "torch.autocast bulunamadı" in caplog.text


async def test_document_store_init_pgvector_backend_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        rag.DocumentStore, "_load_index", lambda self: {"d": {"session_id": "global"}}
    )
    monkeypatch.setattr(rag.DocumentStore, "_check_import", lambda self, _m: False)
    monkeypatch.setattr(rag.DocumentStore, "_init_chroma", lambda self: calls.append("chroma"))
    monkeypatch.setattr(rag.DocumentStore, "_init_pgvector", lambda self: calls.append("pgvector"))
    monkeypatch.setattr(rag.DocumentStore, "_init_fts", lambda self: calls.append("fts"))

    cfg = SimpleNamespace(
        RAG_TOP_K=4,
        RAG_CHUNK_SIZE=8,
        RAG_CHUNK_OVERLAP=2,
        RAG_VECTOR_BACKEND="pgvector",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=True,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=12,
        PGVECTOR_TABLE="tbl",
        PGVECTOR_EMBEDDING_DIM=8,
        PGVECTOR_EMBEDDING_MODEL="mini",
    )
    store = rag.DocumentStore(tmp_path / "store", cfg=cfg)

    assert store.default_top_k == 4
    assert calls == ["pgvector", "fts"]


async def test_document_store_add_document_and_search_helpers(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._bm25_available = True
    store._chroma_available = True
    store._pgvector_available = True
    store.collection = SimpleNamespace(delete=lambda **_k: None, upsert=lambda **_k: None)
    store._upsert_pgvector_chunks = lambda *_args: None  # type: ignore[method-assign]

    class _DummyLock:
        def __enter__(self) -> _DummyLock:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    store._write_lock = _DummyLock()
    store._save_index = lambda: None

    class _FtsConn:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            return None

        def commit(self) -> None:
            return None

    store.fts_conn = _FtsConn()

    doc_id = store._add_document_sync(
        "Title", "keyword body", source="src", tags=["tag"], session_id="s1"
    )
    assert doc_id in store._index

    # keyword search branch
    ok, text = store._keyword_search("keyword", 2, "s1")
    assert ok is True
    assert "Kelime Eşleşmesi" in text


async def test_document_store_add_document_from_url_success_and_failure(
    respx_mock_router,
    tmp_path: Path,
) -> None:
    httpx = pytest.importorskip("httpx")
    store = _make_store_stub(tmp_path)

    async def _fake_add(
        title: str, content: str, source: str, tags: list[str] | None, session_id: str
    ) -> str:
        assert source.startswith("https://example.com")
        assert session_id == "s-url"
        return "doc-url"

    store.add_document = _fake_add  # type: ignore[method-assign]

    respx_mock_router.get("https://example.com/docs").mock(
        return_value=httpx.Response(200, text="<title>My Page</title><p>Body</p>")
    )

    ok, msg = await store.add_document_from_url("https://example.com/docs", session_id="s-url")
    assert ok is True
    assert "doc-url" in msg

    ok, msg = await store.add_document_from_url("ftp://example.com/docs", session_id="s-url")
    assert ok is False
    assert "URL belge eklenemedi" in msg


async def test_document_store_add_document_from_url_redirect_error_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    monkeypatch.setattr(
        rag.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (rag.socket.AF_INET, rag.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    class _Response:
        def __init__(self, url: str, status_code: int, location: str = "") -> None:
            self.url = url
            self.status_code = status_code
            self.headers = {"Location": location} if location else {}
            self.text = ""

        def raise_for_status(self) -> None:
            return None

    class _MissingLocationClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str):
            return _Response(url, 302)

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _MissingLocationClient())
    ok, message = await store.add_document_from_url("https://public.example/start")
    assert ok is False
    assert "Location başlığı yok" in message

    class _LoopingRedirectClient(_MissingLocationClient):
        async def get(self, url: str):
            return _Response(url, 302, location="/again")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: _LoopingRedirectClient())
    ok, message = await store.add_document_from_url("https://public.example/start")
    assert ok is False
    assert "Redirect limiti" in message


@pytest.mark.parametrize(
    ("exc_name", "expected_hint"),
    [
        ("TimeoutException", "timeout"),
        ("RequestError", "network"),
    ],
)
async def test_document_store_add_document_from_url_handles_httpx_transport_errors(
    respx_mock_router,
    tmp_path: Path,
    exc_name: str,
    expected_hint: str,
) -> None:
    httpx = pytest.importorskip("httpx")
    store = _make_store_stub(tmp_path)
    request = httpx.Request("GET", "https://example.com/docs")
    if exc_name == "TimeoutException":
        side_effect: Exception = httpx.TimeoutException(expected_hint)
    else:
        side_effect = httpx.RequestError(expected_hint, request=request)
    respx_mock_router.get("https://example.com/docs").mock(side_effect=side_effect)

    ok, msg = await store.add_document_from_url("https://example.com/docs", session_id="s-url")
    assert ok is False
    assert "URL belge eklenemedi" in msg
    assert expected_hint in msg


async def test_document_store_vector_runtime_init_failures_fallback_to_bm25(
    monkeypatch: pytest.MonkeyPatch,
    mock_chromadb,
    tmp_path: Path,
) -> None:
    # Chroma runtime failure (import hatası değil): PersistentClient patlasa da BM25 devam etmeli.
    mock_chromadb(
        persistent_client_factory=lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("chroma-runtime")
        ),
    )

    chroma_cfg = SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=32,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="chroma",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=32,
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=3,
        PGVECTOR_EMBEDDING_MODEL="mini",
        DATABASE_URL="",
    )
    chroma_store = rag.DocumentStore(tmp_path / "chroma_runtime_fail", cfg=chroma_cfg)
    assert chroma_store._chroma_available is False
    doc_id = chroma_store._add_document_sync(
        "Chroma Fallback", "fallback body", source="test://runtime", session_id="s1"
    )
    bm25_ok, bm25_msg = chroma_store._bm25_search("fallback", 2, "s1")
    assert bm25_ok is True
    assert doc_id in bm25_msg

    # pgvector runtime failure (import hatası değil): create_engine patlasa da BM25 devam etmeli.
    class _SentenceTransformer:
        def __init__(self, _name: str) -> None:
            pass

    def _broken_create_engine(*_args: object, **_kwargs: object):
        raise RuntimeError("pg-runtime")

    blocked_ml_imports = {"sentence_transformers", "torch", "transformers", "triton"}
    original_import = builtins.__import__
    original_import_module = importlib.import_module

    def _guard_real_ml_imports(
        name: str,
        globals_: dict[str, object] | None = None,
        locals_: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name.split(".", 1)[0] in blocked_ml_imports:
            raise AssertionError(f"unexpected ML dependency import: {name}")
        return original_import(name, globals_, locals_, fromlist, level)

    def _guard_import_module(name: str, package: str | None = None) -> object:
        if name.split(".", 1)[0] in blocked_ml_imports:
            raise AssertionError(f"unexpected ML dependency import: {name}")
        return original_import_module(name, package)

    monkeypatch.setattr(builtins, "__import__", _guard_real_ml_imports)
    monkeypatch.setattr(importlib, "import_module", _guard_import_module)
    monkeypatch.setattr(
        rag,
        "get_sentence_transformer_model",
        lambda *_args, **_kwargs: _SentenceTransformer("mini"),
    )
    monkeypatch.setitem(sys.modules, "pgvector", SimpleNamespace(__name__="pgvector"))
    monkeypatch.setitem(
        sys.modules,
        "sqlalchemy",
        SimpleNamespace(create_engine=_broken_create_engine, text=lambda sql: sql),
    )

    pg_cfg = SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=32,
        RAG_CHUNK_OVERLAP=8,
        RAG_VECTOR_BACKEND="pgvector",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=32,
        PGVECTOR_TABLE="rag_embeddings",
        PGVECTOR_EMBEDDING_DIM=3,
        PGVECTOR_EMBEDDING_MODEL="mini",
        DATABASE_URL="postgresql://user:pass@localhost/db",
    )
    pg_store = rag.DocumentStore(tmp_path / "pg_runtime_fail", cfg=pg_cfg)
    assert pg_store._pgvector_available is False
    pg_doc_id = pg_store._add_document_sync(
        "PG Fallback", "vector backend down", source="test://runtime", session_id="s2"
    )
    pg_bm25_ok, pg_bm25_msg = pg_store._bm25_search("backend", 2, "s2")
    assert pg_bm25_ok is True
    assert pg_doc_id in pg_bm25_msg


async def test_init_pgvector_rejects_invalid_table_without_sql(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(DATABASE_URL="postgresql://user:pass@localhost/db")
    store._pg_table = "rag_embeddings;DROP_TABLE_docs"
    store._pgvector_available = True

    def _unexpected_dependency_check(_module_name: str) -> bool:
        raise AssertionError("invalid PGVECTOR_TABLE should be rejected before imports or SQL")

    store._check_import = _unexpected_dependency_check  # type: ignore[method-assign]

    store._init_pgvector()

    assert store._pgvector_available is False


async def test_pgvector_failure_action_message_is_actionable_without_raw_auth_error() -> None:
    msg = rag._pgvector_failure_action_message(
        RuntimeError('password authentication failed for user "sidar"; DETAIL: raw driver text')
    )

    assert "yetki/parola hatası" in msg
    assert "DATABASE_URL" in msg
    assert "SIDAR_CONTAINER_DATABASE_URL" in msg
    assert "POSTGRES_PASSWORD" in msg
    assert "BM25 fallback aktif edildi" in msg
    assert "password authentication failed" not in msg
    assert "raw driver text" not in msg


async def test_document_store_schedule_judge_and_search_with_otel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _Judge:
        enabled = True

        def __init__(self) -> None:
            self.called = False

        def schedule_background_evaluation(self, **_kwargs: object) -> None:
            self.called = True

    judge = _Judge()

    monkeypatch.setitem(
        __import__("sys").modules, "core.judge", SimpleNamespace(get_llm_judge=lambda: judge)
    )
    rag.DocumentStore._schedule_judge("q", "answer")
    assert judge.called is True

    store = _make_store_stub(tmp_path)
    store._search_sync = lambda *_args: (True, "ok")  # type: ignore[method-assign]

    class _Span:
        def __enter__(self) -> _Span:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def set_attribute(self, *_args: object) -> None:
            return None

    class _Tracer:
        def start_as_current_span(self, _name: str) -> _Span:
            return _Span()

    monkeypatch.setattr(rag, "_otel_trace", SimpleNamespace(get_tracer=lambda _name: _Tracer()))
    ok, txt = await store.search("query", session_id="s1")
    assert ok is True and txt == "ok"


async def test_document_store_upsert_pgvector_chunks_rolls_back_on_transaction_failure(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store._pgvector_available = True
    store._pg_table = "rag_embeddings"
    store._pgvector_embed_texts = lambda _chunks: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]

    state = {"rollback": False, "calls": 0}

    class _Conn:
        def execute(self, _sql: object, _params: object = None) -> None:
            state["calls"] += 1
            if state["calls"] >= 2:
                raise RuntimeError("insert failed")

    class _Tx:
        def __enter__(self) -> _Conn:
            return _Conn()

        def __exit__(self, exc_type, _exc, _tb) -> bool:
            if exc_type is not None:
                state["rollback"] = True
            return False

    class _Engine:
        def begin(self) -> _Tx:
            return _Tx()

    store.pg_engine = _Engine()
    store._upsert_pgvector_chunks("d1", "p1", "s1", "title", "src", ["content"])
    assert _Tx().__exit__(None, None, None) is False

    assert state["calls"] >= 2
    assert state["rollback"] is True


async def test_document_store_recursive_chunk_text_overlap_preserves_continuity(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    chunks = store._recursive_chunk_text("supercalifragilistic", size=6, overlap=2)

    assert chunks
    assert all(chunk for chunk in chunks)
    assert all(len(chunk) <= 6 for chunk in chunks)
    assert all(chunks[idx].startswith(chunks[idx - 1][-2:]) for idx in range(1, len(chunks)))

    reconstructed = chunks[0] + "".join(chunk[2:] for chunk in chunks[1:])
    assert reconstructed == "supercalifragilistic"


async def test_document_store_init_backends_and_import_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store._write_lock = threading.Lock()
    store._index = {"doc1": {"session_id": "s1"}}
    (tmp_path / "doc1.txt").write_text("hello world", encoding="utf-8")

    # _check_import true/false branches

    original_import_module = importlib.import_module
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: (
            (_ for _ in ()).throw(ImportError())
            if name == "missing.mod"
            else original_import_module(name)
        ),
    )
    assert store._check_import("json") is True
    assert store._check_import("missing.mod") is False

    # _init_chroma success path
    class _Settings:
        def __init__(self, anonymized_telemetry: bool) -> None:
            self.anonymized_telemetry = anonymized_telemetry

    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            self.created = []

        def get_or_create_collection(self, name: str, **kwargs: object) -> object:
            self.created.append((name, kwargs))
            return object()

    chromadb_mod = SimpleNamespace(PersistentClient=lambda **kwargs: _Client(**kwargs))
    monkeypatch.setitem(__import__("sys").modules, "chromadb", chromadb_mod)
    monkeypatch.setitem(
        __import__("sys").modules, "chromadb.config", SimpleNamespace(Settings=_Settings)
    )
    monkeypatch.setattr(rag, "_build_embedding_function", lambda **_kwargs: object())
    store._use_gpu = True
    store._gpu_device = 0
    store._mixed_precision = False
    store._chroma_available = True
    store._apply_hf_runtime_env = lambda: None  # type: ignore[method-assign]
    store._init_chroma()
    assert store.collection is not None
    assert os.environ["CHROMA_TELEMETRY_DISABLED"] == "1"

    # _init_fts migration path
    store._init_fts()
    count = store.fts_conn.execute("SELECT count(*) as c FROM bm25_index").fetchone()["c"]
    assert count == 1


async def test_document_store_pgvector_init_and_query_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store._check_import = lambda _name: True  # type: ignore[method-assign]
    store._pg_table = "rag_pg"
    store._pg_embedding_dim = 3
    store._pg_embedding_model_name = "mini"
    store._pgvector_available = False
    store.cfg = SimpleNamespace(DATABASE_URL="postgresql+asyncpg://u:p@h/db")

    executed: list[tuple[str, dict[str, object] | None]] = []

    class _Rows:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def fetchall(self) -> list[object]:
            return self._rows

    class _Conn:
        def execute(self, sql: object, params: dict[str, object] | None = None) -> _Rows | None:
            executed.append((str(sql), params))
            if params and "qvec" in params:
                rows = [
                    SimpleNamespace(
                        parent_id="p1",
                        title="Doc 1",
                        source="src://1",
                        chunk_content="a",
                        distance=0.1,
                    ),
                    SimpleNamespace(
                        parent_id="p1",
                        title="Doc 1",
                        source="src://1",
                        chunk_content="a2",
                        distance=0.2,
                    ),
                    SimpleNamespace(
                        parent_id="p2",
                        title="Doc 2",
                        source="src://2",
                        chunk_content="b",
                        distance=0.3,
                    ),
                ]
                return _Rows(rows)
            return None

    class _Begin:
        def __enter__(self) -> _Conn:
            return _Conn()

        def __exit__(self, *_args: object) -> None:
            return None

    class _Engine:
        def begin(self) -> _Begin:
            return _Begin()

    monkeypatch.setitem(
        __import__("sys").modules,
        "sqlalchemy",
        SimpleNamespace(create_engine=lambda *_a, **_k: _Engine(), text=lambda s: s),
    )

    seen_sentence_transformer: dict[str, object] = {}

    class _ST:
        def __init__(self, _model: str, *, device: str, local_files_only: bool) -> None:
            seen_sentence_transformer["device"] = device
            seen_sentence_transformer["local_files_only"] = local_files_only

        def encode(self, _texts: list[str], normalize_embeddings: bool = True) -> list[list[float]]:
            assert normalize_embeddings is True
            return [[0.1, 0.2, 0.3]]

    monkeypatch.setitem(
        __import__("sys").modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_ST)
    )
    store.cfg.USE_GPU = False
    store.cfg.GPU_DEVICE = 1
    store._apply_hf_runtime_env = lambda: None  # type: ignore[method-assign]
    store._init_pgvector()
    assert store._pgvector_available is True
    assert seen_sentence_transformer["device"] == "cpu"
    assert seen_sentence_transformer["local_files_only"] is False

    # _fetch_pgvector with parent de-dup
    store._is_local_llm_provider = False
    results = store._fetch_pgvector("query", top_k=2, session_id="s1")
    assert [r["id"] for r in results] == ["p1", "p2"]

    # _upsert + delete branches
    store._pgvector_embed_texts = lambda _chunks: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]
    store._upsert_pgvector_chunks("chunk-1", "parent-1", "s1", "title", "src", ["content"])
    store._delete_pgvector_parent("parent-1", "s1")
    assert any("DELETE FROM rag_pg" in sql for sql, _ in executed)
    assert not any(sql.lstrip().startswith("# nosec") for sql, _ in executed)
    assert any(sql.lstrip().startswith("INSERT INTO rag_pg") for sql, _ in executed)
    assert any(sql.lstrip().startswith("SELECT doc_id") for sql, _ in executed)


async def test_document_store_load_and_bm25_fetch_and_keyword_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store._write_lock = threading.Lock()
    store._bm25_available = True
    store._index = {
        "d1": {"session_id": "s1", "title": "First", "source": "src://1", "tags": ["alpha"]},
        "d2": {"session_id": "s2", "title": "Second", "source": "src://2", "tags": ["beta"]},
    }
    (tmp_path / "d1.txt").write_text("hello alpha world", encoding="utf-8")
    (tmp_path / "d2.txt").write_text("hello beta world", encoding="utf-8")

    # _load_index invalid json branch
    store.index_file.write_text("{broken", encoding="utf-8")
    assert store._load_index() == {}

    # _init_fts for BM25 tables
    store._init_fts()
    bm25_rows = store._fetch_bm25("hello", top_k=2, session_id="s1")
    assert bm25_rows and bm25_rows[0]["id"] == "d1"
    assert store._fetch_bm25("???", top_k=2, session_id="s1") == []

    # _fetch_chroma empty ids branch and normal branch
    store.collection = SimpleNamespace(
        count=lambda: 10,
        query=lambda **_kwargs: {
            "ids": [["c1", "c2"]],
            "documents": [["snippet1", "snippet2"]],
            "metadatas": [
                [{"parent_id": "d1", "title": "T1", "source": "S1"}, {"parent_id": "d1"}]
            ],
        },
    )
    store.cfg = SimpleNamespace(RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER=2)
    store._is_local_llm_provider = False
    chroma = store._fetch_chroma("q", 2, "s1")
    assert chroma and chroma[0]["id"] == "d1"

    store.collection = SimpleNamespace(count=lambda: 1, query=lambda **_kwargs: {"ids": [[]]})
    assert store._fetch_chroma("q", 2, "s1") == []

    # keyword search/session filtering
    ok, text = store._keyword_search("alpha", 2, "s1")
    assert ok is True and "First" in text


async def test_graph_index_iter_source_files_limits_and_excludes(tmp_path: Path) -> None:
    root = tmp_path
    (root / "a.py").write_text("print('a')", encoding="utf-8")
    (root / "b.js").write_text("console.log('b')", encoding="utf-8")
    skipped = root / "node_modules"
    skipped.mkdir()
    (skipped / "c.py").write_text("print('skip')", encoding="utf-8")
    unsupported = root / "d.txt"
    unsupported.write_text("text", encoding="utf-8")

    graph = rag.GraphIndex(root, max_files=1)
    files = graph._iter_source_files(root)

    assert len(files) == 1
    assert files[0].name in {"a.py", "b.js"}


async def test_graph_index_python_import_candidates_with_relative_levels(tmp_path: Path) -> None:
    root = tmp_path
    pkg = root / "pkg" / "sub"
    pkg.mkdir(parents=True)
    target = root / "pkg" / "shared.py"
    target.write_text("", encoding="utf-8")
    current = pkg / "caller.py"
    current.write_text("", encoding="utf-8")

    candidates = rag.GraphIndex._python_import_candidates(current, "shared", 2, root)
    assert target.resolve() in candidates


async def test_document_store_init_chroma_and_fts_error_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store._chroma_available = True
    store._apply_hf_runtime_env = lambda: None  # type: ignore[method-assign]

    monkeypatch.setitem(
        __import__("sys").modules,
        "chromadb",
        SimpleNamespace(
            PersistentClient=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        ),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "chromadb.config",
        SimpleNamespace(Settings=lambda **_kwargs: object()),
    )
    store._init_chroma()
    assert store._chroma_available is False

    class _BrokenCursor:
        def fetchone(self) -> dict[str, int]:
            return {"c": 0}

    class _BrokenConn:
        row_factory = None

        def execute(self, sql: object, *_args: object) -> _BrokenCursor:
            if "SELECT count" in str(sql):
                return _BrokenCursor()
            raise RuntimeError("insert failed")

        def commit(self) -> None:
            return None

    assert _BrokenCursor().fetchone() == {"c": 0}
    conn_probe = _BrokenConn()
    assert isinstance(conn_probe.execute("SELECT count(*) as c FROM bm25_index"), _BrokenCursor)
    assert conn_probe.commit() is None

    monkeypatch.setattr("sqlite3.connect", lambda *_a, **_k: _BrokenConn())
    store._index = {"doc1": {"session_id": "s1"}}
    (tmp_path / "doc1.txt").write_text("body", encoding="utf-8")
    store._bm25_available = True
    store._write_lock = threading.Lock()
    store._init_fts()
    assert store._bm25_available is False


async def test_document_store_apply_hf_runtime_env_when_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(HF_TOKEN="", HF_HUB_OFFLINE=False, HF_USE_LOCAL_CACHE_ONLY=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "empty-hf"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-hub"))
    monkeypatch.setenv("TRANSFORMERS_CACHE", str(tmp_path / "empty-transformers"))
    monkeypatch.setenv("HF_TOKEN", "keep")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "keep")
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    store._apply_hf_runtime_env()

    assert os.environ["HF_TOKEN"] == "keep"
    assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "keep"
    assert "HF_HUB_OFFLINE" not in os.environ


async def test_document_store_consolidate_session_documents_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {
        "keep-new": {
            "session_id": "s1",
            "last_accessed_at": 30,
            "access_count": 2,
            "title": "Recent",
        },
        "pinned": {
            "session_id": "s1",
            "last_accessed_at": 10,
            "access_count": 0,
            "title": "Pinned",
            "tags": ["pinned"],
        },
        "stable": {"session_id": "s1", "last_accessed_at": 9, "access_count": 2, "title": "Stable"},
    }
    assert store.consolidate_session_documents("s1", keep_recent_docs=1)["status"] == "skipped"

    removed: list[tuple[str, str]] = []
    store._index = {
        "old-1": {
            "session_id": "s1",
            "last_accessed_at": 5,
            "access_count": 0,
            "title": "Old 1",
            "preview": "alpha",
        },
        "old-2": {
            "session_id": "s1",
            "last_accessed_at": 4,
            "access_count": 1,
            "title": "Old 2",
            "preview": "beta",
        },
        "keep-new": {
            "session_id": "s1",
            "last_accessed_at": 30,
            "access_count": 3,
            "title": "Recent",
        },
        "digest-old": {
            "session_id": "s1",
            "source": "memory://nightly-digest/prev",
            "title": "Digest",
        },
    }
    store._add_document_sync = lambda **_kwargs: "digest-new"  # type: ignore[method-assign]
    store.delete_document = lambda doc_id, session_id: removed.append((doc_id, session_id)) or "ok"  # type: ignore[method-assign]

    result = store.consolidate_session_documents("s1", keep_recent_docs=1)
    assert result["status"] == "completed"
    assert result["removed_docs"] == 3
    assert result["summary_doc_id"] == "digest-new"
    assert ("digest-old", "s1") in removed
    assert ("old-1", "s1") in removed
    assert ("old-2", "s1") in removed


async def test_document_store_list_documents_and_status_engine_variants(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    assert "Belge deposu boş" in store.list_documents(session_id="s1")

    store._index = {
        "doc1": {
            "session_id": "s1",
            "title": "Doc 1",
            "source": "file://a",
            "size": 1024,
            "tags": ["x"],
        }
    }
    listed = store.list_documents(session_id="s1")
    assert "[Belge Deposu — 1 belge]" in listed
    assert "Doc 1" in listed

    store._bm25_available = False
    store._graph_rag_enabled = False
    store._graph_ready = False
    store._use_gpu = False
    store._gpu_device = 0

    store._pgvector_available = True
    store._vector_backend = "chroma"
    store._chroma_available = False
    assert "pgvector" in store.status()

    store._pgvector_available = False
    store._vector_backend = "pgvector"
    assert "pgvector (pasif)" in store.status()

    store._vector_backend = "chroma"
    store._chroma_available = True
    store._use_gpu = True
    store._gpu_device = 1
    assert "ChromaDB (Chunking + GPU cuda:1)" in store.status()
    assert "GraphRAG" not in store.status()

    store._graph_rag_enabled = True
    store._graph_ready = False
    assert "GraphRAG" not in store.status()

    store._graph_ready = True
    assert "GraphRAG (hazır)" in store.status()


async def test_document_store_add_file_security_and_failure_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)

    outside = Path("/etc/hosts")
    ok, msg = store.add_document_from_file(str(outside), session_id="s1")
    assert ok is False
    assert "proje dizini dışında" in msg

    blocked = tmp_path / "logs" / "note.txt"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("hello", encoding="utf-8")
    ok, msg = store.add_document_from_file(str(blocked), session_id="s1")
    assert ok is False
    assert "güvenlik politikası" in msg

    empty = tmp_path / "empty.txt"
    empty.write_text("   ", encoding="utf-8")
    ok, msg = store.add_document_from_file(str(empty), session_id="s1")
    assert ok is False
    assert "Dosya boş" in msg

    monkeypatch.setattr(
        Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("read boom"))
    )
    ok, msg = store.add_document_from_file(str(empty), session_id="s1")
    assert ok is False
    assert "Dosya eklenemedi" in msg


async def test_document_store_delete_document_graph_and_wrappers(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)

    class _DummyLock:
        def __enter__(self) -> _DummyLock:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    store._write_lock = _DummyLock()
    store._chroma_available = True
    store.collection = SimpleNamespace(
        delete=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("delete boom"))
    )
    store._pgvector_available = True
    deleted: list[tuple[str, str]] = []
    store._delete_pgvector_parent = lambda parent_id, session_id: deleted.append(
        (parent_id, session_id)
    )  # type: ignore[method-assign]
    store._save_index = lambda: None
    store._update_bm25_cache_on_delete = lambda _doc_id: None
    store._index = {"doc1": {"title": "Doc1", "session_id": "s1", "parent_id": "p1"}}
    (tmp_path / "doc1.txt").write_text("body", encoding="utf-8")

    message = store.delete_document("doc1", session_id="s1")
    assert "Belge silindi" in message
    assert deleted == [("p1", "s1")]

    ok, msg = store.get_document("missing", session_id="s1")
    assert ok is False
    assert "Belge bulunamadı" in msg

    pg_ok, pg_msg = store._pgvector_search("q", 2, "s1")
    assert pg_ok is False
    assert "ilgili sonuç bulunamadı" in pg_msg

    store.collection = SimpleNamespace(count=lambda: 0, query=lambda **_k: {"ids": [[]]})
    ch_ok, ch_msg = store._chroma_search("q", 2, "s1")
    assert ch_ok is False
    assert "ilgili sonuç bulunamadı" in ch_msg

    store._bm25_available = False
    bm_ok, bm_msg = store._bm25_search("q", 2, "s1")
    assert bm_ok is False
    assert "ilgili sonuç bulunamadı" in bm_msg


async def test_document_store_search_mode_and_cache_update_edges(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "T1"}}
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()
    store._bm25_available = False
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False
    store._pgvector_search = lambda q, k, s: (True, f"pg:{q}:{k}:{s}")  # type: ignore[method-assign]
    store._chroma_search = lambda q, k, s: (True, f"ch:{q}:{k}:{s}")  # type: ignore[method-assign]

    ok, res = store._search_sync("q", mode="vector", session_id="s1")
    assert ok is True and res.startswith("pg:")

    store._pgvector_available = False
    ok, res = store._search_sync("q", mode="vector", session_id="s1")
    assert ok is True and res.startswith("ch:")

    store._pgvector_available = True
    ok, res = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is True and res.startswith("pg:")

    # _update_bm25_cache_on_add / _update_bm25_cache_on_delete active branches
    executed: list[tuple[str, tuple[object, ...]]] = []
    store._bm25_available = True
    store._index = {"d1": {"session_id": "s1"}}
    store.fts_conn = SimpleNamespace(
        execute=lambda sql, params: executed.append((sql, params)),
        commit=lambda: executed.append(("COMMIT", ())),
    )
    store._update_bm25_cache_on_add("d1", "hello")
    store._update_bm25_cache_on_delete("d1")
    assert any("INSERT INTO bm25_index" in q for q, _ in executed)
    assert ("COMMIT", ()) in executed


async def test_document_store_judge_and_vector_fetch_error_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(
        __import__("sys").modules,
        "core.judge",
        SimpleNamespace(get_llm_judge=lambda: (_ for _ in ()).throw(RuntimeError("judge boom"))),
    )
    rag.DocumentStore._schedule_judge("q", "a")

    store = _make_store_stub(tmp_path)
    store._pgvector_available = False
    assert store._fetch_pgvector("q", 2, "s1") == []

    store._pgvector_available = True
    store.pg_engine = object()
    monkeypatch.setitem(__import__("sys").modules, "sqlalchemy", SimpleNamespace(text=lambda s: s))
    store._pgvector_embed_texts = lambda _texts: (_ for _ in ()).throw(RuntimeError("embed boom"))  # type: ignore[method-assign]
    assert store._fetch_pgvector("q", 2, "s1") == []


async def test_document_store_pgvector_search_handles_pool_drop_and_empty_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store._pgvector_available = True

    class _EngineBoom:
        def begin(self):
            raise RuntimeError("connection pool dropped")

    store.pg_engine = _EngineBoom()
    monkeypatch.setitem(__import__("sys").modules, "sqlalchemy", SimpleNamespace(text=lambda s: s))
    store._pgvector_embed_texts = lambda _texts: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]

    assert store._fetch_pgvector("q", 2, "s1") == []

    ok, msg = store._pgvector_search("q", 2, "s1")
    assert ok is False
    assert "ilgili sonuç bulunamadı" in msg


async def test_document_store_fetch_chroma_bm25_and_formatter_edges(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_LOCAL_VECTOR_CANDIDATE_MULTIPLIER=1)
    store._is_local_llm_provider = False
    store.collection = SimpleNamespace(
        count=lambda: (_ for _ in ()).throw(RuntimeError("count boom")),
        query=lambda **_kwargs: {
            "ids": [["", "c2"]],
            "documents": [["first", "second"]],
            "metadatas": [[{"parent_id": ""}, {"parent_id": "d2", "title": "Doc2"}]],
        },
    )
    found = store._fetch_chroma("q", 2, "s1")
    assert found and found[0]["id"] == "d2"

    store._bm25_available = False
    assert store._fetch_bm25("hello", 2, "s1") == []

    class _Lock:
        def __enter__(self) -> _Lock:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    store._bm25_available = True
    store._write_lock = _Lock()
    store.fts_conn = SimpleNamespace(
        execute=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fts boom"))
    )
    assert store._fetch_bm25("hello", 2, "s1") == []

    ok, text = store._format_results_from_struct(
        [{"id": "x", "title": "t", "source": "", "snippet": "s", "score": 1.0}],
        "q",
        source_name="BM25",
    )
    assert ok is True
    assert "Kaynak:" not in text


async def test_document_store_graph_impact_and_helpers_extra_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_ready = False
    called: list[str] = []
    store.rebuild_graph_index = lambda root_dir=None: called.append(str(root_dir)) or (True, "ok")  # type: ignore[method-assign]

    # _ensure_graph_ready tetiklenir.
    store._ensure_graph_ready()
    assert called == ["None"]

    # graph_impact_details: boş analiz dalı.
    store._graph_ready = True
    store._graph_index = rag.GraphIndex(tmp_path)
    store._graph_index.impact_analysis = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
    ok, msg = store.graph_impact_details("a.py")
    assert ok is False
    assert "etki analizi üretilemedi" in msg

    # analyze_graph_impact: tüm alanlar dolu iken format satırları.
    store.graph_impact_details = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        True,
        {
            "target": "a.py",
            "node_type": "file",
            "risk_level": "high",
            "direct_dependents": ["b.py"],
            "dependencies": ["c.py"],
            "impacted_endpoints": ["endpoint:GET /x"],
            "impacted_endpoint_handlers": ["api.py"],
            "caller_files": ["ui.js"],
            "review_targets": ["service.py"],
            "dependency_paths": [["ui.js", "api.py", "a.py"]],
        },
    )
    ok, text = store.analyze_graph_impact("a.py")
    assert ok is True
    assert "Doğrudan bağımlılar" in text
    assert "Aşağı akış bağımlılıklar" in text
    assert "Etkilenen endpoint'ler" in text
    assert "Etkilenen endpoint handler dosyaları" in text
    assert "Çağıran dosyalar" in text
    assert "Reviewer için önerilen hedefler" in text
    assert "Örnek etki zincirleri" in text


async def test_document_store_misc_uncovered_fallback_paths(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "Doc"}}
    store._bm25_available = False
    ok, msg = store._search_sync("q", mode="bm25", session_id="s1")
    assert ok is False
    assert "BM25 kullanılamıyor" in msg

    # _touch_document: olmayan belge dalı.
    store._save_index = lambda: (_ for _ in ()).throw(AssertionError("should not save"))  # type: ignore[method-assign]
    store._touch_document("missing")

    # build_graphrag_search_plan: boş sorgu ile vector fetch atlanır.
    store._pgvector_available = True
    store._chroma_available = False
    store.collection = None
    store._graph_rag_enabled = False
    store._fetch_pgvector = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("no fetch")
    )  # type: ignore[method-assign]
    plan = store.build_graphrag_search_plan("", session_id="s1", top_k=2)
    assert plan.query == ""
    assert plan.vector_candidates == []

    # _schedule_judge: judge.enabled=False dalı.
    class _Judge:
        enabled = False

        def schedule_background_evaluation(self, **_kwargs: object) -> None:
            raise AssertionError("should not be called")

    import sys

    sys.modules["core.judge"] = SimpleNamespace(get_llm_judge=lambda: _Judge())
    rag.DocumentStore._schedule_judge("q", "a")


async def test_graph_index_additional_branch_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.py").write_text("x=1", encoding="utf-8")
    keep = root / "keep.py"
    keep.write_text("x=1", encoding="utf-8")
    other = root / "other.py"
    other.write_text("print('ok')\n", encoding="utf-8")

    gi = rag.GraphIndex(root)
    files = gi._iter_source_files(root)
    assert keep in files
    assert all("node_modules" not in str(p) for p in files)
    assert gi._script_import_candidates(keep, "react", root) == []
    legacy_node = ast.Constant(value=" legacy ")
    assert gi._extract_str_literal(legacy_node) == "legacy"

    src = """
from . import mod
@router.get
def no_args(): pass
@router.get("/ok")
def ok(): pass
session.post()
http.get("http://remote.example.com/x")
foo.get("/x")
obj.session.post("/y")
"""
    deps, defs, calls = gi._parse_python_source(keep, src)
    assert isinstance(deps, list)
    assert any(item["path"] == "/ok" for item in defs)
    assert {item["path"] for item in calls} == {"/x", "/y"}

    calls = gi._extract_script_endpoint_calls(
        'fetch("http://remote.example.com/x"); new WebSocket("http://remote.example.com/ws"); new WebSocket("/ws"); new WebSocket("/ws")'
    )
    assert len(calls) == 1

    original_read_text = Path.read_text

    def _boom(self, *args, **kwargs):
        if self == keep:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _boom)
    assert other.read_text(encoding="utf-8") == "print('ok')\n"
    rebuilt = gi.rebuild(root)
    assert rebuilt["nodes"] >= 1

    assert gi.resolve_node_id("   ") is None
    assert gi.explain_dependency_path("missing", "target") == []
    gi.add_node("a")
    gi.add_node("b")
    assert gi.explain_dependency_path("a", "b") == []
    assert gi.impact_analysis("missing") == {}

    gi.add_node("core/a.py", node_type="file")
    gi.add_node("core/b.py", node_type="file")
    gi.add_node("core/c.py", node_type="file")
    gi.add_node("target.py", node_type="file")
    gi.add_edge("core/a.py", "target.py")
    gi.add_edge("core/b.py", "target.py")
    gi.add_edge("core/c.py", "target.py")
    impact = gi.impact_analysis("target.py")
    assert impact["risk_level"] == "medium"


@pytest.mark.xdist_group("env-globals")
async def test_embedding_function_mixed_precision_cuda_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EF:
        def __call__(self, input):
            return ["ok", input]

    class _Factory:
        def __call__(self, **kwargs):
            return _EF()

    fake_embedding_functions = types.SimpleNamespace(
        SentenceTransformerEmbeddingFunction=_Factory()
    )
    fake_chromadb_utils = types.SimpleNamespace(embedding_functions=fake_embedding_functions)
    fake_chromadb = types.SimpleNamespace(utils=fake_chromadb_utils)
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True),
        float16="fp16",
        autocast=lambda **kwargs: contextlib.nullcontext(),
    )

    monkeypatch.setitem(sys.modules, "chromadb", fake_chromadb)
    monkeypatch.setitem(sys.modules, "chromadb.utils", fake_chromadb_utils)
    monkeypatch.setitem(sys.modules, "chromadb.utils.embedding_functions", fake_embedding_functions)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torch.amp", types.ModuleType("torch.amp"))

    ef = rag._build_embedding_function(use_gpu=True, gpu_device=0, mixed_precision=True)
    assert ef is not None
    assert ef.__call__(["x"])[0] == "ok"


async def test_graph_index_parse_and_search_additional_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gi = rag.GraphIndex(tmp_path)
    sample = tmp_path / "svc.py"
    sample.write_text("", encoding="utf-8")

    src = """
@router.get
def no_args(): pass

@router.get("{dynamic}")
def dynamic(): pass

obj.connect("/x")
obj.router.get("/skip")
"""
    deps, defs, calls = gi._parse_python_source(sample, src)
    assert deps == []
    assert defs == []
    assert calls == []

    # ast.Str branchini doğrudan zorla.
    fake_str_cls = type("FakeStr", (), {})
    monkeypatch.setitem(rag.ast.__dict__, "Str", fake_str_cls)
    node = fake_str_cls()
    node.s = " legacy "
    assert gi._extract_str_literal(node) == "legacy"

    gi.add_node("alpha.py", node_type="file")
    gi.add_node("beta.py", node_type="file")
    related = gi.search_related("unmatched-token", top_k=3)
    assert related == []


async def test_document_store_init_and_core_fallback_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(rag.DocumentStore, "_load_index", lambda self: {})
    monkeypatch.setattr(rag.DocumentStore, "_init_fts", lambda self: None)
    chroma_calls: list[str] = []
    monkeypatch.setattr(
        rag.DocumentStore, "_init_chroma", lambda self: chroma_calls.append("chroma")
    )
    monkeypatch.setattr(rag.DocumentStore, "_init_pgvector", lambda self: None)
    monkeypatch.setattr(rag.DocumentStore, "_check_import", lambda self, _m: True)
    cfg = SimpleNamespace(
        RAG_TOP_K=2,
        RAG_CHUNK_SIZE=8,
        RAG_CHUNK_OVERLAP=2,
        RAG_VECTOR_BACKEND="chroma",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=10,
    )
    rag.DocumentStore(tmp_path / "store2", cfg=cfg)
    assert chroma_calls == ["chroma"]

    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(DATABASE_URL="sqlite:///x.db")
    store._check_import = lambda _m: False  # type: ignore[method-assign]
    store._init_pgvector()
    assert getattr(store, "_pgvector_available", False) is False


async def test_document_store_low_level_misc_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {}
    store._save_index()
    assert store.index_file.exists()
    assert store._recursive_chunk_text("", size=10, overlap=2) == []
    assert store._recursive_chunk_text("abc", size=2, overlap=9)

    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("https:///nohost")
    with pytest.raises(ValueError):
        rag.DocumentStore._validate_url_safe("http://10.0.0.1/x")

    # add_document async wrapper
    called = {}
    store._add_document_sync = lambda *args, **kwargs: called.setdefault("ok", "doc-1")  # type: ignore[method-assign]
    assert await store.add_document("t", "c", session_id="s1") == "doc-1"


async def test_document_store_url_file_delete_and_graph_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store._write_lock = threading.Lock()

    # add_document_from_url: title dolu ise regex dalı atlanır
    async def _fake_add(*_args, **_kwargs):
        return "doc-u"

    store.add_document = _fake_add  # type: ignore[method-assign]

    class _Resp:
        text = "<html><body>x</body></html>"
        status_code = 200
        url = "https://example.com/x"
        headers: dict[str, str] = {}

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return _Resp()

    monkeypatch.setitem(sys.modules, "httpx", SimpleNamespace(AsyncClient=lambda **_k: _Client()))
    ok, _msg = await store.add_document_from_url(
        "https://example.com/x", title="manual", session_id="s1"
    )
    assert ok is True

    # file exists/is_file branchleri
    ok, msg = store.add_document_from_file(str(tmp_path / "missing.txt"), session_id="s1")
    assert ok is False and "Dosya bulunamadı" in msg
    d = tmp_path / "adir"
    d.mkdir()
    ok, msg = store.add_document_from_file(str(d), session_id="s1")
    assert ok is False and "yol bir dosya değil" in msg

    # delete_document branchleri
    assert "Belge bulunamadı" in store.delete_document("none", session_id="s1")
    store._index = {"d1": {"title": "Doc", "session_id": "s2"}}
    assert "yetkiniz yok" in store.delete_document("d1", session_id="s1")

    class _FlipLock:
        def __enter__(self):
            store._index.pop("d1", None)
            return self

        def __exit__(self, *_args):
            return None

    store._index = {"d1": {"title": "Doc", "session_id": "s1"}}
    store._write_lock = _FlipLock()
    assert "zaten silinmiş" in store.delete_document("d1", session_id="s1")

    store._graph_rag_enabled = True
    store._graph_root_dir = tmp_path
    store._graph_index = rag.GraphIndex(tmp_path)
    ok, txt = store.rebuild_graph_index(root_dir=str(tmp_path))
    assert ok is True and "GraphIndex hazırlandı" in txt


async def test_document_store_search_projection_and_rrf_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "T1"}}
    store._bm25_available = False
    store._pgvector_available = False
    store._chroma_available = False
    store.collection = None
    store._vector_backend = "bm25"
    store._is_local_llm_provider = True
    store._local_hybrid_enabled = False
    ok, msg = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is False and "ilgili sonuç bulunamadı" in msg

    # Projection break branchleri
    store._graph_rag_enabled = True
    store._graph_ready = True
    g = rag.GraphIndex(tmp_path)
    g.add_node("a.py", node_type="file")
    g.add_node("b.py", node_type="file")
    g.add_node("c.py", node_type="file")
    g.add_edge("a.py", "b.py", kind="imports")
    g.add_edge("b.py", "c.py", kind="imports")
    g.add_edge("c.py", "a.py", kind="imports")
    store._graph_index = g
    proj = store.build_knowledge_graph_projection(session_id="s1", include_code_graph=True, limit=1)
    assert len(proj["edges"]) >= 1
    assert any(e.source.startswith("code:") for e in proj["edges"])

    # search() tracer yok dalı
    rag._otel_trace = None  # type: ignore[assignment]
    store._search_sync = lambda *_args, **_kwargs: (True, "ok")  # type: ignore[method-assign]
    assert await store.search("q", session_id="s1") == (True, "ok")

    # rrf: iki taraf da boş ise keyword fallback
    store._pgvector_available = True
    store._fetch_pgvector = lambda *_a, **_k: []  # type: ignore[method-assign]
    store._fetch_bm25 = lambda *_a, **_k: []  # type: ignore[method-assign]
    store._keyword_search = lambda q, k, s: (True, f"kw:{q}:{k}:{s}")  # type: ignore[method-assign]
    assert store._rrf_search("q", 2, "s1")[1].startswith("kw:")


async def test_document_store_vector_and_keyword_file_not_found_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {"d1": {"session_id": "s1", "title": "Doc1", "source": "src", "tags": ["alpha"]}}
    store._bm25_available = True

    class _Rows:
        def fetchall(self):
            return [{"doc_id": "d1", "score": -1.0}]

    class _Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    store._write_lock = _Lock()
    store.fts_conn = SimpleNamespace(execute=lambda *_a, **_k: _Rows())
    bm = store._fetch_bm25("alpha", 1, "s1")
    assert bm and bm[0]["snippet"] == ""

    kw_ok, kw_msg = store._keyword_search("alpha", 1, "s1")
    assert kw_ok is True and "Doc1" in kw_msg

    # _update_bm25 early return branches
    store._bm25_available = False
    store._update_bm25_cache_on_add("d1", "body")
    store._update_bm25_cache_on_delete("d1")

    # pgvector delete hata dalı
    store._pgvector_available = True
    store.pg_engine = SimpleNamespace(begin=lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setitem(sys.modules, "sqlalchemy", SimpleNamespace(text=lambda s: s))
    store._delete_pgvector_parent("p1", "s1")


async def test_rag_remaining_branches_for_pgvector_and_add_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(DATABASE_URL="postgresql://u:p@h/db")
    store._check_import = lambda _m: True  # type: ignore[method-assign]
    store._pg_table = "t"
    store._pg_embedding_dim = 3
    store._pg_embedding_model_name = "m"
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(
            SentenceTransformer=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("st fail"))
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "sqlalchemy",
        SimpleNamespace(create_engine=lambda *_a, **_k: object(), text=lambda s: s),
    )
    store._init_pgvector()
    assert store._pgvector_available is False

    store._pg_embedding_model = None
    assert store._pgvector_embed_texts(["a"]) == []
    store._pg_embedding_model = SimpleNamespace(
        encode=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("enc fail"))
    )
    assert store._pgvector_embed_texts(["a"]) == []

    store._pgvector_available = True
    store.pg_engine = object()
    store._upsert_pgvector_chunks("d", "p", "s", "t", "src", [])  # 817
    store._pgvector_embed_texts = lambda _chunks: []  # type: ignore[method-assign]
    store._upsert_pgvector_chunks("d", "p", "s", "t", "src", ["c"])  # 823
    store._pgvector_embed_texts = lambda _chunks: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]
    store.pg_engine = SimpleNamespace(begin=lambda: (_ for _ in ()).throw(RuntimeError("sql fail")))
    store._upsert_pgvector_chunks("d", "p", "s", "t", "src", ["c"])  # 860-861

    store.index_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("idx fail"))
    )
    assert store._load_index() == {}

    # recursive chunking deep split paths
    assert store._recursive_chunk_text("X" * 50, size=5, overlap=2)
    assert store._recursive_chunk_text("a\n\n" + "b" * 40, size=8, overlap=2)

    # _add_document_sync: chroma hata dalı + chunks empty branch
    class _DummyLock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    store._write_lock = _DummyLock()
    store._save_index = lambda: None
    store._update_bm25_cache_on_add = lambda *_a: None  # type: ignore[method-assign]
    store._chroma_available = True
    store.collection = SimpleNamespace(
        delete=lambda **_k: (_ for _ in ()).throw(RuntimeError("chroma fail")),
        upsert=lambda **_k: None,
    )
    store._chunk_text = lambda *_a, **_k: []  # type: ignore[method-assign]
    store._pgvector_available = False
    doc = store._add_document_sync("T", "C", source="s", tags=[], session_id="s1")
    assert doc in store._index


async def test_rag_remaining_branches_for_graph_search_and_rrf(tmp_path: Path) -> None:
    # parse branch 217->219, 192
    gi = rag.GraphIndex(tmp_path)
    src = "@router.get\ndef x(): pass\nobj.app.get('/x')\n"
    _deps, defs, calls = gi._parse_python_source(tmp_path / "a.py", src)
    assert defs == [] and calls == []

    # rebuild import target missing node branch (299->297)
    (tmp_path / "main.py").write_text("import missing_mod", encoding="utf-8")
    summary = gi.rebuild(tmp_path)
    assert summary["nodes"] >= 1

    # impact branchleri 400->399, 416->414
    gi.add_node("endpoint:GET /z", node_type="endpoint")
    gi.add_node("handler:virtual", node_type="endpoint")
    gi.add_edge("endpoint:GET /z", "handler:virtual", kind="handled_by")
    gi.add_node("target.py", node_type="file")
    gi.add_edge("target.py", "endpoint:GET /z", kind="calls_endpoint")
    impact = gi.impact_analysis("target.py")
    assert impact["dependency_paths"] == []

    store = _make_store_stub(tmp_path)
    store._graph_rag_enabled = True
    store._graph_ready = True
    store._graph_index = gi
    ok, msg = store.explain_dependency_path("a.py", "missing.py")
    assert ok is False and "bulunamadı" in msg
    store.graph_impact_details = lambda *_a, **_k: (
        True,
        {"target": "x", "node_type": "file", "risk_level": "low", "dependencies": []},
    )  # type: ignore[method-assign]
    ok, text = store.analyze_graph_impact("x")
    assert ok is True and "Aşağı akış bağımlılıklar" not in text


async def test_graph_index_parse_python_source_skips_router_like_attribute_calls(
    tmp_path: Path,
) -> None:
    gi = rag.GraphIndex(tmp_path)
    src = """
def call_it():
    client.router.get('/health')
    service.app.post('/submit')
"""

    _deps, defs, calls = gi._parse_python_source(tmp_path / "a.py", src)

    assert defs == []
    assert calls == []


async def test_document_store_pgvector_init_handles_hnsw_index_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store.cfg = SimpleNamespace(DATABASE_URL="postgresql://u:p@localhost/db")
    store._pg_table = "rag_embeddings"
    store._pg_embedding_dim = 3
    store._pg_embedding_model_name = "mini"
    store._pg_embedding_model = None
    store.pg_engine = None
    store._pgvector_available = False
    store._hf_env_lock = threading.Lock()
    store._hf_env_applied = False
    executed: list[str] = []

    class _Conn:
        def execute(self, statement):
            sql = str(statement)
            executed.append(sql)
            if "embedding_hnsw" in sql:
                raise RuntimeError("hnsw index unavailable")

    class _Begin:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *_args):
            return False

    class _Engine:
        def begin(self):
            return _Begin()

        def dispose(self):
            return None

    sentence_transformers = types.SimpleNamespace(
        SentenceTransformer=lambda _model_name: (_ for _ in ()).throw(
            AssertionError("embedding model should not load after index failure")
        )
    )
    sqlalchemy = types.SimpleNamespace(
        create_engine=lambda *_a, **_k: _Engine(), text=lambda sql: sql
    )
    monkeypatch.setitem(sys.modules, "sentence_transformers", sentence_transformers)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy)
    monkeypatch.setitem(sys.modules, "pgvector", types.SimpleNamespace())
    monkeypatch.setattr(store, "_check_import", lambda _module_name: True)

    store._init_pgvector()

    assert store._pgvector_available is False
    assert any("CREATE EXTENSION" in sql for sql in executed)
    assert any("idx_rag_embeddings_embedding_hnsw" in sql for sql in executed)


async def test_document_store_init_fts_skips_migration_when_index_empty(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._write_lock = threading.Lock()
    store._index = {}

    store._init_fts()

    count = store.fts_conn.execute("SELECT count(*) as c FROM bm25_index").fetchone()["c"]
    assert count == 0


async def test_document_store_recursive_chunk_text_forced_fallback_split(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    original_list = list

    def _patched_list(arg):  # type: ignore[no-untyped-def]
        if isinstance(arg, str) and len(arg) > 1:
            return [arg]
        return original_list(arg)

    monkeypatch.setattr(rag, "list", _patched_list)

    chunks = store._recursive_chunk_text("abcdefghij", size=4, overlap=1)

    assert chunks == ["abcd", "defg", "ghij", "j"]

    # _search_sync fallback zinciri 1521+ branches
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "T"}}
    store._pgvector_available = True
    store._chroma_available = True
    store.collection = object()
    store._bm25_available = False
    store._is_local_llm_provider = False
    store._rrf_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rrf"))  # type: ignore[method-assign]
    store._pgvector_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("pg"))  # type: ignore[method-assign]
    store._chroma_search = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("ch"))  # type: ignore[method-assign]
    store._keyword_search = lambda q, k, s: (True, f"kw:{q}:{k}:{s}")  # type: ignore[method-assign]
    ok, _res = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is True

    # search tracer none -> 1553-1555
    rag._otel_trace = None  # type: ignore[assignment]
    store._search_sync = lambda *_a, **_k: (True, "ok")  # type: ignore[method-assign]
    assert await store.search("q", session_id="s1") == (True, "ok")

    # rrf non-empty bm25 path 1589-1591
    store2 = _make_store_stub(tmp_path)
    store2._pgvector_available = True
    store2._fetch_pgvector = lambda *_a, **_k: [
        {"id": "a", "title": "A", "source": "", "snippet": "", "score": 0.1}
    ]  # type: ignore[method-assign]
    store2._fetch_bm25 = lambda *_a, **_k: [
        {"id": "b", "title": "B", "source": "", "snippet": "", "score": 0.2}
    ]  # type: ignore[method-assign]
    ok, text = store2._rrf_search("q", 2, "s1")
    assert ok is True and "Hibrit RRF" in text

    # fetch_pgvector rows empty -> 1628->1644
    store._pgvector_available = True
    store.pg_engine = SimpleNamespace(
        begin=lambda: contextlib.nullcontext(
            SimpleNamespace(execute=lambda *_a, **_k: SimpleNamespace(fetchall=lambda: []))
        )
    )
    store._pgvector_embed_texts = lambda _t: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]
    monkeypatch.setitem(sys.modules, "sqlalchemy", SimpleNamespace(text=lambda s: s))
    assert store._fetch_pgvector("q", 2, "s1") == []


async def test_rag_remaining_edge_branches_round_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gi = rag.GraphIndex(tmp_path)
    src = """
@router.get()
def a(): pass
obj.client.get('/ok')
"""
    _deps, defs, calls = gi._parse_python_source(tmp_path / "x.py", src)
    assert defs == []
    assert calls and calls[0]["path"] == "/ok"

    # rebuild branch: dep hedefi düğümde yok
    a = tmp_path / "a.py"
    a.write_text("import x", encoding="utf-8")
    monkeypatch.setattr(
        gi, "_extract_dependencies", lambda *_a, **_k: ([tmp_path / "missing.py"], [], [])
    )
    summary = gi.rebuild(tmp_path)
    assert summary["nodes"] >= 1

    # impact: endpoint handler file değil, dependency path boş
    gi.clear()
    gi.add_node("target.py", node_type="file")
    gi.add_node("endpoint:GET /a", node_type="endpoint")
    gi.add_node("endpoint-handler", node_type="endpoint")
    gi.add_edge("endpoint:GET /a", "target.py", kind="handled_by")
    gi.add_edge("endpoint:GET /a", "endpoint-handler", kind="handled_by")
    gi.add_edge("caller.py", "endpoint:GET /a", kind="calls_endpoint")
    gi.add_node("caller.py", node_type="file")
    impact = gi.impact_analysis("target.py")
    assert "endpoint-handler" not in impact["impacted_endpoint_handlers"]

    # _init_chroma embedding_fn None path
    store = _make_store_stub(tmp_path)
    store._use_gpu = False
    store._gpu_device = 0
    store._mixed_precision = False
    store._chroma_available = True
    store._apply_hf_runtime_env = lambda: None  # type: ignore[method-assign]

    class _Client:
        def get_or_create_collection(self, **kwargs):
            assert "embedding_function" not in kwargs
            return object()

    monkeypatch.setitem(
        sys.modules, "chromadb", SimpleNamespace(PersistentClient=lambda **_k: _Client())
    )
    monkeypatch.setitem(
        sys.modules, "chromadb.config", SimpleNamespace(Settings=lambda **_k: object())
    )
    monkeypatch.setattr(rag, "_build_embedding_function", lambda **_k: None)
    store._init_chroma()
    assert store.collection is not None

    # _init_fts migrate exception branch 727->740/738
    store._index = {"d1": {"session_id": "s1"}}
    store._bm25_available = True

    class _Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    store._write_lock = _Lock()
    store._init_fts()
    assert store._bm25_available is True

    # _init_pgvector early returns
    store.cfg = SimpleNamespace(DATABASE_URL="sqlite:///a.db")
    store._init_pgvector()
    store.cfg = SimpleNamespace(DATABASE_URL="postgresql://u:p@h/db")
    store._check_import = lambda _m: False  # type: ignore[method-assign]
    store._init_pgvector()

    # _delete_pgvector_parent guard
    store._pgvector_available = True
    store.pg_engine = None
    store._delete_pgvector_parent("p", "s")

    # _load_index no file (878->883)
    store.index_file.unlink(missing_ok=True)
    assert store._load_index() == {}

    # add_document chroma branching with empty chunks (1028/1034 false)
    class _Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    store._write_lock = _Lock()
    store._save_index = lambda: None
    store._update_bm25_cache_on_add = lambda *_a: None  # type: ignore[method-assign]
    calls = []
    store.collection = SimpleNamespace(
        delete=lambda **_k: calls.append("del"), upsert=lambda **_k: calls.append("up")
    )
    store._chroma_available = True
    store._pgvector_available = False
    store._chunk_size = 0
    store._add_document_sync("t", "c", source="s", tags=[], session_id="s1")
    assert calls == ["del"]

    # _validate_url_safe 1076->1082 path (public ip)
    rag.DocumentStore._validate_url_safe("http://8.8.8.8/x")

    # delete_document doc file yoksa chroma branchine düşsün
    store._index = {"d2": {"title": "D2", "session_id": "s1"}}
    store._chroma_available = False
    store.collection = None
    store._update_bm25_cache_on_delete = lambda *_a: None  # type: ignore[method-assign]
    msg = store.delete_document("d2", session_id="s1")
    assert "Belge silindi" in msg

    # _search_sync fallback zinciri alt dallar
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d1": {"session_id": "s1", "title": "T"}}
    store._bm25_available = False
    store._pgvector_available = False
    store._chroma_available = True
    store.collection = object()
    store._chroma_search = lambda q, k, s: (True, f"ch:{q}")  # type: ignore[method-assign]
    ok, out = store._search_sync("q", mode="auto", session_id="s1")
    assert ok is True and out.startswith("ch:")


async def test_rag_final_remaining_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # __init__ 631->635
    monkeypatch.setattr(rag.DocumentStore, "_load_index", lambda self: {})
    monkeypatch.setattr(rag.DocumentStore, "_init_fts", lambda self: None)
    monkeypatch.setattr(
        rag.DocumentStore,
        "_init_chroma",
        lambda self: (_ for _ in ()).throw(AssertionError("no chroma")),
    )
    monkeypatch.setattr(rag.DocumentStore, "_check_import", lambda self, _m: False)
    cfg = SimpleNamespace(
        RAG_TOP_K=1,
        RAG_CHUNK_SIZE=8,
        RAG_CHUNK_OVERLAP=2,
        RAG_VECTOR_BACKEND="bm25",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=1,
    )
    rag.DocumentStore(tmp_path / "s3", cfg=cfg)

    store = _make_store_stub(tmp_path)

    class _L:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

    store._write_lock = _L()
    store._save_index = lambda: None
    store._update_bm25_cache_on_add = lambda *_a: None  # type: ignore[method-assign]
    store._chroma_available = False
    store.collection = None
    store._pgvector_available = False
    store._add_document_sync("t", "c", source="s", tags=[], session_id="s1")  # 1025->1042

    # _search_sync 1529->1533
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store.default_top_k = 2
    store._index = {"d": {"session_id": "s1", "title": "T"}}
    store._pgvector_available = False
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._bm25_search = lambda q, k, s: (True, f"bm:{q}")  # type: ignore[method-assign]
    assert store._search_sync("q", mode="auto", session_id="s1")[1].startswith("bm:")

    # _fetch_pgvector 1628->1644 with empty rows
    store._pgvector_available = True
    store._pg_table = "t"
    store._is_local_llm_provider = False
    store._pgvector_embed_texts = lambda _t: [[0.1, 0.2, 0.3]]  # type: ignore[method-assign]

    class _Conn:
        def execute(self, *_a, **_k):
            return SimpleNamespace(fetchall=lambda: [])

    store.pg_engine = SimpleNamespace(begin=lambda: contextlib.nullcontext(_Conn()))
    monkeypatch.setitem(sys.modules, "sqlalchemy", SimpleNamespace(text=lambda s: s))
    assert store._fetch_pgvector("q", 2, "s1") == []


async def test_document_store_reinitialization_logs_ready_bm25_vector_backends(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = _make_store_stub(tmp_path)
    store._backend_init_lock = threading.Lock()
    store._vector_initialization_enabled = True
    store._vector_init_done = True
    store._bm25_init_done = True
    store._vector_backend = "bm25"
    store._chroma_available = True
    store._pgvector_available = True
    store._init_chroma = lambda: (_ for _ in ()).throw(AssertionError("already initialized"))
    store._init_pgvector = lambda: (_ for _ in ()).throw(AssertionError("already initialized"))
    store._init_fts = lambda: (_ for _ in ()).throw(AssertionError("already initialized"))
    monkeypatch.setattr(rag.DocumentStore, "_backend_info_logged", {})

    store._initialize_backends_once()

    assert rag.DocumentStore._backend_info_logged["vector_preference_bm25_hint"] is True


async def test_document_store_init_with_vector_initialization_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_calls: list[str] = []
    monkeypatch.setattr(rag.DocumentStore, "_load_index", lambda self: {})
    monkeypatch.setattr(rag.DocumentStore, "_init_fts", lambda self: init_calls.append("fts"))
    monkeypatch.setattr(rag.DocumentStore, "_init_chroma", lambda self: init_calls.append("chroma"))
    monkeypatch.setattr(rag.DocumentStore, "_check_import", lambda self, _m: True)

    cfg = SimpleNamespace(
        RAG_TOP_K=1,
        RAG_CHUNK_SIZE=8,
        RAG_CHUNK_OVERLAP=2,
        RAG_VECTOR_BACKEND="chroma",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        ENABLE_GRAPH_RAG=False,
        BASE_DIR=tmp_path,
        GRAPH_RAG_MAX_FILES=1,
    )
    store = rag.DocumentStore(tmp_path / "no_vector_init", cfg=cfg, initialize_vector=False)

    assert store._chroma_available is False
    assert init_calls == ["fts"]


async def test_add_document_from_file_uses_filename_when_title_empty(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    captured: dict[str, str] = {}

    def _add(title: str, content: str, **_kwargs: object) -> str:
        captured["title"] = title
        captured["content"] = content
        return "doc-file"

    store._add_document_sync = _add  # type: ignore[method-assign]
    path = tmp_path / "notes.txt"
    path.write_text("hello world", encoding="utf-8")
    ok, msg = store.add_document_from_file(str(path), title="", session_id="s-file")

    assert ok is True
    assert "doc-file" in msg
    assert captured["title"] == "notes.txt"


async def test_rrf_search_merges_bm25_only_ids_into_docs_map(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._pgvector_available = False
    store._fetch_chroma = lambda *_a, **_k: [{"id": "v1", "content": "vector"}]  # type: ignore[method-assign]
    store._fetch_bm25 = lambda *_a, **_k: [{"id": "b1", "content": "bm25"}]  # type: ignore[method-assign]
    store._keyword_search = lambda *_a, **_k: (False, "kw")  # type: ignore[method-assign]
    store._format_results_from_struct = lambda final, *_a, **_k: (  # type: ignore[method-assign]
        True,
        ",".join(item["id"] for item in final),
    )

    ok, text = store._rrf_search("query", 5, "s1")
    assert ok is True
    assert "v1" in text and "b1" in text


async def test_rag_almost_final_branches_for_parser_impact_and_fts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gi = rag.GraphIndex(tmp_path)
    deps, defs, calls = gi._parse_python_source(tmp_path / "p.py", "obj.client.get('/z')")
    assert deps == [] and defs == [] and calls[0]["path"] == "/z"

    gi.add_node("target.py", node_type="file")
    gi.add_node("endpoint:GET /k", node_type="endpoint")
    gi.add_edge("caller.py", "endpoint:GET /k", kind="calls_endpoint")
    gi.add_edge("endpoint:GET /k", "target.py", kind="handled_by")
    gi.add_node("caller.py", node_type="file")
    monkeypatch.setattr(gi, "explain_dependency_path", lambda *_a, **_k: [])
    impact = gi.impact_analysis("target.py")
    assert isinstance(impact, dict)

    store = _make_store_stub(tmp_path)

    class _Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

    store._write_lock = _Lock()
    store._bm25_available = True
    store._index = {"missing-doc": {"session_id": "s1"}}
    # file intentionally missing -> line 738 except/pass branch
    store._init_fts()
    assert store._bm25_available is True


async def test_document_store_search_uses_vector_hits_from_fake_vector_store(
    tmp_path: Path,
    fake_vector_store,
) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {"doc-1": {"session_id": "s1"}}
    store._pgvector_available = True
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._vector_backend = "pgvector"
    store.cfg = SimpleNamespace(RAG_TOP_K=2)

    def _pgvector_search(_query: str, _top_k: int, _session_id: str):
        rows = list(fake_vector_store.search.return_value)
        return True, "\n".join(item["content"] for item in rows)

    store._pgvector_search = _pgvector_search  # type: ignore[method-assign]
    store._keyword_search = lambda *_args, **_kwargs: (True, "keyword-fallback")  # type: ignore[method-assign]

    ok, result = store._search_sync("pytest", top_k=2, mode="auto", session_id="s1")

    assert ok is True
    assert "mock context for RAG" in result


async def test_document_store_search_fallbacks_when_fake_vector_store_empty_or_error(
    tmp_path: Path,
    fake_vector_store,
) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {"doc-1": {"session_id": "s1"}}
    store._pgvector_available = True
    store._chroma_available = False
    store.collection = None
    store._bm25_available = True
    store._vector_backend = "pgvector"
    store.cfg = SimpleNamespace(RAG_TOP_K=2)
    store._keyword_search = lambda *_args, **_kwargs: (True, "keyword-fallback")  # type: ignore[method-assign]

    fake_vector_store.set_empty_result()

    def _pgvector_empty(_query: str, _top_k: int, _session_id: str):
        rows = list(fake_vector_store.search.return_value)
        if not rows:
            raise RuntimeError("empty vector results")
        return True, "unused"

    store._pgvector_search = _pgvector_empty  # type: ignore[method-assign]

    ok_empty, result_empty = store._search_sync("pytest", top_k=2, mode="auto", session_id="s1")
    assert ok_empty is True
    assert result_empty == "keyword-fallback"
    fake_vector_store.search.return_value = [{"content": "present"}]
    assert _pgvector_empty("pytest", 2, "s1") == (True, "unused")

    fake_vector_store.set_db_error()

    def _pgvector_error(_query: str, _top_k: int, _session_id: str):
        side_effect = fake_vector_store.search.side_effect
        if isinstance(side_effect, BaseException):
            raise side_effect
        return True, "unused"

    store._pgvector_search = _pgvector_error  # type: ignore[method-assign]

    ok_err, result_err = store._search_sync("pytest", top_k=2, mode="auto", session_id="s1")
    assert ok_err is True
    assert result_err == "keyword-fallback"
    fake_vector_store.search.side_effect = None
    assert _pgvector_error("pytest", 2, "s1") == (True, "unused")


async def test_require_pg_engine_raises_when_engine_missing(tmp_path: Path) -> None:
    """Line 703: pgvector engine başlatılmadıysa açık RuntimeError fırlatılmalı."""
    store = _make_store_stub(tmp_path)
    store.pg_engine = None
    with pytest.raises(RuntimeError, match="pgvector engine başlatılmamış"):
        store._require_pg_engine()

    sentinel = object()
    store.pg_engine = sentinel
    assert store._require_pg_engine() is sentinel


async def test_require_chroma_collection_raises_when_collection_missing(
    tmp_path: Path,
) -> None:
    """Line 709: chroma collection başlatılmadıysa açık RuntimeError fırlatılmalı."""
    store = _make_store_stub(tmp_path)
    store.collection = None
    with pytest.raises(RuntimeError, match="Chroma collection başlatılmamış"):
        store._require_chroma_collection()

    sentinel = SimpleNamespace(count=lambda: 0)
    store.collection = sentinel
    assert store._require_chroma_collection() is sentinel


async def test_fetch_pgvector_returns_empty_when_query_embedding_empty(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._pgvector_available = True
    store.pg_engine = SimpleNamespace(
        begin=lambda: (_ for _ in ()).throw(AssertionError("SQL should not run"))
    )
    store._pgvector_embed_texts = lambda _texts: []  # type: ignore[method-assign]

    assert store._fetch_pgvector("query", top_k=2, session_id="s1") == []


async def test_pgvector_embed_texts_uses_tolist_when_vectors_support_it(
    tmp_path: Path,
) -> None:
    """Lines 920-922: encode() çıktısı tolist'e sahipse bunu kullanmalı."""
    store = _make_store_stub(tmp_path)

    class _FakeVectors:
        def tolist(self) -> list[list[float]]:
            return [[1.0, 2.0], [3.0, 4.0]]

    class _FakeModel:
        def encode(self, texts, **_kwargs):
            assert texts == ["a", "b"]
            return _FakeVectors()

    store._pg_embedding_model = _FakeModel()
    embedded = store._pgvector_embed_texts(["a", "b"])
    assert embedded == [[1.0, 2.0], [3.0, 4.0]]


async def test_pgvector_embed_texts_falls_back_when_vectors_lack_tolist(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)

    class _FakeModel:
        def encode(self, texts, **_kwargs):
            return [[5.0, 6.0]]

    store._pg_embedding_model = _FakeModel()
    embedded = store._pgvector_embed_texts(["x"])
    assert embedded == [[5.0, 6.0]]


async def test_pgvector_embed_texts_returns_empty_for_missing_model_or_texts(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store._pg_embedding_model = None
    assert store._pgvector_embed_texts(["a"]) == []
    store._pg_embedding_model = object()
    assert store._pgvector_embed_texts([]) == []


async def test_load_index_returns_empty_dict_when_json_is_not_dict(tmp_path: Path) -> None:
    """Line 1010: JSON parse edilebilir ama dict değilse {} dönmeli."""
    store = _make_store_stub(tmp_path)
    store.index_file.write_text('["not", "a", "dict"]', encoding="utf-8")
    assert store._load_index() == {}

    store.index_file.write_text('{"d1": {"title": "ok"}}', encoding="utf-8")
    assert store._load_index() == {"d1": {"title": "ok"}}


async def test_analyze_graph_impact_returns_format_error_when_analysis_not_dict(
    tmp_path: Path,
) -> None:
    """Line 1500: graph_impact_details (True, <dict-değil>) dönerse formatlı hata mesajı."""
    store = _make_store_stub(tmp_path)
    store.graph_impact_details = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
        True,
        "string-yerine-dict-değil",
    )
    ok, message = store.analyze_graph_impact("a.py")
    assert ok is False
    assert message == "Graph impact analizi beklenen formatta dönmedi."


async def test_rrf_search_skips_duplicate_doc_id_in_bm25(tmp_path: Path) -> None:
    """Branch 1873->1875: bm25 sonucu zaten docs_map'te varsa skoru güncellenmeli ama tekrar eklenmemeli."""
    store = _make_store_stub(tmp_path)
    store._index = {"d-shared": {"session_id": "s1", "title": "Shared", "source": "src://shared"}}
    store._pgvector_available = True

    vector_doc = {
        "id": "d-shared",
        "title": "Shared",
        "source": "src://shared",
        "snippet": "vector-snippet",
        "score": 0.9,
    }
    bm25_doc = {
        "id": "d-shared",
        "title": "Shared (bm25)",
        "source": "src://shared",
        "snippet": "bm25-snippet",
        "score": 0.5,
    }
    store._fetch_pgvector = lambda _q, _k, _s: [vector_doc]  # type: ignore[method-assign]
    store._fetch_bm25 = lambda _q, _k, _s: [bm25_doc]  # type: ignore[method-assign]

    ok, text = store._rrf_search("query", 1, "s1")
    assert ok is True
    # Vector kayıt korunmalı: snippet vector kaynağından gelmeli, bm25 üzerine yazmamalı.
    assert "vector-snippet" in text
    assert "bm25-snippet" not in text


async def test_document_store_extracts_marketing_entities_and_graph_search(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.entity_graph_file = tmp_path / "entity_graph.json"
    store._entity_graph = {"nodes": {}, "edges": []}
    store._entity_extraction_enabled = True
    store._entity_max_per_doc = 24
    store._graph_rag_enabled = True
    store._graph_ready = True
    store._graph_index = rag.GraphIndex(tmp_path)

    content = """
    Kampanya adı: Bahar Lansmanı
    Marka: Sidar
    Hedef kitle: KOBİ operasyon ekipleri
    Marka dili: güven veren ve net
    Kanal: LinkedIn
    """

    entities, relations = store.extract_document_entities(
        "Bahar kampanya brief",
        content,
        tags=["audience:B2B karar vericiler"],
        source="memory://campaign/2026-spring",
    )

    assert {entity.label for entity in entities} >= {"Campaign", "Brand", "Audience", "Tone"}
    assert any(relation.relation == "TARGETS_AUDIENCE" for relation in relations)
    assert any(relation.relation == "USES_TONE" for relation in relations)

    store._upsert_document_entities(
        "doc1",
        "Bahar kampanya brief",
        content,
        source="memory://campaign/2026-spring",
        tags=["audience:B2B karar vericiler"],
        session_id="marketing",
    )

    results = store.search_entity_graph("Bahar KOBİ güven", session_id="marketing", top_k=5)
    assert results
    assert any(item["node"]["label"] == "Campaign" for item in results)

    ok, text = store.search_graph("Bahar KOBİ", top_k=5)
    assert ok is True
    assert "İlişkisel bellek entity sonuçları" in text
    assert "Bahar Lansmanı" in text

    projection = store.build_knowledge_graph_projection(
        session_id="marketing", include_code_graph=False, limit=20
    )
    assert any(node.id.startswith("entity:campaign:") for node in projection["nodes"])
    assert any(edge.relation == "TARGETS_AUDIENCE" for edge in projection["edges"])

    store._delete_document_entities("doc1")
    assert not store.search_entity_graph("Bahar", session_id="marketing", top_k=5)


async def test_pgvector_failure_action_message_specific_branches() -> None:
    assert "zaman aşımı" in rag._pgvector_failure_action_message(TimeoutError("timed out"))
    assert "bağlantısı kurulamadı" in rag._pgvector_failure_action_message(
        ConnectionError("connection refused")
    )
    assert "pgvector hazırlığı" in rag._pgvector_failure_action_message(
        RuntimeError("extension vector is missing")
    )


async def test_entity_graph_loading_normalization_and_json_extraction_branches(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    graph_file = tmp_path / "entity_graph.json"
    store.entity_graph_file = graph_file
    graph_file.write_text(
        json.dumps({"nodes": {"brand:sidar": {"label": "Brand"}}, "edges": {"bad": "shape"}}),
        encoding="utf-8",
    )

    loaded = store._load_entity_graph()
    assert loaded["nodes"] == {"brand:sidar": {"label": "Brand"}}
    assert loaded["edges"] == ["bad"]

    graph_file.write_text("{broken", encoding="utf-8")
    assert store._load_entity_graph() == {"nodes": {}, "edges": []}

    store._entity_graph = {"nodes": [], "edges": {}}
    ensured = store._ensure_entity_graph()
    assert ensured == {"nodes": {}, "edges": []}

    assert len(store._entity_slug("!!!")) == 12
    assert store._extract_json_entities({"campaign": "Launch", "nested": {"brand": "Sidar"}})
    assert store._extract_json_entities([{"platform": "LinkedIn"}])[0].label == "Channel"


async def test_document_store_llm_entity_extraction_feature_flag_merges_payload(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store._entity_max_per_doc = 24
    store._llm_entity_extraction_settings = rag.LLMEntityExtractionSettings(enabled=True)

    def fake_extractor(title, content, tags, source, settings):
        assert title == "Launch brief"
        assert "Brand: Sidar" in content
        assert tags == ["channel:Email"]
        assert source == "memory://launch"
        assert settings.enabled is True
        return {
            "schema_version": rag.LLM_ENTITY_SCHEMA_VERSION,
            "entities": [
                {"label": "Campaign", "name": "LLM Launch"},
                {"label": "Audience", "name": "Developers"},
            ],
            "relations": [
                {
                    "source_label": "Campaign",
                    "source_name": "LLM Launch",
                    "target_label": "Audience",
                    "target_name": "Developers",
                    "type": "TARGETS_AUDIENCE",
                }
            ],
        }

    store._llm_entity_extractor = fake_extractor

    entities, relations = store.extract_document_entities(
        "Launch brief", "Brand: Sidar", tags=["channel:Email"], source="memory://launch"
    )

    entity_names = {(entity.label, entity.name) for entity in entities}
    assert ("Campaign", "LLM Launch") in entity_names
    assert ("Audience", "Developers") in entity_names
    assert any(relation.relation == "TARGETS_AUDIENCE" for relation in relations)


async def test_extract_document_entities_json_tags_empty_and_invalid_branches(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store._entity_max_per_doc = 24

    empty_entities, empty_relations = store.extract_document_entities("", "   ", tags=["badtag"])
    assert empty_entities == []
    assert empty_relations == []

    entities, relations = store.extract_document_entities(
        "Plain title",
        json.dumps(
            {
                "campaign": "JSON Launch",
                "brand": "Sidar",
                "target_audience": "Developers",
                "brand_voice": "Confident",
                "platform": "LinkedIn",
            }
        ),
        tags=["channel:Newsletter", "ignored"],
        source="https://example.com/campaign",
    )
    labels = {entity.label for entity in entities}
    assert {"Campaign", "Brand", "Audience", "Tone", "Channel", "Source"} <= labels
    assert {relation.relation for relation in relations} >= {
        "TARGETS_AUDIENCE",
        "PROMOTES_BRAND",
        "USES_TONE",
        "RUNS_ON",
        "HAS_BRAND_VOICE",
    }

    invalid_json_entities, _ = store.extract_document_entities("", "{not-json", tags=[])
    assert invalid_json_entities == []


async def test_upsert_and_search_entity_graph_edge_filter_branches(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store.entity_graph_file = tmp_path / "entity_graph.json"
    store._entity_graph = {"nodes": {}, "edges": []}
    store._entity_extraction_enabled = False
    store._upsert_document_entities("skip", "Title", "campaign: x")
    assert store._entity_graph == {"nodes": {}, "edges": []}

    store._entity_extraction_enabled = True
    store._entity_graph = {
        "nodes": {},
        "edges": [
            {
                "source": "campaign:missing",
                "target": "audience:missing",
                "relation": "BROKEN",
                "doc_id": "doc1",
            }
        ],
    }
    store._upsert_document_entities(
        "doc1",
        "Campaign doc",
        "campaign: Valid\naudience: Builders",
        session_id="s1",
    )
    assert all(edge.get("relation") != "BROKEN" for edge in store._entity_graph["edges"])
    assert store.search_entity_graph("", session_id="s1") == []
    store._entity_graph["nodes"]["brand:other"] = {
        "label": "Brand",
        "name": "Other",
        "properties": {"session_id": "other"},
    }
    results = store.search_entity_graph("Other", session_id="s1")
    assert results == []


async def test_knowledge_graph_projection_entity_filters_and_limits(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._index = {
        "doc-other": {"title": "Other", "source": "", "session_id": "other"},
        "doc-s1": {"title": "Doc", "source": "src", "session_id": "s1"},
    }
    store._pgvector_available = True
    store._graph_rag_enabled = False
    store._entity_graph = {
        "nodes": {
            "campaign:keep": {
                "label": "Campaign",
                "name": "Keep",
                "properties": {"session_id": "s1"},
            },
            "brand:global": {"label": "Brand", "name": "Global", "properties": {}},
            "campaign:skip": {
                "label": "Campaign",
                "name": "Skip",
                "properties": {"session_id": "other"},
            },
        },
        "edges": [
            {"source": "campaign:skip", "target": "brand:global", "session_id": "other"},
            {"source": "", "target": "brand:global", "session_id": "s1"},
            {"source": "campaign:keep", "target": "brand:global", "session_id": "s1"},
            {"source": "campaign:keep", "target": "brand:global", "session_id": "s1"},
        ],
    }

    projection = store.build_knowledge_graph_projection(
        session_id="s1", include_code_graph=False, limit=1
    )

    node_ids = {node.id for node in projection["nodes"]}
    assert "doc:doc-other" not in node_ids
    assert "entity:campaign:skip" not in node_ids
    assert "entity:campaign:keep" in node_ids
    assert "entity:brand:global" not in node_ids
    assert not any(edge.relation == "CONTAINS_DOCUMENT" for edge in projection["edges"])
    assert sum(edge.source == "entity:campaign:keep" for edge in projection["edges"]) == 1


async def test_entity_extraction_empty_values_and_invalid_relation_skip(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._entity_max_per_doc = 24
    # Empty JSON list and empty cleaned campaign value cover recursion/no-op branches.
    assert store._extract_json_entities([]) == []
    assert store._extract_json_entities({"campaign": "---"}) == []
    entities, relations = store.extract_document_entities(
        "", "Campaign: ---", tags=["unknown:value"]
    )
    assert entities == []
    assert relations == []

    store.entity_graph_file = tmp_path / "entity_graph.json"
    store._entity_graph = {"nodes": {}, "edges": []}
    store._entity_extraction_enabled = True
    valid_entity = rag.ExtractedKnowledgeEntity("campaign:valid", "Campaign", "Valid")
    invalid_relation = rag.ExtractedKnowledgeRelation(
        "campaign:valid", "audience:missing", "TARGETS_AUDIENCE"
    )
    store.extract_document_entities = lambda *_a, **_kw: ([valid_entity], [invalid_relation])  # type: ignore[method-assign]

    store._upsert_document_entities("doc-invalid", "Title", "Content")

    assert all(edge.get("relation") != "TARGETS_AUDIENCE" for edge in store._entity_graph["edges"])


async def test_entity_graph_load_rejects_non_dict_and_projection_skips_session_nodes(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store.entity_graph_file = tmp_path / "entity_graph.json"
    store.entity_graph_file.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert store._load_entity_graph() == {"nodes": {}, "edges": []}

    store._index = {}
    store._graph_rag_enabled = False
    store._entity_graph = {
        "nodes": {
            "campaign:skip": {
                "label": "Campaign",
                "name": "Skip",
                "properties": {"session_id": "other"},
            },
            "campaign:keep": {
                "label": "Campaign",
                "name": "Keep",
                "properties": {"session_id": "s1"},
            },
        },
        "edges": [],
    }

    projection = store.build_knowledge_graph_projection(
        session_id="s1", include_code_graph=False, limit=2
    )
    node_ids = {node.id for node in projection["nodes"]}
    assert "entity:campaign:skip" not in node_ids
    assert "entity:campaign:keep" in node_ids


async def test_entity_extraction_ignores_blank_regex_capture_and_scalar_json_payload(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store._entity_max_per_doc = 24

    entities, _ = store.extract_document_entities("", "campaign: \nbrand: Sidar", tags=[])

    labels = [entity.label for entity in entities]
    assert "Brand" in labels
    assert "Campaign" in labels
    assert store._extract_json_entities("plain scalar") == []


async def test_pgvector_failure_message_uses_shared_db_diagnosis(monkeypatch) -> None:
    monkeypatch.setattr(
        rag, "postgres_failure_diagnosis", lambda _reason, _exc: "shared-db-diagnosis"
    )

    message = rag._pgvector_failure_action_message(RuntimeError("password authentication failed"))

    assert message == "pgvector pasif, BM25 fallback aktif. Teşhis: shared-db-diagnosis."
    assert "DATABASE_URL değerlerini kontrol edin" not in message


async def test_entity_extraction_ignores_empty_tag_value_after_normalization(
    tmp_path: Path,
) -> None:
    store = _make_store_stub(tmp_path)
    store._entity_max_per_doc = 24

    entities, relations = store.extract_document_entities("", "", tags=["brand: ---"])

    assert entities == []
    assert relations == []


async def test_document_store_listing_marks_unavailable_pgvector_backend(tmp_path: Path) -> None:
    store = _make_store_stub(tmp_path)
    store._vector_backend = "pgvector"
    store._pgvector_available = False
    store._index = {
        "d1": {
            "session_id": "s1",
            "title": "Doc 1",
            "source": "src://1",
            "size": 1024,
            "tags": [],
            "access_count": 0,
        },
    }

    assert "[Belge Deposu — 1 belge] (pgvector pasif)" in store.list_documents(session_id="s1")


@pytest.mark.parametrize(("chroma_available", "pgvector_available"), [(True, False), (False, True)])
async def test_bm25_vector_preference_hint_supports_each_vector_backend_individually(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    chroma_available: bool,
    pgvector_available: bool,
) -> None:
    store = _make_store_stub(tmp_path)
    store._vector_backend = "bm25"
    store._chroma_available = chroma_available
    store._pgvector_available = pgvector_available
    monkeypatch.setattr(rag.DocumentStore, "_backend_info_logged", {})

    store._log_vector_backend_preference_hint()

    assert rag.DocumentStore._backend_info_logged["vector_preference_bm25_hint"] is True


async def test_pgvector_compat_wrappers_delegate_to_backend() -> None:
    assert rag._is_valid_pgvector_identifier("rag_embeddings") is True
    assert rag._is_valid_pgvector_identifier("1bad") is False

    store = rag.DocumentStore.__new__(rag.DocumentStore)
    store._pg_table = "custom_embeddings"
    assert store._pgvector_table_name() == "custom_embeddings"

    legacy_store = rag.DocumentStore.__new__(rag.DocumentStore)
    assert legacy_store._pgvector_table_name() == "rag_embeddings"
