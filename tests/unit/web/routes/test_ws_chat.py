from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketState

from web.routes import ws_chat


class _Ws:
    def __init__(
        self, messages: list[str] | None = None, headers: dict[str, str] | None = None
    ) -> None:
        self.headers = headers or {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.sent: list[dict[str, object]] = []
        self.accepted: list[str | None] = []
        self.closed: list[tuple[int, str]] = []
        self._messages = iter(messages or [])
        self.client_state = WebSocketState.CONNECTED

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted.append(subprotocol)

    async def close(self, code: int, reason: str) -> None:
        self.closed.append((code, reason))

    async def receive_text(self) -> str:
        try:
            return next(self._messages)
        except StopIteration as exc:
            raise ws_chat.WebSocketDisconnect() from exc

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)


class _Agent:
    async def respond(self, _prompt: str):
        yield "\x00TOOL:search\x00"
        yield "\x00THOUGHT:thinking\x00"
        yield "hello"


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_streams_sentinels_and_chunks() -> None:
    ws = _Ws()

    await ws_chat.ws_stream_agent_text_response(ws, _Agent(), "prompt")

    assert ws.sent == [
        {"tool_call": "search"},
        {"thought": "thinking"},
        {"chunk": "hello"},
    ]


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_stops_when_client_disconnects() -> None:
    class _StreamingAgent:
        async def respond(self, _prompt: str):
            yield "first"
            yield "second"

    ws = _Ws()

    async def _send_and_disconnect(payload: dict[str, object]) -> None:
        ws.sent.append(payload)
        ws.client_state = WebSocketState.DISCONNECTED

    ws.send_json = _send_and_disconnect  # type: ignore[method-assign]

    await ws_chat.ws_stream_agent_text_response(ws, _StreamingAgent(), "prompt")

    assert ws.sent == [{"chunk": "first"}]


@pytest.mark.asyncio
async def test_websocket_chat_requires_auth_before_non_auth_action() -> None:
    ws = _Ws(['{"action":"message","message":"hello"}'])

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(set_active_user=lambda *_: None))

    async def _close(websocket, reason: str) -> None:
        await websocket.close(code=1008, reason=reason)

    deps = SimpleNamespace(
        extract_ws_header_token=lambda _header: ("", None),
        resolve_agent_instance=_resolve_agent,
        ws_close_policy_violation=_close,
    )

    await ws_chat.websocket_chat(ws, deps)

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Authentication required")]


class _NeverSendsWs(_Ws):
    """A websocket that accepts the connection but never sends any message."""

    async def receive_text(self) -> str:
        await asyncio.sleep(999)
        return "{}"  # pragma: no cover - unreachable, sleep never resolves in the test


class _RepeatedGarbageWs(_Ws):
    """A websocket that keeps sending unparseable junk fast enough to reset

    a naive per-message timeout, without ever authenticating."""

    async def receive_text(self) -> str:
        await asyncio.sleep(0.001)
        return "not json"


@pytest.mark.asyncio
async def test_websocket_chat_closes_idle_unauthenticated_connection_after_timeout() -> None:
    """Regression test: an unauthenticated client that never sends an auth message

    must not keep the connection open forever (slow DoS / resource exhaustion).
    """
    ws = _NeverSendsWs()

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(set_active_user=lambda *_: None))

    async def _close(websocket, reason: str) -> None:
        await websocket.close(code=1008, reason=reason)

    deps = SimpleNamespace(
        extract_ws_header_token=lambda _header: ("", None),
        resolve_agent_instance=_resolve_agent,
        ws_close_policy_violation=_close,
        cfg=SimpleNamespace(WS_AUTH_TIMEOUT_SECONDS=0.05),
    )

    await asyncio.wait_for(ws_chat.websocket_chat(ws, deps), timeout=5)

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Authentication timeout")]


@pytest.mark.asyncio
async def test_websocket_chat_auth_timeout_is_absolute_not_reset_by_junk_messages() -> None:
    """Regression test: repeatedly sending unparseable junk must not let an

    unauthenticated client reset the auth timeout and stay connected forever.
    """
    ws = _RepeatedGarbageWs()

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(set_active_user=lambda *_: None))

    async def _close(websocket, reason: str) -> None:
        await websocket.close(code=1008, reason=reason)

    deps = SimpleNamespace(
        extract_ws_header_token=lambda _header: ("", None),
        resolve_agent_instance=_resolve_agent,
        ws_close_policy_violation=_close,
        cfg=SimpleNamespace(WS_AUTH_TIMEOUT_SECONDS=0.05),
    )

    await asyncio.wait_for(ws_chat.websocket_chat(ws, deps), timeout=5)

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Authentication timeout")]


@pytest.mark.asyncio
async def test_websocket_chat_uses_default_header_token_extractor_when_dependency_missing() -> None:
    ws = _Ws(['{"action":"message","message":"hello"}'])

    async def _resolve_agent():
        return SimpleNamespace(memory=SimpleNamespace(set_active_user=lambda *_: None))

    async def _close(websocket, reason: str) -> None:
        await websocket.close(code=1008, reason=reason)

    deps = SimpleNamespace(
        resolve_agent_instance=_resolve_agent,
        ws_close_policy_violation=_close,
    )

    await ws_chat.websocket_chat(ws, deps)

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Authentication required")]
