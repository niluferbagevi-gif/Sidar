from __future__ import annotations

import json
import importlib.util
import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

sys.modules.setdefault("httpx", SimpleNamespace())
if "redis" not in sys.modules:
    redis_pkg = types.ModuleType("redis")
    redis_asyncio = types.ModuleType("redis.asyncio")
    redis_asyncio.Redis = object
    redis_ex = types.ModuleType("redis.exceptions")
    redis_ex.ResponseError = RuntimeError
    redis_pkg.asyncio = redis_asyncio
    redis_pkg.exceptions = redis_ex
    sys.modules["redis"] = redis_pkg
    sys.modules["redis.asyncio"] = redis_asyncio
    sys.modules["redis.exceptions"] = redis_ex

import agent.base_agent as base_agent

_SPEC = importlib.util.spec_from_file_location(
    "reviewer_agent_under_test",
    "/workspace/Sidar/agent/roles/reviewer_agent.py",
)
assert _SPEC and _SPEC.loader
reviewer_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(reviewer_mod)
ReviewerAgent = reviewer_mod.ReviewerAgent


class _DummyLLMClient:
    def __init__(self, *_args, **_kwargs):
        pass

    async def chat(self, **_kwargs):
        return "def test_generated():\n    assert True\n"


class _DummyBus:
    def __init__(self):
        self.events: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str):
        self.events.append((channel, message))


class _DummyGitHub:
    def get_repo_info(self):
        return True, "repo-info"

    def list_pull_requests(self, state, limit):
        return True, f"prs:{state}:{limit}"

    def get_pull_request_diff(self, number):
        return True, f"diff:{number}"

    def list_issues(self, state, limit):
        return True, {"state": state, "limit": limit}


class _DummyCode:
    def __init__(self):
        self.commands: list[tuple[str, str]] = []

    def write_file(self, path: str, content: str, _append: bool):
        from pathlib import Path

        Path(path).write_text(content, encoding="utf-8")
        return True, "written"

    def run_shell_in_sandbox(self, command: str, base_dir: str):
        self.commands.append((command, base_dir))
        return True, "ok"

    def lsp_semantic_audit(self, paths):
        return True, {"status": "clean", "summary": "ok", "issues": [], "counts": {}, "targets": paths or []}


class _DummyBrowser:
    def __init__(self):
        self.calls: list[tuple[str, bool, bool]] = []

    def collect_session_signals(self, session_id: str, include_dom: bool = False, include_screenshot: bool = False):
        self.calls.append((session_id, include_dom, include_screenshot))
        return {"status": "ok", "risk": "düşük", "summary": "browser-ok", "current_url": "http://example"}


class _DummyDocStore:
    def __init__(self, *_args, **_kwargs):
        pass

    def graph_impact_details(self, target, _depth):
        return True, {
            "risk_level": "high",
            "review_targets": ["service/core.py"],
            "impacted_endpoint_handlers": ["api/handlers.py"],
            "caller_files": [],
            "direct_dependents": [],
            "impacted_endpoints": ["GET /health"],
        }

    def analyze_graph_impact(self, target, _depth):
        return True, f"graph-report:{target}"


@pytest.fixture()
def reviewer(monkeypatch, tmp_path):
    monkeypatch.setattr(base_agent, "LLMClient", _DummyLLMClient)
    monkeypatch.setattr(reviewer_mod, "GitHubManager", lambda *_a, **_k: _DummyGitHub())
    monkeypatch.setattr(reviewer_mod, "SecurityManager", lambda *_a, **_k: object())
    monkeypatch.setattr(reviewer_mod, "CodeManager", lambda *_a, **_k: _DummyCode())
    monkeypatch.setattr(reviewer_mod, "BrowserManager", lambda *_a, **_k: _DummyBrowser())
    monkeypatch.setattr(reviewer_mod, "DocumentStore", _DummyDocStore)
    bus = _DummyBus()
    monkeypatch.setattr(reviewer_mod, "get_agent_event_bus", lambda: bus)

    cfg = SimpleNamespace(
        AI_PROVIDER="mock",
        GITHUB_TOKEN="token",
        GITHUB_REPO="repo",
        BASE_DIR=tmp_path,
        DOCKER_PYTHON_IMAGE="python:3.11",
        DOCKER_EXEC_TIMEOUT=10,
        REVIEWER_TEST_COMMAND="python -m pytest",
        RAG_DIR=tmp_path / "rag",
        RAG_TOP_K=4,
        RAG_CHUNK_SIZE=256,
        RAG_CHUNK_OVERLAP=32,
        USE_GPU=False,
        GPU_DEVICE="cpu",
        GPU_MIXED_PRECISION=False,
    )
    cfg.RAG_DIR.mkdir(parents=True, exist_ok=True)
    return ReviewerAgent(cfg)


def test_extract_and_fail_closed_helpers():
    raw = "```python\ndef test_x():\n    assert True\n```"
    assert ReviewerAgent._extract_python_code_block(raw).startswith("def test_x")
    fail = ReviewerAgent._fail_closed_test_content("neden")
    assert "AssertionError" in fail and "neden" in fail


def test_build_dynamic_test_content_branches(reviewer, monkeypatch):
    empty = asyncio.run(reviewer._build_dynamic_test_content(""))
    assert "fail_closed" in empty

    async def _raise(*_a, **_k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(reviewer, "call_llm", _raise)
    failed = asyncio.run(reviewer._build_dynamic_test_content("ctx"))
    assert "başarısız" in failed

    async def _invalid(*_a, **_k):
        return "print('no test')"

    monkeypatch.setattr(reviewer, "call_llm", _invalid)
    no_test = asyncio.run(reviewer._build_dynamic_test_content("ctx"))
    assert "geçerli pytest" in no_test

    async def _valid(*_a, **_k):
        return "```python\ndef test_ok():\n    assert 1\n```"

    monkeypatch.setattr(reviewer, "call_llm", _valid)
    ok = asyncio.run(reviewer._build_dynamic_test_content("ctx"))
    assert ok.endswith("\n") and "def test_ok" in ok


def test_run_dynamic_tests_write_fail_and_success(reviewer, monkeypatch):
    async def _fake_content(_ctx):
        return "def test_a():\n    assert True\n"

    monkeypatch.setattr(reviewer, "_build_dynamic_test_content", _fake_content)

    def _write_fail(*_a, **_k):
        return False, "disk-full"

    reviewer.code.write_file = _write_fail
    fail = asyncio.run(reviewer._run_dynamic_tests("ctx"))
    assert "FAIL-CLOSED" in fail and "disk-full" in fail

    reviewer.code = _DummyCode()

    async def _call_tool(name, arg):
        assert name == "run_tests"
        assert arg.startswith("pytest -q temp/reviewer_dynamic_")
        return "[TEST:OK]"

    monkeypatch.setattr(reviewer, "call_tool", _call_tool)
    ok = asyncio.run(reviewer._run_dynamic_tests("ctx"))
    assert "[TEST:OK]" in ok


def test_path_and_command_builders(reviewer):
    paths = ReviewerAgent._extract_changed_paths("a.py ./b.ts ../bad.py /abs.js docs/readme.md")
    assert "a.py" in paths and "b.ts" in paths and "docs/readme.md" in paths
    assert "bad.py" in paths

    cmds = reviewer._build_regression_commands("tests/unit/a_test.py app/main.py")
    assert cmds[0].startswith("pytest -q tests/unit/a_test.py")
    assert "python -m pytest" in cmds

    lsp = ReviewerAgent._build_lsp_candidate_paths("a.py b.ts c.jsx d.md")
    graph = ReviewerAgent._build_graph_candidate_paths("x.py y.ts z.yaml")
    assert lsp == ["a.py", "b.ts", "c.jsx"]
    assert graph == ["x.py", "y.ts"]

    merged = ReviewerAgent._merge_candidate_paths(["./a.py", "a.py"], ["b.py"], [""])
    assert merged == ["a.py", "b.py"]


def test_graph_summaries_and_followups():
    payload = {
        "status": "ok",
        "reports": [
            {
                "ok": True,
                "target": "app/a.py",
                "details": {
                    "risk_level": "high",
                    "review_targets": ["svc/a.py"],
                    "impacted_endpoint_handlers": ["api/x.py"],
                    "caller_files": ["caller.ts"],
                    "direct_dependents": ["dep.jsx"],
                    "impacted_endpoints": ["GET /x"],
                },
            }
        ],
    }
    followups = ReviewerAgent._collect_graph_followup_paths(payload)
    assert set(followups) >= {"svc/a.py", "api/x.py", "caller.ts", "dep.jsx"}

    summary = ReviewerAgent._summarize_graph_payload(payload)
    assert summary["risk"] == "orta"
    assert summary["high_risk_targets"] == ["app/a.py"]

    no_signal = ReviewerAgent._summarize_graph_payload({"status": "no-signal", "summary": "none", "reports": []})
    assert no_signal["status"] == "no-signal" and no_signal["risk"] == "düşük"


def test_lsp_summary_variants():
    clean = ReviewerAgent._summarize_lsp_diagnostics("")
    assert clean["status"] == "clean"

    json_payload = json.dumps({"status": "issues-found", "risk": "orta", "decision": "APPROVE", "counts": {"2": 1}, "summary": "x", "issues": []})
    parsed = ReviewerAgent._summarize_lsp_diagnostics(json_payload)
    assert parsed["summary"] == "x"

    assert ReviewerAgent._summarize_lsp_diagnostics("LSP temiz") ["status"] == "clean"
    assert ReviewerAgent._summarize_lsp_diagnostics("bildirimi dönmedi") ["status"] == "no-signal"
    assert ReviewerAgent._summarize_lsp_diagnostics("hatası: fail") ["status"] == "tool-error"

    severe = ReviewerAgent._summarize_lsp_diagnostics("a severity=1\nb severity=2")
    assert severe["decision"] == "REJECT" and severe["risk"] == "yüksek"
    info_only = ReviewerAgent._summarize_lsp_diagnostics("a severity=3")
    assert info_only["status"] == "info-only"


def test_combined_impact_and_recommendations():
    sem = {
        "counts": {1: 1, 2: 1},
        "issues": [{"path": "/workspace/Sidar/svc/a.py", "message": "bad import"}],
        "summary": "s",
    }
    graph_summary = {"risk": "orta", "followup_paths": ["svc/a.py"], "high_risk_targets": ["app/main.py"]}
    combined = ReviewerAgent._build_combined_impact_report(sem, graph_summary, ["app/main.py"], ["svc/a.py"])
    assert combined["impact_level"] in {"high", "critical"}

    graph_payload = {
        "reports": [
            {"ok": True, "target": "app/main.py", "details": {"review_targets": ["svc/a.py"], "impacted_endpoints": ["GET /x"], "risk_level": "high"}}
        ]
    }
    recs = ReviewerAgent._build_fix_recommendations(sem, graph_payload, combined)
    assert recs and recs[0]["path"] == "svc/a.py"

    only_graph = ReviewerAgent._build_fix_recommendations({"issues": [], "counts": {}}, graph_payload, {"indirect_breakage_paths": []})
    assert only_graph and only_graph[0]["reason"] == "graph"

    semantic_only = ReviewerAgent._build_fix_recommendations(
        {"issues": [{"path": "a.py", "message": "m"}], "counts": {1: 1}},
        {"reports": []},
        {"indirect_breakage_paths": []},
    )
    assert semantic_only and semantic_only[0]["reason"] == "semantic"


def test_review_payload_and_browser_helpers():
    empty = ReviewerAgent._parse_review_payload("")
    assert empty["review_context"] == ""

    data = ReviewerAgent._parse_review_payload('{"review_context":"ctx","browser_session_id":"abc","browser_include_dom":true}')
    assert data["review_context"] == "ctx" and data["browser_session_id"] == "abc"

    inline = ReviewerAgent._parse_review_payload("change browser_session_id=sess-1")
    assert inline["browser_session_id"] == "sess-1"

    summary = ReviewerAgent._summarize_browser_signals({"status": "failed", "risk": "yüksek", "failed_actions": ["a"], "pending_actions": ["b"], "high_risk_actions": ["c"], "current_url": "u"})
    assert summary["status"] == "failed"
    fix = ReviewerAgent._build_browser_fix_recommendations(summary)
    assert fix and fix[0]["reason"] == "browser-signal"
    assert ReviewerAgent._build_browser_fix_recommendations({"failed_actions": [], "pending_actions": [], "high_risk_actions": []}) == []


def test_remediation_loop_builder():
    sem = {"counts": {1: 2}, "summary": "sem"}
    graph = {"risk": "orta", "summary": "graph"}
    impact = {
        "impact_level": "critical",
        "direct_scope_paths": ["a.py"],
        "graph_followup_paths": ["b.py"],
        "issue_paths": ["c.py"],
        "indirect_breakage_paths": ["b.py"],
    }
    loop = ReviewerAgent._build_remediation_loop(sem, graph, impact, [{"path": "d.py"}], ["pytest -q tests/unit"])
    assert loop["status"] == "planned"
    assert loop["needs_human_approval"] is True
    assert "semantic_issues" in loop["blocked_by"]


def test_tool_methods_and_graph_store(reviewer):
    assert asyncio.run(reviewer._tool_repo_info("")) == "repo-info"
    assert asyncio.run(reviewer._tool_list_prs("closed")) == "prs:closed:20"
    assert "⚠" in asyncio.run(reviewer._tool_pr_diff("x"))
    assert asyncio.run(reviewer._tool_pr_diff("12")) == "diff:12"
    assert "state" in asyncio.run(reviewer._tool_list_issues("open"))

    bad_cmd = asyncio.run(reviewer._tool_run_tests("echo nope"))
    assert "⚠ Kullanım" in bad_cmd
    ok_cmd = asyncio.run(reviewer._tool_run_tests("pytest -q"))
    assert "[TEST:OK]" in ok_cmd

    lsp = json.loads(asyncio.run(reviewer._tool_lsp_diagnostics("a.py")))
    assert lsp["status"] == "clean"

    store1 = reviewer._get_graph_store()
    store2 = reviewer._get_graph_store()
    assert store1 is store2

    no_targets = json.loads(asyncio.run(reviewer._tool_graph_impact("")))
    assert no_targets["status"] == "no-targets"

    graph = json.loads(asyncio.run(reviewer._tool_graph_impact("app/main.py")))
    assert graph["status"] == "ok"

    inline_browser = json.loads(asyncio.run(reviewer._tool_browser_signals('{"browser_signals":{"status":"ok"}}')))
    assert inline_browser["status"] == "ok"

    missing_session = json.loads(asyncio.run(reviewer._tool_browser_signals("{}")))
    assert missing_session["status"] == "no-signal"

    with_session = json.loads(asyncio.run(reviewer._tool_browser_signals('{"browser_session_id":"sess","browser_include_dom":true}')))
    assert with_session["summary"] == "browser-ok"


def test_run_task_routing_and_review_flow(reviewer, monkeypatch):
    assert "Boş reviewer" in asyncio.run(reviewer.run_task(""))

    async def _tool(name, arg):
        return f"{name}:{arg}"

    monkeypatch.setattr(reviewer, "call_tool", _tool)
    assert asyncio.run(reviewer.run_task("repo_info")) == "repo_info:"
    assert asyncio.run(reviewer.run_task("list_prs|closed")) == "list_prs:closed"
    assert asyncio.run(reviewer.run_task("pr_diff|7")) == "pr_diff:7"
    assert asyncio.run(reviewer.run_task("list_issues|open")) == "list_issues:open"
    assert asyncio.run(reviewer.run_task("run_tests|pytest -q")) == "run_tests:pytest -q"
    assert asyncio.run(reviewer.run_task("lsp_diagnostics|a.py")) == "lsp_diagnostics:a.py"
    assert asyncio.run(reviewer.run_task("graph_impact|a.py")) == "graph_impact:a.py"

    async def _call_tool_flow(name, arg):
        if name == "run_tests":
            return "[TEST:OK]"
        if name == "graph_impact":
            return json.dumps({"status": "ok", "summary": "g", "reports": []}, ensure_ascii=False)
        if name == "browser_signals":
            return json.dumps({"status": "ok", "risk": "düşük", "summary": "b"}, ensure_ascii=False)
        if name == "lsp_diagnostics":
            return json.dumps({"status": "issues-found", "risk": "yüksek", "decision": "REJECT", "counts": {"1": 1}, "summary": "lsp", "issues": []}, ensure_ascii=False)
        return "x"

    async def _run_dynamic(_ctx):
        return "[TEST:OK]"

    monkeypatch.setattr(reviewer, "call_tool", _call_tool_flow)
    monkeypatch.setattr(reviewer, "_run_dynamic_tests", _run_dynamic)
    monkeypatch.setattr(reviewer, "_build_regression_commands", lambda _ctx: ["pytest -q tests/unit"])

    delegated = reviewer.delegate_to

    result = asyncio.run(reviewer.run_task("review_code|{\"review_context\":\"app/main.py\"}"))
    assert result.target_agent == "coder"
    assert "qa_feedback|" in result.payload

    monkeypatch.setattr(reviewer, "run_task", ReviewerAgent.run_task.__get__(reviewer, ReviewerAgent))
    monkeypatch.setattr(reviewer, "call_tool", _tool)
    assert asyncio.run(reviewer.run_task("unknown")) == "list_prs:open"
