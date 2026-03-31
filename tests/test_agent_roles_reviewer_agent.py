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

    # agent.core.contracts stub (always replace to avoid cross-test pollution)
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

    # config stub (always replace to avoid polluted Config instances)
    cfg_mod = types.ModuleType("config")
    class _Config:
        AI_PROVIDER = "ollama"; OLLAMA_MODEL = "qwen2.5-coder:7b"
        BASE_DIR = "/tmp/sidar_test"; GITHUB_REPO = "dummy/repo"; GITHUB_TOKEN = "dummy_token"
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

    # agent.base_agent stub (always replace so delegate/contract shape is stable)
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
            return contracts.DelegationRequest(
                task_id=task_id or f"{self.role_name}-task",
                reply_to=self.role_name,
                target_agent=target,
                payload=payload,
            )

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

    def test_no_signal_phrase_maps_to_approve_with_medium_risk(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics("LSP bildirimi dönmedi")
        assert result["status"] == "no-signal"
        assert result["decision"] == "APPROVE"
        assert result["risk"] == "orta"

    def test_tool_error_phrase_maps_to_tool_error_status(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics("lsp hatası: timeout")
        assert result["status"] == "tool-error"
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

    def test_json_payload_supports_alternative_context_key_and_flags(self):
        m = _get_reviewer()
        payload = json.dumps(
            {
                "code_context": "def alt_context(): pass",
                "browser_include_dom": True,
                "browser_include_screenshot": True,
            }
        )
        result = m.ReviewerAgent._parse_review_payload(payload)
        assert "alt_context" in result["review_context"]
        assert result["browser_include_dom"] is True
        assert result["browser_include_screenshot"] is True


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


class TestCombinedImpactAndRemediation:
    def test_combined_impact_marks_critical_for_indirect_severity_one(self):
        m = _get_reviewer()
        semantic_report = {
            "counts": {"1": 1},
            "issues": [{"path": "/workspace/Sidar/core/rag.py", "message": "critical type error"}],
        }
        graph_summary = {"followup_paths": ["core/rag.py"], "risk": "orta", "high_risk_targets": ["core/rag.py"]}

        result = m.ReviewerAgent._build_combined_impact_report(
            semantic_report=semantic_report,
            graph_summary=graph_summary,
            direct_scope_paths=["core/db.py"],
            lsp_scope_paths=[],
        )

        assert result["impact_level"] == "critical"
        assert "core/rag.py" in result["indirect_breakage_paths"]

    def test_remediation_loop_observe_only_when_no_findings(self):
        m = _get_reviewer()
        loop = m.ReviewerAgent._build_remediation_loop(
            semantic_report={"counts": {}, "summary": "clean"},
            graph_summary={"risk": "düşük", "summary": "no signal"},
            combined_impact={
                "impact_level": "low",
                "direct_scope_paths": [],
                "graph_followup_paths": [],
                "issue_paths": [],
                "indirect_breakage_paths": [],
            },
            fix_recommendations=[],
            regression_commands=["pytest tests/test_smoke.py"],
        )

        assert loop["status"] == "observe_only"
        assert loop["needs_human_approval"] is False
        assert "python -m pytest" in loop["validation_commands"]


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


class TestReviewerAgentToolEdgeCases:
    def test_tool_pr_diff_requires_numeric_id(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        result = asyncio.run(agent._tool_pr_diff("not-a-number"))
        assert "Kullanım" in result

    def test_tool_run_tests_rejects_unsafe_prefix(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        result = asyncio.run(agent._tool_run_tests("rm -rf /"))
        assert "Kullanım" in result

    def test_tool_graph_impact_returns_no_targets_when_empty(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        raw = asyncio.run(agent._tool_graph_impact(""))
        payload = json.loads(raw)
        assert payload["status"] == "no-targets"
        assert payload["targets"] == []

    def test_tool_browser_signals_returns_inline_payload_directly(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        raw = asyncio.run(
            agent._tool_browser_signals(
                json.dumps({"browser_signals": {"status": "ok", "risk": "düşük", "summary": "inline"}})
            )
        )
        payload = json.loads(raw)
        assert payload["status"] == "ok"
        assert payload["summary"] == "inline"

class TestReviewerAgentRunTask:
    def test_empty_prompt_returns_warning(self):
        async def _run():
            m = _get_reviewer()
            result = await m.ReviewerAgent().run_task("")
            assert "UYARI" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_repo_info_routing(self):
        async def _run():
            m = _get_reviewer()
            result = await m.ReviewerAgent().run_task("repo_info")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_list_prs_routing(self):
        async def _run():
            m = _get_reviewer()
            result = await m.ReviewerAgent().run_task("list_prs|open")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_pr_diff_routing(self):
        async def _run():
            m = _get_reviewer()
            result = await m.ReviewerAgent().run_task("pr_diff|5")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_list_issues_routing(self):
        async def _run():
            m = _get_reviewer()
            result = await m.ReviewerAgent().run_task("list_issues|open")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_review_code_returns_delegation(self):
        async def _run():
            m = _get_reviewer()
            agent = m.ReviewerAgent()
            contracts = sys.modules["agent.core.contracts"]
            result = await agent.run_task("review_code|def hello(): pass")
            assert contracts.is_delegation_request(result)
            assert result.target_agent == "coder"
            assert "qa_feedback" in result.payload
        import asyncio as _asyncio
        _asyncio.run(_run())

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

    def test_review_code_handles_malformed_tool_outputs_with_safe_fallbacks(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        contracts = sys.modules["agent.core.contracts"]

        agent._run_dynamic_tests = AsyncMock(return_value="[TEST:PASS] dynamic")
        agent._build_regression_commands = MagicMock(return_value=["pytest -q tests/test_dummy.py"])

        async def _fake_call_tool(name, arg):
            if name == "run_tests":
                return "[TEST:PASS] pytest -q tests/test_dummy.py"
            if name == "graph_impact":
                return "{broken-json"
            if name == "browser_signals":
                return "{broken-json"
            if name == "lsp_diagnostics":
                return "unexpected plain text"
            return ""

        agent.call_tool = AsyncMock(side_effect=_fake_call_tool)

        async def _run_case():
            result = await agent.run_task("review_code|def ok(): pass")
            assert contracts.is_delegation_request(result)
            payload = result.payload.split("qa_feedback|", 1)[1]
            parsed = json.loads(payload)
            assert parsed["decision"] in {"APPROVE", "REJECT"}
            assert "combined_impact_report" in parsed
            assert "browser_signal_summary" in parsed

        asyncio.run(_run_case())

class TestReviewerAgentFallbacks:
    def test_unknown_prompt_uses_default_list_prs_fallback(self):
        async def _run():
            m = _get_reviewer()
            agent = m.ReviewerAgent()
            result = await agent.run_task("tamamen alakasız bir istek")
            assert "PR listesi" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestReviewerDecisionSignals:
    def test_summarize_lsp_diagnostics_rejects_on_error_severity(self):
        m = _get_reviewer()
        output = "core/foo.py:12 severity=1 message=Syntax error"
        summary = m.ReviewerAgent._summarize_lsp_diagnostics(output)
        assert summary["decision"] == "REJECT"
        assert summary["risk"] == "yüksek"

    def test_summarize_lsp_diagnostics_approves_clean_text(self):
        m = _get_reviewer()
        summary = m.ReviewerAgent._summarize_lsp_diagnostics("LSP temiz")
        assert summary["decision"] == "APPROVE"
        assert summary["status"] == "clean"


class TestReviewerLargeAndBrokenCodeBlocks:
    def test_build_dynamic_test_content_returns_fail_closed_for_large_non_test_output(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        # LLM büyük ama geçersiz (pytest test fonksiyonu yok) bir metin döndürsün.
        agent.call_llm = AsyncMock(return_value=("```python\n" + ("x = 1\n" * 5000) + "```"))

        async def _run_case():
            out = await agent._build_dynamic_test_content("def foo():\n    pass\n")
            assert "fail_closed" in out
            assert "pytest test fonksiyonu içermedi" in out
            agent.call_llm.assert_awaited_once()

        asyncio.run(_run_case())

    def test_review_code_with_large_syntax_broken_context_finishes_without_loop(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        contracts = sys.modules["agent.core.contracts"]

        broken_large_context = "def broken(:\n" + ("print('x')\n" * 4000)
        agent._run_dynamic_tests = AsyncMock(return_value="[TEST:FAIL-CLOSED] syntax error in generated test")
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
            result = await agent.run_task(f"review_code|{broken_large_context}")
            assert contracts.is_delegation_request(result)
            agent._run_dynamic_tests.assert_awaited_once()

            payload = result.payload.split("qa_feedback|", 1)[1]
            parsed = json.loads(payload)
            assert parsed["decision"] == "REJECT"
            assert parsed["risk"] == "yüksek"

        asyncio.run(_run_case())

    def test_run_dynamic_tests_cleans_temp_file_when_run_tests_tool_crashes(self, tmp_path):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        agent.config.BASE_DIR = str(tmp_path)
        agent._build_dynamic_test_content = AsyncMock(return_value="def test_ok():\n    assert True\n")
        agent.code.write_file = MagicMock(return_value=(True, "ok"))
        agent.call_tool = AsyncMock(side_effect=RuntimeError("sandbox runner crashed"))

        async def _run_case():
            with pytest.raises(RuntimeError, match="sandbox runner crashed"):
                await agent._run_dynamic_tests("def foo():\n    pass\n")

            temp_files = list((tmp_path / "temp").glob("reviewer_dynamic_*.py"))
            assert temp_files == []

        asyncio.run(_run_case())

    def test_build_dynamic_test_content_fail_closed_when_llm_api_crashes(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        agent.call_llm = AsyncMock(side_effect=RuntimeError("api down"))

        async def _run_case():
            out = await agent._build_dynamic_test_content("def ok():\n    return True\n")
            assert "fail_closed" in out
            assert "başarısız oldu" in out

        asyncio.run(_run_case())

    def test_review_code_approves_when_no_quality_or_semantic_issue_found(self):
        m = _get_reviewer()
        agent = m.ReviewerAgent()
        contracts = sys.modules["agent.core.contracts"]

        agent._run_dynamic_tests = AsyncMock(return_value="[TEST:PASS] dynamic")
        agent._build_regression_commands = MagicMock(return_value=["pytest -q tests/test_dummy.py"])

        async def _fake_call_tool(name, arg):
            if name == "run_tests":
                return "[TEST:PASS] pytest -q tests/test_dummy.py"
            if name == "graph_impact":
                return json.dumps({"status": "ok", "reports": []}, ensure_ascii=False)
            if name == "browser_signals":
                return json.dumps({"status": "ok", "risk": "düşük", "summary": "Browser temiz."}, ensure_ascii=False)
            if name == "lsp_diagnostics":
                return json.dumps(
                    {"status": "clean", "risk": "düşük", "decision": "APPROVE", "counts": {}, "summary": "LSP temiz."},
                    ensure_ascii=False,
                )
            return ""

        agent.call_tool = AsyncMock(side_effect=_fake_call_tool)

        async def _run_case():
            result = await agent.run_task("review_code|def healthy():\n    return 1")
            assert contracts.is_delegation_request(result)
            payload = result.payload.split("qa_feedback|", 1)[1]
            parsed = json.loads(payload)
            assert parsed["decision"] == "APPROVE"
            assert parsed["risk"] == "düşük"

        asyncio.run(_run_case())

# ===== MERGED FROM tests/test_agent_roles_reviewer_agent_extra.py =====

import asyncio
import json
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_reviewer_deps():
    if "agent" not in sys.modules:
        pkg = types.ModuleType("agent")
        pkg.__path__ = [str(_proj / "agent")]
        pkg.__package__ = "agent"
        sys.modules["agent"] = pkg

    if "agent.core" not in sys.modules:
        core = types.ModuleType("agent.core")
        core.__path__ = [str(_proj / "agent" / "core")]
        core.__package__ = "agent.core"
        sys.modules["agent.core"] = core
    else:
        c = sys.modules["agent.core"]
        if not hasattr(c, "__path__"):
            c.__path__ = [str(_proj / "agent" / "core")]

    if "agent.core.contracts" not in sys.modules:
        from dataclasses import dataclass, field
        contracts = types.ModuleType("agent.core.contracts")

        @dataclass
        class DelegationRequest:
            task_id: str
            reply_to: str
            target_agent: str
            payload: str
            intent: str = "mixed"
            parent_task_id: str = None
            handoff_depth: int = 0
            meta: dict = field(default_factory=dict)

        contracts.DelegationRequest = DelegationRequest
        contracts.is_delegation_request = lambda v: isinstance(v, DelegationRequest)
        sys.modules["agent.core.contracts"] = contracts

    if "agent.core.event_stream" not in sys.modules:
        es = types.ModuleType("agent.core.event_stream")
        _bus = MagicMock()
        _bus.publish = AsyncMock()
        es.get_agent_event_bus = MagicMock(return_value=_bus)
        sys.modules["agent.core.event_stream"] = es

    # config stub (always replace to avoid polluted Config instances)
    cfg_mod = types.ModuleType("config")

    class _Config:
        AI_PROVIDER = "ollama"
        OLLAMA_MODEL = "qwen2.5-coder:7b"
        BASE_DIR = "/tmp/sidar_test"
        GITHUB_REPO = "dummy/repo"
        GITHUB_TOKEN = "dummy_token"
        USE_GPU = False
        GPU_DEVICE = 0
        GPU_MIXED_PRECISION = False
        RAG_DIR = "/tmp/sidar_test/rag"
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 1000
        RAG_CHUNK_OVERLAP = 200
        DOCKER_PYTHON_IMAGE = "python:3.11-alpine"
        DOCKER_EXEC_TIMEOUT = 10
        REVIEWER_TEST_COMMAND = "pytest -q"

    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod

    # core stubs
    llm_stub = types.ModuleType("core.llm_client")
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value="def test_foo(): pass")
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
            mock_inst.collect_session_signals = MagicMock(
                return_value={"status": "no-signal", "risk": "düşük", "summary": ""}
            )
            sys.modules[mod].__dict__[cls] = MagicMock(return_value=mock_inst)

    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")
        contracts = sys.modules["agent.core.contracts"]

        class _BaseAgent:
            def __init__(self, *a, cfg=None, role_name="base", **kw):
                self.cfg = cfg or sys.modules["config"].Config()
                self.role_name = role_name
                self.llm = MagicMock()
                self.llm.chat = AsyncMock(return_value="def test_foo(): pass")
                self.tools = {}

            def register_tool(self, name, fn):
                self.tools[name] = fn

            async def call_tool(self, name, arg):
                if name not in self.tools:
                    return f"HATA: {name} bulunamadı"
                return await self.tools[name](arg)

            async def call_llm(self, msgs, system_prompt=None, temperature=0.7, json_mode=False, **kw):
                return "def test_foo(): pass"

            def delegate_to(self, target, payload, task_id=None, reason=""):
                return contracts.DelegationRequest(
                    task_id=task_id or f"{self.role_name}-task",
                    reply_to=self.role_name,
                    target_agent=target,
                    payload=payload,
                )

            @staticmethod
            def is_delegation_message(v):
                return contracts.is_delegation_request(v)

        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod


def _get_reviewer():
    _stub_reviewer_deps()
    sys.modules.pop("agent.roles.reviewer_agent", None)
    if "agent.roles" not in sys.modules:
        roles = types.ModuleType("agent.roles")
        roles.__path__ = [str(_proj / "agent" / "roles")]
        sys.modules["agent.roles"] = roles
    import agent.roles.reviewer_agent as m
    return m


# ─────────────────────────────────────────────────────────────────────────────
# _build_dynamic_test_content
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestBuildDynamicTestContent:
    def test_empty_context_returns_fail_closed(self):
        async def _run(self_ref=self):
            """Boş bağlam fail-closed test döndürmeli (L85-86)."""
            m = _get_reviewer()
            agent = m.ReviewerAgent()
            result = await agent._build_dynamic_test_content("")
            assert "def test_reviewer_dynamic_generation_fail_closed" in result
            assert "AssertionError" in result

        def test_llm_exception_returns_fail_closed(self):
            async def _run():
                """LLM exception fırlatırsa fail-closed test döndürmeli (L104-107)."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                agent.call_llm = AsyncMock(side_effect=RuntimeError("LLM çöktü"))
                result = await agent._build_dynamic_test_content("def foo(): pass")
                assert "def test_reviewer_dynamic_generation_fail_closed" in result
                assert "LLM" in result or "başarısız" in result
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_llm_output_without_test_fn_returns_fail_closed(self):
            async def _run():
                """LLM çıktısı test fonksiyonu içermiyorsa fail-closed döndürmeli (L110-113)."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                agent.call_llm = AsyncMock(return_value="x = 1 + 1")
                result = await agent._build_dynamic_test_content("some code context")
                assert "def test_reviewer_dynamic_generation_fail_closed" in result
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_valid_llm_output_returned_as_is(self):
            async def _run():
                """Geçerli test kodu döndürülmeli (L114)."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                agent.call_llm = AsyncMock(return_value="def test_my_func():\n    assert 1 == 1\n")
                result = await agent._build_dynamic_test_content("my function code")
                assert "def test_my_func" in result
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_llm_output_with_fenced_code_block(self):
            async def _run():
                """Fenced code block'tan test kodu çıkarılmalı."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                agent.call_llm = AsyncMock(
                    return_value="```python\ndef test_extracted():\n    assert True\n```"
                )
                result = await agent._build_dynamic_test_content("context")
                assert "def test_extracted" in result
                assert "```" not in result
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ─────────────────────────────────────────────────────────────────────────────
    # _run_dynamic_tests: write_file başarısız yolu
    # ─────────────────────────────────────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestRunDynamicTests:
    def test_write_file_failure_returns_fail_closed(self):
        async def _run(self_ref=self):
            """write_file başarısız olursa FAIL-CLOSED döndürmeli (L122-126)."""
            m = _get_reviewer()
            agent = m.ReviewerAgent()
            agent._build_dynamic_test_content = AsyncMock(return_value="def test_foo(): pass\n")
            agent.code.write_file = MagicMock(return_value=(False, "yazma hatası"))

            result = await agent._run_dynamic_tests("kod bağlamı")
            assert "FAIL-CLOSED" in result
            assert "yazma hatası" in result

        def test_write_success_calls_run_tests(self):
            async def _run():
                """write_file başarılıysa run_tests tool çağrılmalı (L128-130)."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                agent._build_dynamic_test_content = AsyncMock(return_value="def test_foo(): pass\n")
                agent.code.write_file = MagicMock(return_value=(True, "yazıldı"))
                agent.call_tool = AsyncMock(return_value="[TEST:OK]")

                result = await agent._run_dynamic_tests("kod bağlamı")
                assert result == "[TEST:OK]"
                agent.call_tool.assert_awaited_once()
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ─────────────────────────────────────────────────────────────────────────────
    # _collect_graph_followup_paths
    # ─────────────────────────────────────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestCollectGraphFollowupPaths:
    def test_empty_graph_payload_returns_empty(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._collect_graph_followup_paths({})
        assert result == []

    def test_non_dict_payload_returns_empty(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._collect_graph_followup_paths("not a dict")
        assert result == []

    def test_ok_false_reports_skipped(self):
        m = _get_reviewer()
        payload = {"reports": [{"ok": False, "details": {"review_targets": ["a.py"]}}]}
        result = m.ReviewerAgent._collect_graph_followup_paths(payload)
        assert result == []

    def test_collects_paths_from_ok_reports(self):
        m = _get_reviewer()
        payload = {
            "reports": [
                {
                    "ok": True,
                    "details": {
                        "review_targets": ["core/agent.py"],
                        "caller_files": ["tests/test_agent.py"],
                    },
                }
            ]
        }
        result = m.ReviewerAgent._collect_graph_followup_paths(payload)
        assert "core/agent.py" in result
        assert "tests/test_agent.py" in result

    def test_non_supported_extension_excluded(self):
        m = _get_reviewer()
        payload = {
            "reports": [
                {"ok": True, "details": {"review_targets": ["config.json", "module.py"]}}
            ]
        }
        result = m.ReviewerAgent._collect_graph_followup_paths(payload)
        assert "config.json" not in result
        assert "module.py" in result


# ─────────────────────────────────────────────────────────────────────────────
# _summarize_graph_payload
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestSummarizeGraphPayload:
    def test_empty_payload_returns_no_signal(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_graph_payload({})
        assert result["status"] == "no-signal"
        assert result["risk"] == "düşük"

    def test_high_risk_target_sets_orta(self):
        m = _get_reviewer()
        payload = {
            "status": "ok",
            "reports": [
                {
                    "ok": True,
                    "target": "agent/core.py",
                    "details": {"risk_level": "high", "impacted_endpoints": ["ep1"]},
                }
            ],
        }
        result = m.ReviewerAgent._summarize_graph_payload(payload)
        assert result["risk"] == "orta"
        assert "agent/core.py" in result["high_risk_targets"]

    def test_no_high_risk_stays_dusuk(self):
        m = _get_reviewer()
        payload = {
            "status": "ok",
            "reports": [
                {"ok": True, "target": "utils.py", "details": {"risk_level": "low"}},
            ],
        }
        result = m.ReviewerAgent._summarize_graph_payload(payload)
        assert result["risk"] == "düşük"


# ─────────────────────────────────────────────────────────────────────────────
# _summarize_lsp_diagnostics: ek yollar
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestSummarizeLspDiagnosticsExtra:
    def test_json_with_summary_parsed_directly(self):
        """JSON payload summary alanı varsa doğrudan parse edilmeli (L268-278)."""
        m = _get_reviewer()
        payload = json.dumps({
            "status": "issues-found",
            "risk": "yüksek",
            "decision": "REJECT",
            "counts": {"1": 2},
            "summary": "Hata bulundu.",
            "issues": [],
        })
        result = m.ReviewerAgent._summarize_lsp_diagnostics(payload)
        assert result["decision"] == "REJECT"
        assert result["summary"] == "Hata bulundu."

    def test_temiz_keyword_returns_clean(self):
        """'temiz' içeren çıktı clean döndürmeli (L281-288)."""
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics("Workspace temiz durumda.")
        assert result["status"] == "clean"

    def test_bildirimi_donmedi_returns_no_signal(self):
        """'bildirimi dönmedi' içeren çıktı no-signal döndürmeli (L289-296)."""
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics("LSP bildirimi dönmedi")
        assert result["status"] == "no-signal"

    def test_hatasi_keyword_returns_tool_error(self):
        """'hatası:' içeren çıktı tool-error döndürmeli (L297-304)."""
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics("LSP çalıştırılırken hatası: timeout")
        assert result["status"] == "tool-error"

    def test_warnings_only_sets_orta_risk(self):
        """Yalnızca warning (severity=2) orta risk olmalı (L318-320)."""
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics(
            "file.py:10 severity=2 warning: unused variable"
        )
        assert result["risk"] == "orta"
        assert result["decision"] == "APPROVE"

    def test_info_only_sets_info_only_status(self):
        """Sadece info/hint (severity=3/4) info-only olmalı (L326-330)."""
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_lsp_diagnostics(
            "file.py:5 severity=3 hint: consider refactoring"
        )
        assert result["status"] == "info-only"


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_issue_path
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestNormalizeIssuePath:
    def test_strips_workspace_prefix(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._normalize_issue_path("/workspace/Sidar/core/agent.py")
        assert result == "core/agent.py"

    def test_strips_leading_dot_slash(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._normalize_issue_path("./core/agent.py")
        assert result == "core/agent.py"

    def test_normalizes_backslash(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._normalize_issue_path("core\\agent.py")
        assert result == "core/agent.py"

    def test_none_returns_empty(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._normalize_issue_path(None)
        assert result == ""


# ─────────────────────────────────────────────────────────────────────────────
# _build_combined_impact_report
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestBuildCombinedImpactReport:
    def test_no_signals_returns_low_impact(self):
        m = _get_reviewer()
        semantic = {"counts": {}, "issues": []}
        graph = {"risk": "düşük", "followup_paths": [], "high_risk_targets": []}
        result = m.ReviewerAgent._build_combined_impact_report(semantic, graph, [], [])
        assert result["impact_level"] == "low"

    def test_issue_paths_gives_medium_impact(self):
        m = _get_reviewer()
        semantic = {
            "counts": {},
            "issues": [{"path": "/workspace/Sidar/core/agent.py", "message": "error"}],
        }
        graph = {"risk": "düşük", "followup_paths": [], "high_risk_targets": []}
        result = m.ReviewerAgent._build_combined_impact_report(semantic, graph, [], [])
        assert result["impact_level"] == "medium"

    def test_orta_graph_risk_gives_high_impact(self):
        m = _get_reviewer()
        semantic = {"counts": {}, "issues": []}
        graph = {"risk": "orta", "followup_paths": [], "high_risk_targets": []}
        result = m.ReviewerAgent._build_combined_impact_report(semantic, graph, [], [])
        assert result["impact_level"] in {"high", "medium"}


# ─────────────────────────────────────────────────────────────────────────────
# _build_fix_recommendations
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestBuildFixRecommendations:
    def test_empty_inputs_returns_empty(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._build_fix_recommendations({}, {}, {"indirect_breakage_paths": []})
        assert result == []

    def test_semantic_issues_creates_recommendations(self):
        m = _get_reviewer()
        semantic = {
            "issues": [
                {"path": "/workspace/Sidar/core/agent.py", "message": "undefined var"},
            ]
        }
        graph = {"reports": []}
        combined = {"indirect_breakage_paths": []}
        result = m.ReviewerAgent._build_fix_recommendations(semantic, graph, combined)
        assert len(result) > 0
        assert result[0]["reason"] == "semantic"

    def test_indirect_breakage_paths_creates_graph_semantic_rec(self):
        m = _get_reviewer()
        semantic = {
            "issues": [
                {"path": "/workspace/Sidar/core/agent.py", "message": "type error"},
            ]
        }
        graph = {
            "reports": [
                {
                    "ok": True,
                    "target": "core/agent.py",
                    "details": {"review_targets": ["core/agent.py"], "impacted_endpoints": ["ep1"]},
                }
            ]
        }
        combined = {"indirect_breakage_paths": ["core/agent.py"]}
        result = m.ReviewerAgent._build_fix_recommendations(semantic, graph, combined)
        assert any(r["reason"] == "graph+semantic" for r in result)


# ─────────────────────────────────────────────────────────────────────────────
# _parse_review_payload
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestParseReviewPayload:
    def test_empty_returns_defaults(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._parse_review_payload("")
        assert result["review_context"] == ""
        assert result["browser_session_id"] == ""

    def test_json_payload_with_review_context(self):
        m = _get_reviewer()
        payload = json.dumps({"review_context": "def foo(): pass", "browser_session_id": "sess-123"})
        result = m.ReviewerAgent._parse_review_payload(payload)
        assert result["review_context"] == "def foo(): pass"
        assert result["browser_session_id"] == "sess-123"

    def test_plain_text_with_browser_session_id(self):
        m = _get_reviewer()
        text = "diff context browser_session_id=abc123"
        result = m.ReviewerAgent._parse_review_payload(text)
        assert result["browser_session_id"] == "abc123"
        assert "browser_session_id=abc123" not in result["review_context"]

    def test_plain_text_without_session_id(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._parse_review_payload("some plain code diff")
        assert result["review_context"] == "some plain code diff"
        assert result["browser_session_id"] == ""

    def test_json_with_code_context_fallback(self):
        m = _get_reviewer()
        payload = json.dumps({"code_context": "class MyClass: pass"})
        result = m.ReviewerAgent._parse_review_payload(payload)
        assert result["review_context"] == "class MyClass: pass"


# ─────────────────────────────────────────────────────────────────────────────
# _summarize_browser_signals
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestSummarizeBrowserSignals:
    def test_none_returns_no_signal(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._summarize_browser_signals(None)
        assert result["status"] == "no-signal"

    def test_failed_status_propagated(self):
        m = _get_reviewer()
        payload = {"status": "failed", "risk": "yüksek", "failed_actions": ["click btn"]}
        result = m.ReviewerAgent._summarize_browser_signals(payload)
        assert result["status"] == "failed"
        assert "click btn" in result["failed_actions"]

    def test_limits_actions_to_8(self):
        m = _get_reviewer()
        payload = {"failed_actions": [f"action_{i}" for i in range(20)]}
        result = m.ReviewerAgent._summarize_browser_signals(payload)
        assert len(result["failed_actions"]) <= 8


# ─────────────────────────────────────────────────────────────────────────────
# _build_browser_fix_recommendations
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestBuildBrowserFixRecommendations:
    def test_no_actions_returns_empty(self):
        m = _get_reviewer()
        result = m.ReviewerAgent._build_browser_fix_recommendations({})
        assert result == []

    def test_failed_actions_returns_recommendation(self):
        m = _get_reviewer()
        browser_summary = {
            "failed_actions": ["click .btn"],
            "pending_actions": [],
            "high_risk_actions": [],
            "current_url": "https://example.com",
        }
        result = m.ReviewerAgent._build_browser_fix_recommendations(browser_summary)
        assert len(result) == 1
        assert result[0]["reason"] == "browser-signal"


# ─────────────────────────────────────────────────────────────────────────────
# _build_remediation_loop
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestBuildRemediationLoop:
    def test_no_issues_observe_only(self):
        m = _get_reviewer()
        semantic = {"counts": {}, "summary": "temiz"}
        graph = {"risk": "düşük", "followup_paths": [], "summary": "ok"}
        combined = {
            "impact_level": "low",
            "direct_scope_paths": [],
            "graph_followup_paths": [],
            "issue_paths": [],
            "indirect_breakage_paths": [],
        }
        result = m.ReviewerAgent._build_remediation_loop(semantic, graph, combined, [], ["pytest -q"])
        assert result["status"] == "observe_only"

    def test_with_issues_planned_status(self):
        m = _get_reviewer()
        semantic = {"counts": {"1": 2}, "summary": "hata var"}
        graph = {"risk": "düşük", "followup_paths": [], "summary": "ok"}
        combined = {
            "impact_level": "medium",
            "direct_scope_paths": ["core/agent.py"],
            "graph_followup_paths": [],
            "issue_paths": ["core/agent.py"],
            "indirect_breakage_paths": [],
        }
        fix_recs = [{"path": "core/agent.py", "reason": "semantic", "action": "düzelt"}]
        result = m.ReviewerAgent._build_remediation_loop(semantic, graph, combined, fix_recs, ["pytest"])
        assert result["status"] == "planned"

    def test_high_impact_needs_human_approval(self):
        m = _get_reviewer()
        semantic = {"counts": {}, "summary": "ok"}
        graph = {"risk": "düşük", "followup_paths": [], "summary": "ok"}
        combined = {
            "impact_level": "high",
            "direct_scope_paths": [],
            "graph_followup_paths": [],
            "issue_paths": [],
            "indirect_breakage_paths": ["risk.py"],
        }
        result = m.ReviewerAgent._build_remediation_loop(semantic, graph, combined, [], [])
        assert result["needs_human_approval"] is True


# ─────────────────────────────────────────────────────────────────────────────
# run_task: çeşitli yollar
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestRunTaskExtra:
    def test_empty_prompt_returns_warning(self):
        async def _run(self_ref=self):
            m = _get_reviewer()
            agent = m.ReviewerAgent()
            result = await agent.run_task("")
            assert "UYARI" in result or "boş" in result.lower()

        def test_run_tests_command_with_pipe_arg(self):
            async def _run():
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                result = await agent.run_task("run_tests|pytest -q tests/")
                assert "test" in result.lower() or "OK" in result or "FAIL" in result
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_run_tests_no_pipe_uses_default(self):
            async def _run():
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                result = await agent.run_task("run_tests")
                assert result is not None
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_lsp_diagnostics_route(self):
            async def _run():
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                result = await agent.run_task("lsp_diagnostics|core/agent.py")
                assert result is not None
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_graph_impact_route(self):
            async def _run():
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                result = await agent.run_task("graph_impact|core/agent.py")
                assert result is not None
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_pr_diff_invalid_number_returns_warning(self):
            async def _run():
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                result = await agent.run_task("pr_diff|abc")
                assert "Kullanım" in result or "⚠" in result
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_run_tests_disallowed_command_returns_warning(self):
            async def _run():
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                result = await agent.run_task("run_tests|rm -rf /")
                assert "Kullanım" in result or "⚠" in result
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_review_keyword_dispatches_review_code(self):
            async def _run():
                """'review' içeren prompt review_code yoluna gitmeli (L947-948)."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                # Sonsuz özyinelemeyi önlemek için call_tool'u patch et
                agent.call_tool = AsyncMock(return_value='{"status":"ok","summary":"","reports":[]}')
                agent._run_dynamic_tests = AsyncMock(return_value="[TEST:OK]")
                agent._build_regression_commands = MagicMock(return_value=[])
                result = await agent.run_task("bu kodu review et lütfen")
                assert result is not None
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_unknown_prompt_falls_back_to_list_prs(self):
            async def _run():
                """Tanımsız prompt list_prs fallback döndürmeli (L950)."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                result = await agent.run_task("bilinmeyen bir komut")
                assert result is not None
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_list_issues_without_pipe_uses_default(self):
            async def _run():
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                result = await agent.run_task("list_issues")
                assert "issue" in result.lower() or "listesi" in result.lower()
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ─────────────────────────────────────────────────────────────────────────────
    # Tool metodları
    # ─────────────────────────────────────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestToolMethods:
    def test_tool_repo_info_error_path(self):
        async def _run(self_ref=self):
            m = _get_reviewer()
            agent = m.ReviewerAgent()
            agent.github.get_repo_info = MagicMock(return_value=(False, "hata mesajı"))
            result = await agent._tool_repo_info("")
            assert "HATA" in result

        def test_tool_list_prs_error_path(self):
            async def _run():
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                agent.github.list_pull_requests = MagicMock(return_value=(False, "PR hatası"))
                result = await agent._tool_list_prs("open")
                assert "HATA" in result
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_tool_list_issues_error_path(self):
            async def _run():
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                agent.github.list_issues = MagicMock(return_value=(False, "issue hatası"))
                result = await agent._tool_list_issues("open")
                assert "HATA" in result
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_tool_browser_signals_no_session_id(self):
            async def _run():
                """session_id olmadan no-signal döndürmeli (L792-800)."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                result = await agent._tool_browser_signals("")
                data = json.loads(result)
                assert data["status"] == "no-signal"
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_tool_browser_signals_with_inline_payload(self):
            async def _run():
                """Inline browser_signals varsa doğrudan döndürmeli (L790-791)."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                payload = json.dumps({"browser_signals": {"status": "ok", "risk": "düşük"}})
                result = await agent._tool_browser_signals(payload)
                data = json.loads(result)
                assert data["status"] == "ok"
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_get_graph_store_creates_once(self):
            async def _run():
                """_get_graph_store singleton davranışı göstermeli (L729-740)."""
                m = _get_reviewer()
                agent = m.ReviewerAgent()
                store1 = agent._get_graph_store()
                store2 = agent._get_graph_store()
                assert store1 is store2
            import asyncio as _asyncio
            _asyncio.run(_run())

        asyncio.run(_run())
