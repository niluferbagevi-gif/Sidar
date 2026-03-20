import sys
import types
from pathlib import Path

from tests.test_rag_edge_case_coverage import _load_rag_module
from tests.test_rag_runtime_extended import _new_store


def test_graph_index_parsing_helpers_cover_imports_literals_endpoints_and_rebuild_failures(tmp_path, monkeypatch):
    mod = _load_rag_module("rag_graph_parse_gaps")
    root = tmp_path / "repo"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "service.py").write_text("", encoding="utf-8")
    client_file = pkg / "client.py"
    client_file.write_text("", encoding="utf-8")
    (root / "a.py").write_text("print('a')", encoding="utf-8")
    (root / "b.py").write_text("print('b')", encoding="utf-8")
    (root / "c.py").write_text("print('c')", encoding="utf-8")
    (root / "script.js").write_text("fetch('/api/items', {method: 'POST'})", encoding="utf-8")
    (root / "broken.py").write_text("def bad(:\n", encoding="utf-8")
    unreadable = root / "unreadable.py"
    unreadable.write_text("print('x')", encoding="utf-8")

    graph = mod.GraphIndex(root, max_files=2)
    files = graph._iter_source_files(root)
    assert len(files) == 2

    rel_candidates = graph._python_import_candidates(client_file, "service", 2, root)
    assert rel_candidates == []

    root_service = root / "service.py"
    root_service.write_text("", encoding="utf-8")
    rel_candidates = graph._python_import_candidates(client_file, "service", 2, root)
    assert rel_candidates == [root_service.resolve()]

    legacy_str_cls = type("LegacyStr", (), {})
    legacy_str = legacy_str_cls()
    legacy_str.s = "  legacy  "
    original_ast_str = mod.ast.Str
    mod.ast.Str = legacy_str_cls
    try:
        assert graph._extract_str_literal(legacy_str) == "legacy"
    finally:
        mod.ast.Str = original_ast_str
    assert graph._normalize_endpoint_path("http://localhost:7860/api/health") == "/api/health"

    deps, endpoint_defs, endpoint_calls = graph._parse_python_source(
        client_file,
        "from .. import service\n@app.get('/status')\ndef status():\n    return client.post('/api/items')\n",
    )
    assert deps == []
    assert endpoint_defs[0]["endpoint_id"] == "endpoint:GET /status"
    assert endpoint_calls == [{"endpoint_id": "endpoint:POST /api/items", "method": "POST", "path": "/api/items"}]

    assert graph._parse_python_source(client_file, "def bad(:\n") == ([], [], [])

    js_calls = graph._extract_script_endpoint_calls(
        "\n".join(
            [
                "fetch('https://remote.example/api')",
                "fetch('/api/items', {method: 'POST'})",
                "fetch('/api/items', {method: 'POST'})",
                "new WebSocket('ws://localhost:7860/ws/live')",
                "new WebSocket('ws://localhost:7860/ws/live')",
                "new WebSocket(`${base}/ws/live`)",
            ]
        )
    )
    assert js_calls == [
        {"endpoint_id": "endpoint:POST /api/items", "method": "POST", "path": "/api/items"},
        {"endpoint_id": "endpoint:WS /ws/live", "method": "WS", "path": "/ws/live"},
    ]

    full_graph = mod.GraphIndex(root)
    original_read_text = Path.read_text

    def _patched_read_text(self, *args, **kwargs):
        if self == unreadable:
            raise OSError("cannot read")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _patched_read_text)
    summary = full_graph.rebuild(root)
    assert summary["nodes"] >= 4
    assert "script.js" in full_graph.nodes


def test_graph_index_resolution_paths_bfs_and_risk_levels(tmp_path):
    mod = _load_rag_module("rag_graph_resolution_gaps")
    graph = mod.GraphIndex(tmp_path)

    graph.add_node("core/a.py", node_type="file")
    graph.add_node("core/b.py", node_type="file")
    graph.add_node("core/c.py", node_type="file")
    graph.add_node("core/d.py", node_type="file")
    graph.add_node("endpoint:GET /health", node_type="endpoint")
    graph.add_edge("core/a.py", "core/b.py")
    graph.add_edge("core/b.py", "core/c.py")
    graph.add_edge("core/c.py", "core/d.py")
    graph.add_edge("endpoint:GET /health", "core/c.py", kind="handled_by")

    assert graph.resolve_node_id("") is None
    assert graph.resolve_node_id("CORE/A.PY") == "core/a.py"
    assert graph.explain_dependency_path("missing", "core/a.py") == []
    assert graph.explain_dependency_path("core/a.py", "missing") == []
    assert graph.explain_dependency_path("core/a.py", "core/d.py") == ["core/a.py", "core/b.py", "core/c.py", "core/d.py"]
    assert graph.explain_dependency_path("core/d.py", "core/a.py") == []

    assert graph._collect_bfs("missing", graph.edges, 2) == {}
    assert graph._collect_bfs("core/a.py", graph.edges, 0) == {}
    assert graph._collect_bfs("core/a.py", graph.edges, 2) == {"core/b.py": 1, "core/c.py": 2}

    low_graph = mod.GraphIndex(tmp_path)
    low_graph.add_node("solo.py", node_type="file")
    low_ok = low_graph.impact_analysis("solo.py")
    assert low_ok["risk_level"] == "low"

    medium_graph = mod.GraphIndex(tmp_path)
    for node_id in ["target.py", "caller1.py", "caller2.py", "caller3.py"]:
        medium_graph.add_node(node_id, node_type="file")
    medium_graph.add_edge("caller1.py", "target.py")
    medium_graph.add_edge("caller2.py", "target.py")
    medium_graph.add_edge("caller3.py", "target.py")
    medium = medium_graph.impact_analysis("target.py")
    assert medium["risk_level"] == "medium"

    high = graph.impact_analysis("core/c.py")
    assert high["risk_level"] == "high"


def test_graph_rag_guards_dispatch_and_formatting_paths(tmp_path, monkeypatch):
    mod = _load_rag_module("rag_graph_store_gaps")
    store = _new_store(mod, tmp_path)

    store._graph_rag_enabled = False
    assert store.rebuild_graph_index() == (False, "GraphRAG devre dışı.")
    assert store.search_graph("x") == (False, "GraphRAG devre dışı.")
    assert store.explain_dependency_path("a", "b") == (False, "GraphRAG devre dışı.")
    assert store.graph_impact_details("a") == (False, "GraphRAG devre dışı.")

    store._graph_rag_enabled = True
    store._graph_ready = True
    assert store.search_graph("   ") == (False, "GraphRAG için boş sorgu gönderilemez.")

    original_explain_dependency_path = store.explain_dependency_path

    monkeypatch.setattr(store, "analyze_graph_impact", lambda target, top_k=5: (True, f"impact:{target}:{top_k}"))
    assert store.search_graph("impact: core/rag.py", top_k=4) == (True, "impact:core/rag.py:4")

    monkeypatch.setattr(store, "explain_dependency_path", lambda source, target: (True, f"path:{source}->{target}"))
    assert store.search_graph("a.py -> b.py") == (True, "path:a.py->b.py")

    monkeypatch.setattr(store, "explain_dependency_path", original_explain_dependency_path)
    store._graph_index = types.SimpleNamespace(search_related=lambda *_a, **_k: [])
    assert store.search_graph("needle") == (False, "GraphRAG içinde 'needle' için ilgili modül bulunamadı.")

    store._graph_index = types.SimpleNamespace(explain_dependency_path=lambda *_a, **_k: [])
    assert store.explain_dependency_path("a", "b") == (False, "Bağımlılık yolu bulunamadı: a -> b")

    monkeypatch.setattr(store, "graph_impact_details", lambda *_a, **_k: (False, "no impact"))
    assert mod.DocumentStore.analyze_graph_impact(store, "a") == (False, "no impact")

    monkeypatch.setattr(
        store,
        "graph_impact_details",
        lambda *_a, **_k: (
            True,
            {
                "target": "core/rag.py",
                "node_type": "file",
                "risk_level": "medium",
                "direct_dependents": ["web_server.py"],
                "dependencies": ["core/db.py"],
                "impacted_endpoints": ["endpoint:GET /status"],
                "impacted_endpoint_handlers": ["web_server.py"],
                "caller_files": ["tests/test_rag_graph_and_io_gap_closers.py"],
                "review_targets": ["web_server.py", "core/db.py"],
                "dependency_paths": [["endpoint:GET /status", "web_server.py", "core/rag.py"]],
            },
        ),
    )
    ok, report = mod.DocumentStore.analyze_graph_impact(store, "core/rag.py")
    assert ok is True
    assert "Aşağı akış bağımlılıklar: core/db.py" in report
    assert "Etkilenen endpoint handler dosyaları: web_server.py" in report
    assert "Örnek etki zincirleri:" in report

    store._graph_index = types.SimpleNamespace(impact_analysis=lambda *_a, **_k: {})
    assert mod.DocumentStore.graph_impact_details(store, "core/rag.py") == (False, "GraphRAG içinde 'core/rag.py' için etki analizi üretilemedi.")
    assert mod.DocumentStore.graph_impact_details(store, "   ") == (False, "Etki analizi için hedef belirtilmedi.")

    store.search_graph = lambda query, top_k=5: (True, f"graph:{query}:{top_k}")
    store._index = {}
    assert store._search_sync("deps", top_k=2, mode="graph", session_id="s1") == (True, "graph:deps:2")


def test_embedding_blank_vectors_file_read_errors_and_delete_valueerror_keyerror(tmp_path, monkeypatch):
    mod = _load_rag_module("rag_io_gap_closers")
    store = _new_store(mod, tmp_path)

    class _Vectors:
        def tolist(self):
            return [[], []]

    st_mod = types.ModuleType("sentence_transformers")
    st_mod.SentenceTransformer = lambda *_a, **_k: types.SimpleNamespace(encode=lambda texts, normalize_embeddings=True: _Vectors())
    monkeypatch.setitem(sys.modules, "sentence_transformers", st_mod)
    assert mod.embed_texts_for_semantic_cache(["", "   "]) == [[], []]

    target = store.store_dir / "broken.txt"
    target.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(mod.Config, "BASE_DIR", tmp_path, raising=False)
    original_read_text = Path.read_text

    def _broken_read_text(self, *args, **kwargs):
        if self == target:
            raise ValueError("invalid pdf payload")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _broken_read_text)
    ok, message = store.add_document_from_file(str(target))
    assert ok is False
    assert "Dosya eklenemedi" in message

    doc_id = store._add_document_sync("Title", "body", source="src", session_id="s1")
    store._chroma_available = True
    store.collection = types.SimpleNamespace(delete=lambda **_k: (_ for _ in ()).throw(KeyError("gone")))
    store._save_index = lambda: None
    store._update_bm25_cache_on_delete = lambda _doc_id: None
    removed = store.delete_document(doc_id, session_id="s1")
    assert "Belge silindi" in removed
    assert doc_id not in store._index

    doc_id_2 = store._add_document_sync("Title-2", "body", source="src", session_id="s1")
    store.collection = types.SimpleNamespace(delete=lambda **_k: (_ for _ in ()).throw(ValueError("already deleted")))
    removed_again = store.delete_document(doc_id_2, session_id="s1")
    assert "Belge silindi" in removed_again
    assert doc_id_2 not in store._index


def test_graph_index_websocket_and_bfs_seen_guards_cover_remaining_branches(tmp_path):
    mod = _load_rag_module("rag_graph_seen_guards")
    graph = mod.GraphIndex(tmp_path)

    ws_calls = graph._extract_script_endpoint_calls(
        "\n".join(
            [
                "new WebSocket('wss://remote.example/ws/ignored')",
                "new WebSocket('ws://localhost/ws/live')",
            ]
        )
    )
    assert ws_calls == [
        {"endpoint_id": "endpoint:WS /ws/live", "method": "WS", "path": "/ws/live"},
    ]

    graph.add_node("a.py", node_type="file")
    graph.add_node("b.py", node_type="file")
    graph.add_node("c.py", node_type="file")
    graph.add_edge("a.py", "b.py")
    graph.add_edge("b.py", "a.py")
    graph.add_edge("b.py", "c.py")
    graph.add_edge("c.py", "b.py")

    assert graph.explain_dependency_path("a.py", "c.py") == ["a.py", "b.py", "c.py"]
    assert graph._collect_bfs("a.py", graph.edges, 3) == {"b.py": 1, "c.py": 2}
