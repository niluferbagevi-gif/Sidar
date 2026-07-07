from __future__ import annotations

import asyncio
import inspect
import json
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


class _DummyEventBus:
    def __init__(self) -> None:
        self.unsubscribed: list[str] = []

    def subscribe(self):
        return "sub-chat", asyncio.Queue()

    def unsubscribe(self, sub_id: str) -> None:
        self.unsubscribed.append(sub_id)


class _Logger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def warning(self, message: str, *args: object) -> None:
        self.messages.append(("warning", message % args if args else message))

    def info(self, message: str, *args: object) -> None:
        self.messages.append(("info", message % args if args else message))

    def debug(self, message: str, *args: object) -> None:
        self.messages.append(("debug", message % args if args else message))

    def exception(self, message: str, *args: object) -> None:
        self.messages.append(("exception", message % args if args else message))


class _LLMProviderError(Exception):
    def __init__(self, message: str = "provider down") -> None:
        super().__init__(message)
        self.provider = "openai"
        self.status_code = 503
        self.retryable = True


class _Memory:
    def __init__(self) -> None:
        self.active_users: list[tuple[str, str]] = []
        self.titles: list[str] = []

    def __len__(self) -> int:
        return 1

    async def set_active_user(self, user_id: str, username: str) -> None:
        self.active_users.append((user_id, username))

    async def aupdate_title(self, title: str) -> None:
        self.titles.append(title)


class _RouteAgent:
    def __init__(self, *, chunks: list[str] | None = None, error: Exception | None = None) -> None:
        self.memory = _Memory()
        self._chunks = chunks or ["hello"]
        self._error = error

    async def respond(self, _message: str):
        if self._error is not None:
            raise self._error
        for chunk in self._chunks:
            yield chunk

    async def _try_multi_agent(self, prompt: str) -> str:
        if "explode" in prompt:
            raise RuntimeError("room provider exploded")
        if "slow" in prompt:
            await asyncio.sleep(999)
        return "room ok"


class _Room:
    def __init__(self, room_id: str) -> None:
        self.room_id = room_id
        self.participants: dict[object, object] = {}
        self.active_task = None
        self.telemetry: list[dict[str, object]] = []
        self.messages: list[dict[str, object]] = []


class _Deps:
    def __init__(self, agent: _RouteAgent | None = None) -> None:
        self.agent = agent or _RouteAgent()
        self.logger = _Logger()
        self.cfg = SimpleNamespace(WS_AUTH_TIMEOUT_SECONDS=1)
        self.llm_api_error_cls = _LLMProviderError
        self.anyio_closed = None
        self.rate_limit = 100
        self.rate_window = 60
        self.event_bus = _DummyEventBus()
        self.collaboration_rooms: dict[str, _Room] = {}
        self.broadcasts: list[dict[str, object]] = []
        self.left = False

    def extract_ws_header_token(self, _header: str):
        return "", None

    async def resolve_agent_instance(self):
        return self.agent

    async def await_if_needed(self, value):
        if inspect.isawaitable(value):
            return await value
        return value

    async def resolve_user_from_token(self, _agent, token: str):
        if token == "valid-token":
            return SimpleNamespace(id="u1", username="ada", role="admin")
        return None

    def normalize_collaboration_role(self, role: str) -> str:
        return role

    async def ws_close_policy_violation(self, websocket, reason: str) -> None:
        await websocket.close(code=1008, reason=reason)

    def set_current_metrics_user_id(self, user_id: str):
        return f"token:{user_id}"

    def reset_current_metrics_user_id(self, _token: str) -> None:
        return None

    def get_agent_event_bus(self):
        return self.event_bus

    async def redis_is_rate_limited(self, *_args) -> bool:
        return False

    async def leave_collaboration_room(self, _websocket) -> None:
        self.left = True

    async def join_collaboration_room(self, websocket, *, room_id, user_id, username, display_name, user_role):
        room = self.collaboration_rooms.setdefault(room_id, _Room(room_id))
        participant = SimpleNamespace(can_write=True, websocket=websocket, user_id=user_id)
        room.participants[self.socket_key(websocket)] = participant
        return room

    def build_room_message(self, **kwargs):
        return dict(kwargs)

    def append_room_message(self, room, message) -> None:
        room.messages.append(message)

    async def broadcast_room_payload(self, _room, payload) -> None:
        self.broadcasts.append(payload)

    def is_sidar_mention(self, message: str) -> bool:
        return message.lower().startswith("@sidar")

    def strip_sidar_mention(self, message: str) -> str:
        return message.split(maxsplit=1)[1] if " " in message else ""

    def socket_key(self, websocket) -> int:
        return id(websocket)

    def collaboration_command_requires_write(self, _command: str) -> bool:
        return False

    def append_room_telemetry(self, room, payload) -> None:
        room.telemetry.append(payload)

    def collaboration_now_iso(self) -> str:
        return "2026-07-07T00:00:00+00:00"

    def mask_collaboration_text(self, text: str) -> str:
        return text

    def build_collaboration_prompt(self, room, *, actor_name: str, command: str) -> str:
        return f"room={room.room_id}; actor={actor_name}; command={command}"

    def iter_stream_chunks(self, result: str):
        return [result]


@pytest.mark.asyncio
async def test_websocket_chat_rejects_invalid_auth_token() -> None:
    ws = _Ws([json.dumps({"action": "auth", "token": "bad-token"})])
    deps = _Deps()

    await ws_chat.websocket_chat(ws, deps)

    assert ws.accepted == [None]
    assert ws.closed == [(1008, "Invalid or expired token")]


@pytest.mark.asyncio
async def test_websocket_chat_ignores_invalid_json_after_auth_then_cleans_up() -> None:
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            "{not-json",
        ]
    )
    deps = _Deps()

    await ws_chat.websocket_chat(ws, deps)

    assert {"auth_ok": True} in ws.sent
    assert deps.left is True
    assert deps.event_bus.unsubscribed == []


@pytest.mark.asyncio
async def test_websocket_chat_reports_llm_provider_error() -> None:
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "message", "message": "hello"}),
        ]
    )
    deps = _Deps(agent=_RouteAgent(error=_LLMProviderError("quota exhausted")))

    await ws_chat.websocket_chat(ws, deps)

    assert any("[LLM Hatası] openai (503): quota exhausted" in str(item) for item in ws.sent)


@pytest.mark.asyncio
async def test_websocket_chat_stops_stream_when_client_disconnects_during_send() -> None:
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "message", "message": "stream"}),
        ]
    )
    deps = _Deps(agent=_RouteAgent(chunks=["first", "second"]))

    async def _send_and_disconnect(payload: dict[str, object]) -> None:
        ws.sent.append(payload)
        if payload.get("chunk") == "first":
            ws.client_state = WebSocketState.DISCONNECTED

    ws.send_json = _send_and_disconnect  # type: ignore[method-assign]

    await ws_chat.websocket_chat(ws, deps)

    assert {"chunk": "first"} in ws.sent
    assert {"chunk": "second"} not in ws.sent


@pytest.mark.asyncio
async def test_websocket_chat_room_stream_error_broadcasts_room_error() -> None:
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "join_room", "room_id": "team:ops", "display_name": "Ada"}),
            json.dumps({"action": "message", "message": "@sidar explode now"}),
        ]
    )
    deps = _Deps()

    await ws_chat.websocket_chat(ws, deps)

    assert any(item.get("type") == "room_error" for item in deps.broadcasts)
    assert any("room provider exploded" in str(item.get("error")) for item in deps.broadcasts)


class _CancelThenDisconnectWs(_Ws):
    async def receive_text(self) -> str:
        try:
            value = next(self._messages)
        except StopIteration as exc:
            raise ws_chat.WebSocketDisconnect() from exc
        if value == "__WAIT_THEN_DISCONNECT__":
            await asyncio.sleep(0.01)
            raise ws_chat.WebSocketDisconnect()
        return value


@pytest.mark.asyncio
async def test_websocket_chat_room_cancel_broadcasts_cancelled_done() -> None:
    ws = _CancelThenDisconnectWs(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "join_room", "room_id": "team:ops", "display_name": "Ada"}),
            json.dumps({"action": "message", "message": "@sidar slow work"}),
            json.dumps({"action": "cancel"}),
            "__WAIT_THEN_DISCONNECT__",
        ]
    )
    deps = _Deps()

    await ws_chat.websocket_chat(ws, deps)

    assert any(item.get("type") == "assistant_done" and item.get("cancelled") is True for item in deps.broadcasts)
