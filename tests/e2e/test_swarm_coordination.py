"""Swarm koordinasyon E2E senaryosu: Researcher + Coder görev bölüşümü."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agent.swarm import SwarmOrchestrator, SwarmTask
from agent.registry import AgentRegistry
from config import Config
from agent.core.contracts import TaskResult


def test_swarm_orchestrator_distributes_tasks_between_researcher_and_coder(monkeypatch):
    async def _run_case() -> None:
        orchestrator = SwarmOrchestrator(cfg=Config())

        class _FakeResearcher:
            async def handle(self, envelope):
                return TaskResult(task_id=envelope.task_id, status="success", summary=f"[RESEARCH] {envelope.goal}")

        class _FakeCoder:
            async def handle(self, envelope):
                return TaskResult(task_id=envelope.task_id, status="success", summary=f"[CODE] {envelope.goal}")

        async def _noop(*_args, **_kwargs):
            return None

        def _create_agent(role, *_args, **_kwargs):
            return _FakeResearcher() if role == "researcher" else _FakeCoder()

        monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role: SimpleNamespace(role_name=role))
        monkeypatch.setattr(AgentRegistry, "create", _create_agent)
        monkeypatch.setattr(orchestrator, "_schedule_autonomous_feedback", _noop)

        tasks = [
            SwarmTask(goal="Bir konu araştır", intent="research", preferred_agent="researcher"),
            SwarmTask(goal="Araştırma raporundan özet kod bloğu yaz", intent="code", preferred_agent="coder"),
        ]

        results = await asyncio.wait_for(
            orchestrator.run_pipeline(tasks, session_id="swarm-e2e"), timeout=30
        )

        assert len(results) == 2
        assert results[0].agent_role == "researcher"
        assert results[1].agent_role == "coder"
        assert "[RESEARCH]" in results[0].summary
        assert "[CODE]" in results[1].summary

    asyncio.run(_run_case())
