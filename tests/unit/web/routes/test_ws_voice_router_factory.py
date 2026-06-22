from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routes import ws_voice


def test_build_ws_voice_router_dispatches_to_websocket_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    async def fake_voice(websocket, deps):
        called["websocket"] = websocket
        called["deps"] = deps
        await websocket.accept()
        await websocket.send_json({"result": "ok"})

    monkeypatch.setattr(ws_voice, "websocket_voice", fake_voice)
    app = FastAPI()
    app.include_router(ws_voice.build_ws_voice_router(lambda: "DEPS"))

    with TestClient(app).websocket_connect("/ws/voice") as websocket:
        assert websocket.receive_json() == {"result": "ok"}

    assert called["deps"] == "DEPS"
    assert called["websocket"].url.path == "/ws/voice"
