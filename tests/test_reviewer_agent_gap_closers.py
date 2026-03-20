import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path


def _load_reviewer_module(module_name: str = "reviewer_gap_under_test"):
    saved = {name: sys.modules.get(name) for name in (
        "config",
        "core.rag",
        "managers.browser_manager",
        "managers.code_manager",
        "managers.github_manager",
        "managers.security",
        "agent",
        "agent.base_agent",
        "agent.core",
        "agent.core.event_stream",
        "agent.roles",
    )}

    cfg_mod = types.ModuleType("config")

    class _Config:
        GITHUB_TOKEN = ""
        GITHUB_REPO = "acme/sidar"
        BASE_DIR = Path(".")
        DOCKER_PYTHON_IMAGE = "python:3.11-alpine"
        DOCKER_EXEC_TIMEOUT = 10
        REVIEWER_TEST_COMMAND = "pytest -q"
        RAG_DIR = Path("rag")
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 64
        RAG_CHUNK_OVERLAP = 8
        USE_GPU = False
        GPU_DEVICE = 0
        GPU_MIXED_PRECISION = False

    cfg_mod.Config = _Config

    rag_mod = types.ModuleType("core.rag")
    rag_mod.DocumentStore = type("DocumentStore", (), {})

    browser_mod = types.ModuleType("managers.browser_manager")

    class _BrowserManager:
        def __init__(self, _cfg):
            return None

        def collect_session_signals(self, *_args, **_kwargs):
            return {"status": "no-signal", "risk": "düşük", "summary": "Browser sinyali alınamadı."}

    browser_mod.BrowserManager = _BrowserManager

    code_mod = types.ModuleType("managers.code_manager")

    class _CodeManager:
        def __init__(self, *_args, **_kwargs):
            return None

        def lsp_semantic_audit(self, _paths=None):
            return True, {"status": "clean", "risk": "düşük", "decision": "APPROVE", "counts": {}, "issues": [], "summary": "LSP diagnostics temiz."}

        def write_file(self, *_args, **_kwargs):
            return True, "ok"

        def run_shell_in_sandbox(self, command, cwd=None):
            return True, f"sandbox:{command}:{cwd}"

    code_mod.CodeManager = _CodeManager

    github_mod = types.ModuleType("managers.github_manager")

    class _GitHubManager:
        def __init__(self, *_args, **_kwargs):
            return None

        def get_repo_info(self):
            return True, "repo"

        def list_pull_requests(self, state, limit):
            return True, f"prs:{state}:{limit}"

        def get_pull_request_diff(self, number):
            return True, f"diff:{number}"

        def list_issues(self, state, limit):
            return True, f"issues:{state}:{limit}"

    github_mod.GitHubManager = _GitHubManager

    security_mod = types.ModuleType("managers.security")
    security_mod.SecurityManager = lambda cfg=None: types.SimpleNamespace(cfg=cfg)

    event_stream_mod = types.ModuleType("agent.core.event_stream")

    class _Bus:
        async def publish(self, *_args, **_kwargs):
            return None

    event_stream_mod.get_agent_event_bus = lambda: _Bus()

    base_agent_mod = types.ModuleType("agent.base_agent")

    class _BaseAgent:
        def __init__(self, cfg=None, role_name="agent"):
            self.cfg = cfg or _Config()
            self.role_name = role_name
            self.tools = {}

        def register_tool(self, name, func):
            self.tools[name] = func

        async def call_tool(self, name, arg):
            return await self.tools[name](arg)

        async def call_llm(self, *_args, **_kwargs):
            return ""

        def delegate_to(self, target_agent, payload, reason=""):
            return types.SimpleNamespace(target_agent=target_agent, payload=payload, reason=reason)

    base_agent_mod.BaseAgent = _BaseAgent

    agent_pkg = types.ModuleType("agent")
    agent_pkg.__path__ = [str(Path("agent").resolve())]
    agent_core_pkg = types.ModuleType("agent.core")
    agent_core_pkg.__path__ = [str(Path("agent/core").resolve())]
    agent_roles_pkg = types.ModuleType("agent.roles")
    agent_roles_pkg.__path__ = [str(Path("agent/roles").resolve())]

    sys.modules.update(
        {
            "config": cfg_mod,
            "core.rag": rag_mod,
            "managers.browser_manager": browser_mod,
            "managers.code_manager": code_mod,
            "managers.github_manager": github_mod,
            "managers.security": security_mod,
            "agent": agent_pkg,
            "agent.base_agent": base_agent_mod,
            "agent.core": agent_core_pkg,
            "agent.core.event_stream": event_stream_mod,
            "agent.roles": agent_roles_pkg,
        }
    )

    try:
        spec = importlib.util.spec_from_file_location(module_name, Path("agent/roles/reviewer_agent.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name, old in saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old



def test_reviewer_dynamic_test_content_fail_closes_for_empty_and_malformed_llm_output(monkeypatch):
    mod = _load_reviewer_module("reviewer_gap_llm")
    agent = mod.ReviewerAgent()

    async def _empty_llm(*_args, **_kwargs):
        return ""

    monkeypatch.setattr(agent, "call_llm", _empty_llm)
    empty = asyncio.run(agent._build_dynamic_test_content("def add_two(x): return x + 2"))
    assert "fail_closed" in empty
    assert "pytest test fonksiyonu içermedi" in empty

    async def _malformed_llm(*_args, **_kwargs):
        return "Malformed JSON"

    monkeypatch.setattr(agent, "call_llm", _malformed_llm)
    malformed = asyncio.run(agent._build_dynamic_test_content("def add_two(x): return x + 2"))
    assert "fail_closed" in malformed
    assert "pytest test fonksiyonu içermedi" in malformed



def test_reviewer_graph_followup_and_summary_ignore_invalid_payload_shapes():
    mod = _load_reviewer_module("reviewer_gap_graph_payload")
    reviewer = mod.ReviewerAgent

    assert reviewer._collect_graph_followup_paths({"reports": "not-a-list"}) == []

    payload = {
        "reports": [
            None,
            {"target": "skip.py", "ok": False, "details": {"review_targets": ["skip.py"]}},
            {"target": "bad-details.py", "ok": True, "details": "broken"},
            {
                "target": "core/db.py",
                "ok": True,
                "details": {
                    "review_targets": "core/db.py",
                    "impacted_endpoint_handlers": ["web_server.py"],
                    "caller_files": ["README.md", "core/db.py"],
                    "direct_dependents": None,
                },
            },
        ]
    }
    assert reviewer._collect_graph_followup_paths(payload) == ["web_server.py", "core/db.py"]

    summary = reviewer._summarize_graph_payload(
        {
            "status": "ok",
            "summary": "GraphRAG üretildi.",
            "reports": [
                {"target": "core/db.py", "ok": True, "details": "broken"},
                {"target": "web_server.py", "ok": True, "details": {"risk_level": "low", "impacted_endpoints": ["endpoint:GET /status"]}},
            ],
        }
    )
    assert summary["risk"] == "düşük"
    assert "etkilenen endpoint=1" in summary["summary"]

    empty_lsp = reviewer._summarize_lsp_diagnostics("")
    assert empty_lsp["status"] == "clean"
    assert "çıktısı boş" in empty_lsp["summary"]

    malformed_lsp = reviewer._summarize_lsp_diagnostics("Malformed JSON")
    assert malformed_lsp["status"] == "clean"
    assert malformed_lsp["summary"] == "LSP diagnostics temiz."



def test_reviewer_review_code_falls_back_on_empty_lsp_and_malformed_graph_output_and_rejects_failed_browser(monkeypatch):
    mod = _load_reviewer_module("reviewer_gap_review_code")
    agent = mod.ReviewerAgent()

    async def _dynamic(_ctx: str) -> str:
        return "[TEST:OK] dynamic"

    async def _run_tests(arg: str) -> str:
        return f"[TEST:OK] {arg}"

    async def _lsp(_arg: str) -> str:
        return ""

    async def _graph(_arg: str) -> str:
        return "Malformed JSON"

    async def _browser(_arg: str) -> str:
        return json.dumps(
            {
                "status": "failed",
                "risk": "yüksek",
                "failed_actions": ["browser_click:#submit"],
                "summary": "Browser click başarısız.",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(agent, "_run_dynamic_tests", _dynamic)
    agent.tools["run_tests"] = _run_tests
    agent.tools["lsp_diagnostics"] = _lsp
    agent.tools["graph_impact"] = _graph
    agent.tools["browser_signals"] = _browser

    out = asyncio.run(agent.run_task("review_code|core/db.py"))
    payload = json.loads(out.payload.split("|", 1)[1])

    assert payload["decision"] == "REJECT"
    assert payload["risk"] == "yüksek"
    assert payload["graph_impact_report"]["status"] == "tool-error"
    assert payload["semantic_risk_report"]["summary"].startswith("LSP diagnostics çıktısı boş")
    assert payload["browser_signal_summary"]["status"] == "failed"
    assert payload["summary"].startswith("[REVIEW:FAIL]")


def test_reviewer_lsp_summary_special_cases_and_info_only_branch():
    mod = _load_reviewer_module("reviewer_gap_lsp_specials")
    reviewer = mod.ReviewerAgent

    clean = reviewer._summarize_lsp_diagnostics("LSP diagnostics temiz")
    assert clean["status"] == "clean"
    assert clean["decision"] == "APPROVE"

    no_signal = reviewer._summarize_lsp_diagnostics("LSP bildirimi dönmedi")
    assert no_signal["status"] == "no-signal"
    assert no_signal["risk"] == "orta"

    tool_error = reviewer._summarize_lsp_diagnostics("Araç hatası: timeout")
    assert tool_error["status"] == "tool-error"
    assert tool_error["summary"] == "LSP diagnostics çalıştırılırken araç hatası oluştu."

    info_only = reviewer._summarize_lsp_diagnostics(
        "- /workspace/Sidar/core/db.py: satır 1, sütun 1 | severity=3 | note\n"
        "- /workspace/Sidar/core/db.py: satır 2, sütun 1 | severity=4 | hint"
    )
    assert info_only["status"] == "info-only"
    assert info_only["counts"] == {3: 1, 4: 1}
    assert "yalnızca bilgilendirici 2 bulgu" in info_only["summary"]


def test_reviewer_combined_impact_and_fix_recommendations_ignore_invalid_issue_shapes():
    mod = _load_reviewer_module("reviewer_gap_invalid_shapes")
    reviewer = mod.ReviewerAgent

    combined = reviewer._build_combined_impact_report(
        {
            "counts": {"oops": 4, 1: 0},
            "issues": [
                "bad-item",
                {"path": "/workspace/Sidar/web_server.py", "severity": 1, "message": "broken import"},
            ],
        },
        {
            "risk": "düşük",
            "followup_paths": ["web_server.py"],
            "high_risk_targets": [],
        },
        ["core/db.py"],
        ["core/db.py", "web_server.py"],
    )
    assert combined["issue_paths"] == ["web_server.py"]
    assert combined["impact_level"] == "high"

    graph_only = reviewer._build_fix_recommendations(
        {
            "issues": [
                "bad-item",
                {"path": "", "message": "missing path"},
                {"path": "/workspace/Sidar/core/db.py", "message": "name is not defined"},
            ]
        },
        {
            "reports": [
                {"target": "bad-details.py", "ok": True, "details": "broken"},
                {
                    "target": "core/db.py",
                    "ok": True,
                    "details": {
                        "risk_level": "high",
                        "review_targets": "not-a-list",
                        "impacted_endpoint_handlers": ["web_server.py"],
                    },
                },
            ]
        },
        {"indirect_breakage_paths": []},
    )
    assert graph_only[0]["path"] == "web_server.py"
    assert graph_only[0]["reason"] == "graph"

    semantic_only = reviewer._build_fix_recommendations(
        {
            "issues": [
                "bad-item",
                {"path": "", "message": "missing path"},
                {"path": "/workspace/Sidar/core/db.py", "message": "name is not defined"},
            ]
        },
        {"reports": []},
        {"indirect_breakage_paths": []},
    )
    assert semantic_only[0]["path"] == "core/db.py"
    assert semantic_only[0]["reason"] == "semantic"


def test_reviewer_parse_payload_and_tool_paths_cover_empty_inline_and_passthrough(monkeypatch):
    mod = _load_reviewer_module("reviewer_gap_tools")
    agent = mod.ReviewerAgent()

    empty_payload = agent._parse_review_payload("")
    assert empty_payload["review_context"] == ""
    assert empty_payload["browser_include_dom"] is False

    graph_no_targets = json.loads(asyncio.run(agent._tool_graph_impact("")))
    assert graph_no_targets["status"] == "no-targets"
    assert graph_no_targets["targets"] == []

    inline_browser = json.loads(
        asyncio.run(
            agent._tool_browser_signals(
                json.dumps(
                    {
                        "review_context": "core/db.py",
                        "browser_signals": {"status": "failed", "risk": "yüksek", "summary": "inline"},
                    },
                    ensure_ascii=False,
                )
            )
        )
    )
    assert inline_browser["summary"] == "inline"

    collected = []

    def _collect_session_signals(session_id, *, include_dom=False, include_screenshot=False):
        collected.append((session_id, include_dom, include_screenshot))
        return {"status": "ok", "risk": "düşük", "summary": "collected"}

    monkeypatch.setattr(agent.browser, "collect_session_signals", _collect_session_signals)
    fetched_browser = json.loads(
        asyncio.run(
            agent._tool_browser_signals(
                json.dumps(
                    {
                        "review_context": "core/db.py",
                        "browser_session_id": "sess-99",
                        "browser_include_dom": True,
                        "browser_include_screenshot": True,
                    },
                    ensure_ascii=False,
                )
            )
        )
    )
    assert fetched_browser["summary"] == "collected"
    assert collected == [("sess-99", True, True)]

    seen = []

    async def _call_tool(name, arg):
        seen.append((name, arg))
        return f"{name}:{arg}"

    monkeypatch.setattr(agent, "call_tool", _call_tool)
    assert asyncio.run(agent.run_task("lsp_diagnostics")) == "lsp_diagnostics:"
    assert asyncio.run(agent.run_task("graph_impact")) == "graph_impact:"
    assert seen == [("lsp_diagnostics", ""), ("graph_impact", "")]


def test_reviewer_review_code_marks_medium_risk_for_semantic_warning_and_high_impact(monkeypatch):
    mod = _load_reviewer_module("reviewer_gap_risk_paths")

    async def _dynamic(_ctx: str) -> str:
        return "[TEST:OK] dynamic"

    async def _run_tests(arg: str) -> str:
        return f"[TEST:OK] {arg}"

    async def _graph_low(_arg: str) -> str:
        return json.dumps({"status": "ok", "risk": "düşük", "summary": "Graph clean.", "reports": []}, ensure_ascii=False)

    async def _graph_high_impact(_arg: str) -> str:
        return json.dumps(
            {
                "status": "ok",
                "risk": "düşük",
                "summary": "Graph followups.",
                "reports": [
                    {
                        "target": "core/db.py",
                        "ok": True,
                        "details": {
                            "risk_level": "high",
                            "review_targets": ["core/db.py", "web_server.py"],
                            "impacted_endpoint_handlers": ["web_server.py"],
                            "caller_files": [],
                            "direct_dependents": [],
                            "impacted_endpoints": ["endpoint:GET /status"],
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )

    async def _browser(_arg: str) -> str:
        return json.dumps({"status": "ok", "risk": "düşük", "summary": "Browser clean."}, ensure_ascii=False)

    agent_warning = mod.ReviewerAgent()
    monkeypatch.setattr(agent_warning, "_run_dynamic_tests", _dynamic)
    agent_warning.tools["run_tests"] = _run_tests
    agent_warning.tools["graph_impact"] = _graph_low
    agent_warning.tools["browser_signals"] = _browser
    agent_warning.tools["lsp_diagnostics"] = lambda _arg: asyncio.sleep(
        0,
        result=json.dumps(
            {
                "status": "issues-found",
                "risk": "orta",
                "decision": "APPROVE",
                "counts": {2: 1},
                "issues": [{"path": "/workspace/Sidar/core/db.py", "message": "warning"}],
                "summary": "LSP warning bulundu.",
            },
            ensure_ascii=False,
        ),
    )

    warning_out = asyncio.run(agent_warning.run_task("review_code|core/db.py"))
    warning_payload = json.loads(warning_out.payload.split("|", 1)[1])
    assert warning_payload["decision"] == "APPROVE"
    assert warning_payload["risk"] == "orta"

    agent_impact = mod.ReviewerAgent()
    monkeypatch.setattr(agent_impact, "_run_dynamic_tests", _dynamic)
    agent_impact.tools["run_tests"] = _run_tests
    agent_impact.tools["graph_impact"] = _graph_high_impact
    agent_impact.tools["browser_signals"] = _browser
    agent_impact.tools["lsp_diagnostics"] = lambda _arg: asyncio.sleep(
        0,
        result=json.dumps(
            {
                "status": "clean",
                "risk": "düşük",
                "decision": "APPROVE",
                "counts": {1: 1},
                "issues": [{"path": "/workspace/Sidar/web_server.py", "message": "error"}],
                "summary": "LSP bulgusu tek dosyada.",
            },
            ensure_ascii=False,
        ),
    )

    impact_out = asyncio.run(agent_impact.run_task("review_code|core/db.py"))
    impact_payload = json.loads(impact_out.payload.split("|", 1)[1])
    assert impact_payload["decision"] == "APPROVE"
    assert impact_payload["combined_impact_report"]["impact_level"] == "critical"
    assert impact_payload["risk"] == "orta"