from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse


def _parse_payload(model: type[Any], payload: Any) -> Any:
    if hasattr(model, "model_validate"):
        return model.model_validate(payload)
    if isinstance(payload, dict):
        return model(**payload)
    return payload


def build_orchestration_router(
    *,
    get_request_user: Callable[..., Any],
    require_admin_user: Callable[..., Any],
    resolve_agent_instance: Callable[[], Awaitable[Any]],
    await_if_needed: Callable[[Any], Awaitable[Any]],
    swarm_orchestrator_cls: type[Any],
    swarm_task_cls: type[Any],
    cfg: Any,
    swarm_execute_request_model: type[Any],
    serialize_swarm_result: Callable[[Any], dict[str, Any]],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/swarm/execute")
    async def execute_swarm(
        payload: Any, user: Any = Depends(get_request_user)
    ) -> Any:
        data = _parse_payload(swarm_execute_request_model, payload)
        agent = await resolve_agent_instance()
        orchestrator = swarm_orchestrator_cls(getattr(agent, "cfg", cfg))
        session_id = data.session_id.strip() or f"swarm-{getattr(user, 'id', 'anon')}"
        tasks = [
            swarm_task_cls(
                goal=item.goal.strip(),
                intent=item.intent.strip() or "mixed",
                context=dict(item.context or {}),
                preferred_agent=(item.preferred_agent or "").strip() or None,
            )
            for item in data.tasks
            if item.goal.strip()
        ]
        if not tasks:
            raise HTTPException(status_code=400, detail="En az bir geçerli task gereklidir")

        if data.mode == "pipeline":
            results = await orchestrator.run_pipeline(tasks, session_id=session_id)
        else:
            results = await orchestrator.run_parallel(
                tasks,
                session_id=session_id,
                max_concurrency=data.max_concurrency,
            )
        return JSONResponse(
            {
                "success": True,
                "mode": data.mode,
                "session_id": session_id,
                "task_count": len(tasks),
                "results": [serialize_swarm_result(item) for item in results],
            }
        )

    @router.get("/todo")
    async def get_todo() -> Any:
        agent = await resolve_agent_instance()
        tasks = agent.todo.get_tasks()
        active = sum(1 for t in tasks if t["status"] != "completed")
        return JSONResponse({"tasks": tasks, "count": len(tasks), "active": active})

    @router.post("/clear")
    async def clear() -> Any:
        agent = await resolve_agent_instance()
        await await_if_needed(agent.memory.clear())
        return JSONResponse({"result": True})

    @router.post("/set-level")
    async def set_level_endpoint(
        request: Request, _user: Any = Depends(require_admin_user)
    ) -> Any:
        body = await request.json()
        new_level = body.get("level", "").strip()
        if not new_level:
            return JSONResponse({"success": False, "error": "Seviye belirtilmedi."}, status_code=400)
        agent = await await_if_needed(resolve_agent_instance())
        result_msg = await asyncio.to_thread(agent.set_access_level, new_level)
        if asyncio.iscoroutine(result_msg):
            result_msg = await result_msg
        return JSONResponse(
            {
                "success": True,
                "message": result_msg,
                "current_level": agent.security.level_name,
            }
        )

    return router
