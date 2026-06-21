from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes import ws_chat


def test_build_ws_chat_router_dispatches_to_websocket_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def fake_chat(websocket, deps):
        called["websocket"] = websocket
        called["deps"] = deps
        await websocket.accept()
        await websocket.send_json({"result": "ok"})

    monkeypatch.setattr(ws_chat, "websocket_chat", fake_chat)
    app = FastAPI()
    app.include_router(ws_chat.build_ws_chat_router(lambda: "DEPS"))

    with TestClient(app).websocket_connect("/ws/chat") as websocket:
        assert websocket.receive_json() == {"result": "ok"}

    assert called["deps"] == "DEPS"
    assert called["websocket"].url.path == "/ws/chat"
