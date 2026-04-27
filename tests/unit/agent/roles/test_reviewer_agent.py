import asyncio
import importlib.util
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


def test_load_reviewer_agent_returns_cached_module(monkeypatch):
    sentinel = object()
    cached_module = SimpleNamespace(ReviewerAgent=sentinel)
    monkeypatch.setitem(sys.modules, "reviewer_agent_under_test", cached_module)

    assert _load_reviewer_agent() is sentinel


def test_load_reviewer_agent_injects_httpx_and_redis_when_missing(monkeypatch):
    sentinel = object()

    class _Loader:
        def exec_module(self, module):
            module.ReviewerAgent = sentinel

    fake_spec = SimpleNamespace(loader=_Loader())
    monkeypatch.delitem(sys.modules, "reviewer_agent_under_test", raising=False)
    monkeypatch.delitem(sys.modules, "httpx", raising=False)
    monkeypatch.delitem(sys.modules, "redis", raising=False)
    monkeypatch.delitem(sys.modules, "redis.asyncio", raising=False)
    monkeypatch.delitem(sys.modules, "redis.exceptions", raising=False)
    monkeypatch.setattr(
        importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: fake_spec
    )
    monkeypatch.setattr(
        importlib.util, "module_from_spec", lambda _spec: ModuleType("reviewer_agent_under_test")
    )

    loaded = _load_reviewer_agent()
    assert loaded is sentinel
    assert "httpx" in sys.modules
    assert "redis" in sys.modules
    assert "redis.asyncio" in sys.modules
    assert "redis.exceptions" in sys.modules


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
            return True, {
                "risk_level": "high",
                "review_targets": [target],
                "impacted_endpoints": ["/x"],
            }
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
    r.delegate_to = lambda target_agent, payload, reason="": SimpleNamespace(
        target_agent=target_agent,
        payload=payload,
        meta={"reason": reason} if reason else {},
    )
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

    empty = ReviewerAgent._summarize_graph_payload(
        {"status": "none", "summary": "yok", "reports": []}
    )
    assert empty["risk"] == "düşük"


def test_lsp_summary_variants_and_normalize_path():
    parsed = ReviewerAgent._summarize_lsp_diagnostics(
        json.dumps(
            {
                "summary": "s",
                "status": "issues-found",
                "risk": "orta",
                "decision": "APPROVE",
                "counts": {"2": 1},
                "issues": [],
            }
        )
    )
    assert parsed["status"] == "issues-found"
    assert ReviewerAgent._summarize_lsp_diagnostics("LSP diagnostics temiz")["status"] == "clean"
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
    combined = ReviewerAgent._build_combined_impact_report(
        semantic, graph_summary, ["src/a.py"], ["src/a.py", "pkg/f.py"]
    )
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

    recs3 = ReviewerAgent._build_fix_recommendations(
        {"issues": [{"path": "x.py", "message": "e"}]}, {"reports": []}, combined2
    )
    assert recs3 and recs3[0]["reason"] == "semantic"


def test_parse_browser_and_remediation_helpers():
    p = ReviewerAgent._parse_review_payload("")
    assert p["review_context"] == ""
    p2 = ReviewerAgent._parse_review_payload('{"review_context":"abc","browser_session_id":"s1"}')
    assert p2["browser_session_id"] == "s1"
    p3 = ReviewerAgent._parse_review_payload("changes browser_session_id=s2")
    assert p3["browser_session_id"] == "s2"

    summary = ReviewerAgent._summarize_browser_signals(
        {
            "failed_actions": ["a"],
            "pending_actions": ["b"],
            "high_risk_actions": ["c"],
            "current_url": "u",
        }
    )
    assert summary["status"] == "no-signal"
    recs = ReviewerAgent._build_browser_fix_recommendations(summary)
    assert recs and recs[0]["reason"] == "browser-signal"
    assert ReviewerAgent._build_browser_fix_recommendations({"failed_actions": []}) == []

    remediation = ReviewerAgent._build_remediation_loop(
        {"counts": {"1": 1}, "summary": "s"},
        {"risk": "orta", "summary": "g"},
        {
            "impact_level": "high",
            "direct_scope_paths": ["a.py"],
            "graph_followup_paths": ["b.py"],
            "issue_paths": ["c.py"],
            "indirect_breakage_paths": ["z.py"],
        },
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

    async def no_test_fn(*_a, **_k):
        return "```python\nprint('no test')\n```"

    reviewer.call_llm = no_test_fn
    fail3 = asyncio.run(reviewer._build_dynamic_test_content("ctx"))
    assert "pytest test fonksiyonu içermedi" in fail3

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
            "lsp_diagnostics": json.dumps(
                {
                    "summary": "temiz",
                    "status": "clean",
                    "risk": "düşük",
                    "decision": "APPROVE",
                    "counts": {},
                    "issues": [],
                }
            ),
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

    result = asyncio.run(reviewer.run_task('review_code|{"review_context":"src/a.py"}'))
    assert result.target_agent == "coder"
    assert result.meta["reason"] == "review_decision"

    # semantic reject branch
    async def fake_call_tool_reject(name, arg):
        if name == "lsp_diagnostics":
            return json.dumps(
                {
                    "summary": "err",
                    "status": "issues-found",
                    "risk": "yüksek",
                    "decision": "REJECT",
                    "counts": {"1": 1},
                    "issues": [{"path": "x.py"}],
                }
            )
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
            return json.dumps(
                {"status": "failed", "risk": "yüksek", "summary": "bf", "failed_actions": ["click"]}
            )
        if name == "lsp_diagnostics":
            return json.dumps(
                {
                    "summary": "ok",
                    "status": "clean",
                    "risk": "düşük",
                    "decision": "APPROVE",
                    "counts": {},
                    "issues": [],
                }
            )
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


def test_run_task_conflicting_signals_prioritizes_fail_closed_decision(reviewer):
    async def fake_call_tool(name, arg):
        if name == "run_tests":
            return "[TEST:OK]"
        if name == "lsp_diagnostics":
            return json.dumps(
                {
                    "summary": "semantik temiz",
                    "status": "clean",
                    "risk": "düşük",
                    "decision": "APPROVE",
                    "counts": {},
                    "issues": [],
                }
            )
        if name == "graph_impact":
            return json.dumps({"status": "ok", "summary": "düşük risk", "reports": []})
        if name == "browser_signals":
            return json.dumps({"status": "ok", "risk": "düşük", "summary": "sinyal temiz"})
        return ""

    async def fake_dynamic(_ctx):
        # Çelişen yönlendirme senaryosu: semantik analiz onaylasa da dinamik test fail sinyali taşıyor.
        return "[TEST:FAIL] assertion failed"

    reviewer.call_tool = fake_call_tool
    reviewer._run_dynamic_tests = fake_dynamic

    result = asyncio.run(reviewer.run_task('review_code|{"review_context":"src/a.py"}'))
    payload = json.loads(result.payload.split("qa_feedback|", 1)[1])

    assert payload["decision"] == "REJECT"
    assert payload["risk"] == "yüksek"
    assert "[REVIEW:FAIL]" in payload["summary"]


def test_init_registers_managers_and_tools(monkeypatch, tmp_path):
    module = sys.modules[ReviewerAgent.__module__]

    def fake_base_init(self, cfg=None, role_name="base"):
        self.cfg = cfg
        self.role_name = role_name
        self.tools = {}
        self.register_tool = lambda name, func: self.tools.__setitem__(name, func)

    class FakeGitHub:
        def __init__(self, token, repo):
            self.token = token
            self.repo = repo

    class FakeSecurity:
        def __init__(self, cfg=None):
            self.cfg = cfg

    class FakeCode:
        def __init__(self, security, base_dir, **kwargs):
            self.security = security
            self.base_dir = base_dir
            self.kwargs = kwargs

    class FakeBrowser:
        def __init__(self, cfg):
            self.cfg = cfg

    monkeypatch.setattr(module.BaseAgent, "__init__", fake_base_init)
    monkeypatch.setattr(module, "GitHubManager", FakeGitHub)
    monkeypatch.setattr(module, "SecurityManager", FakeSecurity)
    monkeypatch.setattr(module, "CodeManager", FakeCode)
    monkeypatch.setattr(module, "BrowserManager", FakeBrowser)
    monkeypatch.setattr(module, "get_agent_event_bus", lambda: DummyEvents())

    cfg = SimpleNamespace(
        GITHUB_TOKEN="t",
        GITHUB_REPO="r",
        BASE_DIR=str(tmp_path),
        DOCKER_PYTHON_IMAGE="python:3.11",
        DOCKER_EXEC_TIMEOUT=15,
        RAG_DIR=str(tmp_path / "rag"),
        RAG_TOP_K=2,
        RAG_CHUNK_SIZE=10,
        RAG_CHUNK_OVERLAP=1,
        USE_GPU=False,
        GPU_DEVICE=0,
        GPU_MIXED_PRECISION=False,
    )
    agent = ReviewerAgent(cfg=cfg)
    assert agent.github.token == "t"
    assert agent.code.base_dir == str(tmp_path)
    assert "browser_signals" in agent.tools


def test_edge_paths_for_uncovered_branches(reviewer, monkeypatch):
    assert ReviewerAgent._extract_python_code_block("print('x')") == "print('x')"

    assert ReviewerAgent._collect_graph_followup_paths({"reports": "x"}) == []
    rich_payload = {
        "reports": [
            {"ok": False, "details": {"review_targets": ["skip.py"]}},
            {"ok": True, "details": {"review_targets": "not-list"}},
            {"ok": True, "details": {"review_targets": ["README.md", "x.py", "x.py"]}},
        ]
    }
    assert ReviewerAgent._collect_graph_followup_paths(rich_payload) == ["x.py"]
    payload = {"status": "ok", "reports": [{"ok": True, "target": "x.py", "details": "bad"}]}
    assert ReviewerAgent._summarize_graph_payload(payload)["high_risk_targets"] == []

    assert ReviewerAgent._summarize_lsp_diagnostics("")["status"] == "clean"
    assert ReviewerAgent._summarize_lsp_diagnostics('{"status":"x"}')["status"] == "clean"
    assert ReviewerAgent._summarize_lsp_diagnostics("random satir")["status"] == "clean"

    semantic = {
        "counts": {"bad": 3},
        "issues": [None, {"path": "/workspace/Sidar/a.py"}, {"path": "/workspace/Sidar/a.py"}],
    }
    combined = ReviewerAgent._build_combined_impact_report(
        semantic,
        {"risk": "orta", "followup_paths": ["b.py"], "high_risk_targets": []},
        ["a.py"],
        [],
    )
    assert combined["impact_level"] == "high"

    graph_payload = {"reports": [{"ok": False}, {"ok": True, "target": "a.py", "details": []}]}
    recs = ReviewerAgent._build_fix_recommendations(
        {"issues": [None, {"path": "", "message": "m"}]},
        graph_payload,
        {"indirect_breakage_paths": []},
    )
    assert recs == []

    graph_payload_non_dict_details = {
        "reports": [{"ok": True, "target": "a.py", "details": "not-dict"}]
    }
    recs_non_dict_details = ReviewerAgent._build_fix_recommendations(
        {"issues": [{"path": "dep.py", "message": "boom"}]},
        graph_payload_non_dict_details,
        {"indirect_breakage_paths": ["dep.py"]},
    )
    assert recs_non_dict_details[0]["path"] == "dep.py"
    assert recs_non_dict_details[0]["related_endpoints"] == []

    graph_payload2 = {
        "reports": [
            {"ok": True, "target": "a.py", "details": {"risk_level": "low", "review_targets": "x"}}
        ]
    }
    recs2 = ReviewerAgent._build_fix_recommendations(
        {"issues": []}, graph_payload2, {"indirect_breakage_paths": []}
    )
    assert recs2 == []

    graph_payload_skip_non_dict_details = {
        "reports": [{"ok": True, "target": "a.py", "details": "not-dict"}]
    }
    recs_skip_non_dict_details = ReviewerAgent._build_fix_recommendations(
        {"issues": []},
        graph_payload_skip_non_dict_details,
        {"indirect_breakage_paths": []},
    )
    assert recs_skip_non_dict_details == []

    graph_payload3 = {
        "reports": [
            {
                "ok": True,
                "target": "a.py",
                "details": {
                    "risk_level": "high",
                    "review_targets": [None, "a.py", "dep.py", "dep.py"],
                    "caller_files": "x",
                },
            },
            {
                "ok": True,
                "target": "b.py",
                "details": {"risk_level": "high", "direct_dependents": ["dep.py", "other.ts"]},
            },
        ]
    }
    recs3 = ReviewerAgent._build_fix_recommendations(
        {"issues": []}, graph_payload3, {"indirect_breakage_paths": []}
    )
    assert [item["path"] for item in recs3] == ["dep.py", "other.ts"]

    parsed = ReviewerAgent._parse_review_payload("[1,2,3]")
    assert parsed["browser_session_id"] == ""
    parsed_fallback = ReviewerAgent._parse_review_payload("{this is invalid json")
    assert parsed_fallback["review_context"] == "{this is invalid json"
    parsed_json_non_dict = ReviewerAgent._parse_review_payload("[1,2,3]")
    assert parsed_json_non_dict["review_context"] == "[1,2,3]"

    module = sys.modules[ReviewerAgent.__module__]
    original_loads = module.json.loads
    monkeypatch.setattr(module.json, "loads", lambda *_a, **_k: [])
    parsed_non_dict_payload = ReviewerAgent._parse_review_payload('{"review_context":"x"}')
    assert parsed_non_dict_payload["review_context"] == '{"review_context":"x"}'
    monkeypatch.setattr(module.json, "loads", original_loads)

    assert ReviewerAgent._extract_changed_paths("src/a/../b.py /abs/x.py foo.py") == [
        "abs/x.py",
        "foo.py",
    ]
    assert reviewer._build_regression_commands("tests/unit/test_a.py src/a.py")[0].startswith(
        "pytest -q tests/unit/test_a.py"
    )

    # cover unlink exception branch
    original_unlink = Path.unlink
    reviewer.call_tool = lambda *_a, **_k: asyncio.sleep(0, result="x")
    reviewer.call_llm = lambda *_a, **_k: asyncio.sleep(
        0, result="def test_ok():\n    assert True\n"
    )

    def bad_unlink(self, missing_ok=True):
        raise OSError("nope")

    monkeypatch.setattr(Path, "unlink", bad_unlink)
    out = asyncio.run(reviewer._run_dynamic_tests("ctx"))
    assert out == "x"
    monkeypatch.setattr(Path, "unlink", original_unlink)


def test_run_task_decision_branches(reviewer):
    reviewer._run_dynamic_tests = lambda _ctx: asyncio.sleep(0, result="[TEST:FAIL-CLOSED]")

    async def call_tool_fail(name, _arg):
        if name == "run_tests":
            return "[TEST:OK]"
        if name == "graph_impact":
            return json.dumps(
                {
                    "status": "ok",
                    "summary": "g",
                    "reports": [
                        {
                            "ok": True,
                            "target": "x.py",
                            "details": {
                                "risk_level": "low",
                                "review_targets": [],
                                "impacted_endpoints": [],
                            },
                        }
                    ],
                }
            )
        if name == "browser_signals":
            return json.dumps({"status": "ok", "risk": "düşük", "summary": "b"})
        if name == "lsp_diagnostics":
            return json.dumps(
                {
                    "summary": "s",
                    "status": "clean",
                    "risk": "düşük",
                    "decision": "APPROVE",
                    "counts": {},
                    "issues": [],
                }
            )
        return ""

    assert asyncio.run(call_tool_fail("unknown", "")) == ""

    reviewer.call_tool = call_tool_fail
    res = asyncio.run(reviewer.run_task("review_code|ctx"))
    data = json.loads(res.payload.split("qa_feedback|", 1)[1])
    assert data["decision"] == "REJECT"

    reviewer._run_dynamic_tests = lambda _ctx: asyncio.sleep(0, result="[TEST:OK]")

    async def call_tool_risk(name, _arg):
        if name == "run_tests":
            return "[TEST:OK]"
        if name == "graph_impact":
            return json.dumps(
                {
                    "status": "ok",
                    "summary": "g",
                    "reports": [
                        {
                            "ok": True,
                            "target": "x.py",
                            "details": {
                                "risk_level": "high",
                                "review_targets": ["b.py"],
                                "impacted_endpoints": [],
                            },
                        }
                    ],
                }
            )
        if name == "browser_signals":
            return json.dumps({"status": "ok", "risk": "orta", "summary": "b"})
        if name == "lsp_diagnostics":
            return json.dumps(
                {
                    "summary": "s",
                    "status": "clean",
                    "risk": "orta",
                    "decision": "APPROVE",
                    "counts": {},
                    "issues": [],
                }
            )
        return ""

    assert asyncio.run(call_tool_risk("unknown", "")) == ""

    reviewer.call_tool = call_tool_risk
    res2 = asyncio.run(reviewer.run_task("review_code|ctx"))
    data2 = json.loads(res2.payload.split("qa_feedback|", 1)[1])
    assert data2["risk"] == "orta"

    async def call_tool_graph_medium(name, _arg):
        if name == "run_tests":
            return "[TEST:OK]"
        if name == "graph_impact":
            return json.dumps(
                {
                    "status": "ok",
                    "summary": "g",
                    "reports": [
                        {
                            "ok": True,
                            "target": "x.py",
                            "details": {
                                "risk_level": "high",
                                "review_targets": ["x.py"],
                                "impacted_endpoints": [],
                            },
                        }
                    ],
                }
            )
        if name == "browser_signals":
            return json.dumps({"status": "ok", "risk": "düşük", "summary": "b"})
        if name == "lsp_diagnostics":
            return json.dumps(
                {
                    "summary": "s",
                    "status": "clean",
                    "risk": "düşük",
                    "decision": "APPROVE",
                    "counts": {},
                    "issues": [],
                }
            )
        return ""

    assert asyncio.run(call_tool_graph_medium("unknown", "")) == ""

    reviewer.call_tool = call_tool_graph_medium
    res3 = asyncio.run(reviewer.run_task("review_code|ctx"))
    data3 = json.loads(res3.payload.split("qa_feedback|", 1)[1])
    assert data3["risk"] == "orta"

    async def call_tool_low_signals(name, _arg):
        if name == "run_tests":
            return "[TEST:OK]"
        if name == "graph_impact":
            return json.dumps({"status": "ok", "summary": "g", "reports": []})
        if name == "browser_signals":
            return json.dumps({"status": "ok", "risk": "düşük", "summary": "b"})
        if name == "lsp_diagnostics":
            return json.dumps(
                {
                    "summary": "s",
                    "status": "clean",
                    "risk": "düşük",
                    "decision": "APPROVE",
                    "counts": {},
                    "issues": [],
                }
            )
        return ""

    assert asyncio.run(call_tool_low_signals("unknown", "")) == ""

    reviewer.call_tool = call_tool_low_signals
    reviewer._build_combined_impact_report = lambda *_a, **_k: {  # type: ignore[method-assign]
        "impact_level": "high",
        "summary": "forced",
        "indirect_breakage_paths": [],
        "direct_scope_paths": [],
        "graph_followup_paths": [],
        "issue_paths": [],
        "high_risk_targets": [],
    }
    res4 = asyncio.run(reviewer.run_task("review_code|ctx"))
    data4 = json.loads(res4.payload.split("qa_feedback|", 1)[1])
    assert data4["risk"] == "orta"


def test_reviewer_generate_candidate_with_fake_llm(reviewer, fake_llm_response):
    async def _reviewer_llm(*_args, **_kwargs):
        _ = await fake_llm_response("reviewer")
        return "def test_generated_reviewer_case():\n    assert True\n"

    reviewer.call_llm = _reviewer_llm
    dynamic_test = asyncio.run(reviewer._build_dynamic_test_content("diff --git a/x.py b/x.py"))
    assert "def test_generated_reviewer_case" in dynamic_test
