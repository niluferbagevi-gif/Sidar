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
