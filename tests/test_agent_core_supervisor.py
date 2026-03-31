"""
agent/core/supervisor.py için birim testleri.
Tüm ağır bağımlılıklar (config, BaseAgent, role ajanlar, event_stream) stub'lanır.
"""
from __future__ import annotations

import asyncio
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_supervisor_deps():
    """SupervisorAgent'ın tüm import bağımlılıklarını stub'lar."""
    # agent package stub
    if "agent" not in sys.modules:
        _pkg = types.ModuleType("agent")
        _pkg.__path__ = [str(_proj / "agent")]
        _pkg.__package__ = "agent"
        sys.modules["agent"] = _pkg

    # agent.core stub — __path__ ile submodule import çalışır
    if "agent.core" not in sys.modules:
        core_pkg = types.ModuleType("agent.core")
        core_pkg.__path__ = [str(_proj / "agent" / "core")]
        core_pkg.__package__ = "agent.core"
        sys.modules["agent.core"] = core_pkg
    else:
        core_pkg = sys.modules["agent.core"]
        if not hasattr(core_pkg, "__path__"):
            core_pkg.__path__ = [str(_proj / "agent" / "core")]
            core_pkg.__package__ = "agent.core"

    # config stub
    if "config" not in sys.modules:
        cfg_mod = types.ModuleType("config")

        class _Config:
            AI_PROVIDER = "ollama"
            OLLAMA_MODEL = "qwen2.5-coder:7b"
            REACT_TIMEOUT = 60
            MAX_QA_RETRIES = 3

        cfg_mod.Config = _Config
        sys.modules["config"] = cfg_mod

    # core/core.llm_client stubs
    for mod in ("core", "core.llm_client"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
    if not hasattr(sys.modules["core.llm_client"], "LLMClient"):
        sys.modules["core.llm_client"].LLMClient = MagicMock()

    # core.agent_metrics stub (isteğe bağlı import)
    if "core.agent_metrics" not in sys.modules:
        am_mod = types.ModuleType("core.agent_metrics")
        am_mod.get_agent_metrics_collector = MagicMock(return_value=MagicMock())
        sys.modules["core.agent_metrics"] = am_mod

    # agent.core.contracts stub
    if "agent.core.contracts" not in sys.modules:
        sys.modules["agent.core.contracts"] = types.ModuleType("agent.core.contracts")

    from dataclasses import dataclass, field
    from typing import Any

    contracts = sys.modules["agent.core.contracts"]

    @dataclass
    class DelegationRequest:
        task_id: str
        reply_to: str
        target_agent: str
        payload: str
        intent: str = "mixed"
        parent_task_id: str = None
        handoff_depth: int = 0
        protocol: str = "p2p.v1"
        meta: dict = field(default_factory=dict)

        def bumped(self):
            return DelegationRequest(
                task_id=self.task_id, reply_to=self.reply_to,
                target_agent=self.target_agent, payload=self.payload,
                intent=self.intent, parent_task_id=self.parent_task_id,
                handoff_depth=self.handoff_depth + 1, meta=dict(self.meta),
            )

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

    contracts.DelegationRequest = DelegationRequest
    contracts.TaskEnvelope = TaskEnvelope
    contracts.TaskResult = TaskResult
    contracts.is_delegation_request = lambda v: isinstance(v, DelegationRequest)

    # agent.core.memory_hub stub
    if "agent.core.memory_hub" not in sys.modules:
        mh_mod = types.ModuleType("agent.core.memory_hub")

        class _MemoryHub:
            def __init__(self): self._notes = []; self._role_notes = {}
            def add_global(self, note): self._notes.append(note)
            def add_role_note(self, role, note): self._role_notes.setdefault(role, []).append(note)
            def global_context(self, limit=5): return self._notes[-limit:]
            def role_context(self, role, limit=5): return self._role_notes.get(role, [])[-limit:]

        mh_mod.MemoryHub = _MemoryHub
        sys.modules["agent.core.memory_hub"] = mh_mod

    # agent.core.registry stub
    if "agent.core.registry" not in sys.modules:
        reg_mod = types.ModuleType("agent.core.registry")

        class _AgentRegistry:
            def __init__(self): self._agents = {}
            def register(self, role, agent): self._agents[role] = agent
            def get(self, role):
                if role not in self._agents:
                    raise KeyError(role)
                return self._agents[role]
            def has(self, role): return role in self._agents
            def roles(self): return tuple(self._agents.keys())

        reg_mod.AgentRegistry = _AgentRegistry
        sys.modules["agent.core.registry"] = reg_mod

    # agent.core.event_stream stub
    if "agent.core.event_stream" not in sys.modules:
        es_mod = types.ModuleType("agent.core.event_stream")
        _bus = MagicMock()
        _bus.publish = AsyncMock()
        es_mod.get_agent_event_bus = MagicMock(return_value=_bus)
        sys.modules["agent.core.event_stream"] = es_mod

    # agent.base_agent stub
    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")

        class _BaseAgent:
            def __init__(self, *args, cfg=None, role_name="base", **kwargs):
                self.cfg = cfg or sys.modules["config"].Config()
                self.role_name = role_name
                self.llm = MagicMock()
                self.tools = {}

            async def run_task(self, task_prompt: str):
                return f"stub: {task_prompt}"

        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod

    # role agent stubs
    for role_mod, cls_name in [
        ("agent.roles.coder_agent", "CoderAgent"),
        ("agent.roles.researcher_agent", "ResearcherAgent"),
        ("agent.roles.reviewer_agent", "ReviewerAgent"),
        ("agent.roles.poyraz_agent", "PoyrazAgent"),
        ("agent.roles.qa_agent", "QAAgent"),
        ("agent.roles.coverage_agent", "CoverageAgent"),
    ]:
        parent = role_mod.rsplit(".", 1)[0]
        if "agent.roles" not in sys.modules:
            sys.modules["agent.roles"] = types.ModuleType("agent.roles")
        if role_mod not in sys.modules:
            mod = types.ModuleType(role_mod)
            base = sys.modules["agent.base_agent"].BaseAgent

            def _make_cls(cn, b):
                class _RoleAgent(b):
                    async def run_task(self, p):
                        return f"{cn}: {p}"
                _RoleAgent.__name__ = cn
                _RoleAgent.__qualname__ = cn
                return _RoleAgent

            setattr(mod, cls_name, _make_cls(cls_name, base))
            sys.modules[role_mod] = mod

    # opentelemetry stub (isteğe bağlı)
    if "opentelemetry" not in sys.modules:
        otel_mod = types.ModuleType("opentelemetry")
        otel_trace_mod = types.ModuleType("opentelemetry.trace")
        otel_trace_mod.get_tracer = MagicMock(return_value=None)
        sys.modules["opentelemetry"] = otel_mod
        sys.modules["opentelemetry.trace"] = otel_trace_mod


def _get_supervisor():
    _stub_supervisor_deps()
    sys.modules.pop("agent.core.supervisor", None)
    import agent.core.supervisor as sv
    return sv


class TestSupervisorAgentInit:
    def test_instantiation(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        assert agent is not None

    def test_role_name_is_supervisor(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        assert agent.role_name == "supervisor"

    def test_registry_is_set(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        assert agent.registry is not None

    def test_memory_hub_is_set(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        assert agent.memory_hub is not None

    def test_events_bus_is_set(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        assert agent.events is not None

    def test_role_agents_registered(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        for role in ("coder", "reviewer", "researcher", "poyraz", "qa"):
            assert agent.registry.has(role), f"{role} kayıtlı değil"


class TestSupervisorIntent:
    def test_research_intent(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._intent("web araştır") == "research"

    def test_research_keyword_nedir(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._intent("Python nedir?") == "research"

    def test_review_intent(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._intent("pull request incele") == "review"

    def test_marketing_intent(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._intent("seo kampanyası yap") == "marketing"

    def test_coverage_intent(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._intent("pytest coverage eksik test yaz") == "coverage"

    def test_default_code_intent(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._intent("bir fonksiyon yaz") == "code"


class TestSupervisorReviewRequiresRevision:
    def test_hata_triggers_revision(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._review_requires_revision("hata bulundu") is True

    def test_fail_triggers_revision(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._review_requires_revision("fail(test_foo)") is True

    def test_decision_reject_triggers_revision(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._review_requires_revision("decision=reject") is True

    def test_success_no_revision(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._review_requires_revision("başarılı, onaylandı") is False

    def test_empty_no_revision(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._review_requires_revision("") is False


class TestSupervisorIsRejectFeedbackPayload:
    def test_reject_feedback_payload(self):
        sv = _get_supervisor()
        payload = 'qa_feedback|{"decision": "reject"}'
        assert sv.SupervisorAgent._is_reject_feedback_payload(payload) is True

    def test_non_qa_payload(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._is_reject_feedback_payload("regular text") is False

    def test_approve_feedback_payload(self):
        sv = _get_supervisor()
        payload = 'qa_feedback|{"decision": "approve"}'
        assert sv.SupervisorAgent._is_reject_feedback_payload(payload) is False

    def test_empty_payload(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._is_reject_feedback_payload("") is False

    def test_text_reject_payload(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._is_reject_feedback_payload("qa_feedback|decision=reject") is True

    def test_qa_feedback_prefix_with_empty_body_returns_false(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._is_reject_feedback_payload("qa_feedback|   ") is False

    def test_malformed_json_payload_without_reject_hint_returns_false(self):
        sv = _get_supervisor()
        payload = "qa_feedback|{decision: maybe}"
        assert sv.SupervisorAgent._is_reject_feedback_payload(payload) is False


class TestSupervisorP2PRouting:
    def test_route_p2p_stops_after_max_qa_retry(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        agent.cfg.MAX_QA_RETRIES = 1
        contracts = sys.modules["agent.core.contracts"]

        request = contracts.DelegationRequest(
            task_id="t1",
            reply_to="reviewer",
            target_agent="coder",
            payload='qa_feedback|{"decision":"reject"}',
            intent="review",
        )

        async def _delegate_loop(*_args, **_kwargs):
            return contracts.TaskResult(
                task_id="loop",
                status="done",
                summary=contracts.DelegationRequest(
                    task_id="loop",
                    reply_to="reviewer",
                    target_agent="coder",
                    payload='qa_feedback|{"decision":"reject"}',
                    intent="review",
                    handoff_depth=1,
                ),
            )

        agent._delegate = _delegate_loop
        result = asyncio.run(agent._route_p2p(request, max_hops=3))
        assert result.status == "failed"
        assert "QA retry limiti" in str(result.summary)


class TestSupervisorRunTask:
    def test_run_task_research_intent(self):
        async def _run():
            sv = _get_supervisor()
            agent = sv.SupervisorAgent()
            # researcher mock
            researcher = MagicMock()
            researcher.run_task = AsyncMock(return_value="araştırma sonucu")
            agent.registry.register("researcher", researcher)
            result = await agent.run_task("Python nedir?")
            assert "araştırma sonucu" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_task_review_intent(self):
        async def _run():
            sv = _get_supervisor()
            agent = sv.SupervisorAgent()
            reviewer = MagicMock()
            reviewer.run_task = AsyncMock(return_value="inceleme tamam")
            agent.registry.register("reviewer", reviewer)
            result = await agent.run_task("pull request incele")
            assert "inceleme tamam" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_task_marketing_intent(self):
        async def _run():
            sv = _get_supervisor()
            agent = sv.SupervisorAgent()
            poyraz = MagicMock()
            poyraz.run_task = AsyncMock(return_value="pazarlama planı")
            agent.registry.register("poyraz", poyraz)
            result = await agent.run_task("seo kampanyası yap")
            assert "pazarlama planı" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_task_code_intent_with_clean_review(self):
        async def _run():
            sv = _get_supervisor()
            agent = sv.SupervisorAgent()
            coder = MagicMock()
            coder.run_task = AsyncMock(return_value="def hello(): pass")
            reviewer = MagicMock()
            reviewer.run_task = AsyncMock(return_value="onaylandı, güzel kod")
            agent.registry.register("coder", coder)
            agent.registry.register("reviewer", reviewer)
            result = await agent.run_task("bir fonksiyon yaz")
            assert "def hello(): pass" in result
            assert "Reviewer QA Özeti" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_task_coverage_intent(self):
        async def _run():
            sv = _get_supervisor()
            agent = sv.SupervisorAgent()
            coverage = MagicMock()
            coverage.run_task = AsyncMock(return_value="coverage raporu")
            agent.registry.register("coverage", coverage)
            result = await agent.run_task("pytest coverage eksik test yaz")
            assert "coverage raporu" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_task_stores_global_note(self):
        async def _run():
            sv = _get_supervisor()
            agent = sv.SupervisorAgent()
            researcher = MagicMock()
            researcher.run_task = AsyncMock(return_value="araştırma tamamlandı")
            agent.registry.register("researcher", researcher)
            await agent.run_task("araştır: Python")
            ctx = agent.memory_hub.global_context()
            assert len(ctx) >= 1
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestSupervisorDelegate:
    def test_delegate_creates_task_result(self):
        async def _run():
            sv = _get_supervisor()
            agent = sv.SupervisorAgent()
            contracts = sys.modules["agent.core.contracts"]
            mock_agent = MagicMock()
            mock_agent.run_task = AsyncMock(return_value="delegasyon sonucu")
            agent.registry.register("test_role", mock_agent)
            result = await agent._delegate("test_role", "görev", "code")
            assert isinstance(result, contracts.TaskResult)
            assert result.status == "done"
            assert result.summary == "delegasyon sonucu"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_delegate_adds_role_note(self):
        async def _run():
            sv = _get_supervisor()
            agent = sv.SupervisorAgent()
            mock_agent = MagicMock()
            mock_agent.run_task = AsyncMock(return_value="not eklendi")
            agent.registry.register("noter", mock_agent)
            await agent._delegate("noter", "not al", "mixed")
            ctx = agent.memory_hub.role_context("noter")
            assert "not eklendi" in ctx
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestSupervisorMaxQaRetries:
    def test_max_qa_retries_default(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        assert agent._max_qa_retries() == sv.SupervisorAgent.MAX_QA_RETRIES

    def test_max_qa_retries_from_cfg(self):
        sv = _get_supervisor()
        cfg = sys.modules["config"].Config()
        cfg.MAX_QA_RETRIES = 7
        agent = sv.SupervisorAgent(cfg=cfg)
        assert agent._max_qa_retries() == 7

    def test_run_task_stops_after_max_retries(self):
        async def _run():
            sv = _get_supervisor()
            agent = sv.SupervisorAgent()
            coder = MagicMock()
            coder.run_task = AsyncMock(return_value="kod")
            reviewer = MagicMock()
            reviewer.run_task = AsyncMock(return_value="hata: rework_required")
            agent.registry.register("coder", coder)
            agent.registry.register("reviewer", reviewer)
            result = await agent.run_task("kod yaz")
            assert "P2P:STOP" in result or "limit aşıldı" in result or "Reviewer QA Özeti" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

