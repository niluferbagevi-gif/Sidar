"""web_server akışında swarm route -> ajan seçimi entegrasyonu."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

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

    user = SimpleNamespace(id="u-test")
    web_server.app.dependency_overrides[web_server._get_request_user] = lambda: user

    try:
        with TestClient(web_server.app) as client:
            response = client.post(
                "/api/swarm/execute",
                json={
                    "mode": "parallel",
                    "tasks": [{"goal": "Kampanya mesajı üret", "intent": "marketing"}],
                    "session_id": "",
                    "max_concurrency": 2,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"][0]["agent_role"] == "poyraz"
        assert captured["intent"] == "marketing"
        assert captured["goal"] == "Kampanya mesajı üret"
        assert captured["session_id"].startswith("swarm-u-test")
    finally:
        web_server.app.dependency_overrides.pop(web_server._get_request_user, None)
