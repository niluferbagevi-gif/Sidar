from __future__ import annotations

import importlib.util
import sys
import types

_httpx_spec = None
if "httpx" not in sys.modules:
    _httpx_spec = importlib.util.find_spec("httpx")
if _httpx_spec is None and "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")

    class AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_httpx.AsyncClient = AsyncClient
    sys.modules["httpx"] = fake_httpx

from agent.roles.reviewer_agent import ReviewerAgent


def test_extract_python_code_block_prefers_fenced_content():
    raw = """Burada örnek:
```python

def test_x():
    assert True
```
"""
    code = ReviewerAgent._extract_python_code_block(raw)
    assert "def test_x" in code
    assert "```" not in code


def test_extract_changed_paths_filters_invalid_paths():
    text = "modified core/rag.py and ../secret.py and /abs/path.py and web_ui_react/src/App.jsx"
    paths = ReviewerAgent._extract_changed_paths(text)
    assert "core/rag.py" in paths
    assert "web_ui_react/src/App.jsx" in paths
    assert "../secret.py" not in paths
    assert "/abs/path.py" not in paths


def test_merge_candidate_paths_deduplicates_and_normalizes():
    merged = ReviewerAgent._merge_candidate_paths(["./core/rag.py", "tests/test_a.py"], ["core/rag.py"])
    assert merged == ["core/rag.py", "tests/test_a.py"]


def test_summarize_lsp_diagnostics_interprets_severity_counts():
    report = ReviewerAgent._summarize_lsp_diagnostics(
        "file=core/a.py severity=1\nfile=core/b.py severity=2\n"
    )
    assert report["status"] == "issues-found"
    assert report["decision"] == "REJECT"
    assert report["risk"] == "yüksek"
    assert report["counts"] == {1: 1, 2: 1}


def test_summarize_graph_payload_collects_followup_and_risk():
    payload = {
        "status": "ok",
        "reports": [
            {
                "ok": True,
                "target": "core/db.py",
                "details": {
                    "risk_level": "high",
                    "impacted_endpoints": ["/chat"],
                    "review_targets": ["core/db.py", "tests/core/test_db_coverage.py"],
                },
            }
        ],
    }
    summary = ReviewerAgent._summarize_graph_payload(payload)
    assert summary["status"] == "ok"
    assert summary["risk"] == "orta"
    assert "core/db.py" in summary["high_risk_targets"]
    assert "core/db.py" in summary["followup_paths"]
