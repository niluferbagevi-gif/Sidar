from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agent.swarm import InMemoryDelegationBackend, SwarmOrchestrator, SwarmTask


def test_dispatch_distributed_uses_preferred_agent_and_backend() -> None:
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    backend = InMemoryDelegationBackend()
    orchestrator.configure_delegation_backend(backend)
    orchestrator.router.route_by_role = lambda _role: SimpleNamespace(role_name="reviewer")

    result = asyncio.run(orchestrator.dispatch_distributed(
        SwarmTask(goal="Kod gözden geçir", intent="review", preferred_agent="reviewer"),
        session_id="sess-1",
        sender="sidar",
        broker="redis",
    ))

    assert result.status == "queued"
    assert result.broker == "redis"
    assert backend.dispatched[0].receiver == "reviewer"


def test_compose_goal_with_browser_context_includes_signal_block() -> None:
    goal = SwarmOrchestrator._compose_goal_with_context(
        "Temel hedef",
        {
            "browser_session_id": "b1",
            "browser_signal_summary": "captcha observed",
            "browser_signal_status": "blocked",
            "browser_signal_risk": "high",
        },
    )

    assert "[BROWSER_SIGNALS]" in goal
    assert "captcha observed" in goal


def test_should_fallback_to_supervisor_detects_json_style_errors() -> None:
    exc = json.JSONDecodeError("bad json", "{", 1)
    assert SwarmOrchestrator._should_fallback_to_supervisor(exc) is True
    assert SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("other error")) is False
