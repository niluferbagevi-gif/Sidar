"""web_server websocket yardımcıları için odaklı birim testleri."""

from __future__ import annotations

import asyncio
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
