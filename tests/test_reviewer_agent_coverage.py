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


if "redis.asyncio" not in sys.modules:
    fake_redis_asyncio = types.ModuleType("redis.asyncio")

    class Redis:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

    fake_redis_asyncio.Redis = Redis
    fake_redis = types.ModuleType("redis")
    fake_redis.asyncio = fake_redis_asyncio
    fake_redis_exceptions = types.ModuleType("redis.exceptions")

    class ResponseError(Exception):
        pass

    fake_redis_exceptions.ResponseError = ResponseError
    fake_redis.exceptions = fake_redis_exceptions
    sys.modules["redis.exceptions"] = fake_redis_exceptions
    sys.modules["redis"] = fake_redis
    sys.modules["redis.asyncio"] = fake_redis_asyncio


if "bs4" not in sys.modules:
    fake_bs4 = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

from agent.roles.reviewer_agent import ReviewerAgent
import asyncio


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


def test_parse_review_payload_supports_json_and_inline_session_id():
    payload = ReviewerAgent._parse_review_payload(
        '{"review_context":"diff","browser_session_id":"sess-1","browser_signals":{"risk":"high"},"browser_include_dom":true}'
    )
    assert payload["review_context"] == "diff"
    assert payload["browser_session_id"] == "sess-1"
    assert payload["browser_signals"] == {"risk": "high"}
    assert payload["browser_include_dom"] is True

    inline = ReviewerAgent._parse_review_payload("core/rag.py güncelle browser_session_id=sess-inline")
    assert inline["browser_session_id"] == "sess-inline"
    assert "browser_session_id" not in inline["review_context"]


def test_build_remediation_loop_toggles_hitl_by_risk_level():
    semantic_report = {"counts": {1: 1}, "summary": "kritik hata"}
    graph_summary = {"risk": "orta", "summary": "graph risk"}
    combined_impact = {
        "impact_level": "critical",
        "direct_scope_paths": ["core/db.py"],
        "graph_followup_paths": ["tests/core/test_db_coverage.py"],
        "issue_paths": ["core/db.py"],
        "indirect_breakage_paths": ["api/routes.py"],
    }
    recommendations = [{"path": "core/db.py"}]

    planned = ReviewerAgent._build_remediation_loop(
        semantic_report,
        graph_summary,
        combined_impact,
        recommendations,
        ["pytest -q tests/core/test_db_coverage.py"],
    )

    assert planned["status"] == "planned"
    assert planned["needs_human_approval"] is True
    assert "semantic_issues" in planned["blocked_by"]
    assert "high_graph_risk" in planned["blocked_by"]
    assert planned["max_auto_attempts"] == 1


def test_build_dynamic_test_content_fail_closed_paths():
    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent.TEST_GENERATION_PROMPT = "prompt"

    empty = asyncio.run(agent._build_dynamic_test_content(""))
    assert "fail_closed" in empty

    async def _bad_llm(*_args, **_kwargs):
        return "print('no tests')"

    agent.call_llm = _bad_llm
    invalid = asyncio.run(agent._build_dynamic_test_content("diff content"))
    assert "geçerli pytest test fonksiyonu" in invalid

    async def _raising_llm(*_args, **_kwargs):
        raise RuntimeError("service down")

    agent.call_llm = _raising_llm
    errored = asyncio.run(agent._build_dynamic_test_content("diff content"))
    assert "başarısız oldu" in errored


def test_summarize_lsp_diagnostics_special_text_branches():
    clean = ReviewerAgent._summarize_lsp_diagnostics("LSP temiz")
    assert clean["status"] == "clean"

    no_signal = ReviewerAgent._summarize_lsp_diagnostics("LSP bildirimi dönmedi")
    assert no_signal["status"] == "no-signal"

    tool_error = ReviewerAgent._summarize_lsp_diagnostics("Araç hatası: timeout")
    assert tool_error["status"] == "tool-error"


def test_build_regression_commands_without_explicit_test_paths():
    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent.config = types.SimpleNamespace(REVIEWER_TEST_COMMAND="pytest -q tests/core/test_db_coverage.py")

    commands = agent._build_regression_commands("core/db.py ve docs/notes.md değişti")

    assert commands == ["pytest -q tests/core/test_db_coverage.py"]
