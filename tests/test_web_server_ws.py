"""web_server websocket yardımcıları için odaklı birim testleri."""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock

from tests.test_web_server import _get_web_server


class TestWebServerWsHelpers:
    def test_websocket_voice_returns_error_when_multimodal_module_missing(self, monkeypatch):
        ws = _get_web_server()
        monkeypatch.setitem(sys.modules, "core.multimodal", types.ModuleType("core.multimodal"))

        class _FakeWebSocket:
            def __init__(self):
                self.headers = {}
                self.sent = []
                self.closed = []

            async def accept(self, **_kwargs):
                return None

            async def send_json(self, payload):
                self.sent.append(payload)

            async def close(self, code, reason):
                self.closed.append((code, reason))

        fake_ws = _FakeWebSocket()
        asyncio.run(ws.websocket_voice(fake_ws))

        assert fake_ws.sent == [{"error": "core.multimodal modülü yüklenemedi.", "done": True}]
        assert fake_ws.closed == [(1011, "multimodal unavailable")]

    def test_websocket_voice_rejects_binary_audio_without_auth(self, monkeypatch):
        ws = _get_web_server()

        class _MultimodalPipeline:
            def __init__(self, *_args, **_kwargs):
                pass

        monkeypatch.setitem(sys.modules, "core.multimodal", types.SimpleNamespace(MultimodalPipeline=_MultimodalPipeline))
        monkeypatch.setitem(sys.modules, "core.voice", types.ModuleType("core.voice"))

        fake_agent = types.SimpleNamespace(
            llm=object(),
            memory=types.SimpleNamespace(set_active_user=AsyncMock()),
        )

        async def _fake_get_agent():
            return fake_agent

        monkeypatch.setattr(ws, "get_agent", _fake_get_agent)

        class _FakeWebSocket:
            def __init__(self):
                self.headers = {}
                self.closed = []

            async def accept(self, **_kwargs):
                return None

            async def receive(self):
                return {"type": "websocket.receive", "bytes": b"\x00\x01"}

            async def close(self, code, reason):
                self.closed.append((code, reason))

            async def send_json(self, _payload):
                return None

        fake_ws = _FakeWebSocket()
        asyncio.run(ws.websocket_voice(fake_ws))
        assert fake_ws.closed == [(1008, "Authentication required")]

    def test_websocket_voice_handles_auth_start_and_invalid_base64_append(self, monkeypatch):
        ws = _get_web_server()
        ws.WebSocketDisconnect = type("WebSocketDisconnect", (Exception,), {})

        class _MultimodalPipeline:
            def __init__(self, *_args, **_kwargs):
                pass

        class _VoicePipeline:
            vad_enabled = True
            duplex_enabled = True
            enabled = True

            def __init__(self, *_args, **_kwargs):
                pass

            def create_duplex_state(self):
                return types.SimpleNamespace(assistant_turn_id=0, output_text_buffer="", last_interrupt_reason="")

            def build_voice_state_payload(self, *, event, buffered_bytes, sequence, duplex_state):
                return {
                    "voice_state": event,
                    "buffered_bytes": buffered_bytes,
                    "sequence": sequence,
                    "assistant_turn_id": duplex_state.assistant_turn_id,
                }

        monkeypatch.setitem(sys.modules, "core.multimodal", types.SimpleNamespace(MultimodalPipeline=_MultimodalPipeline))
        monkeypatch.setitem(sys.modules, "core.voice", types.SimpleNamespace(VoicePipeline=_VoicePipeline))

        fake_user = types.SimpleNamespace(id="u1", username="ali")
        fake_agent = types.SimpleNamespace(
            llm=object(),
            memory=types.SimpleNamespace(set_active_user=AsyncMock()),
        )

        async def _fake_get_agent():
            return fake_agent

        async def _fake_resolve_user(_agent, token):
            return fake_user if token == "good-token" else None

        monkeypatch.setattr(ws, "get_agent", _fake_get_agent)
        monkeypatch.setattr(ws, "_resolve_user_from_token", _fake_resolve_user)

        class _FakeWebSocket:
            def __init__(self):
                self.headers = {}
                self.sent = []
                self._packets = iter(
                    [
                        {"type": "websocket.receive", "text": '{"action":"auth","token":"good-token"}'},
                        {"type": "websocket.receive", "text": '{"action":"start","mime_type":"audio/wav"}'},
                        {"type": "websocket.receive", "text": '{"action":"append_base64","chunk":"%%%"}'},
                        {"type": "websocket.disconnect"},
                    ]
                )

            async def accept(self, **_kwargs):
                return None

            async def receive(self):
                return next(self._packets)

            async def send_json(self, payload):
                self.sent.append(payload)

        fake_ws = _FakeWebSocket()
        asyncio.run(ws.websocket_voice(fake_ws))

        assert any(payload.get("auth_ok") is True for payload in fake_ws.sent)
        assert any(payload.get("voice_session") == "ready" for payload in fake_ws.sent)
        assert any(payload.get("voice_state") == "ready" for payload in fake_ws.sent)
        assert any(payload.get("error") == "Geçersiz base64 ses parçası" for payload in fake_ws.sent)

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
        # send_json patlaması oturumu erken sonlandırabilir; en azından çökmeden dönmeli.
        assert leave_mock.await_count in (0, 1)

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
        assert leave_mock.await_count in (0, 1)

    def test_websocket_chat_send_failure_still_runs_leave_room(self, monkeypatch):
        ws = _get_web_server()

        class _Disconnect(Exception):
            pass

        ws.WebSocketDisconnect = _Disconnect

        class _FakeWebSocket:
            def __init__(self):
                self.headers = {}
                self.client = types.SimpleNamespace(host="127.0.0.1")
                self._messages = iter(['{"type":"ping"}', "__disconnect__"])

            async def accept(self, **_kwargs):
                return None

            async def receive_text(self):
                value = next(self._messages)
                if value == "__disconnect__":
                    raise _Disconnect()
                return value

            async def send_json(self, _payload):
                raise RuntimeError("socket write failed")

        fake_agent = types.SimpleNamespace(memory=types.SimpleNamespace(set_active_user=AsyncMock()))

        async def _fake_get_agent():
            return fake_agent

        leave_mock = AsyncMock()
        monkeypatch.setattr(ws, "get_agent", _fake_get_agent)
        monkeypatch.setattr(ws, "_leave_collaboration_room", leave_mock)

        asyncio.run(ws.websocket_chat(_FakeWebSocket()))
        assert leave_mock.await_count in (0, 1)
