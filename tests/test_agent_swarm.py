import asyncio
import json
from types import SimpleNamespace

import pytest

from agent.core.contracts import DelegationRequest
from agent.registry import AgentSpec
from agent.swarm import InMemoryDelegationBackend, SwarmOrchestrator, SwarmTask, TaskRouter


def test_task_router_routes_by_intent_capability(monkeypatch):
    spec = AgentSpec(role_name="reviewer", capabilities=["code_review"])
    monkeypatch.setattr("agent.swarm.AgentCatalog.find_by_capability", lambda capability: [spec] if capability == "code_review" else [])
    monkeypatch.setattr("agent.swarm.AgentCatalog.list_all", lambda: [])

    router = TaskRouter()
    chosen = router.route("review")

    assert chosen is spec


def test_task_router_fallbacks_to_first_agent_when_capability_missing(monkeypatch):
    fallback = AgentSpec(role_name="coder", capabilities=[])
    monkeypatch.setattr("agent.swarm.AgentCatalog.find_by_capability", lambda _capability: [])
    monkeypatch.setattr("agent.swarm.AgentCatalog.list_all", lambda: [fallback])

    router = TaskRouter()
    assert router.route("unknown_intent") is fallback


def test_loop_repeat_limit_uses_provider_and_override():
    ollama_orchestrator = SwarmOrchestrator(cfg=SimpleNamespace(AI_PROVIDER="ollama"))
    remote_orchestrator = SwarmOrchestrator(cfg=SimpleNamespace(AI_PROVIDER="openai"))
    override_orchestrator = SwarmOrchestrator(
        cfg=SimpleNamespace(AI_PROVIDER="ollama", SWARM_LOOP_GUARD_MAX_REPEAT=5)
    )

    assert ollama_orchestrator._loop_repeat_limit() == 2
    assert remote_orchestrator._loop_repeat_limit() == 3
    assert override_orchestrator._loop_repeat_limit() == 5


def test_compose_goal_with_browser_context():
    result = SwarmOrchestrator._compose_goal_with_context(
        "Fix bug",
        {
            "browser_session_id": "sess-1",
            "browser_signal_summary": "Checkout button fails",
            "browser_signal_status": "failed",
            "browser_signal_risk": "high",
        },
    )

    assert "Fix bug" in result
    assert "[BROWSER_SIGNALS]" in result
    assert "session_id=sess-1" in result


def test_should_fallback_to_supervisor_for_json_and_rate_limit_errors():
    assert SwarmOrchestrator._should_fallback_to_supervisor(json.JSONDecodeError("bad", "{}", 0)) is True
    assert SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("429 too many requests")) is True
    assert SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("plain failure")) is False


def test_p2p_context_contains_handoff_fields():
    delegation = DelegationRequest(
        task_id="t1",
        reply_to="coder",
        target_agent="reviewer",
        payload="review this",
        intent="code_review",
        handoff_depth=2,
        meta={"reason": "needs review"},
    )

    ctx = SwarmOrchestrator._p2p_context(
        {"base": "ok"},
        delegation,
        session_id="session-42",
        hop=3,
        route_trace=["coder", "reviewer"],
    )

    assert ctx["base"] == "ok"
    assert ctx["swarm_hop"] == "3"
    assert ctx["p2p_sender"] == "coder"
    assert ctx["p2p_receiver"] == "reviewer"
    assert ctx["p2p_reason"] == "needs review"
    assert ctx["p2p_handoff_depth"] == "2"


def test_dispatch_distributed_uses_backend_and_receiver(monkeypatch):
    backend = InMemoryDelegationBackend()
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    orchestrator.configure_delegation_backend(backend)

    monkeypatch.setattr(
        orchestrator.router,
        "route_by_role",
        lambda role_name: AgentSpec(role_name=role_name, capabilities=[]),
    )

    task = SwarmTask(goal="Analyze tests", intent="review", preferred_agent="reviewer")
    result = asyncio.run(
        orchestrator.dispatch_distributed(task, session_id="s1", sender="swarm", receiver="reviewer")
    )

    assert result.status == "queued"
    assert result.sender == "reviewer"
    assert result.receiver == "swarm"
    assert len(backend.dispatched) == 1
    assert backend.dispatched[0].headers["session_id"] == "s1"


def test_dispatch_distributed_raises_without_backend():
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    task = SwarmTask(goal="No backend")

    with pytest.raises(RuntimeError, match="backend"):
        asyncio.run(orchestrator.dispatch_distributed(task))
