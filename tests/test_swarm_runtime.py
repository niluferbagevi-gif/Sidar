import asyncio

from agent.core.contracts import TaskResult
from agent.registry import AgentRegistry, AgentSpec
from agent.swarm import SwarmOrchestrator, SwarmTask, TaskRouter


class _OkAgent:
    def __init__(self, cfg=None):
        self.cfg = cfg

    async def handle(self, envelope):
        return TaskResult(
            task_id=envelope.task_id,
            status="success",
            summary=f"handled:{envelope.goal}",
            evidence=[f"role={envelope.receiver}"],
        )


class _FailAgent:
    def __init__(self, cfg=None):
        self.cfg = cfg

    async def handle(self, _envelope):
        raise RuntimeError("boom")


def test_task_router_falls_back_to_any_registered_agent(monkeypatch):
    fallback = AgentSpec(role_name="fallback", agent_class=_OkAgent, capabilities=[])
    monkeypatch.setattr(AgentRegistry, "find_by_capability", classmethod(lambda cls, _: []))
    monkeypatch.setattr(AgentRegistry, "list_all", classmethod(lambda cls: [fallback]))

    spec = TaskRouter().route("unknown-intent")
    assert spec is fallback


def test_orchestrator_returns_skipped_when_no_agent_found(monkeypatch):
    monkeypatch.setattr(AgentRegistry, "find_by_capability", classmethod(lambda cls, _: []))
    monkeypatch.setattr(AgentRegistry, "list_all", classmethod(lambda cls: []))

    result = asyncio.run(SwarmOrchestrator().run("any goal", intent="not-mapped"))

    assert result.status == "skipped"
    assert result.agent_role == "none"


def test_orchestrator_reports_agent_creation_failure(monkeypatch):
    spec = AgentSpec(role_name="broken", agent_class=_OkAgent, capabilities=["code_generation"])
    monkeypatch.setattr(AgentRegistry, "find_by_capability", classmethod(lambda cls, _: [spec]))

    def _raise_create(cls, _role, **_kwargs):
        raise RuntimeError("cannot-create")

    monkeypatch.setattr(AgentRegistry, "create", classmethod(_raise_create))

    result = asyncio.run(SwarmOrchestrator().run("build", intent="code_generation"))

    assert result.status == "failed"
    assert "cannot-create" in result.summary


def test_orchestrator_cleans_active_agents_on_handle_exception(monkeypatch):
    spec = AgentSpec(role_name="failing", agent_class=_FailAgent, capabilities=["code_generation"])
    monkeypatch.setattr(AgentRegistry, "find_by_capability", classmethod(lambda cls, _: [spec]))
    monkeypatch.setattr(AgentRegistry, "create", classmethod(lambda cls, _role, **_kwargs: _FailAgent()))

    orchestrator = SwarmOrchestrator()
    result = asyncio.run(orchestrator.run("build", intent="code_generation"))

    assert result.status == "failed"
    assert orchestrator.active_task_count == 0


def test_run_pipeline_passes_previous_success_summary(monkeypatch):
    spec = AgentSpec(role_name="coder", agent_class=_OkAgent, capabilities=["code_generation"])
    monkeypatch.setattr(AgentRegistry, "find_by_capability", classmethod(lambda cls, _: [spec]))

    contexts = []

    class _CtxAgent(_OkAgent):
        async def handle(self, envelope):
            contexts.append(dict(envelope.context))
            return TaskResult(task_id=envelope.task_id, status="success", summary="x" * 600)

    monkeypatch.setattr(AgentRegistry, "create", classmethod(lambda cls, _role, **_kwargs: _CtxAgent()))

    tasks = [
        SwarmTask(goal="step1", intent="code_generation"),
        SwarmTask(goal="step2", intent="code_generation"),
    ]

    results = asyncio.run(SwarmOrchestrator().run_pipeline(tasks, session_id="s1"))

    assert len(results) == 2
    assert contexts[0]["session_id"] == "s1"
    assert "prev_coder" in contexts[1]
    assert len(contexts[1]["prev_coder"]) == 500


def test_run_parallel_executes_all_tasks(monkeypatch):
    spec = AgentSpec(role_name="coder", agent_class=_OkAgent, capabilities=["code_generation"])
    monkeypatch.setattr(AgentRegistry, "find_by_capability", classmethod(lambda cls, _: [spec]))
    monkeypatch.setattr(AgentRegistry, "create", classmethod(lambda cls, _role, **_kwargs: _OkAgent()))

    tasks = [SwarmTask(goal=f"g{i}", intent="code_generation") for i in range(5)]
    results = asyncio.run(SwarmOrchestrator().run_parallel(tasks, max_concurrency=2))

    assert len(results) == 5
    assert all(r.status == "success" for r in results)
