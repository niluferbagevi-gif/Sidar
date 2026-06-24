"""Backend E2E coverage for booting the app and streaming chat over WebSocket."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.db import Database

if "opentelemetry.instrumentation.httpx" not in sys.modules:
    fake_httpx_mod = SimpleNamespace(
        HTTPXClientInstrumentor=SimpleNamespace(instrument=lambda *args, **kwargs: None)
    )
    sys.modules["opentelemetry.instrumentation.httpx"] = fake_httpx_mod

import web_server
from web_server import app


class _E2EMemory:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.active_user: tuple[str, str] | None = None
        self.title = ""

    def __len__(self) -> int:
        return 0

    async def set_active_user(self, user_id: str, username: str) -> None:
        self.active_user = (user_id, username)

    async def aupdate_title(self, title: str) -> None:
        self.title = title

    async def update_title(self, title: str) -> None:
        self.title = title


@pytest.mark.integration
def test_boot_health_then_chat_websocket_tool_call_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise app boot, WebSocket auth, tool-call streaming, and final response."""
    mock_db = Mock(spec=Database)
    fake_agent = SimpleNamespace(
        memory=_E2EMemory(mock_db),
        system_prompt="",
        cfg=SimpleNamespace(AI_PROVIDER="openai"),
        health=SimpleNamespace(get_health_summary=lambda: {"status": "ok", "ollama_online": True}),
    )

    async def _fake_get_agent():
        return fake_agent

    async def _fake_resolve(_agent, token):
        if token == "e2e-token":
            return SimpleNamespace(
                id="e2e-user-id", username="e2e_user", role="admin", tenant_id="default"
            )
        return None

    async def _never_rate_limited(*_args, **_kwargs):
        return False

    async def _respond(prompt: str, **_kwargs):
        assert prompt == "E2E araç çağrısı yap ve cevapla"
        yield "\x00THOUGHT:E2E plan hazırlanıyor\x00"
        yield "\x00TOOL:docs_search\x00"
        yield "Araç sonucu alındı. "
        yield "Yanıt hazır."

    fake_agent.respond = _respond
    assert asyncio.run(_fake_resolve(fake_agent, "invalid")) is None
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _never_rate_limited)

    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200

        with client.websocket_connect("/ws/chat") as websocket:
            websocket.send_json({"action": "auth", "token": "e2e-token"})
            assert websocket.receive_json() == {"auth_ok": True}

            websocket.send_json({"message": "E2E araç çağrısı yap ve cevapla"})

            chunks: list[str] = []
            tool_calls: list[str] = []
            thoughts: list[str] = []
            done = False
            while not done:
                event = websocket.receive_json()
                if "chunk" in event:
                    chunks.append(event["chunk"])
                if "tool_call" in event:
                    tool_calls.append(event["tool_call"])
                if "thought" in event:
                    thoughts.append(event["thought"])
                done = bool(event.get("done"))

    assert fake_agent.memory.active_user == ("e2e-user-id", "e2e_user")
    assert thoughts == ["E2E plan hazırlanıyor"]
    assert tool_calls == ["docs_search"]
    assert "".join(chunks) == "Araç sonucu alındı. Yanıt hazır."
