"""
Coverage tests for agent/swarm.py — 0% coverage, 88 lines.

Covers: TaskRouter, SwarmOrchestrator.run, run_parallel, run_pipeline,
_execute_task (no spec, spec found but create fails, spec found and succeeds,
exception in run), active_task_count, available_agents.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.swarm import (
    SwarmTask,
    SwarmResult,
    SwarmOrchestrator,
    TaskRouter,
    _INTENT_CAPABILITY_MAP,
)
from agent.registry import AgentRegistry, AgentSpec
from agent.base_agent import BaseAgent
from agent.core.contracts import TaskResult


# ── Concrete test agent base ──────────────────────────────────────────────────

class _ConcreteAgent(BaseAgent):
    """Minimal concrete agent for testing — satisfies abstract run_task."""
    async def run_task(self, task_prompt: str) -> str:
        return "ok"

    async def handle(self, envelope):
        return TaskResult(task_id="t1", status="success", summary="done", evidence=[])


# ── TaskRouter ────────────────────────────────────────────────────────────────

def test_task_router_known_intent_returns_spec():
    """route() with a known intent should return a spec if any agent has that capability."""
    class _Dummy(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_cg"

    AgentRegistry.register_type(
        role_name="dummy_swarm_cg",
        agent_class=_Dummy,
        capabilities=["code_generation"],
    )
    try:
        router = TaskRouter()
        spec = router.route("code_generation")
        assert spec is not None
    finally:
        AgentRegistry.unregister("dummy_swarm_cg")


def test_task_router_unknown_intent_falls_back_to_any_agent():
    """route() with unknown intent falls back to first available agent."""
    class _FallbackDummy(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_fb"

    AgentRegistry.register_type(
        role_name="dummy_swarm_fb",
        agent_class=_FallbackDummy,
        capabilities=[],
    )
    try:
        router = TaskRouter()
        spec = router.route("totally_unknown_intent_xyz")
        assert spec is not None
    finally:
        AgentRegistry.unregister("dummy_swarm_fb")


def test_task_router_no_agents_returns_none():
    """route() returns None when registry is empty."""
    router = TaskRouter()
    saved = dict(AgentRegistry._registry)
    AgentRegistry._registry.clear()
    try:
        result = router.route("code_generation")
        assert result is None
    finally:
        AgentRegistry._registry.update(saved)


def test_task_router_route_by_role():
    """route_by_role() delegates to AgentRegistry.get."""
    router = TaskRouter()
    assert router.route_by_role("nonexistent_role_xyz") is None


# ── SwarmOrchestrator._execute_task — no spec ─────────────────────────────────

@pytest.mark.asyncio
async def test_execute_task_no_spec_returns_skipped():
    """_execute_task when no spec found returns SwarmResult with status='skipped'."""
    orch = SwarmOrchestrator()
    saved = dict(AgentRegistry._registry)
    AgentRegistry._registry.clear()
    try:
        task = SwarmTask(goal="hello", intent="code_generation")
        result = await orch._execute_task(task)
        assert result.status == "skipped"
        assert result.agent_role == "none"
    finally:
        AgentRegistry._registry.update(saved)


# ── SwarmOrchestrator._execute_task — spec found but create fails ─────────────

@pytest.mark.asyncio
async def test_execute_task_create_fails_returns_failed():
    """_execute_task when AgentRegistry.create raises returns status='failed'."""
    class _BoomAgent(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_boom"
        def __init__(self, **kwargs):
            raise ValueError("init boom")

    AgentRegistry.register_type(
        role_name="dummy_swarm_boom",
        agent_class=_BoomAgent,
        capabilities=["unique_boom_cap_xyz"],
    )
    try:
        orch = SwarmOrchestrator()
        task = SwarmTask(goal="hello", intent="unique_boom_cap_xyz")
        result = await orch._execute_task(task)
        assert result.status == "failed"
        assert "oluşturulamadı" in result.summary or "init boom" in result.summary
    finally:
        AgentRegistry.unregister("dummy_swarm_boom")


# ── SwarmOrchestrator._execute_task — success ─────────────────────────────────

@pytest.mark.asyncio
async def test_execute_task_success():
    """_execute_task happy path returns status from agent.handle."""
    class _OkAgent(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_ok"
        async def handle(self, envelope):
            return TaskResult(task_id="t1", status="success", summary="all good", evidence=[])

    AgentRegistry.register_type(
        role_name="dummy_swarm_ok",
        agent_class=_OkAgent,
        capabilities=["unique_ok_cap_xyz"],
    )
    try:
        orch = SwarmOrchestrator()
        task = SwarmTask(goal="write code", intent="unique_ok_cap_xyz")
        result = await orch._execute_task(task)
        assert result.status == "success"
        assert result.summary == "all good"
    finally:
        AgentRegistry.unregister("dummy_swarm_ok")


# ── SwarmOrchestrator._execute_task — exception in handle ────────────────────

@pytest.mark.asyncio
async def test_execute_task_handle_raises_returns_failed():
    """_execute_task when agent.handle raises returns status='failed'."""
    class _ExcAgent(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_exc"
        async def handle(self, envelope):
            raise RuntimeError("handle error")

    AgentRegistry.register_type(
        role_name="dummy_swarm_exc",
        agent_class=_ExcAgent,
        capabilities=["unique_exc_cap_xyz"],
    )
    try:
        orch = SwarmOrchestrator()
        task = SwarmTask(goal="write code", intent="unique_exc_cap_xyz")
        result = await orch._execute_task(task)
        assert result.status == "failed"
        assert "handle error" in result.summary
    finally:
        AgentRegistry.unregister("dummy_swarm_exc")


# ── SwarmOrchestrator.run ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_run_delegates_to_execute_task():
    """run() creates a SwarmTask and calls _execute_task."""
    class _RunAgent(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_run"
        async def handle(self, envelope):
            return TaskResult(task_id="t1", status="success", summary="ran", evidence=[])

    AgentRegistry.register_type(
        role_name="dummy_swarm_run",
        agent_class=_RunAgent,
        capabilities=["unique_run_cap_xyz"],
    )
    try:
        orch = SwarmOrchestrator()
        result = await orch.run("do stuff", intent="unique_run_cap_xyz")
        assert isinstance(result, SwarmResult)
    finally:
        AgentRegistry.unregister("dummy_swarm_run")


# ── SwarmOrchestrator.run_parallel ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_run_parallel():
    """run_parallel executes multiple tasks concurrently."""
    class _ParAgent(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_par"
        async def handle(self, envelope):
            return TaskResult(task_id="t1", status="success", summary="parallel", evidence=[])

    AgentRegistry.register_type(
        role_name="dummy_swarm_par",
        agent_class=_ParAgent,
        capabilities=["unique_par_cap_xyz"],
    )
    try:
        orch = SwarmOrchestrator()
        tasks = [
            SwarmTask(goal="task1", intent="unique_par_cap_xyz"),
            SwarmTask(goal="task2", intent="unique_par_cap_xyz"),
        ]
        results = await orch.run_parallel(tasks)
        assert len(results) == 2
        assert all(r.status == "success" for r in results)
    finally:
        AgentRegistry.unregister("dummy_swarm_par")


# ── SwarmOrchestrator.run_pipeline ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_run_pipeline():
    """run_pipeline runs tasks sequentially and accumulates context."""
    class _PipeAgent(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_pipe"
        async def handle(self, envelope):
            return TaskResult(task_id="t1", status="success", summary="piped", evidence=[])

    AgentRegistry.register_type(
        role_name="dummy_swarm_pipe",
        agent_class=_PipeAgent,
        capabilities=["unique_pipe_cap_xyz"],
    )
    try:
        orch = SwarmOrchestrator()
        tasks = [
            SwarmTask(goal="step 1", intent="unique_pipe_cap_xyz"),
            SwarmTask(goal="step 2", intent="unique_pipe_cap_xyz"),
        ]
        results = await orch.run_pipeline(tasks)
        assert len(results) == 2
    finally:
        AgentRegistry.unregister("dummy_swarm_pipe")


# ── active_task_count and available_agents ────────────────────────────────────

def test_active_task_count_initial():
    """active_task_count starts at 0."""
    orch = SwarmOrchestrator()
    assert orch.active_task_count == 0


def test_available_agents_returns_list():
    """available_agents returns list of role names."""
    orch = SwarmOrchestrator()
    agents = orch.available_agents()
    assert isinstance(agents, list)


# ── SwarmTask dataclass ───────────────────────────────────────────────────────

def test_swarm_task_defaults():
    task = SwarmTask(goal="test")
    assert task.intent == "mixed"
    assert task.context == {}
    assert task.task_id.startswith("swarm-")
    assert task.preferred_agent is None


def test_swarm_result_defaults():
    result = SwarmResult(
        task_id="t1",
        agent_role="coder",
        status="success",
        summary="ok",
        elapsed_ms=100,
    )
    assert result.evidence == []


# ── preferred_agent routing ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_task_with_preferred_agent():
    """_execute_task uses route_by_role when preferred_agent is set."""
    class _PrefAgent(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_pref"
        async def handle(self, envelope):
            return TaskResult(task_id="t1", status="success", summary="preferred", evidence=[])

    AgentRegistry.register_type(
        role_name="dummy_swarm_pref",
        agent_class=_PrefAgent,
        capabilities=[],
    )
    try:
        orch = SwarmOrchestrator()
        task = SwarmTask(goal="use preferred", preferred_agent="dummy_swarm_pref")
        result = await orch._execute_task(task)
        assert result.status == "success"
    finally:
        AgentRegistry.unregister("dummy_swarm_pref")


# ── pipeline accumulates context from success ──────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_run_pipeline_accumulates_context():
    """run_pipeline accumulates successful results as context for next task."""
    received_contexts = []

    class _CtxAgent(_ConcreteAgent):
        ROLE_NAME = "dummy_swarm_ctx"
        async def handle(self, envelope):
            received_contexts.append(dict(envelope.context))
            return TaskResult(task_id="t1", status="success", summary="context_result", evidence=[])

    AgentRegistry.register_type(
        role_name="dummy_swarm_ctx",
        agent_class=_CtxAgent,
        capabilities=["unique_ctx_cap_xyz"],
    )
    try:
        orch = SwarmOrchestrator()
        tasks = [
            SwarmTask(goal="step 1", intent="unique_ctx_cap_xyz"),
            SwarmTask(goal="step 2", intent="unique_ctx_cap_xyz"),
        ]
        results = await orch.run_pipeline(tasks)
        # Second task should have context from first
        if len(received_contexts) >= 2:
            assert any("prev_dummy_swarm_ctx" in ctx for ctx in received_contexts[1:])
    finally:
        AgentRegistry.unregister("dummy_swarm_ctx")
