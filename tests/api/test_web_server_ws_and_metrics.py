from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Iterator

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

import web_server


class _MemoryStub:
    def __init__(self) -> None:
        self._turns = []

    def __len__(self) -> int:
        return len(self._turns)

    async def set_active_user(self, _user_id: str, _username: str) -> None:
        return None

    async def update_title(self, _title: str) -> None:
        return None

    def get_all_sessions(self):
        return ["s1", "s2"]


class _AgentStub:
    VERSION = "5.1.0"

    def __init__(self) -> None:
        self.memory = _MemoryStub()
        self.docs = SimpleNamespace(doc_count=3)
        self.cfg = SimpleNamespace(AI_PROVIDER="test", USE_GPU=False)

    async def respond(self, _msg: str):
        yield "selam"
        yield "dünya"


class _BusStub:
    def subscribe(self):
        import asyncio

        return "sub", asyncio.Queue()

    def unsubscribe(self, _sub_id):
        return None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    agent = _AgentStub()

    async def _fake_get_agent():
        return agent

    async def _not_limited(*_args, **_kwargs):
        return False

    async def _resolve_user(*_args, **_kwargs):
        return SimpleNamespace(id="u1", username="alice", role="developer")

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _not_limited)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_user)
    monkeypatch.setattr(web_server, "get_agent_event_bus", lambda: _BusStub())

    web_server.app.dependency_overrides[web_server._require_admin_user] = lambda: SimpleNamespace(role="admin")
    web_server.app.dependency_overrides[web_server._require_metrics_access] = lambda: SimpleNamespace(role="admin")
    with TestClient(web_server.app, raise_server_exceptions=False) as test_client:
        yield test_client
    web_server.app.dependency_overrides.clear()


def test_register_agent_plugin_file_accepts_utf8_upload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server, "_persist_and_import_plugin_file", lambda *_a, **_k: None)
    monkeypatch.setattr(
        web_server,
        "_register_plugin_agent",
        lambda **kwargs: {"role_name": kwargs["role_name"], "capabilities": kwargs["capabilities"]},
    )

    response = client.post(
        "/api/agents/register-file",
        params={"capabilities": "code_generation,review", "role_name": "custom_agent"},
        files={"file": ("plugin.py", b"class Demo: pass", "text/plain")},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["agent"]["role_name"] == "custom_agent"
    assert body["agent"]["capabilities"] == ["code_generation", "review"]


def test_metrics_returns_json_payload(client: TestClient) -> None:
    response = client.get("/metrics", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "5.1.0"
    assert payload["sessions_total"] == 2
    assert payload["rag_documents"] == 3


def test_chat_websocket_auth_and_stream_flow(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_text(json.dumps({"action": "auth", "token": "tkn"}))
        assert ws.receive_json()["auth_ok"] is True

        ws.send_text(json.dumps({"message": "Merhaba"}))
        first = ws.receive_json()
        second = ws.receive_json()
        done = ws.receive_json()

    chunks = [first.get("chunk"), second.get("chunk")]
    assert chunks == ["selam", "dünya"]
    assert done == {"done": True}
