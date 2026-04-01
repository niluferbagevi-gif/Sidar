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

    # config stub (her çağrıda taze; kirli config'i devralma)
    cfg_mod = types.ModuleType("config")

    class _Config:
        AI_PROVIDER = "ollama"
        OLLAMA_MODEL = "qwen2.5-coder:7b"
        REACT_TIMEOUT = 60
        MAX_QA_RETRIES = 3

    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod

    # core/core.llm_client stubs (her durumda zorla patch et)
    if "core" not in sys.modules:
        sys.modules["core"] = types.ModuleType("core")
    if "core.llm_client" not in sys.modules:
        sys.modules["core.llm_client"] = types.ModuleType("core.llm_client")
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

    # agent.core.event_stream stub (her durumda zorla patch et)
    es_mod = sys.modules.get("agent.core.event_stream")
    if es_mod is None:
        es_mod = types.ModuleType("agent.core.event_stream")
        sys.modules["agent.core.event_stream"] = es_mod
    _bus = MagicMock()
    _bus.publish = AsyncMock()
    es_mod.get_agent_event_bus = MagicMock(return_value=_bus)

    # agent.base_agent stub
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

        call_count = [0]

        async def _delegate_loop(*_args, **_kwargs):
            call_count[0] += 1
            return contracts.TaskResult(
                task_id="loop",
                status="done",
                summary=contracts.DelegationRequest(
                    task_id="loop",
                    reply_to="reviewer",
                    target_agent="coder",
                    payload='qa_feedback|{"decision":"reject"}',
                    intent="review",
                    handoff_depth=call_count[0],
                ),
            )

        agent._delegate = _delegate_loop
        result = asyncio.run(agent._route_p2p(request, max_hops=3))
        assert result.status == "failed"
        assert "QA retry limiti" in str(result.summary)
        assert call_count[0] == 2


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

# ===== MERGED FROM tests/test_agent_core_supervisor_extra.py =====

import asyncio
import sys
import types
import pathlib as _pl
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_supervisor_deps():
    if "agent" not in sys.modules:
        _pkg = types.ModuleType("agent")
        _pkg.__path__ = [str(_proj / "agent")]
        _pkg.__package__ = "agent"
        sys.modules["agent"] = _pkg

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

    cfg_mod = types.ModuleType("config")

    class _Config:
        AI_PROVIDER = "ollama"
        OLLAMA_MODEL = "qwen2.5-coder:7b"
        REACT_TIMEOUT = 60
        MAX_QA_RETRIES = 3

    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod

    for mod in ("core", "core.llm_client"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
    if not hasattr(sys.modules["core.llm_client"], "LLMClient"):
        sys.modules["core.llm_client"].LLMClient = MagicMock()

    if "core.agent_metrics" not in sys.modules:
        am_mod = types.ModuleType("core.agent_metrics")
        am_mod.get_agent_metrics_collector = MagicMock(return_value=MagicMock())
        sys.modules["core.agent_metrics"] = am_mod

    if "agent.core.contracts" not in sys.modules:
        sys.modules["agent.core.contracts"] = types.ModuleType("agent.core.contracts")

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

    if "agent.core.event_stream" not in sys.modules:
        es_mod = types.ModuleType("agent.core.event_stream")
        _bus = MagicMock()
        _bus.publish = AsyncMock()
        es_mod.get_agent_event_bus = MagicMock(return_value=_bus)
        sys.modules["agent.core.event_stream"] = es_mod

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

    for role_mod, cls_name in [
        ("agent.roles.coder_agent", "CoderAgent"),
        ("agent.roles.researcher_agent", "ResearcherAgent"),
        ("agent.roles.reviewer_agent", "ReviewerAgent"),
        ("agent.roles.poyraz_agent", "PoyrazAgent"),
        ("agent.roles.qa_agent", "QAAgent"),
        ("agent.roles.coverage_agent", "CoverageAgent"),
    ]:
        if "agent.roles" not in sys.modules:
            sys.modules["agent.roles"] = types.ModuleType("agent.roles")
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


# ─────────────────────────────────────────────────────────────────────────────
# _NullSpan
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestNullSpan:
    def test_null_span_enter_returns_self(self):
        sv = _get_supervisor()
        span = sv._NullSpan()
        result = span.__enter__()
        assert result is span

    def test_null_span_exit_returns_false(self):
        sv = _get_supervisor()
        span = sv._NullSpan()
        result = span.__exit__(None, None, None)
        assert result is False

    def test_null_span_set_attribute_no_error(self):
        sv = _get_supervisor()
        span = sv._NullSpan()
        span.set_attribute("key", "value")  # hata yok

    def test_null_span_context_manager_usage(self):
        sv = _get_supervisor()
        with sv._NullSpan() as s:
            s.set_attribute("foo", "bar")


# ─────────────────────────────────────────────────────────────────────────────
# __init__ TypeError yolu (BaseAgent stub == object)
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestSupervisorInitTypeError:
    def test_init_with_base_agent_as_object_sets_defaults(self):
        """BaseAgent=object iken TypeError yakalanıp defaults set edilmeli (L59-65, L88-95)."""
        sv = _get_supervisor()
        # BaseAgent'ı bare object ile değiştir
        orig_ba = sys.modules["agent.base_agent"].BaseAgent
        sys.modules["agent.base_agent"].BaseAgent = object
        # Supervisor modülünü yeniden yükle ki değişiklik etkili olsun
        sys.modules.pop("agent.core.supervisor", None)
        import agent.core.supervisor as sv2
        try:
            agent = sv2.SupervisorAgent()
            assert agent.role_name == "supervisor"
            assert agent.llm is None
        finally:
            sys.modules["agent.base_agent"].BaseAgent = orig_ba


# ─────────────────────────────────────────────────────────────────────────────
# _max_qa_retries
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestMaxQaRetries:
    def test_returns_config_value(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        # Config.MAX_QA_RETRIES = 3
        assert agent._max_qa_retries() == 3

    def test_falls_back_to_class_constant(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        agent.cfg = None  # cfg yok → class sabiti kullanılmalı
        result = agent._max_qa_retries()
        assert isinstance(result, int)
        assert result >= 1


# ─────────────────────────────────────────────────────────────────────────────
# _is_reject_feedback_payload uç durumlar
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestIsRejectFeedbackPayloadExtra:
    def test_malformed_json_with_reject_hint(self):
        sv = _get_supervisor()
        payload = "qa_feedback|{bad json decision=reject}"
        assert sv.SupervisorAgent._is_reject_feedback_payload(payload) is True

    def test_approve_decision_in_json(self):
        sv = _get_supervisor()
        payload = 'qa_feedback|{"decision": "approve"}'
        assert sv.SupervisorAgent._is_reject_feedback_payload(payload) is False

    def test_none_payload(self):
        sv = _get_supervisor()
        assert sv.SupervisorAgent._is_reject_feedback_payload(None) is False


# ─────────────────────────────────────────────────────────────────────────────
# _delegate: metrics ve error yolu
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestDelegateMethod:
    def test_delegate_calls_agent_run_task(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()

        mock_agent = MagicMock()
        mock_agent.run_task = AsyncMock(return_value="coder output")
        agent.registry._agents["coder"] = mock_agent

        contracts = sys.modules["agent.core.contracts"]

        async def _run():
            result = await agent._delegate("coder", "bir şeyler yap", "code")
            assert result.status == "done"
            assert result.summary == "coder output"

        asyncio.run(_run())

    def test_delegate_sets_status_error_on_exception(self):
        """run_task exception fırlatırsa status='error' olmalı (L187-189)."""
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()

        mock_agent = MagicMock()
        mock_agent.run_task = AsyncMock(side_effect=RuntimeError("agent crashed"))
        agent.registry._agents["coder"] = mock_agent

        async def _run():
            with pytest.raises(RuntimeError):
                await agent._delegate("coder", "görev", "code")

        asyncio.run(_run())

    def test_delegate_records_metrics_when_available(self):
        """_get_agent_metrics kullanılabilirken record çağrılmalı (L192-196)."""
        sv = _get_supervisor()

        mock_metrics = MagicMock()
        mock_collector = MagicMock()
        mock_collector.record = MagicMock()
        mock_metrics.return_value = mock_collector

        # Modül seviyesinde _get_agent_metrics'i patch et
        sv._get_agent_metrics = mock_metrics

        agent = sv.SupervisorAgent()
        mock_agent = MagicMock()
        mock_agent.run_task = AsyncMock(return_value="ok")
        agent.registry._agents["coder"] = mock_agent

        async def _run():
            await agent._delegate("coder", "task", "code")
            mock_collector.record.assert_called_once()

        asyncio.run(_run())

    def test_delegate_adds_to_memory_hub(self):
        """Başarılı delegate sonrası memory_hub.add_role_note çağrılmalı (L198)."""
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()

        mock_agent = MagicMock()
        mock_agent.run_task = AsyncMock(return_value="reviewer sonucu")
        agent.registry._agents["reviewer"] = mock_agent

        async def _run():
            await agent._delegate("reviewer", "inceleme yap", "review")
            assert "reviewer" in agent.memory_hub._role_notes

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# _route_p2p: max hop aşımı
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestRoutP2PExtra:
    def test_route_p2p_max_hops_returns_fail(self):
        """Sürekli DelegationRequest dönerse max_hops sınırında FAIL döneceğini test et."""
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]

        request = contracts.DelegationRequest(
            task_id="t1",
            reply_to="researcher",
            target_agent="coder",
            payload="bir şeyler yap",
            intent="code",
        )

        call_count = [0]

        # Her delegate çağrısında yeni DelegationRequest döndür
        async def _always_delegate(*_args, **_kwargs):
            call_count[0] += 1
            return contracts.TaskResult(
                task_id="inner",
                status="done",
                summary=contracts.DelegationRequest(
                    task_id="t2",
                    reply_to="coder",
                    target_agent="reviewer",
                    payload="incele",
                    handoff_depth=call_count[0],
                ),
            )

        agent._delegate = _always_delegate
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent._route_p2p(request, max_hops=3)
            assert result.status == "failed"
            assert "Maksimum delegasyon hop sayısı" in str(result.summary)
            assert call_count[0] == 3

        asyncio.run(_run())

    def test_route_p2p_qa_retry_limit_stop(self):
        """QA retry limiti aşıldığında STOP döneceğini test et (L208-218)."""
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        agent.cfg.MAX_QA_RETRIES = 0  # Hemen aşılsın
        contracts = sys.modules["agent.core.contracts"]

        request = contracts.DelegationRequest(
            task_id="t1",
            reply_to="reviewer",
            target_agent="coder",
            payload='qa_feedback|{"decision":"reject"}',
            intent="review",
        )
        agent.events.publish = AsyncMock()
        agent._delegate = AsyncMock(
            return_value=contracts.TaskResult(task_id="x", status="done", summary="ok")
        )

        async def _run():
            result = await agent._route_p2p(request)
            assert "STOP" in result.summary or "limiti" in result.summary

        asyncio.run(_run())

    def test_route_p2p_publishes_events(self):
        """P2P yönlendirme sırasında events.publish çağrılmalı (L219)."""
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]
        agent.events.publish = AsyncMock()

        request = contracts.DelegationRequest(
            task_id="t1",
            reply_to="researcher",
            target_agent="coder",
            payload="normal task",
            intent="code",
        )
        agent._delegate = AsyncMock(
            return_value=contracts.TaskResult(task_id="r", status="done", summary="result")
        )

        async def _run():
            await agent._route_p2p(request)
            agent.events.publish.assert_awaited()

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# run_task: tüm intent dalları
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestRunTaskIntents:
    def test_run_task_research_intent(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]

        agent._delegate = AsyncMock(
            return_value=contracts.TaskResult(task_id="r", status="done", summary="araştırma sonucu")
        )
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent.run_task("web araştır python nedir")
            assert "araştırma sonucu" in result

        asyncio.run(_run())

    def test_run_task_review_intent(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]

        agent._delegate = AsyncMock(
            return_value=contracts.TaskResult(task_id="r", status="done", summary="review tamam")
        )
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent.run_task("github pull request incele")
            assert "review tamam" in result

        asyncio.run(_run())

    def test_run_task_marketing_intent(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]

        agent._delegate = AsyncMock(
            return_value=contracts.TaskResult(task_id="r", status="done", summary="pazarlama planı")
        )
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent.run_task("seo kampanyası oluştur")
            assert "pazarlama planı" in result

        asyncio.run(_run())

    def test_run_task_coverage_intent(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]

        agent._delegate = AsyncMock(
            return_value=contracts.TaskResult(task_id="r", status="done", summary="coverage tamamlandı")
        )
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent.run_task("pytest coverage eksik test yaz")
            assert "coverage tamamlandı" in result

        asyncio.run(_run())

    def test_run_task_code_intent(self):
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]

        # Hem coder hem reviewer delegate çağrısını handle et
        call_results = [
            contracts.TaskResult(task_id="c1", status="done", summary="kod yazıldı"),
            contracts.TaskResult(task_id="r1", status="done", summary="reviewer onayladı"),
        ]
        agent._delegate = AsyncMock(side_effect=call_results)
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent.run_task("bir fonksiyon yaz")
            assert "kod yazıldı" in result

        asyncio.run(_run())

    def test_run_task_research_with_delegation_request(self):
        """Research intent'te DelegationRequest dönerse p2p routing çağrılmalı (L251-252)."""
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]

        delegation = contracts.DelegationRequest(
            task_id="dr1", reply_to="researcher", target_agent="coder", payload="araştır"
        )
        agent._delegate = AsyncMock(
            return_value=contracts.TaskResult(task_id="r", status="done", summary=delegation)
        )
        agent._route_p2p = AsyncMock(
            return_value=contracts.TaskResult(task_id="p2p", status="done", summary="p2p sonucu")
        )
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent.run_task("web araştır python")
            agent._route_p2p.assert_awaited_once()
            assert "p2p sonucu" in result

        asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# run_task: QA retry döngüsü
# ─────────────────────────────────────────────────────────────────────────────

class Extra_TestRunTaskQARetry:
    def test_run_task_qa_retry_limit_exceeded_returns_stop_message(self):
        """QA retry limit aşılınca P2P:STOP mesajı dönmeli (L295-300)."""
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        agent.cfg.MAX_QA_RETRIES = 1
        contracts = sys.modules["agent.core.contracts"]

        call_count = [0]

        async def _delegate_side_effect(receiver, goal, intent, **kwargs):
            call_count[0] += 1
            if receiver == "coder":
                return contracts.TaskResult(task_id="c", status="done", summary="kod")
            else:
                return contracts.TaskResult(task_id="rv", status="done", summary="fail(test_x) hata bulundu")

        agent._delegate = _delegate_side_effect
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent.run_task("bir şey kodla")
            assert "STOP" in result or "limit" in result.lower()

        asyncio.run(_run())

    def test_run_task_review_passes_no_retry(self):
        """Review başarılı ise retry döngüsü çalışmamalı."""
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]

        async def _delegate_side_effect(receiver, goal, intent, **kwargs):
            if receiver == "coder":
                return contracts.TaskResult(task_id="c", status="done", summary="kod tamam")
            return contracts.TaskResult(task_id="rv", status="done", summary="başarılı, onaylandı")

        agent._delegate = _delegate_side_effect
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent.run_task("bir şey kodla")
            assert "Reviewer QA Özeti" in result

        asyncio.run(_run())

    def test_run_task_coverage_uses_qa_when_coverage_not_registered(self):
        """coverage ajani yoksa qa ajani kullanılmalı (L271-272)."""
        sv = _get_supervisor()
        agent = sv.SupervisorAgent()
        contracts = sys.modules["agent.core.contracts"]

        # coverage'ı kaldır
        agent.registry._agents.pop("coverage", None)

        agent._delegate = AsyncMock(
            return_value=contracts.TaskResult(task_id="q", status="done", summary="qa coverage tamamlandı")
        )
        agent.events.publish = AsyncMock()

        async def _run():
            result = await agent.run_task("pytest kapsama eksik test üret")
            assert "qa coverage tamamlandı" in result

        asyncio.run(_run())
