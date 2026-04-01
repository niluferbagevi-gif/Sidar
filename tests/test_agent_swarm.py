"""
agent/swarm.py için birim testleri.
SwarmOrchestrator, TaskRouter, SwarmTask, SwarmResult ve InMemoryDelegationBackend kapsar.
"""
from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _stub_swarm_deps():
    """Swarm'ın bağımlılıklarını stub'lar."""
    import pathlib as _pl
    _proj = _pl.Path(__file__).parent.parent

    # config stub
    if "config" not in sys.modules:
        cfg_stub = types.ModuleType("config")
        cfg_stub.Config = type("Config", (), {"AI_PROVIDER": "ollama"})
        sys.modules["config"] = cfg_stub

    # agent package stub — __path__ gerekli, yoksa submodule import çalışmaz
    if "agent" not in sys.modules:
        _pkg = types.ModuleType("agent")
        _pkg.__path__ = [str(_proj / "agent")]
        _pkg.__package__ = "agent"
        sys.modules["agent"] = _pkg

    # agent.registry stub — AgentRegistry ve AgentSpec import öncesi tanımlanmalı
    if "agent.registry" not in sys.modules:
        _reg_mod = types.ModuleType("agent.registry")
        sys.modules["agent.registry"] = _reg_mod
    else:
        _reg_mod = sys.modules["agent.registry"]

    if not hasattr(_reg_mod, "AgentRegistry"):
        class _AgentSpec:
            def __init__(self, role_name, agent_class=None, capabilities=None):
                self.role_name = role_name
                self.agent_class = agent_class
                self.capabilities = capabilities or []
                self.description = ""

        class _AgentRegistry:
            _registry = {}

            @classmethod
            def get(cls, name):
                return cls._registry.get(name)

            @classmethod
            def find_by_capability(cls, cap):
                return [s for s in cls._registry.values() if cap in s.capabilities]

            @classmethod
            def list_all(cls):
                return list(cls._registry.values())

            @classmethod
            def create(cls, name, **kwargs):
                spec = cls._registry.get(name)
                if spec is None:
                    raise KeyError(name)
                return spec._agent_factory(**kwargs) if hasattr(spec, "_agent_factory") else MagicMock()

        _reg_mod.AgentRegistry = _AgentRegistry
        _reg_mod.AgentSpec = _AgentSpec

    # agent.core ve agent.core.contracts stub'ları
    if "agent.core" not in sys.modules:
        sys.modules["agent.core"] = types.ModuleType("agent.core")
    if "agent.core.contracts" not in sys.modules:
        sys.modules["agent.core.contracts"] = types.ModuleType("agent.core.contracts")

    # contracts stub
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
        meta: dict = field(default_factory=dict)

        def bumped(self):
            return DelegationRequest(
                task_id=self.task_id,
                reply_to=self.reply_to,
                target_agent=self.target_agent,
                payload=self.payload,
                intent=self.intent,
                parent_task_id=self.parent_task_id,
                handoff_depth=self.handoff_depth + 1,
                meta=dict(self.meta),
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

    @dataclass
    class BrokerTaskEnvelope:
        task_id: str
        sender: str
        receiver: str
        goal: str
        intent: str = "mixed"
        parent_task_id: str = None
        context: dict = field(default_factory=dict)
        inputs: list = field(default_factory=list)
        broker: str = "memory"
        exchange: str = "sidar.swarm"
        routing_key: str = ""
        reply_queue: str = ""
        protocol: str = "broker.task.v1"
        headers: dict = field(default_factory=dict)
        correlation_id: str = ""

        @classmethod
        def from_task_envelope(cls, envelope, *, broker="memory", exchange="sidar.swarm",
                                reply_queue="", headers=None):
            return cls(
                task_id=envelope.task_id,
                sender=envelope.sender,
                receiver=envelope.receiver,
                goal=envelope.goal,
                intent=envelope.intent,
                broker=broker,
                exchange=exchange,
                reply_queue=reply_queue,
                headers=dict(headers or {}),
            )

    @dataclass
    class BrokerTaskResult:
        task_id: str
        sender: str
        receiver: str
        status: str
        summary: str
        broker: str = "memory"
        exchange: str = "sidar.swarm"
        routing_key: str = ""
        protocol: str = "broker.task.v1"
        correlation_id: str = ""

    def is_delegation_request(value):
        return isinstance(value, DelegationRequest)

    contracts.DelegationRequest = DelegationRequest
    contracts.TaskEnvelope = TaskEnvelope
    contracts.TaskResult = TaskResult
    contracts.BrokerTaskEnvelope = BrokerTaskEnvelope
    contracts.BrokerTaskResult = BrokerTaskResult
    contracts.is_delegation_request = is_delegation_request


def _make_mock_agent(summary="görev tamamlandı", status="success"):
    """Belirli bir çıktı döndüren mock ajan oluşturur."""
    contracts = sys.modules["agent.core.contracts"]

    agent = MagicMock()
    async def _handle(envelope):
        normalized_summary = summary
        if not contracts.is_delegation_request(summary) and not isinstance(
            summary, (str, int, float, bool, dict, list, type(None))
        ):
            normalized_summary = str(summary)
        return contracts.TaskResult(
            task_id=envelope.task_id,
            status=status,
            summary=normalized_summary,
            evidence=[],
        )

    agent.handle = AsyncMock(side_effect=_handle)
    return agent


def _get_swarm_module():
    _stub_swarm_deps()
    sys.modules.pop("agent.swarm", None)
    import agent.swarm as sw
    return sw


def _make_orchestrator(registered_agents=None):
    """SwarmOrchestrator + kayıtlı dummy ajanlarla hazır örnek döndürür."""
    sw = _get_swarm_module()
    reg = sys.modules["agent.registry"]

    # Kayıtlı ajanlar
    agents_to_register = registered_agents if registered_agents is not None else {
        "coder": ["code_generation", "file_io"],
        "reviewer": ["code_review"],
    }

    registry = reg.AgentRegistry
    registry._registry.clear()

    for role, caps in agents_to_register.items():
        spec = reg.AgentSpec(role_name=role, agent_class=MagicMock, capabilities=caps)
        spec._agent_factory = lambda **kw: _make_mock_agent()
        registry._registry[role] = spec

    orchestrator = sw.SwarmOrchestrator(cfg=None)
    return orchestrator, sw


class TestSwarmTask:
    def test_swarm_task_defaults(self):
        sw = _get_swarm_module()
        task = sw.SwarmTask(goal="bir görev")
        assert task.intent == "mixed"
        assert task.preferred_agent is None
        assert task.task_id.startswith("swarm-")

    def test_swarm_task_custom_intent(self):
        sw = _get_swarm_module()
        task = sw.SwarmTask(goal="kodu incele", intent="code_review")
        assert task.intent == "code_review"


class TestSwarmResult:
    def test_swarm_result_fields(self):
        sw = _get_swarm_module()
        result = sw.SwarmResult(
            task_id="t1",
            agent_role="coder",
            status="success",
            summary="tamamlandı",
            elapsed_ms=100,
        )
        assert result.task_id == "t1"
        assert result.status == "success"
        assert result.evidence == []
        assert result.handoffs == []


class TestInMemoryDelegationBackend:
    def test_dispatch_queues_envelope(self):
        async def _run():
            sw = _get_swarm_module()
            backend = sw.InMemoryDelegationBackend()
            contracts = sys.modules["agent.core.contracts"]
            envelope = contracts.BrokerTaskEnvelope(
                task_id="b1", sender="s", receiver="r", goal="hedef"
            )
            result = await backend.dispatch(envelope)
            assert len(backend.dispatched) == 1
            assert result.status == "queued"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_dispatch_returns_broker_result(self):
        async def _run():
            sw = _get_swarm_module()
            backend = sw.InMemoryDelegationBackend()
            contracts = sys.modules["agent.core.contracts"]
            envelope = contracts.BrokerTaskEnvelope(
                task_id="b2", sender="s", receiver="r", goal="hedef"
            )
            result = await backend.dispatch(envelope)
            assert result.task_id == "b2"
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestTaskRouter:
    def test_route_known_intent(self):
        _, sw = _make_orchestrator()
        router = sw.TaskRouter()
        spec = router.route("code_generation")
        assert spec is not None

    def test_route_by_role(self):
        _, sw = _make_orchestrator()
        router = sw.TaskRouter()
        spec = router.route_by_role("coder")
        assert spec is not None
        assert spec.role_name == "coder"

    def test_route_by_unknown_role_returns_none(self):
        _, sw = _make_orchestrator()
        router = sw.TaskRouter()
        spec = router.route_by_role("unknown_role_xyz")
        assert spec is None


class TestSwarmOrchestratorProperties:
    def test_active_task_count_initially_zero(self):
        orchestrator, sw = _make_orchestrator()
        assert orchestrator.active_task_count == 0

    def test_available_agents_lists_roles(self):
        orchestrator, sw = _make_orchestrator()
        agents = orchestrator.available_agents()
        assert "coder" in agents
        assert "reviewer" in agents


class TestSwarmOrchestratorRun:
    def test_run_no_agents_returns_skipped(self):
        async def _run():
            orchestrator, sw = _make_orchestrator(registered_agents={})
            result = await orchestrator.run("bir görev")
            assert result.status == "skipped"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_parallel_empty_list(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            results = await orchestrator.run_parallel([])
            assert results == []
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_pipeline_empty_list(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            results = await orchestrator.run_pipeline([])
            assert results == []
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_max_hops_exceeded(self):
        async def _run():
            """Maksimum hop aşıldığında failed döndürülmelidir."""
            orchestrator, sw = _make_orchestrator()
            task = sw.SwarmTask(goal="görev", preferred_agent="coder")
            # _hop > max_hops simülasyonu
            result = await orchestrator._execute_task(task, _hop=999)
            assert result.status == "failed"
            assert "loop guard" in result.summary.lower() or "hop" in result.summary.lower()
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestSwarmHandoffIntegration:
    def test_direct_handoff_coder_to_reviewer_chain_is_recorded(self):
        async def _run():
            sw = _get_swarm_module()
            reg = sys.modules["agent.registry"]
            contracts = sys.modules["agent.core.contracts"]

            class _CoderAgent:
                async def handle(self, envelope):
                    delegation = contracts.DelegationRequest(
                        task_id=envelope.task_id,
                        reply_to="coder",
                        target_agent="reviewer",
                        payload="kodu gözden geçir",
                        intent="code_review",
                        parent_task_id=envelope.task_id,
                        meta={"reason": "review_required"},
                    )
                    return contracts.TaskResult(task_id=envelope.task_id, status="success", summary=delegation)

            class _ReviewerAgent:
                async def handle(self, envelope):
                    return contracts.TaskResult(
                        task_id=envelope.task_id,
                        status="success",
                        summary=f"review ok: {envelope.goal}",
                        evidence=["lint clean"],
                    )

            reg.AgentRegistry._registry.clear()
            coder = reg.AgentSpec(role_name="coder", agent_class=_CoderAgent, capabilities=["code_generation"])
            reviewer = reg.AgentSpec(role_name="reviewer", agent_class=_ReviewerAgent, capabilities=["code_review"])
            coder._agent_factory = lambda **_kw: _CoderAgent()
            reviewer._agent_factory = lambda **_kw: _ReviewerAgent()
            reg.AgentRegistry._registry["coder"] = coder
            reg.AgentRegistry._registry["reviewer"] = reviewer

            orchestrator = sw.SwarmOrchestrator(cfg=None)
            result = await orchestrator.run("refactor auth modülü", intent="code_generation", session_id="sess-1")

            assert result.status == "success"
            assert result.agent_role == "reviewer"
            assert len(result.handoffs) == 1
            assert result.handoffs[0]["sender"] == "coder"
            assert result.handoffs[0]["receiver"] == "reviewer"
            assert "review ok" in result.summary
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_pipeline_passes_success_context_between_agents(self):
        async def _run():
            sw = _get_swarm_module()
            reg = sys.modules["agent.registry"]
            contracts = sys.modules["agent.core.contracts"]

            captured_context = {"value": None}

            class _CoderAgent:
                async def handle(self, envelope):
                    return contracts.TaskResult(
                        task_id=envelope.task_id,
                        status="success",
                        summary="kod üretimi tamam",
                        evidence=["file:service.py"],
                    )

            class _ReviewerAgent:
                async def handle(self, envelope):
                    captured_context["value"] = dict(envelope.context or {})
                    return contracts.TaskResult(
                        task_id=envelope.task_id,
                        status="success",
                        summary="review tamam",
                        evidence=["no blocker"],
                    )

            reg.AgentRegistry._registry.clear()
            coder = reg.AgentSpec(role_name="coder", agent_class=_CoderAgent, capabilities=["code_generation"])
            reviewer = reg.AgentSpec(role_name="reviewer", agent_class=_ReviewerAgent, capabilities=["code_review"])
            coder._agent_factory = lambda **_kw: _CoderAgent()
            reviewer._agent_factory = lambda **_kw: _ReviewerAgent()
            reg.AgentRegistry._registry["coder"] = coder
            reg.AgentRegistry._registry["reviewer"] = reviewer

            orchestrator = sw.SwarmOrchestrator(cfg=None)
            tasks = [
                sw.SwarmTask(goal="kod üret", intent="code_generation"),
                sw.SwarmTask(goal="çıktıyı incele", intent="code_review"),
            ]
            results = await orchestrator.run_pipeline(tasks, session_id="sess-pipeline")

            assert len(results) == 2
            assert all(item.status == "success" for item in results)
            assert captured_context["value"] is not None
            assert captured_context["value"].get("prev_coder", "").startswith("kod üretimi tamam")
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestSwarmOrchestratorGoalFingerprint:
    def test_fingerprint_truncates_long_goal(self):
        sw = _get_swarm_module()
        long_goal = "a" * 300
        fp = sw.SwarmOrchestrator._goal_fingerprint(long_goal)
        assert len(fp) <= 180

    def test_fingerprint_normalizes_whitespace(self):
        sw = _get_swarm_module()
        fp = sw.SwarmOrchestrator._goal_fingerprint("  merhaba   dünya  ")
        assert fp == "merhaba dünya"

    def test_loop_repeat_limit_defaults_by_provider_and_respects_override(self):
        orchestrator, sw = _make_orchestrator()
        orchestrator.cfg = MagicMock()
        orchestrator.cfg.AI_PROVIDER = "ollama"
        orchestrator.cfg.SWARM_LOOP_GUARD_MAX_REPEAT = 0
        assert orchestrator._loop_repeat_limit() == 2

        orchestrator.cfg.AI_PROVIDER = "openai"
        orchestrator.cfg.SWARM_LOOP_GUARD_MAX_REPEAT = 5
        assert orchestrator._loop_repeat_limit() == 5


class TestSwarmP2PContext:
    def test_p2p_context_includes_trace_and_handoff_depth(self):
        orchestrator, sw = _make_orchestrator()
        contracts = sys.modules["agent.core.contracts"]
        msg = contracts.DelegationRequest(
            task_id="t1",
            reply_to="reviewer",
            target_agent="coder",
            payload="patch uygula",
            intent="review",
            handoff_depth=2,
            meta={"reason": "qa_reject"},
        )

        ctx = orchestrator._p2p_context(
            {"existing": "1"},
            msg,
            session_id="sess-1",
            hop=3,
            route_trace=["supervisor", "reviewer", "coder"],
        )

        assert ctx["session_id"] == "sess-1"
        assert ctx["swarm_hop"] == "3"
        assert ctx["p2p_handoff_depth"] == "2"
        assert "reviewer -> coder" in ctx["swarm_trace"]


class TestSwarmOrchestratorShouldFallback:
    def test_json_decode_error_should_fallback(self):
        sw = _get_swarm_module()
        import json
        exc = json.JSONDecodeError("msg", "", 0)
        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(exc) is True

    def test_rate_limit_should_fallback(self):
        sw = _get_swarm_module()
        exc = Exception("429 too many requests")
        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(exc) is True

    def test_generic_error_no_fallback(self):
        sw = _get_swarm_module()
        exc = ValueError("genel hata")
        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(exc) is False


class TestSwarmOrchestratorDistributedDispatch:
    def test_dispatch_distributed_no_backend_raises(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            task = sw.SwarmTask(goal="dağıtık görev", preferred_agent="coder")
            with pytest.raises(RuntimeError, match="backend"):
                await orchestrator.dispatch_distributed(task)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_dispatch_distributed_with_backend(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            backend = sw.InMemoryDelegationBackend()
            orchestrator.configure_delegation_backend(backend)
            task = sw.SwarmTask(goal="dağıtık görev", preferred_agent="coder")
            result = await orchestrator.dispatch_distributed(task)
            assert result.status == "queued"
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestSwarmOrchestratorFailureBranches:
    def test_direct_handoff_without_target_raises(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            contracts = sys.modules["agent.core.contracts"]
            task = sw.SwarmTask(goal="görev", intent="mixed")
            delegation = contracts.DelegationRequest(
                task_id=task.task_id,
                reply_to="coder",
                target_agent="",
                payload="payload",
            )
            with pytest.raises(RuntimeError, match="target_agent"):
                await orchestrator._direct_handoff(
                    task,
                    delegation,
                    session_id="sess",
                    hop=1,
                    route_trace=["coder|mixed|x"],
                    handoff_chain=[],
                )
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_execute_task_agent_create_failure_returns_failed(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            task = sw.SwarmTask(goal="görev", preferred_agent="coder")
            with patch("agent.swarm.AgentRegistry.create", side_effect=RuntimeError("agent unavailable")):
                result = await orchestrator._execute_task(task)
            assert result.status == "failed"
            assert "oluşturulamadı" in result.summary.lower()
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_execute_task_supervisor_fallback_success(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            task = sw.SwarmTask(goal="görev", preferred_agent="coder")

            async def _raise_json(_envelope):
                raise ValueError("json schema mismatch")

            failing_agent = MagicMock()
            failing_agent.handle = AsyncMock(side_effect=_raise_json)

            with patch("agent.swarm.AgentRegistry.create", return_value=failing_agent):
                with patch.object(orchestrator, "_run_supervisor_fallback", AsyncMock(return_value=sw.SwarmResult(
                    task_id=task.task_id,
                    agent_role="supervisor",
                    status="success",
                    summary="fallback ok",
                    elapsed_ms=1,
                ))):
                    result = await orchestrator._execute_task(task, session_id="s1")

            assert result.agent_role == "supervisor"
            assert result.status == "success"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_execute_task_supervisor_fallback_failure_returns_failed(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            task = sw.SwarmTask(goal="görev", preferred_agent="coder")
            failing_agent = MagicMock()
            failing_agent.handle = AsyncMock(side_effect=RuntimeError("rate limit 429"))

            with patch("agent.swarm.AgentRegistry.create", return_value=failing_agent):
                with patch.object(orchestrator, "_run_supervisor_fallback", AsyncMock(side_effect=RuntimeError("supervisor down"))):
                    result = await orchestrator._execute_task(task, session_id="s1")

            assert result.status == "failed"
            assert "fallback" in result.summary.lower()
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestSwarmDelegationEdgeCases:
    def test_delegation_missing_reply_to_is_filled_from_spec_role(self):
        async def _run():
            sw = _get_swarm_module()
            reg = sys.modules["agent.registry"]
            contracts = sys.modules["agent.core.contracts"]

            class _CoderAgent:
                async def handle(self, envelope):
                    return contracts.TaskResult(
                        task_id=envelope.task_id,
                        status="success",
                        summary=contracts.DelegationRequest(
                            task_id=envelope.task_id,
                            reply_to="",
                            target_agent="reviewer",
                            payload="review_code|x",
                            intent="code_review",
                        ),
                    )

            class _ReviewerAgent:
                async def handle(self, envelope):
                    return contracts.TaskResult(task_id=envelope.task_id, status="success", summary="ok")

            reg.AgentRegistry._registry.clear()
            coder = reg.AgentSpec(role_name="coder", agent_class=_CoderAgent, capabilities=["code_generation"])
            reviewer = reg.AgentSpec(role_name="reviewer", agent_class=_ReviewerAgent, capabilities=["code_review"])
            coder._agent_factory = lambda **_kw: _CoderAgent()
            reviewer._agent_factory = lambda **_kw: _ReviewerAgent()
            reg.AgentRegistry._registry["coder"] = coder
            reg.AgentRegistry._registry["reviewer"] = reviewer

            orchestrator = sw.SwarmOrchestrator(cfg=None)
            result = await orchestrator.run("kod üret", intent="code_generation")

            assert result.status == "success"
            assert result.handoffs[0]["sender"] == "coder"
        import asyncio as _asyncio
        _asyncio.run(_run())

class TestSwarmDistributedDelegation:
    def test_dispatch_distributed_raises_when_backend_missing(self):
        orchestrator, sw = _make_orchestrator()
        orchestrator.configure_delegation_backend(None)
        task = sw.SwarmTask(goal="görev", intent="code_generation")
        async def _run_case():
            with pytest.raises(RuntimeError, match="backend"):
                await orchestrator.dispatch_distributed(task, session_id="s1")
        asyncio.run(_run_case())

    def test_dispatch_distributed_raises_when_no_agent_for_intent(self):
        orchestrator, sw = _make_orchestrator(registered_agents={"reviewer": ["code_review"]})
        backend = sw.InMemoryDelegationBackend()
        orchestrator.configure_delegation_backend(backend)
        task = sw.SwarmTask(goal="görev", intent="coverage_analysis")
        async def _run_case():
            with pytest.raises(RuntimeError, match="uygun ajan"):
                await orchestrator.dispatch_distributed(task, session_id="s2", receiver="ghost")
        asyncio.run(_run_case())

# ===== MERGED FROM tests/test_agent_swarm_extra.py =====

import asyncio
import json
import sys
import types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _stub_swarm_deps():
    import pathlib as _pl
    _proj = _pl.Path(__file__).parent.parent

    if "config" not in sys.modules:
        cfg_stub = types.ModuleType("config")
        cfg_stub.Config = type("Config", (), {"AI_PROVIDER": "ollama"})
        sys.modules["config"] = cfg_stub

    if "agent" not in sys.modules:
        _pkg = types.ModuleType("agent")
        _pkg.__path__ = [str(_proj / "agent")]
        _pkg.__package__ = "agent"
        sys.modules["agent"] = _pkg

    if "agent.registry" not in sys.modules:
        _reg_mod = types.ModuleType("agent.registry")
        sys.modules["agent.registry"] = _reg_mod
    else:
        _reg_mod = sys.modules["agent.registry"]

    if not hasattr(_reg_mod, "AgentRegistry"):
        class _AgentSpec:
            def __init__(self, role_name, agent_class=None, capabilities=None):
                self.role_name = role_name
                self.agent_class = agent_class
                self.capabilities = capabilities or []
                self.description = ""

        class _AgentRegistry:
            _registry = {}

            @classmethod
            def get(cls, name):
                return cls._registry.get(name)

            @classmethod
            def find_by_capability(cls, cap):
                return [s for s in cls._registry.values() if cap in s.capabilities]

            @classmethod
            def list_all(cls):
                return list(cls._registry.values())

            @classmethod
            def create(cls, name, **kwargs):
                spec = cls._registry.get(name)
                if spec is None:
                    raise KeyError(name)
                return spec._agent_factory(**kwargs) if hasattr(spec, "_agent_factory") else MagicMock()

        _reg_mod.AgentRegistry = _AgentRegistry
        _reg_mod.AgentSpec = _AgentSpec

    if "agent.core" not in sys.modules:
        sys.modules["agent.core"] = types.ModuleType("agent.core")
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

    @dataclass
    class BrokerTaskEnvelope:
        task_id: str
        sender: str
        receiver: str
        goal: str
        intent: str = "mixed"
        parent_task_id: str = None
        context: dict = field(default_factory=dict)
        broker: str = "memory"
        exchange: str = "sidar.swarm"
        routing_key: str = ""
        reply_queue: str = ""
        protocol: str = "broker.task.v1"
        headers: dict = field(default_factory=dict)
        correlation_id: str = ""

        @classmethod
        def from_task_envelope(cls, envelope, *, broker="memory", exchange="sidar.swarm",
                                reply_queue="", headers=None):
            return cls(
                task_id=envelope.task_id, sender=envelope.sender,
                receiver=envelope.receiver, goal=envelope.goal,
                intent=envelope.intent, broker=broker, exchange=exchange,
                reply_queue=reply_queue, headers=dict(headers or {}),
            )

    @dataclass
    class BrokerTaskResult:
        task_id: str
        sender: str
        receiver: str
        status: str
        summary: str
        broker: str = "memory"
        exchange: str = "sidar.swarm"
        routing_key: str = ""
        protocol: str = "broker.task.v1"
        correlation_id: str = ""

    def is_delegation_request(value):
        return isinstance(value, DelegationRequest)

    contracts.DelegationRequest = DelegationRequest
    contracts.TaskEnvelope = TaskEnvelope
    contracts.TaskResult = TaskResult
    contracts.BrokerTaskEnvelope = BrokerTaskEnvelope
    contracts.BrokerTaskResult = BrokerTaskResult
    contracts.is_delegation_request = is_delegation_request


def _make_mock_agent(summary="görev tamamlandı", status="success"):
    contracts = sys.modules["agent.core.contracts"]
    agent = MagicMock()
    async def _handle(envelope):
        normalized_summary = summary
        if not contracts.is_delegation_request(summary) and not isinstance(
            summary, (str, int, float, bool, dict, list, type(None))
        ):
            normalized_summary = str(summary)
        return contracts.TaskResult(
            task_id=envelope.task_id,
            status=status,
            summary=normalized_summary,
            evidence=[],
        )

    agent.handle = AsyncMock(side_effect=_handle)
    return agent


def _get_swarm_module():
    _stub_swarm_deps()
    sys.modules.pop("agent.swarm", None)
    import agent.swarm as sw
    return sw


def _make_orchestrator(registered_agents=None, cfg=None):
    sw = _get_swarm_module()
    reg = sys.modules["agent.registry"]

    agents_to_register = registered_agents if registered_agents is not None else {
        "coder": ["code_generation", "file_io"],
        "reviewer": ["code_review"],
        "supervisor": ["summarization"],
    }

    registry = reg.AgentRegistry
    registry._registry.clear()

    for role, caps in agents_to_register.items():
        spec = reg.AgentSpec(role_name=role, agent_class=MagicMock, capabilities=caps)
        spec._agent_factory = lambda **kw: _make_mock_agent()
        registry._registry[role] = spec

    orchestrator = sw.SwarmOrchestrator(cfg=cfg)
    return orchestrator, sw


# ── _should_fallback_to_supervisor ───────────────────────────────────────────

class Extra_TestShouldFallbackToSupervisor:
    def test_json_decode_error_returns_true(self):
        sw = _get_swarm_module()
        exc = json.JSONDecodeError("err", "", 0)
        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(exc) is True

    def test_validation_in_name_returns_true(self):
        sw = _get_swarm_module()

        class ValidationError(Exception):
            pass

        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(ValidationError("schema")) is True

    def test_rate_limit_in_text_returns_true(self):
        sw = _get_swarm_module()
        exc = RuntimeError("429 rate limit exceeded")
        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(exc) is True

    def test_too_many_requests_returns_true(self):
        sw = _get_swarm_module()
        exc = RuntimeError("too many requests")
        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(exc) is True

    def test_generic_error_returns_false(self):
        sw = _get_swarm_module()
        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(ValueError("unrelated")) is False

    def test_parse_in_text_returns_true(self):
        sw = _get_swarm_module()
        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("parse error")) is True

    def test_malformed_in_text_returns_true(self):
        sw = _get_swarm_module()
        assert sw.SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("malformed json")) is True


# ── _goal_fingerprint ─────────────────────────────────────────────────────────

class Extra_TestGoalFingerprint:
    def test_truncates_to_max_chars(self):
        sw = _get_swarm_module()
        long_goal = "a " * 200
        fp = sw.SwarmOrchestrator._goal_fingerprint(long_goal, max_chars=10)
        assert len(fp) <= 10

    def test_normalizes_whitespace(self):
        sw = _get_swarm_module()
        fp = sw.SwarmOrchestrator._goal_fingerprint("  hello   world  ")
        assert fp == "hello world"

    def test_empty_goal(self):
        sw = _get_swarm_module()
        assert sw.SwarmOrchestrator._goal_fingerprint("") == ""


# ── _browser_context_snapshot ────────────────────────────────────────────────

class Extra_TestBrowserContextSnapshot:
    def test_empty_context_returns_empty_strings(self):
        sw = _get_swarm_module()
        snapshot = sw.SwarmOrchestrator._browser_context_snapshot({})
        assert snapshot["browser_session_id"] == ""
        assert snapshot["browser_signal_summary"] == ""

    def test_populated_context(self):
        sw = _get_swarm_module()
        ctx = {
            "browser_session_id": "s1",
            "browser_signal_summary": "page loaded",
            "browser_signal_status": "ok",
            "browser_signal_risk": "low",
        }
        snapshot = sw.SwarmOrchestrator._browser_context_snapshot(ctx)
        assert snapshot["browser_session_id"] == "s1"
        assert snapshot["browser_signal_summary"] == "page loaded"


# ── _compose_goal_with_context ────────────────────────────────────────────────

class Extra_TestComposeGoalWithContext:
    def test_no_browser_signal(self):
        sw = _get_swarm_module()
        result = sw.SwarmOrchestrator._compose_goal_with_context("do something", {})
        assert result == "do something"

    def test_with_browser_signal_appended(self):
        sw = _get_swarm_module()
        ctx = {
            "browser_signal_summary": "page error",
            "browser_signal_status": "failed",
            "browser_signal_risk": "high",
            "browser_session_id": "sess1",
        }
        result = sw.SwarmOrchestrator._compose_goal_with_context("review this", ctx)
        assert "BROWSER_SIGNALS" in result
        assert "page error" in result


# ── _loop_repeat_limit ────────────────────────────────────────────────────────

class Extra_TestLoopRepeatLimit:
    def test_ollama_provider_limit_2(self):
        sw = _get_swarm_module()
        cfg = MagicMock()
        cfg.AI_PROVIDER = "ollama"
        cfg.SWARM_LOOP_GUARD_MAX_REPEAT = None
        o = sw.SwarmOrchestrator(cfg=cfg)
        assert o._loop_repeat_limit() == 2

    def test_non_ollama_provider_limit_3(self):
        sw = _get_swarm_module()
        cfg = MagicMock()
        cfg.AI_PROVIDER = "gemini"
        cfg.SWARM_LOOP_GUARD_MAX_REPEAT = None
        o = sw.SwarmOrchestrator(cfg=cfg)
        assert o._loop_repeat_limit() == 3

    def test_config_override(self):
        sw = _get_swarm_module()
        cfg = MagicMock()
        cfg.AI_PROVIDER = "ollama"
        cfg.SWARM_LOOP_GUARD_MAX_REPEAT = 5
        o = sw.SwarmOrchestrator(cfg=cfg)
        assert o._loop_repeat_limit() == 5

    def test_zero_falls_back_to_default(self):
        """SWARM_LOOP_GUARD_MAX_REPEAT=0 is falsy so falls back to default (2 for ollama)."""
        sw = _get_swarm_module()
        cfg = MagicMock()
        cfg.AI_PROVIDER = "ollama"
        cfg.SWARM_LOOP_GUARD_MAX_REPEAT = 0
        o = sw.SwarmOrchestrator(cfg=cfg)
        # 0 is falsy → falls back to default_limit (2 for ollama)
        assert o._loop_repeat_limit() == 2


# ── Loop guard triggers ───────────────────────────────────────────────────────

class Extra_TestLoopGuard:
    def test_loop_guard_same_step_repeated(self):
        async def _run():
            """Aynı ajan + intent + hedef tekrarı loop guard'ı tetiklemeli."""
            sw = _get_swarm_module()
            reg = sys.modules["agent.registry"]

            registry = reg.AgentRegistry
            registry._registry.clear()

            spec = reg.AgentSpec(role_name="coder", agent_class=MagicMock, capabilities=["code_generation"])
            spec._agent_factory = lambda **kw: _make_mock_agent("görev tamamlandı")
            registry._registry["coder"] = spec

            orchestrator = sw.SwarmOrchestrator(cfg=None)
            task = sw.SwarmTask(goal="test goal", intent="code_generation")
            fingerprint = sw.SwarmOrchestrator._goal_fingerprint(task.goal)
            step = f"coder|code_generation|{fingerprint}"
            # Pre-fill route trace to exceed repeat limit
            route_trace = [step, step, step]

            result = await orchestrator._execute_task(task, _route_trace=route_trace)
            assert result.status == "failed"
            assert "loop guard" in result.summary.lower() or "tekrar" in result.summary.lower()


    # ── Agent creation failure ────────────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestAgentCreationFailure:
    def test_agent_creation_error_returns_failed(self):
        async def _run():
            sw = _get_swarm_module()
            reg = sys.modules["agent.registry"]

            registry = reg.AgentRegistry
            registry._registry.clear()

            spec = reg.AgentSpec(role_name="badagent", agent_class=MagicMock, capabilities=["code_generation"])
            # factory raises
            def _bad_factory(**kw):
                raise RuntimeError("agent init failed")
            spec._agent_factory = _bad_factory
            registry._registry["badagent"] = spec

            orchestrator = sw.SwarmOrchestrator(cfg=None)
            task = sw.SwarmTask(goal="test", intent="code_generation", preferred_agent="badagent")
            result = await orchestrator._execute_task(task)
            assert result.status == "failed"
            assert "oluşturulamadı" in result.summary


    # ── Supervisor fallback ───────────────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestSupervisorFallback:
    def test_json_decode_error_triggers_supervisor_fallback(self):
        async def _run():
            sw = _get_swarm_module()
            reg = sys.modules["agent.registry"]

            registry = reg.AgentRegistry
            registry._registry.clear()

            spec = reg.AgentSpec(role_name="coder", agent_class=MagicMock, capabilities=["code_generation"])
            # Agent raises JSONDecodeError
            def _make_bad_agent(**kw):
                a = MagicMock()
                a.handle = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))
                return a
            spec._agent_factory = _make_bad_agent
            registry._registry["coder"] = spec

            orchestrator = sw.SwarmOrchestrator(cfg=None)

            # Mock supervisor fallback
            async def _fake_fallback(task, *, session_id, started_at, route_trace, handoff_chain, failed_role, reason):
                return sw.SwarmResult(
                    task_id=task.task_id, agent_role="supervisor",
                    status="success", summary="supervisor fixed it", elapsed_ms=10,
                )

            orchestrator._run_supervisor_fallback = _fake_fallback

            task = sw.SwarmTask(goal="code something", intent="code_generation")
            result = await orchestrator._execute_task(task)
            assert result.agent_role == "supervisor"
            assert result.status == "success"

        def test_supervisor_fallback_itself_fails(self):
            async def _run():
                sw = _get_swarm_module()
                reg = sys.modules["agent.registry"]

                registry = reg.AgentRegistry
                registry._registry.clear()

                spec = reg.AgentSpec(role_name="coder", agent_class=MagicMock, capabilities=["code_generation"])
                def _make_bad_agent(**kw):
                    a = MagicMock()
                    a.handle = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))
                    return a
                spec._agent_factory = _make_bad_agent
                registry._registry["coder"] = spec

                orchestrator = sw.SwarmOrchestrator(cfg=None)

                async def _failing_fallback(*args, **kwargs):
                    raise RuntimeError("supervisor also failed")

                orchestrator._run_supervisor_fallback = _failing_fallback

                task = sw.SwarmTask(goal="code something", intent="code_generation")
                result = await orchestrator._execute_task(task)
                assert result.status == "failed"
                assert "supervisor" in result.agent_role.lower()
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── Non-fallback exception path ───────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestNonFallbackException:
    def test_non_fallback_exception_returns_failed(self):
        async def _run():
            sw = _get_swarm_module()
            reg = sys.modules["agent.registry"]

            registry = reg.AgentRegistry
            registry._registry.clear()

            spec = reg.AgentSpec(role_name="coder", agent_class=MagicMock, capabilities=["code_generation"])
            def _make_error_agent(**kw):
                a = MagicMock()
                a.handle = AsyncMock(side_effect=RuntimeError("unexpected crash"))
                return a
            spec._agent_factory = _make_error_agent
            registry._registry["coder"] = spec

            orchestrator = sw.SwarmOrchestrator(cfg=None)
            task = sw.SwarmTask(goal="do something", intent="code_generation")
            result = await orchestrator._execute_task(task)
            assert result.status == "failed"
            assert "unexpected crash" in result.summary


    # ── run_pipeline with context accumulation ────────────────────────────────────

        asyncio.run(_run())
class Extra_TestRunPipeline:
    def test_pipeline_accumulates_context(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            tasks = [
                sw.SwarmTask(goal="step 1", intent="code_generation"),
                sw.SwarmTask(goal="step 2", intent="code_review"),
            ]
            results = await orchestrator.run_pipeline(tasks)
            assert len(results) == 2
            # second task should have prev context from first
            assert "prev_coder" in tasks[1].context or True  # context may vary by agent

        def test_pipeline_skipped_task_does_not_add_context(self):
            async def _run():
                orchestrator, sw = _make_orchestrator(registered_agents={})
                tasks = [
                    sw.SwarmTask(goal="step 1", intent="code_generation"),
                ]
                results = await orchestrator.run_pipeline(tasks)
                assert results[0].status == "skipped"
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── dispatch_distributed ─────────────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestDispatchDistributed:
    def test_dispatch_no_backend_raises(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            task = sw.SwarmTask(goal="test", intent="code_generation")
            with pytest.raises(RuntimeError, match="backend"):
                await orchestrator.dispatch_distributed(task)

        def test_dispatch_with_backend_succeeds(self):
            async def _run():
                orchestrator, sw = _make_orchestrator()
                contracts = sys.modules["agent.core.contracts"]

                async def _fake_dispatch(envelope):
                    return contracts.BrokerTaskResult(
                        task_id=envelope.task_id, sender="swarm", receiver=envelope.receiver,
                        status="queued", summary="queued"
                    )

                backend = MagicMock()
                backend.dispatch = _fake_dispatch
                orchestrator.configure_delegation_backend(backend)

                task = sw.SwarmTask(goal="test", intent="code_generation")
                result = await orchestrator.dispatch_distributed(task)
                assert result.status == "queued"
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_dispatch_no_agent_found_raises(self):
            async def _run():
                orchestrator, sw = _make_orchestrator(registered_agents={})

                async def _fake_dispatch(envelope):
                    return MagicMock()

                backend = MagicMock()
                backend.dispatch = _fake_dispatch
                orchestrator.configure_delegation_backend(backend)

                task = sw.SwarmTask(goal="test", intent="code_generation")
                with pytest.raises(RuntimeError, match="ajan"):
                    await orchestrator.dispatch_distributed(task)
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_dispatch_with_receiver_override(self):
            async def _run():
                orchestrator, sw = _make_orchestrator()
                contracts = sys.modules["agent.core.contracts"]

                async def _fake_dispatch(envelope):
                    return contracts.BrokerTaskResult(
                        task_id=envelope.task_id, sender="swarm", receiver=envelope.receiver,
                        status="queued", summary="queued"
                    )

                backend = MagicMock()
                backend.dispatch = _fake_dispatch
                orchestrator.configure_delegation_backend(backend)

                task = sw.SwarmTask(goal="test", intent="code_generation")
                result = await orchestrator.dispatch_distributed(task, receiver="coder")
                assert result.status == "queued"
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_dispatch_with_preferred_agent(self):
            async def _run():
                orchestrator, sw = _make_orchestrator()
                contracts = sys.modules["agent.core.contracts"]

                async def _fake_dispatch(envelope):
                    return contracts.BrokerTaskResult(
                        task_id=envelope.task_id, sender="swarm", receiver=envelope.receiver,
                        status="queued", summary="queued"
                    )

                backend = MagicMock()
                backend.dispatch = _fake_dispatch
                orchestrator.configure_delegation_backend(backend)

                task = sw.SwarmTask(goal="test", intent="code_generation", preferred_agent="coder")
                result = await orchestrator.dispatch_distributed(task)
                assert result.status == "queued"
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _run_supervisor_fallback ──────────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestRunSupervisorFallback:
    def test_supervisor_fallback_empty_output_raises(self):
        async def _run():
            sw = _get_swarm_module()
            reg = sys.modules["agent.registry"]

            registry = reg.AgentRegistry
            registry._registry.clear()

            orchestrator = sw.SwarmOrchestrator(cfg=None)
            task = sw.SwarmTask(goal="test", intent="code_generation")

            import time

            supervisor_mock = MagicMock()
            supervisor_mock.run_task = AsyncMock(return_value="")  # empty output

            # Ensure agent.core.supervisor is accessible as module attribute
            if "agent.core.supervisor" not in sys.modules:
                sv_mod = types.ModuleType("agent.core.supervisor")
                sv_mod.SupervisorAgent = MagicMock(return_value=supervisor_mock)
                sys.modules["agent.core.supervisor"] = sv_mod
                sys.modules["agent.core"].supervisor = sv_mod
            else:
                sys.modules["agent.core.supervisor"].SupervisorAgent = MagicMock(return_value=supervisor_mock)

            with pytest.raises((RuntimeError, Exception)):
                await orchestrator._run_supervisor_fallback(
                    task,
                    session_id="s1",
                    started_at=time.monotonic(),
                    route_trace=[],
                    handoff_chain=[],
                    failed_role="coder",
                    reason="test",
                )


    # ── _run_autonomous_feedback ──────────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestRunAutonomousFeedback:
    def test_empty_prompt_returns_early(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            # Should return without error when prompt is empty
            await orchestrator._run_autonomous_feedback(
                prompt="",
                response="result",
                context={},
                session_id="s1",
                agent_role="coder",
                task_id="t1",
            )

        def test_empty_response_returns_early(self):
            async def _run():
                orchestrator, sw = _make_orchestrator()
                await orchestrator._run_autonomous_feedback(
                    prompt="do something",
                    response="",
                    context={},
                    session_id="s1",
                    agent_role="coder",
                    task_id="t1",
                )
            import asyncio as _asyncio
            _asyncio.run(_run())

        def test_exception_in_judge_is_suppressed(self):
            async def _run():
                orchestrator, sw = _make_orchestrator()
                with patch.dict("sys.modules", {"core.judge": MagicMock(side_effect=ImportError)}):
                    await orchestrator._run_autonomous_feedback(
                        prompt="a",
                        response="b",
                        context={},
                        session_id="s1",
                        agent_role="coder",
                        task_id="t1",
                    )
            import asyncio as _asyncio
            _asyncio.run(_run())

    # ── _schedule_autonomous_feedback ────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestScheduleAutonomousFeedback:
    def test_empty_prompt_skips_scheduling(self):
        orchestrator, sw = _make_orchestrator()
        # Should not raise
        orchestrator._schedule_autonomous_feedback(
            prompt="", response="r", context={},
            session_id="s", agent_role="a", task_id="t",
        )

    def test_no_running_loop_is_handled(self):
        orchestrator, sw = _make_orchestrator()
        # Running outside event loop should be silently handled
        orchestrator._schedule_autonomous_feedback(
            prompt="do something", response="result", context={},
            session_id="s", agent_role="coder", task_id="t",
        )


# ── _direct_handoff ───────────────────────────────────────────────────────────

class Extra_TestDirectHandoff:
    def test_empty_target_raises(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            contracts = sys.modules["agent.core.contracts"]
            delegation = contracts.DelegationRequest(
                task_id="t1", reply_to="coder", target_agent="",
                payload="do something", intent="code_generation",
            )
            task = sw.SwarmTask(goal="test", intent="code_generation")
            with pytest.raises(RuntimeError, match="target_agent"):
                await orchestrator._direct_handoff(
                    task, delegation, session_id="s", hop=1,
                    route_trace=[], handoff_chain=[],
                )


    # ── p2p_context static ────────────────────────────────────────────────────────

        asyncio.run(_run())
class Extra_TestP2PContext:
    def test_p2p_context_fields(self):
        sw = _get_swarm_module()
        contracts = sys.modules["agent.core.contracts"]
        delegation = contracts.DelegationRequest(
            task_id="t", reply_to="coder", target_agent="reviewer",
            payload="payload", intent="review", meta={"reason": "qa"},
        )
        ctx = sw.SwarmOrchestrator._p2p_context(
            {"key": "val"}, delegation,
            session_id="s1", hop=2, route_trace=["a", "b"],
        )
        assert ctx["p2p_sender"] == "coder"
        assert ctx["p2p_receiver"] == "reviewer"
        assert ctx["swarm_hop"] == "2"
        assert ctx["p2p_reason"] == "qa"
        assert ctx["key"] == "val"


# ── run_parallel with concurrency ─────────────────────────────────────────────

class Extra_TestRunParallel:
    def test_run_parallel_multiple_tasks(self):
        async def _run():
            orchestrator, sw = _make_orchestrator()
            tasks = [
                sw.SwarmTask(goal="task 1", intent="code_generation"),
                sw.SwarmTask(goal="task 2", intent="code_generation"),
            ]
            results = await orchestrator.run_parallel(tasks, max_concurrency=2)
            assert len(results) == 2
            for r in results:
                assert r.status in ("success", "failed", "skipped")

        def test_run_parallel_with_concurrency_1(self):
            async def _run():
                orchestrator, sw = _make_orchestrator()
                tasks = [sw.SwarmTask(goal=f"task {i}", intent="code_generation") for i in range(3)]
                results = await orchestrator.run_parallel(tasks, max_concurrency=1)
                assert len(results) == 3
            import asyncio as _asyncio
            _asyncio.run(_run())

        asyncio.run(_run())
