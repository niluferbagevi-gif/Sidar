from pathlib import Path

from core.rag import GraphIndex


def test_rebuild_links_python_imports_and_endpoint_edges(tmp_path: Path) -> None:
    api_file = tmp_path / "api.py"
    api_file.write_text(
        """
from fastapi import APIRouter
router = APIRouter()

@router.get('/health')
def health():
    return {'ok': True}
""",
        encoding="utf-8",
    )
    worker_file = tmp_path / "worker.py"
    worker_file.write_text(
        """
import api
import requests

def ping():
    return requests.get('/health')
""",
        encoding="utf-8",
    )

    graph = GraphIndex(tmp_path)
    summary = graph.rebuild()

    assert summary["nodes"] >= 3
    assert "worker.py" in graph.nodes
    assert "api.py" in graph.nodes
    assert "endpoint:GET /health" in graph.nodes
    assert "api.py" in graph.neighbors("worker.py")
    assert "endpoint:GET /health" in graph.neighbors("worker.py")
    assert "api.py" in graph.neighbors("endpoint:GET /health")


def test_resolve_and_explain_dependency_path_handles_case_and_suffix(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import b", encoding="utf-8")
    (tmp_path / "b.py").write_text("import c", encoding="utf-8")
    (tmp_path / "c.py").write_text("# leaf", encoding="utf-8")

    graph = GraphIndex(tmp_path)
    graph.rebuild()

    assert graph.resolve_node_id("A.PY") == "a.py"
    assert graph.resolve_node_id("c.py") == "c.py"
    assert graph.resolve_node_id("missing.py") is None

    assert graph.explain_dependency_path("a.py", "c.py") == ["a.py", "b.py", "c.py"]
    assert graph.explain_dependency_path("missing.py", "c.py") == []
