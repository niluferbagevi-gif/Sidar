"""Coder -> Reviewer yazılım döngüsü E2E senaryosu."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from agent.core.contracts import TaskResult
from agent.core.supervisor import SupervisorAgent
from config import Config


def test_supervisor_runs_coder_then_reviewer_pipeline():
    async def _run_case() -> None:
        supervisor = SupervisorAgent(cfg=Config())
        supervisor.events.publish = AsyncMock()

        supervisor._delegate = AsyncMock(
            side_effect=[
                TaskResult(task_id="t-code", status="done", summary="print('hello pipeline')"),
                TaskResult(task_id="t-review", status="done", summary="[REVIEW] onaylandı"),
            ]
        )

        result = await supervisor.run_task("Basit bir hello-world scripti yaz")

        assert "print('hello pipeline')" in result
        assert "[REVIEW] onaylandı" in result
        assert supervisor._delegate.await_count == 2
        first_call = supervisor._delegate.await_args_list[0].args
        second_call = supervisor._delegate.await_args_list[1].args
        assert first_call[0] == "coder"
        assert second_call[0] == "reviewer"

    asyncio.run(_run_case())
