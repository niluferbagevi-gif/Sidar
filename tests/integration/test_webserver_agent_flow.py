"""web_server akışında swarm route -> ajan seçimi entegrasyonu."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import web_server


def test_execute_swarm_routes_marketing_intent_to_poyraz(monkeypatch):
    captured: dict[str, str] = {}

    class _FakeOrchestrator:
        def __init__(self, _cfg):
            pass

        async def run_parallel(self, tasks, *, session_id: str, max_concurrency: int):
            captured["intent"] = tasks[0].intent
            captured["goal"] = tasks[0].goal
            captured["session_id"] = session_id
            return [
                SimpleNamespace(
                    task_id=tasks[0].task_id,
                    agent_role="poyraz",
                    status="success",
                    summary="[POYRAZ] kampanya taslağı hazır",
                    elapsed_ms=7,
                    evidence=[],
                    handoffs=[],
                    graph={},
                )
            ]

    monkeypatch.setattr(web_server, "SwarmOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(web_server, "get_agent", AsyncMock(return_value=SimpleNamespace(cfg=web_server.cfg)))

    payload = web_server._SwarmExecuteRequest(
        mode="parallel",
        tasks=[
            web_server._SwarmTaskRequest(
                goal="Kampanya mesajı üret",
                intent="marketing",
            )
        ],
        session_id="",
        max_concurrency=2,
    )

    async def _run_case() -> None:
        user = SimpleNamespace(id="u-test")
        response = await web_server.execute_swarm(payload, user=user)
        body = response.body.decode("utf-8")

        assert '"success":true' in body
        assert '"agent_role":"poyraz"' in body
        assert captured["intent"] == "marketing"
        assert captured["goal"] == "Kampanya mesajı üret"
        assert captured["session_id"].startswith("swarm-u-test")

    asyncio.run(_run_case())
