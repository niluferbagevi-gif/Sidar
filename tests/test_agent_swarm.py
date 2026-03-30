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
            def __init__(self, role_name, capabilities=None):
                self.role_name = role_name
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
    result = contracts.TaskResult(task_id="t", status=status, summary=summary, evidence=[])
    agent.handle = AsyncMock(return_value=result)
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
        spec = reg.AgentSpec(role_name=role, capabilities=caps)
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
    @pytest.mark.asyncio
    async def test_dispatch_queues_envelope(self):
        sw = _get_swarm_module()
        backend = sw.InMemoryDelegationBackend()
        contracts = sys.modules["agent.core.contracts"]
        envelope = contracts.BrokerTaskEnvelope(
            task_id="b1", sender="s", receiver="r", goal="hedef"
        )
        result = await backend.dispatch(envelope)
        assert len(backend.dispatched) == 1
        assert result.status == "queued"

    @pytest.mark.asyncio
    async def test_dispatch_returns_broker_result(self):
        sw = _get_swarm_module()
        backend = sw.InMemoryDelegationBackend()
        contracts = sys.modules["agent.core.contracts"]
        envelope = contracts.BrokerTaskEnvelope(
            task_id="b2", sender="s", receiver="r", goal="hedef"
        )
        result = await backend.dispatch(envelope)
        assert result.task_id == "b2"


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
    @pytest.mark.asyncio
    async def test_run_no_agents_returns_skipped(self):
        orchestrator, sw = _make_orchestrator(registered_agents={})
        result = await orchestrator.run("bir görev")
        assert result.status == "skipped"

    @pytest.mark.asyncio
    async def test_run_parallel_empty_list(self):
        orchestrator, sw = _make_orchestrator()
        results = await orchestrator.run_parallel([])
        assert results == []

    @pytest.mark.asyncio
    async def test_run_pipeline_empty_list(self):
        orchestrator, sw = _make_orchestrator()
        results = await orchestrator.run_pipeline([])
        assert results == []

    @pytest.mark.asyncio
    async def test_run_max_hops_exceeded(self):
        """Maksimum hop aşıldığında failed döndürülmelidir."""
        orchestrator, sw = _make_orchestrator()
        task = sw.SwarmTask(goal="görev", preferred_agent="coder")
        # _hop > max_hops simülasyonu
        result = await orchestrator._execute_task(task, _hop=999)
        assert result.status == "failed"
        assert "loop guard" in result.summary.lower() or "hop" in result.summary.lower()


class TestSwarmHandoffIntegration:
    @pytest.mark.asyncio
    async def test_direct_handoff_coder_to_reviewer_chain_is_recorded(self):
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
        coder = reg.AgentSpec(role_name="coder", capabilities=["code_generation"])
        reviewer = reg.AgentSpec(role_name="reviewer", capabilities=["code_review"])
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

    @pytest.mark.asyncio
    async def test_pipeline_passes_success_context_between_agents(self):
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
        coder = reg.AgentSpec(role_name="coder", capabilities=["code_generation"])
        reviewer = reg.AgentSpec(role_name="reviewer", capabilities=["code_review"])
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
    @pytest.mark.asyncio
    async def test_dispatch_distributed_no_backend_raises(self):
        orchestrator, sw = _make_orchestrator()
        task = sw.SwarmTask(goal="dağıtık görev", preferred_agent="coder")
        with pytest.raises(RuntimeError, match="backend"):
            await orchestrator.dispatch_distributed(task)

    @pytest.mark.asyncio
    async def test_dispatch_distributed_with_backend(self):
        orchestrator, sw = _make_orchestrator()
        backend = sw.InMemoryDelegationBackend()
        orchestrator.configure_delegation_backend(backend)
        task = sw.SwarmTask(goal="dağıtık görev", preferred_agent="coder")
        result = await orchestrator.dispatch_distributed(task)
        assert result.status == "queued"


class TestSwarmOrchestratorFailureBranches:
    @pytest.mark.asyncio
    async def test_direct_handoff_without_target_raises(self):
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

    @pytest.mark.asyncio
    async def test_execute_task_agent_create_failure_returns_failed(self):
        orchestrator, sw = _make_orchestrator()
        task = sw.SwarmTask(goal="görev", preferred_agent="coder")
        with patch("agent.swarm.AgentRegistry.create", side_effect=RuntimeError("agent unavailable")):
            result = await orchestrator._execute_task(task)
        assert result.status == "failed"
        assert "oluşturulamadı" in result.summary.lower()

    @pytest.mark.asyncio
    async def test_execute_task_supervisor_fallback_success(self):
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

    @pytest.mark.asyncio
    async def test_execute_task_supervisor_fallback_failure_returns_failed(self):
        orchestrator, sw = _make_orchestrator()
        task = sw.SwarmTask(goal="görev", preferred_agent="coder")
        failing_agent = MagicMock()
        failing_agent.handle = AsyncMock(side_effect=RuntimeError("rate limit 429"))

        with patch("agent.swarm.AgentRegistry.create", return_value=failing_agent):
            with patch.object(orchestrator, "_run_supervisor_fallback", AsyncMock(side_effect=RuntimeError("supervisor down"))):
                result = await orchestrator._execute_task(task, session_id="s1")

        assert result.status == "failed"
        assert "fallback" in result.summary.lower()


class TestSwarmDelegationEdgeCases:
    @pytest.mark.asyncio
    async def test_delegation_missing_reply_to_is_filled_from_spec_role(self):
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
        coder = reg.AgentSpec(role_name="coder", capabilities=["code_generation"])
        reviewer = reg.AgentSpec(role_name="reviewer", capabilities=["code_review"])
        coder._agent_factory = lambda **_kw: _CoderAgent()
        reviewer._agent_factory = lambda **_kw: _ReviewerAgent()
        reg.AgentRegistry._registry["coder"] = coder
        reg.AgentRegistry._registry["reviewer"] = reviewer

        orchestrator = sw.SwarmOrchestrator(cfg=None)
        result = await orchestrator.run("kod üret", intent="code_generation")

        assert result.status == "success"
        assert result.handoffs[0]["sender"] == "coder"
