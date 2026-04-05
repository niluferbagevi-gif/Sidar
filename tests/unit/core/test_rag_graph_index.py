"""Unit tests for GraphIndex parsing helpers in core.rag."""

from __future__ import annotations

from pathlib import Path

from core.rag import GraphIndex


def test_iter_source_files_filters_extensions_and_ignored_dirs(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "b.js").write_text("console.log('ok')", encoding="utf-8")
    (tmp_path / "c.txt").write_text("ignore", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.ts").write_text("x", encoding="utf-8")

    idx = GraphIndex(tmp_path)
    files = idx._iter_source_files(tmp_path)
    names = {p.name for p in files}

    assert "a.py" in names
    assert "b.js" in names
    assert "c.txt" not in names
    assert "ignored.ts" not in names


def test_normalize_endpoint_path_rejects_external_urls() -> None:
    assert GraphIndex._normalize_endpoint_path("https://example.org/api") is None
    assert GraphIndex._normalize_endpoint_path("http://localhost:7860/api") == "/api"
    assert GraphIndex._normalize_endpoint_path("ws://127.0.0.1/ws/chat") == "/ws/chat"


def test_extract_script_endpoint_calls_detects_fetch_and_websocket() -> None:
    idx = GraphIndex(Path("."))
    content = """
    fetch('/api/health');
    fetch('/api/items', { method: 'POST' });
    new WebSocket('ws://localhost:7860/ws/chat');
    """

    calls = idx._extract_script_endpoint_calls(content)
    endpoint_ids = {item["endpoint_id"] for item in calls}

    assert "endpoint:GET /api/health" in endpoint_ids
    assert "endpoint:POST /api/items" in endpoint_ids
    assert "endpoint:WS /ws/chat" in endpoint_ids
