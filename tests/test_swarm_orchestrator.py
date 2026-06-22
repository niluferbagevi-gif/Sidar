"""Production cutover smoke tests for the swarm orchestrator.

These tests are referenced from `.github/workflows/migration-cutover-checks.yml`
and run against the alembic-migrated PostgreSQL slice. They must therefore stay
self-contained: no real LLM calls, no external services, no network. The intent
is to prove that the swarm orchestrator wiring keeps composing tasks, routing
to known roles, and dispatching through the in-memory broker after a migration
chain has been applied.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.registry import AgentCatalog, AgentSpec
from agent.swarm import (
    InMemoryDelegationBackend,
    SwarmOrchestrator,
    SwarmTask,
    TaskRouter,
)


@pytest.fixture
def isolated_catalog() -> dict[str, AgentSpec]:
    snapshot = dict(AgentCatalog._registry)
    AgentCatalog._registry.clear()
    try:
        yield AgentCatalog._registry
    finally:
        AgentCatalog._registry.clear()
        AgentCatalog._registry.update(snapshot)


def _register(role: str, *capabilities: str) -> None:
    AgentCatalog.register_type(
        role_name=role,
        agent_class=type(f"_{role.title()}Agent", (), {"ROLE_NAME": role}),
        capabilities=list(capabilities),
        description=f"stub {role}",
        version="ci",
        is_builtin=False,
    )


def test_task_router_routes_intent_to_capability(isolated_catalog: dict) -> None:
    _register("coder", "code_generation")
    _register("reviewer", "code_review")

    router = TaskRouter()

    coder_spec = router.route("code")
    reviewer_spec = router.route("review")

    assert coder_spec is not None and coder_spec.role_name == "coder"
    assert reviewer_spec is not None and reviewer_spec.role_name == "reviewer"


def test_task_router_falls_back_to_first_registered_agent(isolated_catalog: dict) -> None:
    _register("only_one", "irrelevant_capability")

    router = TaskRouter()

    fallback = router.route("nonexistent_intent")

    assert fallback is not None
    assert fallback.role_name == "only_one"


def test_task_router_falls_back_to_first_capability_candidate_when_preferred_role_missing(
    isolated_catalog: dict,
) -> None:
    _register("alpha", "code_generation")
    _register("beta", "code_generation")

    routed = TaskRouter().route("code")

    assert routed is not None
    assert routed.role_name == "alpha"


def test_task_router_preferred_role_absent_uses_catalog_candidate_order(
    isolated_catalog: dict,
) -> None:
    _register("beta", "code_generation")
    _register("alpha", "code_generation")

    routed = TaskRouter().route("code")

    assert routed is not None
    assert routed.role_name == "beta"


def test_task_router_returns_none_when_catalog_is_empty(isolated_catalog: dict) -> None:
    router = TaskRouter()
    assert router.route("anything") is None
    assert router.route_by_role("anything") is None


def test_task_router_route_by_role_returns_registered_spec(isolated_catalog: dict) -> None:
    _register("coverage", "coverage_analysis")

    spec = TaskRouter().route_by_role("coverage")

    assert spec is not None
    assert spec.role_name == "coverage"


def test_compose_goal_with_browser_signal_appends_summary_block() -> None:
    composed = SwarmOrchestrator._compose_goal_with_context(
        "Run regression suite",
        {
            "browser_session_id": "sess-1",
            "browser_signal_summary": "checkout flow flaky",
            "browser_signal_status": "warning",
            "browser_signal_risk": "medium",
        },
    )

    assert "Run regression suite" in composed
    assert "[BROWSER_SIGNALS]" in composed
    assert "session_id=sess-1" in composed
    assert "summary=checkout flow flaky" in composed


def test_compose_goal_without_browser_signal_returns_plain_goal() -> None:
    composed = SwarmOrchestrator._compose_goal_with_context("Plain goal", {})
    assert composed == "Plain goal"


def test_swarm_orchestrator_requires_backend_for_distributed_dispatch() -> None:
    orchestrator = SwarmOrchestrator()
    task = SwarmTask(goal="x", intent="code")

    with pytest.raises(RuntimeError):
        asyncio.run(orchestrator.dispatch_distributed(task))


def test_swarm_orchestrator_dispatches_through_in_memory_backend(
    isolated_catalog: dict,
) -> None:
    _register("coder", "code_generation")

    backend = InMemoryDelegationBackend()
    orchestrator = SwarmOrchestrator()
    orchestrator.configure_delegation_backend(backend)

    task = SwarmTask(
        goal="ship payment fix",
        intent="code",
        context={"trace_id": "ci-trace"},
    )

    result = asyncio.run(
        orchestrator.dispatch_distributed(task, session_id="ci-session", broker="memory"),
    )

    assert result.task_id == task.task_id
    assert result.status == "queued"
    assert backend.dispatched, "InMemoryDelegationBackend should have captured the envelope"
    envelope = backend.dispatched[0]
    assert envelope.task_id == task.task_id
    assert envelope.broker == "memory"
    assert envelope.headers.get("session_id") == "ci-session"


def test_swarm_orchestrator_distributed_dispatch_raises_when_no_agent_available() -> None:
    backend = InMemoryDelegationBackend()
    orchestrator = SwarmOrchestrator()
    orchestrator.configure_delegation_backend(backend)

    task = SwarmTask(goal="x", intent="completely_unknown_intent_for_ci")

    snapshot = dict(AgentCatalog._registry)
    AgentCatalog._registry.clear()
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(orchestrator.dispatch_distributed(task))
    finally:
        AgentCatalog._registry.update(snapshot)
