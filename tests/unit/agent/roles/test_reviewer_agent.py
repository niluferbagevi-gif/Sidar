import importlib.util
import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_reviewer_agent():
    module_name = "reviewer_agent_under_test"
    if module_name in sys.modules:
        return sys.modules[module_name].ReviewerAgent
    if "httpx" not in sys.modules:
        sys.modules["httpx"] = ModuleType("httpx")
    if "redis" not in sys.modules:
        redis_module = ModuleType("redis")
        redis_asyncio = ModuleType("redis.asyncio")
        redis_exceptions = ModuleType("redis.exceptions")
        redis_asyncio.Redis = object
        redis_exceptions.ResponseError = Exception
        redis_module.asyncio = redis_asyncio
        redis_module.exceptions = redis_exceptions
        sys.modules["redis"] = redis_module
        sys.modules["redis.asyncio"] = redis_asyncio
        sys.modules["redis.exceptions"] = redis_exceptions
    module_path = Path("agent/roles/reviewer_agent.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.ReviewerAgent


ReviewerAgent = _load_reviewer_agent()


class DummyEvents:
    def __init__(self):
        self.messages = []

    async def publish(self, role, message):
        self.messages.append((role, message))


class DummyCode:
    def __init__(self):
        self.write_ok = True
        self.write_msg = "ok"
        self.run_ok = True
        self.run_out = "tests passed"
        self.audit_payload = {}

    def write_file(self, *_args, **_kwargs):
        return self.write_ok, self.write_msg

    def run_shell_in_sandbox(self, *_args, **_kwargs):
        return self.run_ok, self.run_out

    def lsp_semantic_audit(self, _paths):
        return True, self.audit_payload


class DummyGithub:
    def __init__(self):
        self.repo = (True, "repo")
        self.prs = (True, "prs")
        self.diff = (True, "diff")
        self.issues = (True, ["i1"])

    def get_repo_info(self):
        return self.repo

    def list_pull_requests(self, *_args):
        return self.prs

    def get_pull_request_diff(self, *_args):
        return self.diff

    def list_issues(self, *_args):
        return self.issues


class DummyBrowser:
    def __init__(self):
        self.signal = {"status": "ok", "summary": "ok"}

    def collect_session_signals(self, *_args, **_kwargs):
        return self.signal


class DummyDocs:
    def __init__(self, ok=True):
        self.ok = ok

    def graph_impact_details(self, target, _depth):
        if self.ok:
            return True, {"risk_level": "high", "review_targets": [target], "impacted_endpoints": ["/x"]}
        return False, "err"

    def analyze_graph_impact(self, target, _depth):
        return True, f"report:{target}"


@pytest.fixture
def reviewer(tmp_path):
    r = ReviewerAgent.__new__(ReviewerAgent)
    r.config = SimpleNamespace(
        BASE_DIR=str(tmp_path),
        REVIEWER_TEST_COMMAND="python -m pytest",
        RAG_DIR=str(tmp_path / "rag"),
        RAG_TOP_K=5,
        RAG_CHUNK_SIZE=100,
        RAG_CHUNK_OVERLAP=10,
        USE_GPU=False,
        GPU_DEVICE=0,
        GPU_MIXED_PRECISION=False,
    )
    r.cfg = r.config
    r.role_name = "reviewer"
    r.code = DummyCode()
    r.github = DummyGithub()
    r.browser = DummyBrowser()
    r.events = DummyEvents()
    r._graph_docs = None
    return r


def test_extract_helpers_and_paths():
    assert ReviewerAgent._extract_python_code_block("```python\nassert 1\n```") == "assert 1"
    fail = ReviewerAgent._fail_closed_test_content("neden")
    assert "def test_reviewer_dynamic_generation_fail_closed" in fail

    paths = ReviewerAgent._extract_changed_paths("a.py ../x.py /tmp/y.py src/a.ts tests/t.py")
    assert paths == ["a.py", "x.py", "tmp/y.py", "src/a.ts", "tests/t.py"]
    assert ReviewerAgent._build_lsp_candidate_paths("a.py b.md c.jsx") == ["a.py", "c.jsx"]
    assert ReviewerAgent._build_graph_candidate_paths("a.py b.ts c.md") == ["a.py", "b.ts"]
    assert ReviewerAgent._merge_candidate_paths(["./a.py", "a.py"], ["b.py"]) == ["a.py", "b.py"]


def test_graph_followups_and_summary():
    payload = {
        "status": "ok",
        "reports": [
            {
                "ok": True,
                "target": "x.py",
                "details": {
                    "risk_level": "high",
                    "review_targets": ["a.py"],
                    "impacted_endpoint_handlers": ["b.ts"],
                    "caller_files": ["c.jsx"],
                    "direct_dependents": ["d.py"],
                    "impacted_endpoints": ["/a"],
                },
            }
        ],
    }
    followups = ReviewerAgent._collect_graph_followup_paths(payload)
    assert followups == ["a.py", "b.ts", "c.jsx", "d.py"]
    summary = ReviewerAgent._summarize_graph_payload(payload)
    assert summary["risk"] == "orta"
    assert summary["high_risk_targets"] == ["x.py"]

    empty = ReviewerAgent._summarize_graph_payload({"status": "none", "summary": "yok", "reports": []})
    assert empty["risk"] == "düşük"


def test_lsp_summary_variants_and_normalize_path():
    parsed = ReviewerAgent._summarize_lsp_diagnostics(
        json.dumps({"summary": "s", "status": "issues-found", "risk": "orta", "decision": "APPROVE", "counts": {"2": 1}, "issues": []})
    )
    assert parsed["status"] == "issues-found"
    assert ReviewerAgent._summarize_lsp_diagnostics("LSP diagnostics temiz") ["status"] == "clean"
    assert ReviewerAgent._summarize_lsp_diagnostics("bildirimi dönmedi")["status"] == "no-signal"
    assert ReviewerAgent._summarize_lsp_diagnostics("hatası: boom")["status"] == "tool-error"
    issues = ReviewerAgent._summarize_lsp_diagnostics("x severity=1\ny severity=2\nz severity=3")
    assert issues["decision"] == "REJECT"
    only_info = ReviewerAgent._summarize_lsp_diagnostics("z severity=4")
    assert only_info["status"] == "info-only"
    assert ReviewerAgent._normalize_issue_path("/workspace/Sidar/a/b.py") == "a/b.py"


def test_combined_impact_and_recommendations():
    semantic = {
        "counts": {"1": 1, "2": 0},
        "issues": [{"path": "/workspace/Sidar/pkg/f.py", "message": "m"}],
    }
    graph_summary = {"risk": "orta", "followup_paths": ["pkg/f.py"], "high_risk_targets": ["t.py"]}
    combined = ReviewerAgent._build_combined_impact_report(semantic, graph_summary, ["src/a.py"], ["src/a.py", "pkg/f.py"])
    assert combined["impact_level"] == "critical"
    assert combined["indirect_breakage_paths"] == ["pkg/f.py"]

    graph_payload = {
        "reports": [
            {
                "ok": True,
                "target": "src/a.py",
                "details": {
                    "risk_level": "high",
                    "review_targets": ["pkg/f.py", "ext/e.py"],
                    "impacted_endpoints": ["/h"],
                },
            }
        ]
    }
    recs = ReviewerAgent._build_fix_recommendations(semantic, graph_payload, combined)
    assert recs[0]["reason"] == "graph+semantic"

    combined2 = {"indirect_breakage_paths": []}
    recs2 = ReviewerAgent._build_fix_recommendations({"issues": []}, graph_payload, combined2)
    assert recs2 and recs2[0]["reason"] == "graph"

    recs3 = ReviewerAgent._build_fix_recommendations({"issues": [{"path": "x.py", "message": "e"}]}, {"reports": []}, combined2)
    assert recs3 and recs3[0]["reason"] == "semantic"


def test_parse_browser_and_remediation_helpers():
    p = ReviewerAgent._parse_review_payload("")
    assert p["review_context"] == ""
    p2 = ReviewerAgent._parse_review_payload('{"review_context":"abc","browser_session_id":"s1"}')
    assert p2["browser_session_id"] == "s1"
    p3 = ReviewerAgent._parse_review_payload("changes browser_session_id=s2")
    assert p3["browser_session_id"] == "s2"

    summary = ReviewerAgent._summarize_browser_signals({"failed_actions": ["a"], "pending_actions": ["b"], "high_risk_actions": ["c"], "current_url": "u"})
    assert summary["status"] == "no-signal"
    recs = ReviewerAgent._build_browser_fix_recommendations(summary)
    assert recs and recs[0]["reason"] == "browser-signal"
    assert ReviewerAgent._build_browser_fix_recommendations({"failed_actions": []}) == []

    remediation = ReviewerAgent._build_remediation_loop(
        {"counts": {"1": 1}, "summary": "s"},
        {"risk": "orta", "summary": "g"},
        {"impact_level": "high", "direct_scope_paths": ["a.py"], "graph_followup_paths": ["b.py"], "issue_paths": ["c.py"], "indirect_breakage_paths": ["z.py"]},
        [{"path": "d.py"}],
        ["pytest -q tests/a.py"],
    )
    assert remediation["needs_human_approval"] is True
    assert remediation["status"] == "planned"


def test_dynamic_build_and_run(reviewer, monkeypatch):
    async def fake_call_llm(*_args, **_kwargs):
        return "```python\ndef test_ok():\n    assert True\n```"

    reviewer.call_llm = fake_call_llm
    content = asyncio.run(reviewer._build_dynamic_test_content("ctx"))
    assert "def test_ok" in content
    fail = asyncio.run(reviewer._build_dynamic_test_content(""))
    assert "fail_closed" in fail

    async def raises(*_a, **_k):
        raise RuntimeError("llm boom")

    reviewer.call_llm = raises
    fail2 = asyncio.run(reviewer._build_dynamic_test_content("ctx"))
    assert "başarısız" in fail2

    async def fake_call_tool(name, arg):
        assert name == "run_tests"
        return f"ran:{arg}"

    reviewer.call_tool = fake_call_tool
    reviewer.call_llm = fake_call_llm
    out = asyncio.run(reviewer._run_dynamic_tests("ctx"))
    assert out.startswith("ran:pytest -q temp/reviewer_dynamic_")

    reviewer.code.write_ok = False
    out2 = asyncio.run(reviewer._run_dynamic_tests("ctx"))
    assert "[TEST:FAIL-CLOSED]" in out2


def test_tools(reviewer, monkeypatch):
    assert asyncio.run(reviewer._tool_repo_info("")) == "repo"
    reviewer.github.repo = (False, "x")
    assert "[HATA]" in asyncio.run(reviewer._tool_repo_info(""))

    assert asyncio.run(reviewer._tool_list_prs("")) == "prs"
    reviewer.github.prs = (False, "err")
    assert "[HATA]" in asyncio.run(reviewer._tool_list_prs("closed"))

    assert "Kullanım" in asyncio.run(reviewer._tool_pr_diff("abc"))
    assert asyncio.run(reviewer._tool_pr_diff("1")) == "diff"
    reviewer.github.diff = (False, "bad")
    assert "[HATA]" in asyncio.run(reviewer._tool_pr_diff("1"))

    assert asyncio.run(reviewer._tool_list_issues("")) == "['i1']"
    reviewer.github.issues = (False, "bad")
    assert "[HATA]" in asyncio.run(reviewer._tool_list_issues(""))

    bad = asyncio.run(reviewer._tool_run_tests("echo hi"))
    assert "Kullanım" in bad
    ok = asyncio.run(reviewer._tool_run_tests("pytest -q"))
    assert "[TEST:OK]" in ok
    reviewer.code.run_ok = False
    fail = asyncio.run(reviewer._tool_run_tests("python -m pytest"))
    assert "[TEST:FAIL-CLOSED]" in fail

    reviewer.code.audit_payload = {"summary": "ok"}
    lsp = asyncio.run(reviewer._tool_lsp_diagnostics("src/a.py"))
    assert json.loads(lsp)["targets"] == ["src/a.py"]

    reviewer._graph_docs = DummyDocs(ok=True)
    graph = json.loads(asyncio.run(reviewer._tool_graph_impact("src/a.py")))
    assert graph["status"] == "ok"
    reviewer._graph_docs = DummyDocs(ok=False)
    graph2 = json.loads(asyncio.run(reviewer._tool_graph_impact("README.md")))
    assert graph2["status"] == "no-signal"
    graph3 = json.loads(asyncio.run(reviewer._tool_graph_impact("")))
    assert graph3["status"] == "no-targets"

    inline = asyncio.run(reviewer._tool_browser_signals('{"browser_signals":{"status":"ok"}}'))
    assert json.loads(inline)["status"] == "ok"
    no_signal = asyncio.run(reviewer._tool_browser_signals("{}"))
    assert json.loads(no_signal)["status"] == "no-signal"
    got = asyncio.run(reviewer._tool_browser_signals('{"browser_session_id":"s"}'))
    assert json.loads(got)["status"] == "ok"


def test_get_graph_store(reviewer, monkeypatch):
    class FakeStore:
        def __init__(self, *args, **kwargs):
            self.args = args

    monkeypatch.setattr(sys.modules[ReviewerAgent.__module__], "DocumentStore", FakeStore)
    store1 = reviewer._get_graph_store()
    store2 = reviewer._get_graph_store()
    assert store1 is store2


def test_run_task_main_paths(reviewer):
    async def fake_call_tool(name, arg):
        mapping = {
            "repo_info": "repo",
            "list_prs": "prs",
            "pr_diff": "diff",
            "list_issues": "issues",
            "run_tests": "[TEST:OK]",
            "lsp_diagnostics": json.dumps({"summary": "temiz", "status": "clean", "risk": "düşük", "decision": "APPROVE", "counts": {}, "issues": []}),
            "graph_impact": json.dumps({"status": "ok", "summary": "g", "reports": []}),
            "browser_signals": json.dumps({"status": "ok", "risk": "düşük", "summary": "b"}),
        }
        return mapping[name]

    async def fake_dynamic(_ctx):
        return "[TEST:OK]"

    reviewer.call_tool = fake_call_tool
    reviewer._run_dynamic_tests = fake_dynamic

    assert asyncio.run(reviewer.run_task("")) == "[UYARI] Boş reviewer görevi verildi."
    assert asyncio.run(reviewer.run_task("repo_info")) == "repo"
    assert asyncio.run(reviewer.run_task("list_prs")) == "prs"
    assert asyncio.run(reviewer.run_task("pr_diff|12")) == "diff"
    assert asyncio.run(reviewer.run_task("list_issues")) == "issues"
    assert asyncio.run(reviewer.run_task("run_tests")) == "[TEST:OK]"
    assert "summary" in (asyncio.run(reviewer.run_task("lsp_diagnostics|a.py")))
    assert "status" in (asyncio.run(reviewer.run_task("graph_impact|a.py")))

    result = asyncio.run(reviewer.run_task("review_code|{\"review_context\":\"src/a.py\"}"))
    assert result.target_agent == "coder"
    assert result.meta["reason"] == "review_decision"

    # semantic reject branch
    async def fake_call_tool_reject(name, arg):
        if name == "lsp_diagnostics":
            return json.dumps({"summary": "err", "status": "issues-found", "risk": "yüksek", "decision": "REJECT", "counts": {"1": 1}, "issues": [{"path": "x.py"}]})
        if name == "browser_signals":
            return json.dumps({"status": "ok", "risk": "düşük", "summary": "b"})
        if name == "graph_impact":
            return json.dumps({"status": "ok", "summary": "g", "reports": []})
        return "[TEST:OK]"

    reviewer.call_tool = fake_call_tool_reject
    result2 = asyncio.run(reviewer.run_task("review_code|ctx"))
    assert result2.target_agent == "coder"

    async def fake_call_tool_browser_fail(name, arg):
        if name == "browser_signals":
            return json.dumps({"status": "failed", "risk": "yüksek", "summary": "bf", "failed_actions": ["click"]})
        if name == "lsp_diagnostics":
            return json.dumps({"summary": "ok", "status": "clean", "risk": "düşük", "decision": "APPROVE", "counts": {}, "issues": []})
        if name == "graph_impact":
            return json.dumps({"status": "ok", "summary": "g", "reports": []})
        return "[TEST:OK]"

    reviewer.call_tool = fake_call_tool_browser_fail
    result3 = asyncio.run(reviewer.run_task("review_code|ctx"))
    assert result3.target_agent == "coder"

    assert (asyncio.run(reviewer.run_task("lütfen review et"))).target_agent == "coder"

    async def default_call(name, arg):
        return "prs" if name == "list_prs" else "x"

    reviewer.call_tool = default_call
    assert asyncio.run(reviewer.run_task("unknown")) == "prs"
