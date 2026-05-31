from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from web.routes.orchestration import build_orchestration_router


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


@dataclass
class _TaskInput:
    goal: str
    intent: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    preferred_agent: str = ""


@dataclass
class _ExecuteRequest:
    tasks: list[_TaskInput]
    mode: str = "parallel"
    session_id: str = ""
    max_concurrency: int = 2


@dataclass
class _SwarmTask:
    goal: str
    intent: str
    context: dict[str, Any]
    preferred_agent: str | None


class _Orchestrator:
    calls: list[tuple[str, list[_SwarmTask], str, int | None]] = []

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    async def run_pipeline(self, tasks: list[_SwarmTask], *, session_id: str) -> list[Any]:
        self.calls.append(("pipeline", tasks, session_id, None))
        return [SimpleNamespace(ok=True)]

    async def run_parallel(
        self, tasks: list[_SwarmTask], *, session_id: str, max_concurrency: int
    ) -> list[Any]:
        self.calls.append(("parallel", tasks, session_id, max_concurrency))
        return [SimpleNamespace(ok=True)]


def _exports(agent: Any) -> dict[str, Any]:
    async def _resolve_agent() -> Any:
        return agent

    return build_orchestration_router(
        get_request_user=lambda: SimpleNamespace(id="u1"),
        require_admin_user=lambda: SimpleNamespace(id="admin"),
        resolve_agent_instance=_resolve_agent,
        await_if_needed=_await_if_needed,
        swarm_orchestrator_cls=_Orchestrator,
        swarm_task_cls=_SwarmTask,
        cfg=SimpleNamespace(),
        swarm_execute_request_model=_ExecuteRequest,
    ).legacy_exports


@pytest.mark.asyncio
async def test_execute_swarm_filters_blank_tasks_and_routes_both_modes() -> None:
    _Orchestrator.calls.clear()
    exports = _exports(SimpleNamespace(cfg=SimpleNamespace()))
    user = SimpleNamespace(id="u1")
    tasks = [_TaskInput(goal="  ship  ", intent="  "), _TaskInput(goal="   ")]

    pipeline = await exports["execute_swarm"](_ExecuteRequest(tasks=tasks, mode="pipeline"), user)
    parallel = await exports["execute_swarm"](_ExecuteRequest(tasks=tasks), user)

    assert pipeline.status_code == 200
    assert parallel.status_code == 200
    assert _Orchestrator.calls[0][0:3] == (
        "pipeline",
        [_SwarmTask("ship", "mixed", {}, None)],
        "swarm-u1",
    )
    assert _Orchestrator.calls[1][0] == "parallel"
    assert _Orchestrator.calls[1][3] == 2

    with pytest.raises(HTTPException, match="En az bir geçerli task"):
        await exports["execute_swarm"](_ExecuteRequest(tasks=[_TaskInput(goal=" ")]), user)


@pytest.mark.asyncio
async def test_orchestration_todo_and_set_level_edges() -> None:
    async def _set_level(level: str) -> str:
        agent.security.level_name = level
        return f"level={level}"

    agent = SimpleNamespace(
        todo=SimpleNamespace(get_tasks=lambda: [{"status": "pending"}, {"status": "completed"}]),
        memory=SimpleNamespace(clear=lambda: None),
        security=SimpleNamespace(level_name="low"),
        set_access_level=_set_level,
    )
    exports = _exports(agent)

    class _Request:
        def __init__(self, level: str) -> None:
            self.level = level

        async def json(self) -> dict[str, str]:
            return {"level": self.level}

    todo = await exports["get_todo"]()
    assert todo.status_code == 200
    assert (
        todo.body == b'{"tasks":[{"status":"pending"},{"status":"completed"}],"count":2,"active":1}'
    )
    assert (await exports["clear"]()).status_code == 200
    assert (await exports["set_level_endpoint"](_Request(" "))).status_code == 400
    changed = await exports["set_level_endpoint"](_Request("high"))
    assert changed.status_code == 200
    assert agent.security.level_name == "high"
