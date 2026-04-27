from pathlib import Path

import pytest

from core.rag import GraphIndex


@pytest.mark.integration
def test_graph_index_links_frontend_calls_to_backend_endpoint_and_dependency_chain(
    tmp_path: Path,
) -> None:
    (tmp_path / "helper.py").write_text("def build_message():\n    return 'ok'\n", encoding="utf-8")

    (tmp_path / "backend.py").write_text(
        "from fastapi import FastAPI\n"
        "from helper import build_message\n\n"
        "app = FastAPI()\n\n"
        "@app.post('/api/hello')\n"
        "def hello():\n"
        "    return {'message': build_message()}\n",
        encoding="utf-8",
    )

    (tmp_path / "frontend.js").write_text(
        "async function run(){\n" "  await fetch('/api/hello', { method: 'POST' });\n" "}\n",
        encoding="utf-8",
    )

    graph = GraphIndex(tmp_path, max_files=20)
    stats = graph.rebuild()

    endpoint_id = "endpoint:POST /api/hello"
    assert stats["nodes"] >= 4
    assert endpoint_id in graph.nodes
    assert "backend.py" in graph.neighbors(endpoint_id)
    assert endpoint_id in graph.neighbors("frontend.js")

    impact = graph.impact_analysis("helper.py")
    assert endpoint_id in impact["impacted_endpoints"]
    assert "backend.py" in impact["review_targets"]
