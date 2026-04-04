from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

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
import json
from types import SimpleNamespace

import pytest


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


def test_reviewer_init_registers_tools(monkeypatch: pytest.MonkeyPatch):
    import agent.roles.reviewer_agent as mod

    def _fake_base_init(self, cfg=None, role_name="base"):
        self.cfg = cfg
        self.role_name = role_name
        self.tools = {}

    monkeypatch.setattr(mod.BaseAgent, "__init__", _fake_base_init)
    monkeypatch.setattr(mod, "GitHubManager", lambda *_a, **_k: object())
    monkeypatch.setattr(mod, "SecurityManager", lambda *_a, **_k: object())
    monkeypatch.setattr(mod, "CodeManager", lambda *_a, **_k: object())
    monkeypatch.setattr(mod, "BrowserManager", lambda *_a, **_k: object())
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: object())

    cfg = SimpleNamespace(
        GITHUB_TOKEN="t",
        GITHUB_REPO="r",
        BASE_DIR=".",
        DOCKER_PYTHON_IMAGE="python:3.11",
        DOCKER_EXEC_TIMEOUT=10,
    )
    agent = mod.ReviewerAgent(cfg=cfg)

    assert agent.role_name == "reviewer"
    assert "repo_info" in agent.tools
    assert "browser_signals" in agent.tools


def test_tool_helpers_and_graph_store_paths():
    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent.config = SimpleNamespace(
        REVIEWER_TEST_COMMAND="python -m pytest",
        BASE_DIR=".",
        RAG_DIR=".",
        RAG_TOP_K=4,
        RAG_CHUNK_SIZE=128,
        RAG_CHUNK_OVERLAP=16,
        USE_GPU=False,
        GPU_DEVICE="cpu",
        GPU_MIXED_PRECISION=False,
    )
    agent._graph_docs = None

    class _Github:
        def get_repo_info(self):
            return True, "repo-ok"

        def list_pull_requests(self, state, limit):
            return True, f"prs-{state}-{limit}"

        def get_pull_request_diff(self, number):
            return (number == 3), f"diff-{number}"

        def list_issues(self, state, limit):
            return True, [state, limit]

    class _Code:
        def run_shell_in_sandbox(self, command, base):
            return ("pytest" in command), f"{command}@{base}"

        def lsp_semantic_audit(self, paths):
            return True, {"status": "clean", "summary": "ok", "paths": paths or []}

    class _Docs:
        def graph_impact_details(self, target, _k):
            return (target != "bad.py"), {"risk_level": "high", "review_targets": ["core/a.py"]}

        def analyze_graph_impact(self, target, _k):
            return True, f"analysis:{target}"

    class _Browser:
        def collect_session_signals(self, session_id, include_dom=False, include_screenshot=False):
            return {"status": "ok", "summary": session_id, "include_dom": include_dom, "include_screenshot": include_screenshot}

    agent.github = _Github()
    agent.code = _Code()
    agent.browser = _Browser()
    agent._get_graph_store = lambda: _Docs()

    assert asyncio.run(agent._tool_repo_info("")) == "repo-ok"
    assert asyncio.run(agent._tool_list_prs("closed")) == "prs-closed-20"
    assert "Kullanım" in asyncio.run(agent._tool_pr_diff("x"))
    assert "diff-3" in asyncio.run(agent._tool_pr_diff("3"))
    assert "[HATA]" in asyncio.run(agent._tool_pr_diff("2"))
    assert asyncio.run(agent._tool_list_issues("")) == "['open', 20]"

    denied = asyncio.run(agent._tool_run_tests("echo hello"))
    assert "Kullanım" in denied
    allowed = asyncio.run(agent._tool_run_tests("pytest -q"))
    assert "[TEST:OK]" in allowed

    lsp = json.loads(asyncio.run(agent._tool_lsp_diagnostics("core/a.py docs/readme.md")))
    assert lsp["targets"] == ["core/a.py"]

    empty_graph = json.loads(asyncio.run(agent._tool_graph_impact("")))
    assert empty_graph["status"] == "no-targets"
    graph = json.loads(asyncio.run(agent._tool_graph_impact("core/a.py bad.py")))
    assert graph["status"] == "ok"
    assert len(graph["reports"]) == 2

    inline = asyncio.run(agent._tool_browser_signals('{"browser_signals":{"status":"ok"}}'))
    assert json.loads(inline)["status"] == "ok"
    no_sig = json.loads(asyncio.run(agent._tool_browser_signals("core/a.py")))
    assert no_sig["status"] == "no-signal"
    with_sig = json.loads(asyncio.run(agent._tool_browser_signals('{"browser_session_id":"s1","browser_include_dom":true}')))
    assert with_sig["summary"] == "s1"


def test_combined_impact_and_recommendation_fallbacks():
    semantic = {
        "counts": {1: 1},
        "issues": [{"path": "/workspace/Sidar/core/a.py", "message": "broken import"}],
    }
    graph_summary = {"risk": "düşük", "followup_paths": ["core/a.py"], "high_risk_targets": ["core/x.py"]}
    combined = ReviewerAgent._build_combined_impact_report(semantic, graph_summary, ["core/b.py"], ["core/a.py"])
    assert combined["impact_level"] == "critical"
    assert combined["indirect_breakage_paths"] == ["core/a.py"]

    graph_payload = {
        "reports": [
            {
                "ok": True,
                "target": "core/x.py",
                "details": {"risk_level": "high", "review_targets": ["core/c.py"], "impacted_endpoints": ["/x"]},
            }
        ]
    }

    recs_graph_sem = ReviewerAgent._build_fix_recommendations(semantic, graph_payload, combined)
    assert recs_graph_sem and recs_graph_sem[0]["reason"] == "graph+semantic"

    no_semantic = {"counts": {}, "issues": []}
    combined_no_indirect = {"indirect_breakage_paths": []}
    recs_graph = ReviewerAgent._build_fix_recommendations(no_semantic, graph_payload, combined_no_indirect)
    assert any(item["reason"] == "graph" for item in recs_graph)

    semantic_only = {"counts": {2: 2}, "issues": [{"path": "core/d.py", "message": "warn"}]}
    recs_sem = ReviewerAgent._build_fix_recommendations(semantic_only, {"reports": []}, combined_no_indirect)
    assert recs_sem[0]["reason"] == "semantic"


def test_lsp_and_browser_summaries_extra_paths():
    empty = ReviewerAgent._summarize_lsp_diagnostics("")
    assert empty["status"] == "clean"

    payload = ReviewerAgent._summarize_lsp_diagnostics(
        json.dumps({"status": "issues-found", "risk": "orta", "decision": "APPROVE", "summary": "s", "counts": {"2": 1}})
    )
    assert payload["status"] == "issues-found"
    assert payload["counts"] == {"2": 1}

    info_only = ReviewerAgent._summarize_lsp_diagnostics("line severity=3")
    assert info_only["status"] == "info-only"
    assert ReviewerAgent._normalize_issue_path(r".\core\a.py") == "core/a.py"

    bs = ReviewerAgent._summarize_browser_signals(None)
    assert bs["status"] == "no-signal"
    assert ReviewerAgent._build_browser_fix_recommendations(bs) == []
    recs = ReviewerAgent._build_browser_fix_recommendations(
        {"failed_actions": ["click"], "pending_actions": ["submit"], "high_risk_actions": ["delete"], "current_url": "u"}
    )
    assert recs and recs[0]["reason"] == "browser-signal"


def test_run_task_routing_and_review_code_flow():
    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent.config = SimpleNamespace(REVIEWER_TEST_COMMAND="pytest -q")

    class _Events:
        async def publish(self, *_args, **_kwargs):
            return None

    agent.events = _Events()

    async def _call_tool(name: str, arg: str):
        mapping = {
            "repo_info": "repo",
            "list_prs": f"prs:{arg}",
            "pr_diff": f"diff:{arg}",
            "list_issues": f"issues:{arg}",
            "run_tests": "[TEST:PASS]",
            "lsp_diagnostics": "LSP diagnostics temiz.",
            "graph_impact": json.dumps({"status": "ok", "summary": "g", "reports": []}, ensure_ascii=False),
            "browser_signals": json.dumps({"status": "ok", "risk": "orta", "summary": "b"}, ensure_ascii=False),
        }
        return mapping[name]

    async def _run_dynamic_tests(_ctx: str):
        return "[TEST:PASS]"

    agent.call_tool = _call_tool
    agent._run_dynamic_tests = _run_dynamic_tests
    agent.delegate_to = lambda _a, payload, reason="": payload

    assert asyncio.run(agent.run_task("")) == "[UYARI] Boş reviewer görevi verildi."
    assert asyncio.run(agent.run_task("repo_info")) == "repo"
    assert asyncio.run(agent.run_task("list_prs|closed")) == "prs:closed"
    assert asyncio.run(agent.run_task("pr_diff|9")) == "diff:9"
    assert asyncio.run(agent.run_task("list_issues")) == "issues:open"
    assert asyncio.run(agent.run_task("run_tests|pytest -q")) == "[TEST:PASS]"
    assert asyncio.run(agent.run_task("lsp_diagnostics|core/a.py")) == "LSP diagnostics temiz."
    assert asyncio.run(agent.run_task("graph_impact|core/a.py")) == json.dumps({"status": "ok", "summary": "g", "reports": []}, ensure_ascii=False)
    assert asyncio.run(agent.run_task("incele")) == asyncio.run(agent.run_task("review_code|Doğal dil inceleme isteği"))

    raw = asyncio.run(agent.run_task('review_code|{"review_context":"core/a.py"}'))
    payload = json.loads(raw.split("qa_feedback|", 1)[1])
    assert payload["decision"] == "APPROVE"
    assert payload["risk"] == "orta"

def test_run_dynamic_tests_handles_write_failure_and_cleanup(monkeypatch: pytest.MonkeyPatch, tmp_path):
    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent.config = SimpleNamespace(BASE_DIR=str(tmp_path))

    async def _build(_ctx: str):
        return "def test_dyn():\n    assert True\n"

    class _CodeFail:
        def write_file(self, *_args, **_kwargs):
            return False, "disk full"

    agent._build_dynamic_test_content = _build
    agent.code = _CodeFail()
    failed = asyncio.run(agent._run_dynamic_tests("ctx"))
    assert "[TEST:FAIL-CLOSED]" in failed
    assert "disk full" in failed

    class _CodeOk:
        def write_file(self, path, content, _append):
            Path(path).write_text(content, encoding="utf-8")
            return True, "ok"

    async def _run_tool(_name: str, _arg: str):
        return "[TEST:OK]"

    agent.code = _CodeOk()
    agent.call_tool = _run_tool
    ok = asyncio.run(agent._run_dynamic_tests("ctx"))
    assert ok == "[TEST:OK]"
    assert not list((tmp_path / "temp").glob("reviewer_dynamic_*.py"))


def test_collect_and_summarize_graph_payload_edge_cases():
    assert ReviewerAgent._collect_graph_followup_paths({"reports": "bad"}) == []

    payload = {
        "status": "ok",
        "reports": [
            {"ok": False, "details": {}},
            {"ok": True, "details": "invalid"},
            {
                "ok": True,
                "target": "core/h.py",
                "details": {"risk_level": "low", "impacted_endpoints": [], "review_targets": ["core/h.py"]},
            },
        ],
    }
    summary = ReviewerAgent._summarize_graph_payload(payload)
    assert summary["risk"] == "düşük"
    assert summary["followup_paths"] == ["core/h.py"]


def test_combined_impact_and_fix_recommendation_additional_branches():
    semantic_medium = {
        "counts": {"x": 1, "1": 0},
        "issues": ["bad", {"path": "core/m.py", "message": "warn"}],
    }
    combined_medium = ReviewerAgent._build_combined_impact_report(
        semantic_medium,
        {"risk": "düşük", "followup_paths": []},
        ["core/direct.py"],
        ["core/m.py"],
    )
    assert combined_medium["impact_level"] == "medium"

    combined_high = ReviewerAgent._build_combined_impact_report(
        {"counts": {}, "issues": []},
        {"risk": "orta", "followup_paths": []},
        [],
        [],
    )
    assert combined_high["impact_level"] == "high"

    graph_payload = {
        "reports": [
            "bad",
            {"ok": True, "target": "core/t.py", "details": "x"},
            {"ok": True, "target": "core/t.py", "details": {"risk_level": "low"}},
            {
                "ok": True,
                "target": "core/t.py",
                "details": {"risk_level": "high", "review_targets": ["core/t.py", "core/u.py", "core/u.py"]},
            },
        ]
    }
    recs = ReviewerAgent._build_fix_recommendations({"issues": []}, graph_payload, {"indirect_breakage_paths": []})
    assert len([r for r in recs if r["path"] == "core/u.py"]) == 1


def test_parse_review_payload_empty_and_invalid_json_fallback():
    empty = ReviewerAgent._parse_review_payload("")
    assert empty["review_context"] == ""

    fallback = ReviewerAgent._parse_review_payload('{"a":')
    assert fallback["review_context"] == '{"a":'


def test_get_graph_store_initializes_once(monkeypatch: pytest.MonkeyPatch):
    import agent.roles.reviewer_agent as mod

    calls = []

    class _Docs:
        pass

    def _factory(*args, **kwargs):
        calls.append((args, kwargs))
        return _Docs()

    monkeypatch.setattr(mod, "DocumentStore", _factory)
    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent._graph_docs = None
    agent.config = SimpleNamespace(
        RAG_DIR=".",
        RAG_TOP_K=1,
        RAG_CHUNK_SIZE=32,
        RAG_CHUNK_OVERLAP=4,
        USE_GPU=False,
        GPU_DEVICE="cpu",
        GPU_MIXED_PRECISION=False,
    )

    first = agent._get_graph_store()
    second = agent._get_graph_store()
    assert first is second
    assert len(calls) == 1


def test_run_task_decision_branches_for_risk_and_reject():
    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent.config = SimpleNamespace(REVIEWER_TEST_COMMAND="pytest -q")

    class _Events:
        async def publish(self, *_args, **_kwargs):
            return None

    agent.events = _Events()

    async def _run_dynamic(_ctx: str):
        return "[TEST:PASS]"

    scenarios = [
        (
            "semantic_reject",
            '{"status":"issues-found","risk":"yüksek","decision":"REJECT","summary":"s","counts":{"1":1}}',
            json.dumps({"status": "ok", "summary": "g", "reports": []}, ensure_ascii=False),
            json.dumps({"status": "ok", "risk": "düşük", "summary": "b"}, ensure_ascii=False),
            "REJECT",
            "yüksek",
        ),
        (
            "semantic_orta",
            '{"status":"issues-found","risk":"orta","decision":"APPROVE","summary":"s","counts":{"2":1}}',
            json.dumps({"status": "ok", "summary": "g", "reports": []}, ensure_ascii=False),
            json.dumps({"status": "ok", "risk": "düşük", "summary": "b"}, ensure_ascii=False),
            "APPROVE",
            "orta",
        ),
        (
            "graph_orta",
            '{"status":"clean","risk":"düşük","decision":"APPROVE","summary":"s","counts":{}}',
            json.dumps({"status": "ok", "summary": "g", "reports": [{"ok": True, "target": "core/x.py", "details": {"risk_level": "high", "review_targets": ["core/x.py"]}}]}, ensure_ascii=False),
            json.dumps({"status": "ok", "risk": "düşük", "summary": "b"}, ensure_ascii=False),
            "APPROVE",
            "orta",
        ),
        (
            "browser_failed",
            '{"status":"clean","risk":"düşük","decision":"APPROVE","summary":"s","counts":{}}',
            json.dumps({"status": "ok", "summary": "g", "reports": []}, ensure_ascii=False),
            json.dumps({"status": "failed", "risk": "orta", "summary": "b", "failed_actions": ["x"]}, ensure_ascii=False),
            "REJECT",
            "yüksek",
        ),
    ]

    for name, lsp_out, graph_out, browser_out, expected_decision, expected_risk in scenarios:
        async def _call_tool(tool_name: str, _arg: str, _l=lsp_out, _g=graph_out, _b=browser_out):
            mapping = {
                "run_tests": "[TEST:PASS]",
                "lsp_diagnostics": _l,
                "graph_impact": _g,
                "browser_signals": _b,
            }
            return mapping.get(tool_name, "ok")

        agent.call_tool = _call_tool
        agent._run_dynamic_tests = _run_dynamic
        agent.delegate_to = lambda _a, payload, reason="": payload

        raw = asyncio.run(agent.run_task(f"review_code|{{\"review_context\":\"core/{name}.py\"}}"))
        payload = json.loads(raw.split("qa_feedback|", 1)[1])
        assert payload["decision"] == expected_decision
        assert payload["risk"] == expected_risk

def test_build_dynamic_test_content_success_and_cleanup_unlink_error(monkeypatch, tmp_path):
    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent.TEST_GENERATION_PROMPT = "prompt"
    agent.config = SimpleNamespace(BASE_DIR=str(tmp_path), REVIEWER_TEST_COMMAND="pytest -q")

    async def _ok_llm(*_args, **_kwargs):
        return "def test_generated():\n    assert True\n"

    async def _call_tool(_name: str, _arg: str):
        return "[TEST:OK]"

    agent.call_llm = _ok_llm
    generated = asyncio.run(agent._build_dynamic_test_content("ctx"))
    assert generated.endswith("\n")

    class _CodeOk:
        def write_file(self, path, content, _append):
            Path(path).write_text(content, encoding="utf-8")
            return True, "ok"

    agent.code = _CodeOk()
    agent.call_tool = _call_tool

    original_unlink = Path.unlink

    def _raise_unlink(self, missing_ok=False):
        raise OSError("cannot remove")

    monkeypatch.setattr(Path, "unlink", _raise_unlink)
    out = asyncio.run(agent._run_dynamic_tests("ctx"))
    assert out == "[TEST:OK]"
    monkeypatch.setattr(Path, "unlink", original_unlink)


def test_collect_graph_followup_and_lsp_no_match_paths():
    payload = {
        "reports": [
            {
                "ok": True,
                "details": {
                    "review_targets": "not-a-list",
                    "impacted_endpoint_handlers": ["core/a.py", "core/a.py", "README.md"],
                    "caller_files": ["core/b.ts", "core/b.ts"],
                    "direct_dependents": [""],
                },
            }
        ]
    }
    paths = ReviewerAgent._collect_graph_followup_paths(payload)
    assert paths == ["core/a.py", "core/b.ts"]

    parsed = ReviewerAgent._summarize_lsp_diagnostics('{"status":"issues-found","counts":{},"decision":"APPROVE"}')
    assert parsed["status"] == "clean"

    unknown = ReviewerAgent._summarize_lsp_diagnostics("just text without severity marker")
    assert unknown["status"] == "clean"


def test_fix_recommendations_skips_invalid_issue_path_and_non_list_graph_values():
    semantic = {"issues": [{"path": "", "message": "m"}, {"path": "core/a.py", "message": "ok"}]}
    graph_payload = {
        "reports": [
            {
                "ok": True,
                "target": "core/t.py",
                "details": {
                    "risk_level": "high",
                    "review_targets": "core/u.py",
                    "caller_files": ["core/v.py"],
                    "direct_dependents": ["core/w.py"],
                },
            }
        ]
    }
    combined = {"indirect_breakage_paths": []}

    recs = ReviewerAgent._build_fix_recommendations(semantic, graph_payload, combined)
    assert any(item["path"] == "core/v.py" for item in recs)
    assert any(item["path"] == "core/w.py" for item in recs)
    assert all(item["path"] != "core/u.py" for item in recs)


def test_parse_review_payload_json_non_object_fallback():
    payload = ReviewerAgent._parse_review_payload('["x"] browser_session_id=s99')
    assert payload["browser_session_id"] == "s99"
    assert payload["review_context"].startswith('["x"]')


def test_run_task_browser_risk_and_combined_impact_raise_risk():
    agent = ReviewerAgent.__new__(ReviewerAgent)
    agent.config = SimpleNamespace(REVIEWER_TEST_COMMAND="pytest -q")

    class _Events:
        async def publish(self, *_args, **_kwargs):
            return None

    agent.events = _Events()

    async def _run_dynamic(_ctx: str):
        return "[TEST:PASS]"

    async def _call_tool(tool_name: str, _arg: str):
        mapping = {
            "run_tests": "[TEST:PASS]",
            "lsp_diagnostics": '{"status":"clean","risk":"düşük","decision":"APPROVE","summary":"s","counts":{}}',
            "graph_impact": json.dumps({"status": "ok", "summary": "g", "reports": []}, ensure_ascii=False),
            "browser_signals": json.dumps({"status": "ok", "risk": "orta", "summary": "b"}, ensure_ascii=False),
        }
        return mapping.get(tool_name, "ok")

    agent.call_tool = _call_tool
    agent._run_dynamic_tests = _run_dynamic
    agent.delegate_to = lambda _a, payload, reason="": payload

    raw = asyncio.run(agent.run_task('review_code|{"review_context":"core/a.py"}'))
    result = json.loads(raw.split("qa_feedback|", 1)[1])
    assert result["risk"] == "orta"

    async def _call_tool_low_risk(tool_name: str, _arg: str):
        mapping = {
            "run_tests": "[TEST:PASS]",
            "lsp_diagnostics": '{"status":"clean","risk":"düşük","decision":"APPROVE","summary":"s","counts":{}}',
            "graph_impact": json.dumps(
                {
                    "status": "ok",
                    "summary": "g",
                    "reports": [
                        {"ok": True, "target": "core/x.py", "details": {"risk_level": "high", "review_targets": ["core/x.py"]}}
                    ],
                },
                ensure_ascii=False,
            ),
            "browser_signals": json.dumps({"status": "ok", "risk": "düşük", "summary": "b"}, ensure_ascii=False),
        }
        return mapping.get(tool_name, "ok")

    agent.call_tool = _call_tool_low_risk
    raw2 = asyncio.run(agent.run_task('review_code|{"review_context":"core/a.py"}'))
    result2 = json.loads(raw2.split("qa_feedback|", 1)[1])
    assert result2["risk"] == "orta"
