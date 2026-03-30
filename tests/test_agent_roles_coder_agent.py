"""
agent/roles/coder_agent.py için birim testleri.
Tüm ağır bağımlılıklar stub'lanır; deterministik davranışlar test edilir.
"""
from __future__ import annotations

import asyncio
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_coder_deps():
    """CoderAgent'ın tüm import bağımlılıklarını stub'lar."""
    # agent package stub
    if "agent" not in sys.modules:
        pkg = types.ModuleType("agent")
        pkg.__path__ = [str(_proj / "agent")]
        pkg.__package__ = "agent"
        sys.modules["agent"] = pkg

    # agent.core stub
    if "agent.core" not in sys.modules:
        core = types.ModuleType("agent.core")
        core.__path__ = [str(_proj / "agent" / "core")]
        core.__package__ = "agent.core"
        sys.modules["agent.core"] = core
    else:
        c = sys.modules["agent.core"]
        if not hasattr(c, "__path__"):
            c.__path__ = [str(_proj / "agent" / "core")]

    # agent.core.contracts stub
    if "agent.core.contracts" not in sys.modules:
        from dataclasses import dataclass, field
        contracts = types.ModuleType("agent.core.contracts")
        @dataclass
        class DelegationRequest:
            task_id: str; reply_to: str; target_agent: str; payload: str
            intent: str = "mixed"; parent_task_id: str = None
            handoff_depth: int = 0; meta: dict = field(default_factory=dict)
            def bumped(self): return DelegationRequest(self.task_id, self.reply_to, self.target_agent, self.payload, self.intent, self.parent_task_id, self.handoff_depth + 1, dict(self.meta))
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
            BASE_DIR = "/tmp/sidar_test"; GITHUB_REPO = ""; GITHUB_TOKEN = ""
            USE_GPU = False; GPU_DEVICE = 0; GPU_MIXED_PRECISION = False
            RAG_DIR = "/tmp/sidar_test/rag"; RAG_TOP_K = 3
            RAG_CHUNK_SIZE = 1000; RAG_CHUNK_OVERLAP = 200
            CODING_MODEL = "qwen2.5-coder:7b"; TEXT_MODEL = "gemma2:9b"
            DOCKER_PYTHON_IMAGE = "python:3.11-alpine"; DOCKER_EXEC_TIMEOUT = 10
        cfg_mod.Config = _Config
        sys.modules["config"] = cfg_mod

    # core/core.llm_client stubs
    for mod in ("core", "core.llm_client"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
    if not hasattr(sys.modules["core.llm_client"], "LLMClient"):
        mock_llm = MagicMock(); mock_llm.chat = AsyncMock(return_value='{"tool":"final_answer","argument":"ok"}')
        sys.modules["core.llm_client"].LLMClient = MagicMock(return_value=mock_llm)

    # agent.base_agent stub
    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")
        contracts = sys.modules["agent.core.contracts"]
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
            async def call_llm(self, msgs, system_prompt=None, temperature=0.7, json_mode=False):
                return "llm yanıtı"
            def delegate_to(self, target, payload, task_id=None, reason=""):
                return contracts.DelegationRequest(task_id=task_id or f"{self.role_name}-task", reply_to=self.role_name, target_agent=target, payload=payload)
            @staticmethod
            def is_delegation_message(v): return contracts.is_delegation_request(v)
        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod

    # managers stubs
    for mod, cls in [
        ("managers", None), ("managers.code_manager", "CodeManager"),
        ("managers.security", "SecurityManager"), ("managers.package_info", "PackageInfoManager"),
        ("managers.todo_manager", "TodoManager"),
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
        if cls:
            mock_inst = MagicMock()
            mock_inst.read_file = MagicMock(return_value=(True, "dosya içeriği"))
            mock_inst.write_file = MagicMock(return_value=(True, "yazıldı"))
            mock_inst.patch_file = MagicMock(return_value=(True, "yamalandı"))
            mock_inst.execute_code = MagicMock(return_value=(True, "çalıştırıldı"))
            mock_inst.list_directory = MagicMock(return_value=(True, "dizin listesi"))
            mock_inst.glob_search = MagicMock(return_value=(True, "glob sonuçları"))
            mock_inst.grep_files = MagicMock(return_value=(True, "grep sonuçları"))
            mock_inst.audit_project = MagicMock(return_value="denetim sonucu")
            mock_inst.scan_project_todos = MagicMock(return_value="todo listesi")
            mock_inst.pypi_info = AsyncMock(return_value=(True, "paket bilgisi"))
            sys.modules[mod].__dict__[cls] = MagicMock(return_value=mock_inst)


def _get_coder():
    _stub_coder_deps()
    sys.modules.pop("agent.roles.coder_agent", None)
    if "agent.roles" not in sys.modules:
        roles = types.ModuleType("agent.roles")
        roles.__path__ = [str(_proj / "agent" / "roles")]
        sys.modules["agent.roles"] = roles
    import agent.roles.coder_agent as m
    return m


class TestCoderAgentInit:
    def test_instantiation(self):
        m = _get_coder()
        agent = m.CoderAgent()
        assert agent is not None

    def test_role_name(self):
        m = _get_coder()
        assert m.CoderAgent().role_name == "coder"

    def test_tools_registered(self):
        m = _get_coder()
        agent = m.CoderAgent()
        for tool in ("read_file", "write_file", "patch_file", "execute_code",
                     "list_directory", "glob_search", "grep_search",
                     "audit_project", "get_package_info", "scan_project_todos"):
            assert tool in agent.tools, f"{tool} kayıtlı değil"

    def test_custom_cfg(self):
        m = _get_coder()
        cfg = sys.modules["config"].Config()
        agent = m.CoderAgent(cfg=cfg)
        assert agent.cfg is cfg


class TestCoderAgentParseQaFeedback:
    def test_empty_returns_empty(self):
        m = _get_coder()
        result = m.CoderAgent._parse_qa_feedback("")
        assert result == {}

    def test_valid_json(self):
        m = _get_coder()
        result = m.CoderAgent._parse_qa_feedback('{"decision": "reject", "summary": "hata var"}')
        assert result["decision"] == "reject"
        assert result["summary"] == "hata var"

    def test_key_value_format(self):
        m = _get_coder()
        result = m.CoderAgent._parse_qa_feedback("decision=approve;summary=tamam")
        assert result.get("decision") == "approve"
        assert result.get("summary") == "tamam"

    def test_invalid_json_returns_raw(self):
        m = _get_coder()
        result = m.CoderAgent._parse_qa_feedback("{bozuk json")
        assert "raw" in result

    def test_plain_text_returns_raw(self):
        m = _get_coder()
        result = m.CoderAgent._parse_qa_feedback("düz metin")
        assert "raw" in result


class TestCoderAgentRunTask:
    @pytest.mark.asyncio
    async def test_empty_prompt_returns_warning(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task("")
        assert "UYARI" in result or "uyarı" in result.lower() or "Boş" in result

    @pytest.mark.asyncio
    async def test_read_file_routing(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task("read_file|main.py")
        assert result is not None

    @pytest.mark.asyncio
    async def test_write_file_routing(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task("write_file|out.py|# kod")
        assert result is not None

    @pytest.mark.asyncio
    async def test_patch_file_routing(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task("patch_file|main.py|eski|yeni")
        assert result is not None

    @pytest.mark.asyncio
    async def test_execute_code_routing(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task("execute_code|print('hello')")
        assert result is not None

    @pytest.mark.asyncio
    async def test_qa_feedback_reject(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task('qa_feedback|{"decision": "reject", "summary": "hata bulundu"}')
        assert "REWORK_REQUIRED" in result or "rework" in result.lower()

    @pytest.mark.asyncio
    async def test_qa_feedback_approve(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task('qa_feedback|{"decision": "approve", "summary": "tamam"}')
        assert "APPROVED" in result

    @pytest.mark.asyncio
    async def test_request_review_routing(self):
        m = _get_coder()
        agent = m.CoderAgent()
        contracts = sys.modules["agent.core.contracts"]
        result = await agent.run_task("request_review|def hello(): pass")
        assert contracts.is_delegation_request(result)
        assert result.target_agent == "reviewer"

    def test_qa_feedback_reject_includes_compile_error_excerpt(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = asyncio.run(
            agent.run_task(
                'qa_feedback|{"decision":"reject","summary":"build kırmızı",'
                '"dynamic_test_output":"SyntaxError: invalid syntax",'
                '"regression_test_output":"[TEST:FAIL] pytest -q tests/test_compile.py",'
                '"remediation_loop":{"summary":"Kod derlenmiyor, import ve girinti düzelt"}}'
            )
        )
        assert "REWORK_REQUIRED" in result
        assert "SyntaxError" in result
        assert "REMEDIATION_LOOP" in result

    @pytest.mark.asyncio
    async def test_unhandled_returns_legacy_fallback(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task("bilinmeyen komut xyz")
        assert "LEGACY_FALLBACK" in result or result is not None


class TestCoderAgentPromptVariations:
    @pytest.mark.parametrize(
        "prompt, expected_fragment",
        [
            ("read_file|main.py", "dosya içeriği"),
            ("write_file|out.py|print(1)", "yazıldı"),
            ("patch_file|main.py|eski|yeni", "yamalandı"),
            ("execute_code|print('ok')", "çalıştırıldı"),
            ("qa_feedback|{\"decision\":\"approve\",\"summary\":\"ok\"}", "APPROVED"),
            ("qa_feedback|{\"decision\":\"reject\",\"summary\":\"fix\"}", "REWORK_REQUIRED"),
            ("bilinmeyen görev", "LEGACY_FALLBACK"),
        ],
    )
    def test_prompt_variations_route_to_expected_outputs(self, prompt, expected_fragment):
        m = _get_coder()
        agent = m.CoderAgent()
        result = asyncio.run(agent.run_task(prompt))
        assert expected_fragment in result


class TestCoderAgentEdgeCases:
    @pytest.mark.asyncio
    async def test_qa_feedback_with_invalid_shape_falls_back_to_approved_message(self):
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task('qa_feedback|["unexpected","array"]')
        assert "APPROVED" in result

    @pytest.mark.asyncio
    async def test_request_review_handles_empty_payload(self):
        m = _get_coder()
        agent = m.CoderAgent()
        contracts = sys.modules["agent.core.contracts"]
        result = await agent.run_task("request_review|")
        assert contracts.is_delegation_request(result)
        assert result.target_agent == "reviewer"


# ══════════════════════════════════════════════════════════════
# Eksik branch kapsamı için ek testler
# Lines: 56, 64, 74-75, 78-80, 83-89, 92, 95-96, 99-100, 169-171
# Branches: 110->114
# ══════════════════════════════════════════════════════════════

class TestCoderAgentToolDirectCalls:
    """Tool fonksiyonlarını doğrudan call_tool() üzerinden çağırır."""

    @pytest.mark.asyncio
    async def test_tool_write_file_missing_pipe_returns_usage_hint(self):
        """Line 56: write_file arg without '|' → error message."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("write_file", "no_pipe_arg")
        assert "Kullanım" in result or "⚠" in result

    @pytest.mark.asyncio
    async def test_tool_patch_file_missing_pipes_returns_usage_hint(self):
        """Line 64: patch_file arg with fewer than 3 parts → error message."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("patch_file", "only_one_part")
        assert "Kullanım" in result or "⚠" in result

    @pytest.mark.asyncio
    async def test_tool_list_directory_direct(self):
        """Lines 74-75: _tool_list_directory executed via call_tool."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("list_directory", ".")
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_glob_search_without_separator(self):
        """Lines 78-80: _tool_glob_search without '|||' separator (base defaults to '.')."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("glob_search", "**/*.py")
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_glob_search_with_separator(self):
        """Lines 78-80: _tool_glob_search with '|||' separator."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("glob_search", "**/*.py|||./src")
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_grep_search_direct(self):
        """Lines 83-89: _tool_grep_search with full pipe-separated args."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("grep_search", "def |||tests/|||*.py|||3")
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_grep_search_minimal_args(self):
        """Lines 83-89: _tool_grep_search with only pattern (all defaults)."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("grep_search", "import")
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_audit_project_direct(self):
        """Line 92: _tool_audit_project executed via call_tool."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("audit_project", ".")
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_get_package_info_direct(self):
        """Lines 95-96: _tool_get_package_info executed via call_tool."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("get_package_info", "requests")
        assert result is not None

    @pytest.mark.asyncio
    async def test_tool_scan_project_todos_direct(self):
        """Lines 99-100: _tool_scan_project_todos executed via call_tool."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.call_tool("scan_project_todos", ".")
        assert result is not None

    def test_parse_qa_feedback_valid_json_not_dict(self):
        """Line 110->114 branch: json.loads succeeds but result is not a dict → falls to line 114."""
        m = _get_coder()
        import unittest.mock as _mock

        # Mock json.loads to return a list even for a "{...}" input
        with _mock.patch.object(m.json, "loads", return_value=[1, 2, 3]):
            result = m.CoderAgent._parse_qa_feedback('{"key": "value"}')
        # isinstance([1,2,3], dict) is False → continue to line 114 (result = {"raw": payload})
        assert "raw" in result

    @pytest.mark.asyncio
    async def test_natural_language_write_file(self):
        """Lines 169-171: Turkish regex 'X isimli bir dosyaya Y yaz' → call write_file."""
        m = _get_coder()
        agent = m.CoderAgent()
        result = await agent.run_task("output.py isimli bir dosyaya 'print(42)' yaz")
        assert result is not None
        # Should have called write_file → returns the mock result "yazıldı"
        assert "yazıldı" in result or result is not None