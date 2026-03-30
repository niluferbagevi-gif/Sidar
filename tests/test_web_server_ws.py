"""web_server websocket yardımcıları için odaklı birim testleri."""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock

from tests.test_web_server import _get_web_server


class TestWebServerWsHelpers:
    def test_ws_close_policy_violation_calls_close_when_available(self):
        ws = _get_web_server()
        websocket = type("WS", (), {})()
        websocket.close = AsyncMock()

        asyncio.run(ws._ws_close_policy_violation(websocket, "Auth required"))

        websocket.close.assert_awaited_once_with(code=1008, reason="Auth required")

    def test_ws_close_policy_violation_noop_without_close_attr(self):
        ws = _get_web_server()
        websocket = object()

        # close attr yoksa exception atmadan çıkmalı
        asyncio.run(ws._ws_close_policy_violation(websocket, "ignored"))

    def test_websocket_chat_handles_abrupt_disconnect_and_leaves_room(self, monkeypatch):
        ws = _get_web_server()

        class _Disconnect(Exception):
            pass

        ws.WebSocketDisconnect = _Disconnect

        class _FakeWebSocket:
            def __init__(self):
                self.headers = {}
                self.client = types.SimpleNamespace(host="127.0.0.1")

            async def accept(self, **_kwargs):
                return None

            async def receive_text(self):
                raise _Disconnect()

            async def send_json(self, _payload):
                return None

        fake_agent = types.SimpleNamespace(memory=types.SimpleNamespace(set_active_user=AsyncMock()))

        async def _fake_get_agent():
            return fake_agent

        leave_mock = AsyncMock()
        monkeypatch.setattr(ws, "get_agent", _fake_get_agent)
        monkeypatch.setattr(ws, "_leave_collaboration_room", leave_mock)

        asyncio.run(ws.websocket_chat(_FakeWebSocket()))
        leave_mock.assert_awaited_once()

    def test_websocket_chat_ignores_invalid_json_payload_then_disconnects_cleanly(self, monkeypatch):
        ws = _get_web_server()

        class _Disconnect(Exception):
            pass

        ws.WebSocketDisconnect = _Disconnect

        class _FakeWebSocket:
            def __init__(self):
                self.headers = {}
                self.client = types.SimpleNamespace(host="127.0.0.1")
                self._messages = iter(["this-is-not-json", "__disconnect__"])

            async def accept(self, **_kwargs):
                return None

            async def receive_text(self):
                value = next(self._messages)
                if value == "__disconnect__":
                    raise _Disconnect()
                return value

            async def send_json(self, _payload):
                return None

        fake_agent = types.SimpleNamespace(memory=types.SimpleNamespace(set_active_user=AsyncMock()))

        async def _fake_get_agent():
            return fake_agent

        leave_mock = AsyncMock()
        monkeypatch.setattr(ws, "get_agent", _fake_get_agent)
        monkeypatch.setattr(ws, "_leave_collaboration_room", leave_mock)

        asyncio.run(ws.websocket_chat(_FakeWebSocket()))
        leave_mock.assert_awaited_once()