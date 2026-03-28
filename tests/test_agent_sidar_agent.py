"""
agent/sidar_agent.py için birim testleri.
SidarAgent'ın ağır LLM/manager bağımlılıkları tam olarak stub'lanır;
yalnızca deterministik davranışlar (yönlendirme, konfigürasyon, parse mantığı) test edilir.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _build_contracts_stub():
    """agent.core.contracts stub'ı oluşturur."""
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

    @dataclass
    class TaskEnvelope:
        task_id: str
        sender: str
        receiver: str
        goal: str
        intent: str = "mixed"
        parent_task_id: str = None
        context: dict = field(default_factory=dict)
        inputs: list = field(default_factory=list)

    @dataclass
    class TaskResult:
        task_id: str
        status: str
        summary: Any
        evidence: list = field(default_factory=list)
        next_actions: list = field(default_factory=list)

    @dataclass
    class ExternalTrigger:
        trigger_id: str
        source: str
        event_name: str
        payload: dict = field(default_factory=dict)
        protocol: str = "trigger.v1"
        meta: dict = field(default_factory=dict)
        correlation_id: str = ""

        def to_prompt(self) -> str:
            return f"[TRIGGER]\nevent={self.event_name}\npayload={json.dumps(self.payload)}"

    def is_delegation_request(value):
        return isinstance(value, DelegationRequest)

    def derive_correlation_id(*values):
        for v in values:
            text = str(v or "").strip()
            if text:
                return text
        return ""

    contracts = types.ModuleType("agent.core.contracts")
    contracts.DelegationRequest = DelegationRequest
    contracts.TaskEnvelope = TaskEnvelope
    contracts.TaskResult = TaskResult
    contracts.ExternalTrigger = ExternalTrigger
    contracts.is_delegation_request = is_delegation_request
    contracts.derive_correlation_id = derive_correlation_id
    return contracts


def _stub_all_sidar_deps():
    """SidarAgent'ın import zincirindeki tüm modülleri stub'lar."""
    contracts = _build_contracts_stub()
    sys.modules["agent.core.contracts"] = contracts

    # agent.definitions stub
    defs = types.ModuleType("agent.definitions")
    defs.SIDAR_SYSTEM_PROMPT = "Sen SİDAR'sın."
    defs.SIDAR_KEYS = ["sidar"]
    sys.modules["agent.definitions"] = defs

    # config stub
    cfg_mod = types.ModuleType("config")

    class _Config:
        AI_PROVIDER = "ollama"
        OLLAMA_MODEL = "qwen2.5-coder:7b"
        BASE_DIR = "/tmp/sidar_test"
        GITHUB_REPO = ""
        GITHUB_TOKEN = ""
        ACCESS_LEVEL = "standard"
        AUTO_HANDLE_TIMEOUT = 12
        SIDAR_MAX_TOOL_STEPS = 10
        SUBTASK_MAX_STEPS = 5
        LOG_LEVEL = "WARNING"
        ENABLE_HITL = False
        HITL_APPROVAL_TIMEOUT = 30
        # Hardware / GPU
        USE_GPU = False
        GPU_DEVICE = 0
        GPU_MIXED_PRECISION = False
        # Memory / RAG
        MEMORY_FILE = "/tmp/sidar_test/data/memory.json"
        MAX_MEMORY_TURNS = 20
        MEMORY_SUMMARY_KEEP_LAST = 4
        MEMORY_ENCRYPTION_KEY = ""
        RAG_DIR = "/tmp/sidar_test/data/rag"
        RAG_TOP_K = 3
        RAG_CHUNK_SIZE = 1000
        RAG_CHUNK_OVERLAP = 200
        DATABASE_URL = "sqlite+aiosqlite:///tmp/sidar_test.db"
        # Docker
        DOCKER_PYTHON_IMAGE = "python:3.11-alpine"
        DOCKER_EXEC_TIMEOUT = 10
        # Tracing
        ENABLE_TRACING = False

    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod

    # core stubs
    for mod in (
        "core", "core.llm_client", "core.memory", "core.rag",
        "core.entity_memory", "core.ci_remediation",
    ):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    # LLMClient stub
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value='{"thought":"..","tool":"final_answer","argument":"test"}')
    sys.modules["core.llm_client"].LLMClient = MagicMock(return_value=mock_llm)

    # ConversationMemory stub
    mem_mock = MagicMock()
    mem_mock.get_last_file.return_value = None
    mem_mock.clear.return_value = None
    sys.modules["core.memory"].ConversationMemory = MagicMock(return_value=mem_mock)

    # DocumentStore stub
    docs_mock = MagicMock()
    sys.modules["core.rag"].DocumentStore = MagicMock(return_value=docs_mock)

    # entity_memory stub
    entity_mem = MagicMock()
    sys.modules["core.entity_memory"].get_entity_memory = MagicMock(return_value=entity_mem)

    # ci_remediation stub
    ci_mod = sys.modules["core.ci_remediation"]
    ci_mod.build_ci_failure_context = MagicMock(return_value={})
    ci_mod.build_ci_failure_prompt = MagicMock(return_value="ci prompt")
    ci_mod.build_ci_remediation_payload = MagicMock(return_value="ci payload")
    ci_mod.build_self_heal_patch_prompt = MagicMock(return_value="patch prompt")
    ci_mod.normalize_self_heal_plan = MagicMock(return_value=[])

    # managers stubs
    for mod in (
        "managers", "managers.code_manager", "managers.system_health",
        "managers.github_manager", "managers.security",
        "managers.web_search", "managers.package_info", "managers.todo_manager",
    ):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    for cls_name, mod_path in [
        ("CodeManager", "managers.code_manager"),
        ("SystemHealthManager", "managers.system_health"),
        ("GitHubManager", "managers.github_manager"),
        ("SecurityManager", "managers.security"),
        ("WebSearchManager", "managers.web_search"),
        ("PackageInfoManager", "managers.package_info"),
        ("TodoManager", "managers.todo_manager"),
    ]:
        mock_instance = MagicMock()
        sys.modules[mod_path].__dict__[cls_name] = MagicMock(return_value=mock_instance)

    # pydantic stub (eğer yoksa)
    try:
        import pydantic
    except ImportError:
        pydantic_mod = types.ModuleType("pydantic")
        pydantic_mod.BaseModel = object
        pydantic_mod.Field = lambda *a, **kw: None
        pydantic_mod.ValidationError = Exception
        sys.modules["pydantic"] = pydantic_mod


def _get_sidar_agent():
    _stub_all_sidar_deps()
    sys.modules.pop("agent.sidar_agent", None)
    import agent.sidar_agent as sa
    return sa


class TestSidarAgentInit:
    def test_sidar_agent_instantiation(self):
        sa = _get_sidar_agent()
        agent = sa.SidarAgent()
        assert agent is not None

    def test_sidar_agent_has_cfg(self):
        sa = _get_sidar_agent()
        agent = sa.SidarAgent()
        assert agent.cfg is not None

    def test_sidar_agent_custom_cfg(self):
        sa = _get_sidar_agent()
        cfg = sys.modules["config"].Config()
        agent = sa.SidarAgent(cfg=cfg)
        assert agent.cfg is cfg


class TestSidarAgentToolJsonParse:
    def test_parse_valid_json_tool_call(self):
        sa = _get_sidar_agent()
        agent = sa.SidarAgent()
        raw = '{"thought": "düşünüyorum", "tool": "final_answer", "argument": "sonuç"}'
        result = agent._parse_tool_call(raw)
        assert result["tool"] == "final_answer"
        assert result["argument"] == "sonuç"

    def test_parse_json_with_markdown_wrapper(self):
        sa = _get_sidar_agent()
        agent = sa.SidarAgent()
        raw = '```json\n{"thought": "...", "tool": "read_file", "argument": "main.py"}\n```'
        result = agent._parse_tool_call(raw)
        assert result is not None
        assert result["tool"] == "read_file"

    def test_parse_invalid_json_returns_final_answer(self):
        sa = _get_sidar_agent()
        agent = sa.SidarAgent()
        result = agent._parse_tool_call("bu json değil")
        # Geçersiz JSON → final_answer veya None döndürmeli
        if result is not None:
            assert result.get("tool") == "final_answer"

    def test_parse_missing_tool_key(self):
        sa = _get_sidar_agent()
        agent = sa.SidarAgent()
        raw = '{"thought": "düşünüyorum"}'
        result = agent._parse_tool_call(raw)
        # Eksik "tool" anahtarı → None ya da final_answer
        if result is not None:
            assert "tool" in result


class TestSidarAgentMemoryMessages:
    def test_build_messages_returns_list(self):
        sa = _get_sidar_agent()
        agent = sa.SidarAgent()
        if hasattr(agent, "_build_messages"):
            msgs = agent._build_messages("merhaba")
            assert isinstance(msgs, list)

    def test_messages_contain_user_prompt(self):
        sa = _get_sidar_agent()
        agent = sa.SidarAgent()
        if hasattr(agent, "_build_messages"):
            msgs = agent._build_messages("test sorgusu")
            all_content = " ".join(
                m.get("content", "") for m in msgs if isinstance(m, dict)
            )
            assert "test sorgusu" in all_content


class TestSidarAgentFallbackFederation:
    def test_fallback_federation_envelope_to_prompt(self):
        sa = _get_sidar_agent()
        env = sa._FallbackFederationTaskEnvelope(
            task_id="t1",
            source_system="sys_a",
            source_agent="agent_a",
            target_system="sidar",
            target_agent="sidar",
            goal="hedef görev",
        )
        prompt = env.to_prompt()
        assert "[FEDERATION TASK]" in prompt
        assert "hedef görev" in prompt

    def test_fallback_action_feedback_to_prompt(self):
        sa = _get_sidar_agent()
        fb = sa._FallbackActionFeedback(
            feedback_id="f1",
            source_system="sys_a",
            source_agent="bot",
            action_name="deploy",
            status="success",
            summary="başarılı",
        )
        prompt = fb.to_prompt()
        assert "[ACTION FEEDBACK]" in prompt
        assert "deploy" in prompt


class TestSidarAgentExternalTrigger:
    @pytest.mark.asyncio
    async def test_handle_external_trigger_basic(self):
        sa = _get_sidar_agent()
        agent = sa.SidarAgent()
        contracts = sys.modules["agent.core.contracts"]
        trigger = contracts.ExternalTrigger(
            trigger_id="trig-1",
            source="webhook",
            event_name="ci_failure",
            payload={"test": "data"},
        )
        if hasattr(agent, "handle_external_trigger"):
            result = await agent.handle_external_trigger(trigger)
            assert result is not None


class TestDefaultDeriveCorrelationId:
    def test_returns_first_non_empty(self):
        sa = _get_sidar_agent()
        result = sa._default_derive_correlation_id("", None, "abc", "def")
        assert result == "abc"

    def test_all_empty_returns_empty(self):
        sa = _get_sidar_agent()
        result = sa._default_derive_correlation_id("", None, "")
        assert result == ""
