"""
agent/base_agent.py için birim testleri.
BaseAgent soyut sınıfının register_tool, call_tool, call_llm,
delegate_to, is_delegation_message ve handle metodları test edilir.
"""
from __future__ import annotations

import sys
import types
import pytest


# ──────────────────────────────────────────────────────────────
# Stub: config
# ──────────────────────────────────────────────────────────────
def _stub_config():
    if "config" not in sys.modules:
        mod = types.ModuleType("config")

        class Config:
            AI_PROVIDER = "openai"
            OPENAI_API_KEY = "test-key"
            OPENAI_MODEL = "gpt-4o"
            ANTHROPIC_API_KEY = ""
            ANTHROPIC_MODEL = ""
            GEMINI_API_KEY = ""
            GEMINI_MODEL = ""

        mod.Config = Config
        sys.modules["config"] = mod
    return sys.modules["config"]


# ──────────────────────────────────────────────────────────────
# Stub: core.llm_client
# ──────────────────────────────────────────────────────────────
def _stub_llm_client():
    for mod_name in ("core", "core.llm_client"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    class FakeLLMClient:
        def __init__(self, provider=None, cfg=None):
            self.last_call = None

        async def chat(self, *, messages, model=None, system_prompt=None,
                       temperature=0.3, stream=False, json_mode=False):
            self.last_call = {
                "messages": messages,
                "system_prompt": system_prompt,
                "temperature": temperature,
            }
            return "mocked-llm-response"

    sys.modules["core.llm_client"].LLMClient = FakeLLMClient
    sys.modules["core"].LLMClient = FakeLLMClient


_stub_config()
_stub_llm_client()


# ──────────────────────────────────────────────────────────────
# Concrete subclass for testing (BaseAgent is abstract)
# ──────────────────────────────────────────────────────────────
def _make_agent(role_name: str = "test"):
    from agent.base_agent import BaseAgent
    from config import Config

    class ConcreteAgent(BaseAgent):
        SYSTEM_PROMPT = "You are a test agent."

        async def run_task(self, task_prompt: str):
            return f"done: {task_prompt}"

    cfg = Config()
    return ConcreteAgent(cfg, role_name=role_name)


# ══════════════════════════════════════════════════════════════
# Initialization
# ══════════════════════════════════════════════════════════════

class TestBaseAgentInit:
    def test_role_name_stored(self):
        agent = _make_agent("coder")
        assert agent.role_name == "coder"

    def test_tools_empty_on_init(self):
        agent = _make_agent()
        assert agent.tools == {}

    def test_llm_assigned(self):
        agent = _make_agent()
        assert agent.llm is not None

    def test_default_config_used_when_none(self):
        from agent.base_agent import BaseAgent

        class MinimalAgent(BaseAgent):
            async def run_task(self, task_prompt: str):
                return "ok"

        a = MinimalAgent()
        assert a.cfg is not None


# ══════════════════════════════════════════════════════════════
# register_tool / call_tool
# ══════════════════════════════════════════════════════════════

class TestToolDispatch:
    @pytest.mark.asyncio
    async def test_register_and_call_tool(self):
        agent = _make_agent()

        async def echo(arg: str) -> str:
            return f"echo:{arg}"

        agent.register_tool("echo", echo)
        result = await agent.call_tool("echo", "hello")
        assert result == "echo:hello"

    @pytest.mark.asyncio
    async def test_call_unknown_tool_returns_error(self):
        agent = _make_agent()
        result = await agent.call_tool("nonexistent", "x")
        assert "HATA" in result
        assert "nonexistent" in result

    def test_register_tool_overwrites(self):
        agent = _make_agent()

        async def v1(arg): return "v1"
        async def v2(arg): return "v2"

        agent.register_tool("t", v1)
        agent.register_tool("t", v2)
        assert agent.tools["t"] is v2


# ══════════════════════════════════════════════════════════════
# call_llm
# ══════════════════════════════════════════════════════════════

class TestCallLLM:
    @pytest.mark.asyncio
    async def test_returns_string(self):
        agent = _make_agent()
        result = await agent.call_llm([{"role": "user", "content": "test"}])
        assert isinstance(result, str)
        assert result == "mocked-llm-response"

    @pytest.mark.asyncio
    async def test_custom_system_prompt_forwarded(self):
        agent = _make_agent()
        await agent.call_llm(
            [{"role": "user", "content": "q"}],
            system_prompt="custom prompt",
        )
        assert agent.llm.last_call["system_prompt"] == "custom prompt"

    @pytest.mark.asyncio
    async def test_default_system_prompt_used(self):
        agent = _make_agent()
        await agent.call_llm([{"role": "user", "content": "q"}])
        assert agent.llm.last_call["system_prompt"] == "You are a test agent."

    @pytest.mark.asyncio
    async def test_temperature_forwarded(self):
        agent = _make_agent()
        await agent.call_llm(
            [{"role": "user", "content": "q"}],
            temperature=0.9,
        )
        assert agent.llm.last_call["temperature"] == 0.9


# ══════════════════════════════════════════════════════════════
# delegate_to
# ══════════════════════════════════════════════════════════════

class TestDelegateTo:
    def test_returns_delegation_request(self):
        from agent.core.contracts import DelegationRequest
        agent = _make_agent("researcher")
        req = agent.delegate_to("coder", "write tests", task_id="t1")
        assert isinstance(req, DelegationRequest)

    def test_target_agent_set(self):
        agent = _make_agent("researcher")
        req = agent.delegate_to("coder", "write tests")
        assert req.target_agent == "coder"

    def test_reply_to_is_role_name(self):
        agent = _make_agent("researcher")
        req = agent.delegate_to("coder", "write tests")
        assert req.reply_to == "researcher"

    def test_payload_set(self):
        agent = _make_agent()
        req = agent.delegate_to("qa", "run linter", task_id="t2")
        assert req.payload == "run linter"

    def test_auto_task_id_when_empty(self):
        agent = _make_agent("qa")
        req = agent.delegate_to("coder", "payload")
        assert req.task_id.startswith("p2p-qa")

    def test_explicit_task_id_preserved(self):
        agent = _make_agent()
        req = agent.delegate_to("coder", "payload", task_id="explicit-id")
        assert req.task_id == "explicit-id"

    def test_reason_stored_in_meta(self):
        agent = _make_agent()
        req = agent.delegate_to("coder", "payload", reason="need code")
        assert req.meta.get("reason") == "need code"

    def test_empty_reason_no_meta_key(self):
        agent = _make_agent()
        req = agent.delegate_to("coder", "payload")
        assert "reason" not in req.meta

    def test_handoff_depth_clamped_to_zero(self):
        agent = _make_agent()
        req = agent.delegate_to("coder", "payload", handoff_depth=-5)
        assert req.handoff_depth == 0

    def test_handoff_depth_positive(self):
        agent = _make_agent()
        req = agent.delegate_to("coder", "payload", handoff_depth=3)
        assert req.handoff_depth == 3


# ══════════════════════════════════════════════════════════════
# is_delegation_message
# ══════════════════════════════════════════════════════════════

class TestIsDelegationMessage:
    def test_delegation_request_is_true(self):
        from agent.core.contracts import DelegationRequest
        agent = _make_agent()
        req = DelegationRequest(
            task_id="t1", reply_to="a", target_agent="b", payload="p"
        )
        assert agent.is_delegation_message(req) is True

    def test_plain_string_is_false(self):
        agent = _make_agent()
        assert agent.is_delegation_message("some result") is False

    def test_none_is_false(self):
        agent = _make_agent()
        assert agent.is_delegation_message(None) is False


# ══════════════════════════════════════════════════════════════
# handle (TaskEnvelope → TaskResult)
# ══════════════════════════════════════════════════════════════

class TestHandle:
    @pytest.mark.asyncio
    async def test_handle_returns_task_result(self):
        from agent.core.contracts import TaskEnvelope, TaskResult
        agent = _make_agent()
        envelope = TaskEnvelope(
            task_id="env-1",
            sender="supervisor",
            receiver="test",
            goal="do something",
        )
        result = await agent.handle(envelope)
        assert isinstance(result, TaskResult)

    @pytest.mark.asyncio
    async def test_handle_task_id_preserved(self):
        from agent.core.contracts import TaskEnvelope
        agent = _make_agent()
        envelope = TaskEnvelope(
            task_id="env-42",
            sender="supervisor",
            receiver="test",
            goal="goal",
        )
        result = await agent.handle(envelope)
        assert result.task_id == "env-42"

    @pytest.mark.asyncio
    async def test_handle_status_success(self):
        from agent.core.contracts import TaskEnvelope
        agent = _make_agent()
        envelope = TaskEnvelope(
            task_id="env-3",
            sender="supervisor",
            receiver="test",
            goal="goal",
        )
        result = await agent.handle(envelope)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_handle_summary_contains_goal(self):
        from agent.core.contracts import TaskEnvelope
        agent = _make_agent()
        envelope = TaskEnvelope(
            task_id="env-4",
            sender="supervisor",
            receiver="test",
            goal="my-unique-goal",
        )
        result = await agent.handle(envelope)
        assert "my-unique-goal" in str(result.summary)

    @pytest.mark.asyncio
    async def test_handle_delegation_result_task_id_filled(self):
        """run_task DelegationRequest döndürürse task_id envelope'dan alınır."""
        from agent.core.contracts import TaskEnvelope, DelegationRequest
        from agent.base_agent import BaseAgent
        from config import Config

        class DelegatingAgent(BaseAgent):
            async def run_task(self, task_prompt: str):
                return DelegationRequest(
                    task_id="",  # boş — handle tarafından doldurulmalı
                    reply_to="delegating",
                    target_agent="coder",
                    payload=task_prompt,
                )

        agent = DelegatingAgent(Config(), role_name="delegating")
        envelope = TaskEnvelope(
            task_id="filled-id",
            sender="supervisor",
            receiver="delegating",
            goal="delegate this",
        )
        result = await agent.handle(envelope)
        delegation = result.summary
        assert isinstance(delegation, DelegationRequest)
        assert delegation.task_id == "filled-id"
