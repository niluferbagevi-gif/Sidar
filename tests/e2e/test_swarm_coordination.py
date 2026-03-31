"""Swarm koordinasyon E2E senaryosu: Researcher + Coder görev bölüşümü."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.swarm import SwarmOrchestrator, SwarmTask
from agent.registry import AgentRegistry
from config import Config


@pytest.mark.asyncio
async def test_swarm_orchestrator_distributes_tasks_between_researcher_and_coder(monkeypatch):
    orchestrator = SwarmOrchestrator(cfg=Config())

    class _FakeResearcher:
        async def run_task(self, prompt: str):
            return f"[RESEARCH] {prompt}"

    class _FakeCoder:
        async def run_task(self, prompt: str):
            return f"[CODE] {prompt}"

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role: SimpleNamespace(role_name=role))
    monkeypatch.setattr(AgentRegistry, "create", lambda role, cfg=None: _FakeResearcher() if role == "researcher" else _FakeCoder())
    monkeypatch.setattr(orchestrator, "_schedule_autonomous_feedback", _noop)

    tasks = [
        SwarmTask(goal="Bir konu araştır", intent="research", preferred_agent="researcher"),
        SwarmTask(goal="Araştırma raporundan özet kod bloğu yaz", intent="code", preferred_agent="coder"),
    ]

    results = await orchestrator.run_pipeline(tasks, session_id="swarm-e2e")

    assert len(results) == 2
    assert results[0].agent_role == "researcher"
    assert results[1].agent_role == "coder"
    assert "[RESEARCH]" in results[0].summary
    assert "[CODE]" in results[1].summary
