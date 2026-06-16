from __future__ import annotations

from types import SimpleNamespace

import pytest

from web.routes import ws_chat


class _Ws:
    def __init__(self, messages: list[str] | None = None, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.sent: list[dict[str, object]] = []
        self.accepted: list[str | None] = []
        self.closed: list[tuple[int, str]] = []
        self._messages = iter(messages or [])

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
