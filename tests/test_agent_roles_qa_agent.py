"""
agent/roles/qa_agent.py için birim testleri.
"""
from __future__ import annotations

import json
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_qa_deps():
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
        contracts = types.ModuleType("agent.core.contracts")
        contracts.is_delegation_request = lambda v: False
        sys.modules["agent.core.contracts"] = contracts

    # config stub (her çağrıda taze; kirli config'i devralma)
    cfg_mod = types.ModuleType("config")
    class _Config:
        AI_PROVIDER = "ollama"; OLLAMA_MODEL = "qwen2.5-coder:7b"
        BASE_DIR = "/tmp/sidar_test"
        USE_GPU = False; GPU_DEVICE = 0; GPU_MIXED_PRECISION = False
        RAG_DIR = "/tmp/sidar_test/rag"; RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 1000; RAG_CHUNK_OVERLAP = 200
    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod

    # core stubs
    for mod in ("core", "core.llm_client", "core.ci_remediation"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
    if not hasattr(sys.modules["core.llm_client"], "LLMClient"):
        mock_llm = MagicMock(); mock_llm.chat = AsyncMock(return_value="llm yanıtı")
        sys.modules["core.llm_client"].LLMClient = MagicMock(return_value=mock_llm)
    ci = sys.modules["core.ci_remediation"]
    if not hasattr(ci, "build_ci_remediation_payload"):
        ci.build_ci_remediation_payload = MagicMock(return_value={"remediation_loop": {}, "root_cause_summary": "", "suspected_targets": []})

    # managers stubs
    for mod, cls in [
        ("managers", None), ("managers.code_manager", "CodeManager"), ("managers.security", "SecurityManager"),
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
        if cls:
            mock_inst = MagicMock()
            mock_inst.read_file = MagicMock(return_value=(True, "dosya içeriği"))
            mock_inst.list_directory = MagicMock(return_value=(True, "dizin listesi"))
            mock_inst.grep_files = MagicMock(return_value=(True, "grep sonucu"))
            sys.modules[mod].__dict__[cls] = MagicMock(return_value=mock_inst)

    # agent.base_agent stub (her çağrıda taze)
    ba_mod = types.ModuleType("agent.base_agent")
    class _BaseAgent:
        def __init__(self, *a, cfg=None, role_name="base", **kw):
            self.cfg = cfg or sys.modules["config"].Config()
            self.role_name = role_name
            self.llm = MagicMock(); self.llm.chat = AsyncMock(return_value="llm yanıtı")
            self.tools = {}
        def register_tool(self, name, fn): self.tools[name] = fn
        async def call_tool(self, name, arg):
            if name not in self.tools: return f"HATA: {name} bulunamadı"
            return await self.tools[name](arg)
        async def call_llm(self, msgs, system_prompt=None, temperature=0.7, **kw): return "llm test kodu"
    ba_mod.BaseAgent = _BaseAgent
    sys.modules["agent.base_agent"] = ba_mod


def _get_qa():
    _stub_qa_deps()
    sys.modules.pop("agent.roles.qa_agent", None)
    if "agent.roles" not in sys.modules:
        roles = types.ModuleType("agent.roles"); roles.__path__ = [str(_proj / "agent" / "roles")]
        sys.modules["agent.roles"] = roles
    import agent.roles.qa_agent as m
    return m


class TestQAAgentInit:
    def test_instantiation(self):
        assert _get_qa().QAAgent() is not None

    def test_role_name(self):
        assert _get_qa().QAAgent().role_name == "qa"

    def test_tools_registered(self):
        m = _get_qa()
        agent = m.QAAgent()
        for tool in ("read_file", "list_directory", "grep_search", "coverage_config", "ci_remediation"):
            assert tool in agent.tools, f"{tool} kayıtlı değil"


class TestQAAgentParseJsonPayload:
    def test_empty_returns_empty(self):
        m = _get_qa()
        assert m.QAAgent._parse_json_payload("") == {}

    def test_valid_json(self):
        m = _get_qa()
        result = m.QAAgent._parse_json_payload('{"key": "val"}')
        assert result["key"] == "val"

    def test_invalid_json_returns_failure_summary(self):
        m = _get_qa()
        result = m.QAAgent._parse_json_payload("{bozuk}")
        assert "failure_summary" in result

    def test_json_array_returns_failure_summary(self):
        m = _get_qa()
        result = m.QAAgent._parse_json_payload('["a", "b"]')
        assert "failure_summary" in result

    def test_plain_text_returns_failure_summary(self):
        m = _get_qa()
        result = m.QAAgent._parse_json_payload("plain text")
        assert "failure_summary" in result


class TestQAAgentSuggestTestPath:
    def test_empty_path_returns_default(self):
        m = _get_qa()
        result = m.QAAgent._suggest_test_path("")
        assert result == "tests/test_generated_coverage.py"

    def test_module_path(self):
        m = _get_qa()
        result = m.QAAgent._suggest_test_path("core/memory.py")
        assert result == "tests/test_memory.py"

    def test_nested_path(self):
        m = _get_qa()
        result = m.QAAgent._suggest_test_path("agent/roles/coder_agent.py")
        assert result == "tests/test_coder_agent.py"

    def test_relative_path_with_dot(self):
        m = _get_qa()
        result = m.QAAgent._suggest_test_path("./managers/security.py")
        assert "security" in result


class TestQAAgentCoverageConfig:
    def test_coverage_config_summary_reads_coveragerc(self, tmp_path):
        m = _get_qa()
        coveragerc = tmp_path / ".coveragerc"
        coveragerc.write_text(
            "[run]\n"
            "omit =\n"
            "    tests/*\n"
            "    scripts/*\n\n"
            "[report]\n"
            "fail_under = 85\n"
            "show_missing = true\n"
            "skip_covered = false\n",
            encoding="utf-8",
        )
        cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path))
        agent = m.QAAgent(cfg=cfg)
        summary = agent._coverage_config_summary()
        assert summary["exists"] is True
        assert summary["fail_under"] == 85
        assert summary["show_missing"] is True
        assert summary["skip_covered"] is False
        assert summary["omit"] == ["tests/*", "scripts/*"]

    def test_coverage_config_summary_defaults_when_file_missing(self, tmp_path):
        m = _get_qa()
        cfg = types.SimpleNamespace(BASE_DIR=str(tmp_path))
        agent = m.QAAgent(cfg=cfg)
        summary = agent._coverage_config_summary()
        assert summary["exists"] is False
        assert summary["fail_under"] == 0
        assert summary["show_missing"] is False
        assert summary["skip_covered"] is False
        assert summary["omit"] == []


class TestQAAgentRunTask:
    def test_empty_prompt_returns_warning(self):
        async def _run():
            m = _get_qa()
            result = await m.QAAgent().run_task("")
            assert "UYARI" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_coverage_config_routing(self):
        async def _run():
            m = _get_qa()
            agent = m.QAAgent()
            with patch.object(agent, '_coverage_config_summary', return_value={"fail_under": 100, "exists": False, "omit": [], "path": "/tmp/.coveragerc", "show_missing": False, "skip_covered": False}):
                result = await agent.run_task("coverage_config")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_read_file_routing(self):
        async def _run():
            m = _get_qa()
            result = await m.QAAgent().run_task("read_file|main.py")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_list_directory_routing(self):
        async def _run():
            m = _get_qa()
            result = await m.QAAgent().run_task("list_directory|.")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_grep_search_routing(self):
        async def _run():
            m = _get_qa()
            result = await m.QAAgent().run_task("grep_search|def test_|||*.py")
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_ci_remediation_routing(self):
        async def _run():
            m = _get_qa()
            result = await m.QAAgent().run_task('ci_remediation|{"diagnosis": "test hatası"}')
            parsed = json.loads(result)
            assert isinstance(parsed, dict)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_coverage_keyword_triggers_plan(self):
        async def _run():
            m = _get_qa()
            agent = m.QAAgent()
            with patch.object(agent, '_coverage_config_summary', return_value={"fail_under": 100, "exists": False, "omit": [], "path": "/tmp/.coveragerc", "show_missing": False, "skip_covered": False}):
                result = await agent.run_task("coverage eksik testleri bul")
            parsed = json.loads(result)
            assert "coverage" in parsed
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_write_missing_tests_routing(self):
        async def _run():
            m = _get_qa()
            agent = m.QAAgent()
            with patch.object(agent, '_generate_test_code', AsyncMock(return_value="def test_foo(): pass")):
                result = await agent.run_task("write_missing_tests|core/memory.py|bağlam")
            assert "test_foo" in result or result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_coverage_plan_routing(self):
        async def _run():
            m = _get_qa()
            agent = m.QAAgent()
            with patch.object(agent, '_coverage_config_summary', return_value={"fail_under": 100, "exists": False, "omit": [], "path": "/tmp/.coveragerc", "show_missing": False, "skip_covered": False}):
                result = await agent.run_task("coverage_plan|{}")
            parsed = json.loads(result)
            assert "coverage" in parsed
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_non_qa_prompt_falls_back_to_generate_test_code(self):
        async def _run():
            m = _get_qa()
            agent = m.QAAgent()
            with patch.object(agent, '_generate_test_code', AsyncMock(return_value="def test_freeform(): pass")) as gen:
                result = await agent.run_task("merhaba dunya")
            assert "test_freeform" in result
            gen.assert_awaited_once_with("", "merhaba dunya")
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_generate_test_code_builds_prompt_and_calls_llm(self):
        async def _run():
            m = _get_qa()
            agent = m.QAAgent()
            with patch.object(
                agent,
                "_coverage_config_summary",
                return_value={
                    "fail_under": 92,
                    "exists": True,
                    "omit": ["tests/*"],
                    "path": "/tmp/.coveragerc",
                    "show_missing": True,
                    "skip_covered": False,
                },
            ):
                with patch.object(agent, "call_llm", AsyncMock(return_value="def test_case(): pass")) as call_llm:
                    result = await agent._generate_test_code("agent/roles/qa_agent.py", "edge case context")
            assert "test_case" in result
            kwargs = call_llm.call_args.kwargs
            assert kwargs["system_prompt"] == agent.TEST_GENERATION_PROMPT
            assert kwargs["temperature"] == 0.1
            prompt_text = call_llm.call_args.args[0][0]["content"]
            assert "Hedef modül: agent/roles/qa_agent.py" in prompt_text
            assert "Coverage fail_under: 92" in prompt_text
            assert "Coverage omit: tests/*" in prompt_text
            assert "edge case context" in prompt_text
        import asyncio as _asyncio
        _asyncio.run(_run())
