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


def test_execute_task_returns_skipped_when_router_cannot_resolve_agent() -> None:
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    orchestrator.router.route = lambda _intent: None

    result = asyncio.run(
        orchestrator._execute_task(
            SwarmTask(task_id="t-1", goal="noop", intent="unknown", preferred_agent=None),
            session_id="sess-2",
        )
    )

    assert result.status == "skipped"
    assert result.agent_role == "none"


def test_execute_task_uses_legacy_run_task_when_handle_missing(monkeypatch) -> None:
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    orchestrator.router.route = lambda _intent: SimpleNamespace(role_name="legacy")

    class _LegacyAgent:
        async def run_task(self, goal: str) -> str:
            return f"legacy:{goal}"

    monkeypatch.setattr("agent.swarm.AgentCatalog.create", lambda *_args, **_kwargs: _LegacyAgent())
    monkeypatch.setattr(orchestrator, "_schedule_autonomous_feedback", lambda **_kwargs: None)

    result = asyncio.run(
        orchestrator._execute_task(
            SwarmTask(task_id="t-legacy", goal="kodu gözden geçir", intent="review", context={}),
            session_id="sess-3",
        )
    )

    assert result.status == "success"
    assert result.agent_role == "legacy"
    assert result.summary == "legacy:kodu gözden geçir"
