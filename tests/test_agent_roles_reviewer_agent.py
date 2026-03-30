"""
agent/roles/reviewer_agent.py için birim testleri.
Statik/deterministik metotlar ve run_task yönlendirme mantığı test edilir.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_reviewer_deps():
    # agent package stub
    if "agent" not in sys.modules:
        pkg = types.ModuleType("agent"); pkg.__path__ = [str(_proj / "agent")]; pkg.__package__ = "agent"
        sys.modules["agent"] = pkg

    # agent.core stub
    if "agent.core" not in sys.modules:
        core = types.ModuleType("agent.core"); core.__path__ = [str(_proj / "agent" / "core")]; core.__package__ = "agent.core"
        sys.modules["agent.core"] = core
    else:
        c = sys.modules["agent.core"]
        if not hasattr(c, "__path__"): c.__path__ = [str(_proj / "agent" / "core")]

    # agent.core.contracts stub
    if "agent.core.contracts" not in sys.modules:
        from dataclasses import dataclass, field
        contracts = types.ModuleType("agent.core.contracts")
        @dataclass
        class DelegationRequest:
            task_id: str; reply_to: str; target_agent: str; payload: str
            intent: str = "mixed"; parent_task_id: str = None
            handoff_depth: int = 0; meta: dict = field(default_factory=dict)
        contracts.DelegationRequest = DelegationRequest
        contracts.is_delegation_request = lambda v: isinstance(v, DelegationRequest)
        sys.modules["agent.core.contracts"] = contracts

    # agent.core.event_stream stub
    if "agent.core.event_stream" not in sys.modules:
        es = types.ModuleType("agent.core.event_stream")
        _bus = MagicMock(); _bus.publish = AsyncMock()
        es.get_agent_event_bus = MagicMock(return_value=_bus)
        sys.modules["agent.core.event_stream"] = es

    # config stub
    if "config" not in sys.modules:
        cfg_mod = types.ModuleType("config")
        class _Config:
            AI_PROVIDER = "ollama"; OLLAMA_MODEL = "qwen2.5-coder:7b"
            BASE_DIR = "/tmp/sidar_test"; GITHUB_REPO = "owner/repo"; GITHUB_TOKEN = ""
            USE_GPU = False; GPU_DEVICE = 0; GPU_MIXED_PRECISION = False
            RAG_DIR = "/tmp/sidar_test/rag"; RAG_TOP_K = 3
            RAG_CHUNK_SIZE = 1000; RAG_CHUNK_OVERLAP = 200
            DOCKER_PYTHON_IMAGE = "python:3.11-alpine"; DOCKER_EXEC_TIMEOUT = 10
            REVIEWER_TEST_COMMAND = "pytest -q"
        cfg_mod.Config = _Config
        sys.modules["config"] = cfg_mod

    # core stubs — always replace so real modules don't interfere
    llm_stub = types.ModuleType("core.llm_client")
    mock_llm = MagicMock(); mock_llm.chat = AsyncMock(return_value='def test_foo(): pass')
    llm_stub.LLMClient = MagicMock(return_value=mock_llm)
    sys.modules["core.llm_client"] = llm_stub

    rag_stub = types.ModuleType("core.rag")
    mock_docs = MagicMock()
    mock_docs.search = MagicMock(return_value=(True, "sonuç"))
    mock_docs.graph_impact_details = MagicMock(return_value=(True, {}))
    mock_docs.analyze_graph_impact = MagicMock(return_value=(True, ""))
    rag_stub.DocumentStore = MagicMock(return_value=mock_docs)
    sys.modules["core.rag"] = rag_stub

    if "core" not in sys.modules:
        sys.modules["core"] = types.ModuleType("core")

    # managers stubs
    for mod, cls in [
        ("managers", None),
        ("managers.code_manager", "CodeManager"),
        ("managers.security", "SecurityManager"),
        ("managers.github_manager", "GitHubManager"),
        ("managers.browser_manager", "BrowserManager"),
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
        if cls:
            mock_inst = MagicMock()
            mock_inst.get_repo_info = MagicMock(return_value=(True, "repo bilgisi"))
            mock_inst.list_pull_requests = MagicMock(return_value=(True, "PR listesi"))
            mock_inst.get_pull_request_diff = MagicMock(return_value=(True, "diff"))
            mock_inst.list_issues = MagicMock(return_value=(True, "issue listesi"))
            mock_inst.run_shell_in_sandbox = MagicMock(return_value=(True, "test passed"))
            mock_inst.write_file = MagicMock(return_value=(True, "yazıldı"))
            mock_inst.lsp_semantic_audit = MagicMock(return_value=(True, {}))
            mock_inst.collect_session_signals = MagicMock(return_value={"status": "no-signal", "risk": "düşük", "summary": ""})
            sys.modules[mod].__dict__[cls] = MagicMock(return_value=mock_inst)

    # agent.base_agent stub
    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")
        contracts = sys.modules["agent.core.contracts"]
        class _BaseAgent:
            def __init__(self, *a, cfg=None, role_name="base", **kw):
                self.cfg = cfg or sys.modules["config"].Config()
                self.role_name = role_name
                self.llm = MagicMock(); self.llm.chat = AsyncMock(return_value='def test_foo(): pass')
                self.tools = {}
            def register_tool(self, name, fn): self.tools[name] = fn
            async def call_tool(self, name, arg):
                if name not in self.tools: return f"HATA: {name} bulunamadı"
                return await self.tools[name](arg)
            async def call_llm(self, msgs, system_prompt=None, temperature=0.7, json_mode=False, **kw):
                return 'def test_foo(): pass'
            def delegate_to(self, target, payload, task_id=None, reason=""):
                return contracts.DelegationRequest(task_id=task_id or f"{self.role_name}-task", reply_to=self.role_name, target_agent=target, payload=payload)
            @staticmethod
            def is_delegation_message(v): return contracts.is_delegation_request(v)
        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod


def _get_reviewer():
    _stub_reviewer_deps()
    sys.modules.pop("agent.roles.reviewer_agent", None)
    if "agent.roles" not in sys.modules:
        roles = types.ModuleType("agent.roles"); roles.__path__ = [str(_proj / "agent" / "roles")]
        sys.modules["agent.roles"] = roles
    import agent.roles.reviewer_agent as m
    return m


class TestReviewerAgentInit:
    def test_instantiation(self):
        assert _get_reviewer().ReviewerAgent() is not None

    def test_role_name(self):
        assert _get_reviewer().ReviewerAgent().role_name == "reviewer"

    def test_tools_registered(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        for tool in ("repo_info", "list_prs", "pr_diff", "list_issues",
                     "run_tests", "lsp_diagnostics", "graph_impact", "browser_signals"):
            assert tool in agent.tools, f"{tool} kayıtlı değil"


class TestExtractPythonCodeBlock:
    def test_no_fence_returns_as_is(self):
        m = _get_reviewer()
        code = "def test_foo(): pass"
        assert m.ReviewerAgent._extract_python_code_block(code) == code

    def test_python_fence_extracted(self):
        m = _get_reviewer()
        raw = "```python\ndef test_foo(): pass\n```"
        result = m.ReviewerAgent._extract_python_code_block(raw)
        assert "def test_foo" in result
        assert "```" not in result

    def test_generic_fence_extracted(self):
        m = _get_reviewer()
        raw = "```\ndef test_bar(): pass\n```"
        result = m.ReviewerAgent._extract_python_code_block(raw)
        assert "def test_bar" in result

    def test_empty_returns_empty(self):
        m = _get_reviewer()
        assert m.ReviewerAgent._extract_python_code_block("") == ""


class TestFailClosedTestContent:
    def test_contains_assert_error(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._fail_closed_test_content("test hatası")
        assert "def test_reviewer_dynamic_generation_fail_closed" in result
        assert "AssertionError" in result

    def test_contains_reason(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._fail_closed_test_content("özel hata mesajı")
        assert "özel hata mesajı" in result


class TestExtractChangedPaths:
    def test_extracts_py_files(self):
        m = _get_reviewer()
        context = "core/memory.py değiştirildi, tests/test_memory.py güncellendi"
        paths = m.ReviewerAgent._extract_changed_paths(context)
        assert any("memory.py" in p for p in paths)

    def test_extracts_multiple_extensions(self):
        m = _get_reviewer()
        context = "src/App.tsx, api/server.ts, config.json"
        paths = m.ReviewerAgent._extract_changed_paths(context)
        assert len(paths) >= 1

    def test_empty_context_returns_empty(self):
        m = _get_reviewer()
        assert m.ReviewerAgent._extract_changed_paths("") == []

    def test_no_duplicates(self):
        m = _get_reviewer()
        context = "core/memory.py core/memory.py core/memory.py"
        paths = m.ReviewerAgent._extract_changed_paths(context)
        assert paths.count("core/memory.py") == 1


class TestBuildLspCandidatePaths:
    def test_returns_only_supported_extensions(self):
        m = _get_reviewer()
        context = "core/memory.py main.js config.json README.md"
        paths = m.ReviewerAgent._build_lsp_candidate_paths(context)
        for p in paths:
            assert p.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))

    def test_json_not_included(self):
        m = _get_reviewer()
        context = "config.json data.json"
        paths = m.ReviewerAgent._build_lsp_candidate_paths(context)
        assert not any(p.endswith(".json") for p in paths)


class TestBuildGraphCandidatePaths:
    def test_limits_to_12(self):
        m = _get_reviewer()
        context = " ".join(f"module_{i}.py" for i in range(20))
        paths = m.ReviewerAgent._build_graph_candidate_paths(context)
        assert len(paths) <= 12


class TestMergeCandidatePaths:
    def test_merges_without_duplicates(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._merge_candidate_paths(
            ["a.py", "b.py"],
            ["b.py", "c.py"],
        )
        assert result == ["a.py", "b.py", "c.py"]

    def test_strips_leading_slashes(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._merge_candidate_paths(["./a.py", "/b.py"])
        assert "a.py" in result
        assert "b.py" in result


class TestSummarizeLspDiagnostics:
    def test_empty_returns_clean(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics("")
        assert result["status"] == "clean"
        assert result["decision"] == "APPROVE"


class TestReviewerAgentPromptVariations:
    @pytest.mark.parametrize(
        "prompt, expected_fragment",
        [
            ("repo_info", "repo bilgisi"),
            ("list_prs|open", "PR listesi"),
            ("pr_diff|12", "diff"),
            ("list_issues|open", "issue listesi"),
            ("run_tests|pytest -q", "test passed"),
        ],
    )
    def test_prompt_variants_route_to_expected_tools(self, prompt, expected_fragment):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        result = asyncio.run(agent.run_task(prompt))
        assert expected_fragment in result

    def test_graph_and_lsp_variants_return_structured_outputs(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        lsp_result = asyncio.run(agent.run_task("lsp_diagnostics|core/app.py"))
        graph_result = asyncio.run(agent.run_task("graph_impact|core/app.py"))
        assert lsp_result is not None
        assert graph_result is not None

    def test_errors_result_in_reject(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics(
            "file.py:1 severity=1 error: undefined variable"
        )
        assert result["decision"] == "REJECT"
        assert result["risk"] == "yüksek"

    def test_warnings_only_approve(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics(
            "file.py:1 severity=2 warning: unused variable"
        )
        assert result["decision"] == "APPROVE"

    def test_json_payload_parsed(self):
        m = _get_reviewer()
        payload = json.dumps({"status": "clean", "risk": "düşük", "decision": "APPROVE", "counts": {}, "summary": "temiz"})
        result = m.ReviewerAgent._summarize_lsp_diagnostics(payload)
        assert result["decision"] == "APPROVE"


class TestParseReviewPayload:
    def test_empty_returns_defaults(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._parse_review_payload("")
        assert result["review_context"] == ""
        assert result["browser_session_id"] == ""

    def test_plain_text_as_context(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._parse_review_payload("kod değişikliği var")
        assert "kod değişikliği var" in result["review_context"]

    def test_json_payload_parsed(self):
        m = _get_reviewer()
        payload = json.dumps({"review_context": "def foo(): pass"})
        result = m.ReviewerAgent._parse_review_payload(payload)
        assert "def foo" in result["review_context"]

    def test_browser_session_id_extracted(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._parse_review_payload("kod browser_session_id=sess-123 değişikliği")
        assert result["browser_session_id"] == "sess-123"


class TestCollectGraphFollowupPaths:
    def test_empty_reports_returns_empty(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._collect_graph_followup_paths({})
        assert result == []

    def test_extracts_paths_from_reports(self):
        m = _get_reviewer()
        payload = {
            "reports": [
                {
                    "ok": True,
                    "details": {"review_targets": ["core/memory.py", "core/rag.py"]},
                }
            ]
        }
        result = m.ReviewerAgent._collect_graph_followup_paths(payload)
        assert "core/memory.py" in result


class TestSummarizeGraphPayload:
    def test_no_ok_reports_returns_no_signal(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_graph_payload({})
        assert result["status"] == "no-signal"

    def test_ok_reports_produces_summary(self):
        m = _get_reviewer()
        payload = {
            "status": "ok",
            "reports": [
                {"ok": True, "target": "core/memory.py", "details": {"risk_level": "low", "impacted_endpoints": []}}
            ]
        }
        result = m.ReviewerAgent._summarize_graph_payload(payload)
        assert "summary" in result


class TestReviewerAgentRunTask:
    @pytest.mark.asyncio
    async def test_empty_prompt_returns_warning(self):
        m = _get_reviewer()
        result = await m.ReviewerAgent().run_task("")
        assert "UYARI" in result

    @pytest.mark.asyncio
    async def test_repo_info_routing(self):
        m = _get_reviewer()
        result = await m.ReviewerAgent().run_task("repo_info")
        assert result is not None

    @pytest.mark.asyncio
    async def test_list_prs_routing(self):
        m = _get_reviewer()
        result = await m.ReviewerAgent().run_task("list_prs|open")
        assert result is not None

    @pytest.mark.asyncio
    async def test_pr_diff_routing(self):
        m = _get_reviewer()
        result = await m.ReviewerAgent().run_task("pr_diff|5")
        assert result is not None

    @pytest.mark.asyncio
    async def test_list_issues_routing(self):
        m = _get_reviewer()
        result = await m.ReviewerAgent().run_task("list_issues|open")
        assert result is not None

    @pytest.mark.asyncio
    async def test_review_code_returns_delegation(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        contracts = sys.modules["agent.core.contracts"]
        result = await agent.run_task("review_code|def hello(): pass")
        assert contracts.is_delegation_request(result)
        assert result.target_agent == "coder"
        assert "qa_feedback" in result.payload

    def test_review_code_rejects_when_dynamic_tests_fail_closed(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        contracts = sys.modules["agent.core.contracts"]

        agent._run_dynamic_tests = AsyncMock(return_value="[TEST:FAIL-CLOSED] dynamic test derlenemedi")
        agent._build_regression_commands = MagicMock(return_value=["pytest -q tests/test_dummy.py"])

        async def _fake_call_tool(name, arg):
            if name == "run_tests":
                return "[TEST:PASS] pytest -q tests/test_dummy.py"
            if name == "graph_impact":
                return json.dumps({"status": "ok", "reports": []}, ensure_ascii=False)
            if name == "browser_signals":
                return json.dumps({"status": "ok", "risk": "düşük", "summary": "clean"}, ensure_ascii=False)
            if name == "lsp_diagnostics":
                return json.dumps(
                    {"status": "clean", "risk": "düşük", "decision": "APPROVE", "counts": {}, "summary": "temiz"},
                    ensure_ascii=False,
                )
            return ""

        agent.call_tool = AsyncMock(side_effect=_fake_call_tool)
        async def _run_case():
            result = await agent.run_task("review_code|def broken():")
            assert contracts.is_delegation_request(result)

            payload = result.payload.split("qa_feedback|", 1)[1]
            parsed = json.loads(payload)
            assert parsed["decision"] == "REJECT"
            assert parsed["risk"] == "yüksek"

        asyncio.run(_run_case())
