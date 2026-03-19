import importlib.util
import sys
import types
from pathlib import Path


def _load_rag_module():
    spec = importlib.util.spec_from_file_location("rag_graph_test_mod", Path("core/rag.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RAG_MOD = _load_rag_module()


def test_graph_index_rebuilds_and_explains_dependency_path(tmp_path):
    (tmp_path / "a.py").write_text("import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import c\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("VALUE = 1\n", encoding="utf-8")

    index = RAG_MOD.GraphIndex(tmp_path, max_files=10)
    summary = index.rebuild()
    path = index.explain_dependency_path("a.py", "c.py")

    assert summary["nodes"] == 3
    assert summary["edges"] >= 2
    assert path == ["a.py", "b.py", "c.py"]


def test_document_store_supports_graph_mode_search_and_path_queries(tmp_path, monkeypatch):
    (tmp_path / "alpha.py").write_text("import beta\n", encoding="utf-8")
    (tmp_path / "beta.py").write_text("import gamma\n", encoding="utf-8")
    (tmp_path / "gamma.py").write_text("VALUE = 3\n", encoding="utf-8")

    monkeypatch.setattr(RAG_MOD.DocumentStore, "_check_import", lambda self, _: False)

    cfg = types.SimpleNamespace(
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
        RAG_VECTOR_BACKEND="chroma",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        BASE_DIR=tmp_path,
        ENABLE_GRAPH_RAG=True,
        GRAPH_RAG_MAX_FILES=20,
    )
    store = RAG_MOD.DocumentStore(tmp_path / "rag_store", cfg=cfg)

    ok_search, graph_text = store.search_graph("alpha", top_k=3)
    ok_path, path_text = store.explain_dependency_path("alpha.py", "gamma.py")

    assert ok_search is True
    assert "alpha.py" in graph_text
    assert ok_path is True
    assert "1. alpha.py" in path_text
    assert "3. gamma.py" in path_text


def test_graph_index_tracks_endpoints_and_impact_analysis(tmp_path):
    (tmp_path / "service.py").write_text(
        "from fastapi import FastAPI\n"
        "import helper\n"
        "app = FastAPI()\n"
        "@app.get('/api/items')\n"
        "async def list_items():\n"
        "    return helper.VALUE\n",
        encoding="utf-8",
    )
    (tmp_path / "helper.py").write_text("VALUE = 7\n", encoding="utf-8")
    (tmp_path / "client.js").write_text("fetch('/api/items')\n", encoding="utf-8")

    index = RAG_MOD.GraphIndex(tmp_path, max_files=10)
    summary = index.rebuild()
    impact = index.impact_analysis("helper.py", top_k=5)

    assert summary["nodes"] >= 4
    assert "endpoint:GET /api/items" in index.nodes
    assert "client.js" in impact["caller_files"]
    assert "endpoint:GET /api/items" in impact["impacted_endpoints"]
    assert "service.py" in impact["impacted_endpoint_handlers"]
    assert impact["risk_level"] == "high"
    assert "service.py" in impact["review_targets"]
    assert any(path[-1] == "helper.py" for path in impact["dependency_paths"])


def test_document_store_graph_impact_includes_reviewer_targets(tmp_path, monkeypatch):
    (tmp_path / "service.py").write_text(
        "from fastapi import FastAPI\n"
        "import helper\n"
        "app = FastAPI()\n"
        "@app.post('/api/save')\n"
        "async def save_item():\n"
        "    return helper.persist()\n",
        encoding="utf-8",
    )
    (tmp_path / "helper.py").write_text("def persist():\n    return {'ok': True}\n", encoding="utf-8")
    (tmp_path / "client.js").write_text("fetch('/api/save', {method: 'POST'})\n", encoding="utf-8")

    monkeypatch.setattr(RAG_MOD.DocumentStore, "_check_import", lambda self, _: False)
    cfg = types.SimpleNamespace(
        RAG_TOP_K=5,
        RAG_CHUNK_SIZE=64,
        RAG_CHUNK_OVERLAP=8,
        HF_TOKEN="",
        HF_HUB_OFFLINE=False,
        RAG_VECTOR_BACKEND="chroma",
        AI_PROVIDER="openai",
        RAG_LOCAL_ENABLE_HYBRID=False,
        BASE_DIR=tmp_path,
        ENABLE_GRAPH_RAG=True,
        GRAPH_RAG_MAX_FILES=20,
    )
    store = RAG_MOD.DocumentStore(tmp_path / "rag_store", cfg=cfg)

    ok, report = store.analyze_graph_impact("helper.py", top_k=5)

    assert ok is True
    assert "Risk seviyesi: high" in report
    assert "Etkilenen endpoint handler dosyaları: service.py" in report
    assert "Reviewer için önerilen hedefler:" in report