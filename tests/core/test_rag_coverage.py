from pathlib import Path

from core.rag import GraphIndex


def test_normalize_endpoint_path_rejects_dynamic_and_external_urls():
    assert GraphIndex._normalize_endpoint_path("/api/health") == "/api/health"
    assert GraphIndex._normalize_endpoint_path("https://example.com/private") is None
    assert GraphIndex._normalize_endpoint_path("/api/${id}") is None


def test_extract_script_endpoint_calls_detects_fetch_and_websocket():
    graph = GraphIndex(Path("."))
    content = """
fetch('/api/items', { method: 'POST' })
fetch('/api/items')
const ws = new WebSocket('/ws/voice')
"""
    calls = graph._extract_script_endpoint_calls(content)
    assert {item["endpoint_id"] for item in calls} >= {
        "endpoint:POST /api/items",
        "endpoint:GET /api/items",
        "endpoint:WS /ws/voice",
    }


def test_parse_python_source_extracts_decorated_endpoint_and_http_call(tmp_path):
    app_file = tmp_path / "app.py"
    app_file.write_text("# test", encoding="utf-8")
    source = """
from fastapi import APIRouter
import requests
router = APIRouter()

@router.get('/api/ping')
def ping():
    return {'ok': True}


def run():
    requests.post('/api/items')
"""
    graph = GraphIndex(tmp_path)
    deps, endpoint_defs, endpoint_calls = graph._parse_python_source(app_file, source)

    assert deps == []
    assert endpoint_defs[0]["endpoint_id"] == "endpoint:GET /api/ping"
    assert endpoint_calls[0]["endpoint_id"] == "endpoint:POST /api/items"


def test_iter_source_files_skips_build_and_respects_extensions(tmp_path: Path):
    (tmp_path / "api.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "index.js").write_text("fetch('/api/x')", encoding="utf-8")
    (tmp_path / "docs.txt").write_text("text", encoding="utf-8")

    graph = GraphIndex(tmp_path)
    files = graph._iter_source_files(tmp_path)

    assert [p.name for p in files] == ["api.py"]


def test_script_import_candidates_and_endpoint_node_id(tmp_path: Path):
    (tmp_path / "src").mkdir()
    current = tmp_path / "src" / "app.js"
    current.write_text("import './util'", encoding="utf-8")
    util = tmp_path / "src" / "util.js"
    util.write_text("export const x = 1", encoding="utf-8")

    candidates = GraphIndex._script_import_candidates(current, "./util", tmp_path)
    assert util in candidates
    assert GraphIndex._endpoint_node_id("get", "api/items") == "endpoint:GET /api/items"
