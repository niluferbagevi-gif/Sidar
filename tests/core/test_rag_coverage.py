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
