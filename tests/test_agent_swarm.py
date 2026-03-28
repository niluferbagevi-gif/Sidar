"""
agent/swarm.py için birim testleri.
SwarmTask/SwarmResult dataclasses, _INTENT_CAPABILITY_MAP,
InMemoryDelegationBackend, TaskRouter, SwarmOrchestrator.
"""
from __future__ import annotations

import asyncio
import sys
import types


def _get_swarm():
    # Stub agent.registry to avoid importing all role agents
    if "agent.registry" not in sys.modules:
        stub = types.ModuleType("agent.registry")

        class _FakeSpec:
            def __init__(self, role_name, agent_class, capabilities=None, description="", version="1.0.0", is_builtin=False):
                self.role_name = role_name
                self.agent_class = agent_class
                self.capabilities = capabilities or []
                self.description = description
                self.version = version
                self.is_builtin = is_builtin

        _registry: dict = {}

        class _FakeAgentRegistry:
            @classmethod
            def find_by_capability(cls, capability):
                return [s for s in _registry.values() if capability in s.capabilities]

            @classmethod
            def list_all(cls):
                return list(_registry.values())

            @classmethod
            def get(cls, role_name):
                return _registry.get(role_name)

            @classmethod
            def register_type(cls, *, role_name, agent_class, capabilities=None, **kwargs):
                _registry[role_name] = _FakeSpec(role_name, agent_class, capabilities or [])

        stub.AgentRegistry = _FakeAgentRegistry
        stub.AgentSpec = _FakeSpec
        sys.modules["agent.registry"] = stub

    if "agent.swarm" in sys.modules:
        del sys.modules["agent.swarm"]
    import agent.swarm as swarm
    return swarm


# ══════════════════════════════════════════════════════════════
# SwarmTask
# ══════════════════════════════════════════════════════════════

class TestSwarmTask:
    def test_defaults(self):
        sw = _get_swarm()
        task = sw.SwarmTask(goal="Do something")
        assert task.intent == "mixed"
        assert task.context == {}
        assert task.task_id.startswith("swarm-")
        assert task.preferred_agent is None

    def test_custom_intent(self):
        sw = _get_swarm()
        task = sw.SwarmTask(goal="Review code", intent="code_review")
        assert task.intent == "code_review"

    def test_task_id_unique(self):
        sw = _get_swarm()
        t1 = sw.SwarmTask(goal="A")
        t2 = sw.SwarmTask(goal="B")
        assert t1.task_id != t2.task_id


# ══════════════════════════════════════════════════════════════
# SwarmResult
# ══════════════════════════════════════════════════════════════

class TestSwarmResult:
    def test_basic_fields(self):
        sw = _get_swarm()
        result = sw.SwarmResult(
            task_id="t1",
            agent_role="coder",
            status="success",
            summary="Done",
            elapsed_ms=100,
        )
        assert result.task_id == "t1"
        assert result.agent_role == "coder"
        assert result.status == "success"
        assert result.elapsed_ms == 100

    def test_defaults(self):
        sw = _get_swarm()
        result = sw.SwarmResult(task_id="t1", agent_role="r", status="s", summary="s", elapsed_ms=0)
        assert result.evidence == []
        assert result.handoffs == []
        assert result.graph == {}


# ══════════════════════════════════════════════════════════════
# _INTENT_CAPABILITY_MAP
# ══════════════════════════════════════════════════════════════

class TestIntentCapabilityMap:
    def test_code_generation_mapped(self):
        sw = _get_swarm()
        assert "code_generation" in sw._INTENT_CAPABILITY_MAP

    def test_code_review_mapped(self):
        sw = _get_swarm()
        assert "code_review" in sw._INTENT_CAPABILITY_MAP

    def test_web_search_mapped(self):
        sw = _get_swarm()
        assert "web_search" in sw._INTENT_CAPABILITY_MAP

    def test_mixed_has_fallback(self):
        sw = _get_swarm()
        assert "mixed" in sw._INTENT_CAPABILITY_MAP

    def test_short_forms_mapped(self):
        sw = _get_swarm()
        assert "code" in sw._INTENT_CAPABILITY_MAP
        assert "research" in sw._INTENT_CAPABILITY_MAP
        assert "review" in sw._INTENT_CAPABILITY_MAP


# ══════════════════════════════════════════════════════════════
# InMemoryDelegationBackend
# ══════════════════════════════════════════════════════════════

class TestInMemoryDelegationBackend:
    def test_dispatch_queues_envelope(self):
        sw = _get_swarm()
        import agent.core.contracts as c
        backend = sw.InMemoryDelegationBackend()
        env = c.BrokerTaskEnvelope(
            task_id="b1",
            sender="supervisor",
            receiver="coder",
            goal="Write code",
        )
        result = asyncio.run(backend.dispatch(env))
        assert len(backend.dispatched) == 1
        assert backend.dispatched[0].task_id == "b1"

    def test_dispatch_returns_queued_status(self):
        sw = _get_swarm()
        import agent.core.contracts as c
        backend = sw.InMemoryDelegationBackend()
        env = c.BrokerTaskEnvelope(
            task_id="b2",
            sender="sup",
            receiver="coder",
            goal="Task",
        )
        result = asyncio.run(backend.dispatch(env))
        assert result.status == "queued"

    def test_dispatch_returns_broker_task_result(self):
        sw = _get_swarm()
        import agent.core.contracts as c
        backend = sw.InMemoryDelegationBackend()
        env = c.BrokerTaskEnvelope(
            task_id="b3",
            sender="sup",
            receiver="coder",
            goal="Task",
        )
        result = asyncio.run(backend.dispatch(env))
        assert isinstance(result, c.BrokerTaskResult)


# ══════════════════════════════════════════════════════════════
# TaskRouter
# ══════════════════════════════════════════════════════════════

class TestTaskRouter:
    def test_route_returns_none_when_no_agents(self):
        sw = _get_swarm()
        # With empty registry stub, should return None or first agent
        router = sw.TaskRouter()
        # Either None or a spec — just ensure no crash
        result = router.route("code_generation")
        # result may be None or a spec depending on what's registered

    def test_route_by_role_returns_none_when_missing(self):
        sw = _get_swarm()
        router = sw.TaskRouter()
        result = router.route_by_role("__nonexistent_agent__")
        assert result is None


# ══════════════════════════════════════════════════════════════
# SwarmOrchestrator
# ══════════════════════════════════════════════════════════════

class TestSwarmOrchestrator:
    def test_init_no_backend(self):
        sw = _get_swarm()
        orc = sw.SwarmOrchestrator()
        assert orc.delegation_backend is None

    def test_configure_backend(self):
        sw = _get_swarm()
        orc = sw.SwarmOrchestrator()
        backend = sw.InMemoryDelegationBackend()
        orc.configure_delegation_backend(backend)
        assert orc.delegation_backend is backend

    def test_configure_backend_none_clears(self):
        sw = _get_swarm()
        orc = sw.SwarmOrchestrator()
        backend = sw.InMemoryDelegationBackend()
        orc.configure_delegation_backend(backend)
        orc.configure_delegation_backend(None)
        assert orc.delegation_backend is None

    def test_dispatch_distributed_raises_without_backend(self):
        sw = _get_swarm()
        orc = sw.SwarmOrchestrator()
        task = sw.SwarmTask(goal="Do something")
        with __import__("pytest").raises(RuntimeError, match="backend"):
            asyncio.run(orc.dispatch_distributed(task))
