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
async def test_send_json_if_connected_returns_false_without_sending_when_disconnected() -> None:
    ws = _Ws()
    ws.client_state = WebSocketState.DISCONNECTED

    sent = await ws_chat.send_json_if_connected(ws, {"chunk": "late"})

    assert sent is False
    assert ws.sent == []


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_flushes_legacy_voice_pipeline() -> None:
    class _LegacyVoicePipeline:
        enabled = True

        def __init__(self) -> None:
            self.extract_calls: list[tuple[str, bool]] = []
            self.synthesized: list[str] = []

        def extract_ready_segments(self, text: str, *, flush: bool = False):
            self.extract_calls.append((text, flush))
            return ([text] if flush and text else [], "" if flush else text)

        async def synthesize_text(self, segment: str):
            self.synthesized.append(segment)
            return {
                "success": True,
                "audio_bytes": b"wav-bytes",
                "mime_type": "audio/wav",
                "provider": "mock",
                "voice": "test",
            }

    class _StreamingAgent:
        async def respond(self, _prompt: str):
            yield "Merhaba"

    ws = _Ws()
    voice_pipeline = _LegacyVoicePipeline()
    ws._sidar_voice_pipeline = voice_pipeline

    await ws_chat.ws_stream_agent_text_response(ws, _StreamingAgent(), "prompt")

    assert ws.sent == [
        {"chunk": "Merhaba"},
        {
            "audio_chunk": "d2F2LWJ5dGVz",
            "audio_text": "Merhaba",
            "audio_mime_type": "audio/wav",
            "audio_provider": "mock",
            "audio_voice": "test",
            "assistant_turn_id": 0,
            "audio_sequence": 1,
        },
    ]
    assert voice_pipeline.extract_calls == [("Merhaba", False), ("Merhaba", True)]
    assert voice_pipeline.synthesized == ["Merhaba"]


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_flushes_buffered_voice_pipeline_after_sentinels() -> (
    None
):
    class _BufferedVoicePipeline:
        enabled = True

        def __init__(self) -> None:
            self.buffer_calls: list[tuple[object, str, bool]] = []
            self.buffered_text = ""
            self.synthesized: list[str] = []

        def buffer_assistant_text(self, duplex_state: object, text: str, *, flush: bool = False):
            self.buffer_calls.append((duplex_state, text, flush))
            if text:
                self.buffered_text += text
            if not flush or not self.buffered_text:
                return 7, []
            packet_text = self.buffered_text
            self.buffered_text = ""
            return 7, [{"assistant_turn_id": 7, "audio_sequence": 3, "text": packet_text}]

        async def synthesize_text(self, segment: str):
            self.synthesized.append(segment)
            return {"success": True, "audio_bytes": b"ok"}

    class _SentinelAgent:
        async def respond(self, _prompt: str):
            yield "\x00TOOL:search\x00"
            yield "\x00THOUGHT:thinking\x00"
            yield "Cevap"

    ws = _Ws()
    voice_pipeline = _BufferedVoicePipeline()
    duplex_state = object()
    ws._sidar_voice_pipeline = voice_pipeline
    ws._sidar_voice_duplex_state = duplex_state

    await ws_chat.ws_stream_agent_text_response(ws, _SentinelAgent(), "prompt")

    assert ws.sent == [
        {"tool_call": "search"},
        {"thought": "thinking"},
        {"chunk": "Cevap"},
        {
            "audio_chunk": "b2s=",
            "audio_text": "Cevap",
            "audio_mime_type": "audio/wav",
            "audio_provider": "",
            "audio_voice": "",
            "assistant_turn_id": 7,
            "audio_sequence": 3,
        },
    ]
    assert voice_pipeline.buffer_calls == [
        (duplex_state, "Cevap", False),
        (duplex_state, "", True),
    ]
    assert voice_pipeline.synthesized == ["Cevap"]


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_skips_voice_flush_when_disconnects_after_text() -> (
    None
):
    class _VoicePipeline:
        enabled = True

        def __init__(self) -> None:
            self.synthesized: list[str] = []

        def extract_ready_segments(self, text: str, *, flush: bool = False):
            return ([text] if flush and text else [], text)

        async def synthesize_text(self, segment: str):
            self.synthesized.append(segment)
            return {"success": True, "audio_bytes": b"late"}

    class _StreamingAgent:
        async def respond(self, _prompt: str):
            yield "first"
            yield "second"

    ws = _Ws()
    voice_pipeline = _VoicePipeline()
    ws._sidar_voice_pipeline = voice_pipeline

    async def _send_and_disconnect(payload: dict[str, object]) -> None:
        ws.sent.append(payload)
        ws.client_state = WebSocketState.DISCONNECTED

    ws.send_json = _send_and_disconnect  # type: ignore[method-assign]

    await ws_chat.ws_stream_agent_text_response(ws, _StreamingAgent(), "prompt")

    assert ws.sent == [{"chunk": "first"}]
    assert voice_pipeline.synthesized == ["first"]


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
    """A websocket that keeps sending unparseable junk to defeat a naive timeout.

    Sends fast enough to reset a naive per-message timeout, without ever
    authenticating.
    """

    async def receive_text(self) -> str:
        await asyncio.sleep(0.001)
        return "not json"


@pytest.mark.asyncio
async def test_websocket_chat_closes_idle_unauthenticated_connection_after_timeout() -> None:
    """Regression test: an idle unauthenticated client must not stay connected forever.

    An unauthenticated client that never sends an auth message must not keep
    the connection open forever (slow DoS / resource exhaustion).
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
    """Regression test: junk messages must not reset the auth timeout.

    Repeatedly sending unparseable junk must not let an unauthenticated
    client reset the auth timeout and stay connected forever.
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
        self.queue: asyncio.Queue[object] = asyncio.Queue()

    def subscribe(self):
        return "sub-chat", self.queue

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


class _SlowRouteAgent(_RouteAgent):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    async def respond(self, _message: str):
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield "late"  # pragma: no cover - cancelled before yielding


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

    async def join_collaboration_room(
        self, websocket, *, room_id, user_id, username, display_name, user_role
    ):
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
async def test_websocket_chat_rejects_invalid_header_token_before_first_message() -> None:
    class _HeaderDeps(_Deps):
        def extract_ws_header_token(self, _header: str):
            return "bad-token", "sidar.ws.chat"

    ws = _Ws(headers={"sec-websocket-protocol": "sidar.ws.chat, bad-token"})
    deps = _HeaderDeps()

    await ws_chat.websocket_chat(ws, deps)

    assert ws.accepted == ["sidar.ws.chat"]
    assert ws.closed == [(1008, "Invalid or expired token")]
    assert deps.agent.memory.active_users == []


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
async def test_websocket_chat_ignores_malformed_json_and_processes_next_message() -> None:
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            "{not-json",
            json.dumps({"action": "message", "message": "hello"}),
        ]
    )
    deps = _Deps(agent=_RouteAgent(chunks=["after-json-error"]))

    await ws_chat.websocket_chat(ws, deps)

    assert {"auth_ok": True} in ws.sent
    assert {"chunk": "after-json-error"} in ws.sent
    assert {"done": True} in ws.sent


@pytest.mark.asyncio
async def test_websocket_chat_ignores_empty_message_after_auth() -> None:
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "message", "message": "   "}),
        ]
    )
    deps = _Deps()

    await ws_chat.websocket_chat(ws, deps)

    assert {"auth_ok": True} in ws.sent
    assert not any("chunk" in item for item in ws.sent)


@pytest.mark.asyncio
async def test_websocket_chat_returns_rate_limit_response() -> None:
    class _RateLimitedDeps(_Deps):
        async def redis_is_rate_limited(self, *_args) -> bool:
            return True

    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "message", "message": "hello"}),
        ]
    )
    deps = _RateLimitedDeps()

    await ws_chat.websocket_chat(ws, deps)

    assert {
        "chunk": "[Hız Sınırı] Çok fazla istek. Lütfen bir dakika bekleyin.",
        "done": True,
    } in ws.sent


@pytest.mark.asyncio
async def test_websocket_chat_cancel_active_task_sends_cancel_confirmation() -> None:
    ws = _CancelThenDisconnectWs(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "message", "message": "slow"}),
            json.dumps({"action": "cancel"}),
            "__WAIT_THEN_DISCONNECT__",
        ]
    )
    agent = _SlowRouteAgent()
    deps = _Deps(agent=agent)

    await ws_chat.websocket_chat(ws, deps)

    assert agent.cancelled is True
    assert {
        "chunk": "\n\n*[Sistem: İşlem kullanıcı tarafından iptal edildi]*\n",
        "done": True,
    } in ws.sent


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
async def test_websocket_chat_streams_status_queue_events() -> None:
    class _StatusAgent(_RouteAgent):
        async def respond(self, _message: str):
            await asyncio.sleep(0.01)
            yield "after-status"

    ws = _CancelThenDisconnectWs(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "message", "message": "stream status"}),
            "__WAIT_THEN_DISCONNECT__",
        ]
    )
    deps = _Deps(agent=_StatusAgent())
    deps.event_bus.queue.put_nowait(SimpleNamespace(source="planner", message="working"))

    await ws_chat.websocket_chat(ws, deps)

    assert {"status": "planner: working"} in ws.sent
    assert {"chunk": "after-status"} in ws.sent


@pytest.mark.asyncio
async def test_websocket_chat_falls_back_to_sync_update_title_when_async_missing() -> None:
    class _SyncTitleMemory:
        def __init__(self) -> None:
            self.titles: list[str] = []
            self.active_users: list[tuple[str, str]] = []

        def __len__(self) -> int:
            return 0

        async def set_active_user(self, user_id: str, username: str) -> None:
            self.active_users.append((user_id, username))

        def update_title(self, title: str) -> None:
            self.titles.append(title)

    memory = _SyncTitleMemory()
    agent = _RouteAgent(chunks=["titled"])
    agent.memory = memory
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "message", "message": "a" * 35}),
        ]
    )
    deps = _Deps(agent=agent)

    await ws_chat.websocket_chat(ws, deps)

    assert memory.titles == ["a" * 30 + "..."]
    assert {"chunk": "titled"} in ws.sent


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


@pytest.mark.asyncio
async def test_websocket_chat_room_empty_sidar_command_broadcasts_error() -> None:
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "join_room", "room_id": "team:ops", "display_name": "Ada"}),
            json.dumps({"action": "message", "message": "@Sidar"}),
        ]
    )
    deps = _Deps()

    await ws_chat.websocket_chat(ws, deps)

    assert any(
        item.get("type") == "room_error" and "komut bulunamadı" in str(item.get("error"))
        for item in deps.broadcasts
    )
    assert not any(item.get("type") == "assistant_stream_start" for item in deps.broadcasts)


@pytest.mark.asyncio
async def test_websocket_chat_room_sidar_command_streams_successful_response() -> None:
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "join_room", "room_id": "team:ops", "display_name": "Ada"}),
            json.dumps({"action": "message", "message": "@Sidar summarize notes"}),
        ]
    )
    deps = _Deps()

    await ws_chat.websocket_chat(ws, deps)

    assert any(item.get("type") == "assistant_stream_start" for item in deps.broadcasts)
    assert any(
        item.get("type") == "assistant_chunk" and item.get("chunk") == "room ok"
        for item in deps.broadcasts
    )
    assert any(item.get("type") == "assistant_done" for item in deps.broadcasts)
    room = deps.collaboration_rooms["team:ops"]
    assert any(message.get("kind") == "assistant_reply" for message in room.messages)


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

    assert any(
        item.get("type") == "assistant_done" and item.get("cancelled") is True
        for item in deps.broadcasts
    )


@pytest.mark.asyncio
async def test_websocket_chat_room_rbac_denied_records_telemetry_and_error() -> None:
    class _ReadOnlyDeps(_Deps):
        async def join_collaboration_room(
            self, websocket, *, room_id, user_id, username, display_name, user_role
        ):
            room = self.collaboration_rooms.setdefault(room_id, _Room(room_id))
            participant = SimpleNamespace(can_write=False, websocket=websocket, user_id=user_id)
            room.participants[self.socket_key(websocket)] = participant
            return room

        def collaboration_command_requires_write(self, _command: str) -> bool:
            return True

    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "join_room", "room_id": "team:ops", "display_name": "Ada"}),
            json.dumps({"action": "message", "message": "@sidar deploy production"}),
        ]
    )
    deps = _ReadOnlyDeps()

    await ws_chat.websocket_chat(ws, deps)

    room = deps.collaboration_rooms["team:ops"]
    assert any(item.get("kind") == "rbac_denied" for item in room.telemetry)
    assert any(
        item.get("type") == "room_error" and "yazma yetkisine sahip değil" in str(item.get("error"))
        for item in deps.broadcasts
    )


@pytest.mark.asyncio
async def test_websocket_chat_disconnect_cleans_lifecycle_and_room() -> None:
    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "join_room", "room_id": "team:ops", "display_name": "Ada"}),
        ]
    )
    deps = _Deps()

    await ws_chat.websocket_chat(ws, deps)

    assert deps.left is True
    assert any(
        level == "info" and "bağlantısını kesti" in msg for level, msg in deps.logger.messages
    )


@pytest.mark.asyncio
async def test_websocket_chat_anyio_closed_resource_cleans_up_like_disconnect() -> None:
    class _ClosedResourceError(Exception):
        pass

    class _ClosedWs(_Ws):
        async def receive_text(self) -> str:
            raise _ClosedResourceError("closed")

    ws = _ClosedWs([json.dumps({"action": "auth", "token": "valid-token"})])
    deps = _Deps()
    deps.anyio_closed = _ClosedResourceError

    await ws_chat.websocket_chat(ws, deps)

    assert deps.left is True
    assert any("ClosedResourceError" in msg for _level, msg in deps.logger.messages)


@pytest.mark.asyncio
async def test_websocket_chat_unexpected_exception_sends_error_and_leaves_room() -> None:
    class _BoomWs(_Ws):
        async def receive_text(self) -> str:
            raise RuntimeError("socket boom")

    ws = _BoomWs()
    deps = _Deps()

    await ws_chat.websocket_chat(ws, deps)

    assert {"error": "WebSocket oturumu beklenmedik şekilde sonlandı.", "done": True} in ws.sent
    assert deps.left is True
    assert any(level == "warning" and "socket boom" in msg for level, msg in deps.logger.messages)


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_stops_when_tool_send_fails(monkeypatch) -> None:
    class _ToolThenChunkAgent:
        async def respond(self, _prompt: str):
            yield "\x00TOOL:search\x00"
            yield "late"

    async def _send_json_if_connected(_websocket, payload):
        ws.sent.append(payload)
        return False

    ws = _Ws()
    monkeypatch.setattr(ws_chat, "send_json_if_connected", _send_json_if_connected)

    await ws_chat.ws_stream_agent_text_response(ws, _ToolThenChunkAgent(), "prompt")

    assert ws.sent == [{"tool_call": "search"}]


@pytest.mark.asyncio
async def test_ws_stream_agent_text_response_stops_when_thought_send_fails(monkeypatch) -> None:
    class _ThoughtThenChunkAgent:
        async def respond(self, _prompt: str):
            yield "\x00THOUGHT:thinking\x00"
            yield "late"

    async def _send_json_if_connected(_websocket, payload):
        ws.sent.append(payload)
        return False

    ws = _Ws()
    monkeypatch.setattr(ws_chat, "send_json_if_connected", _send_json_if_connected)

    await ws_chat.ws_stream_agent_text_response(ws, _ThoughtThenChunkAgent(), "prompt")

    assert ws.sent == [{"thought": "thinking"}]


@pytest.mark.asyncio
async def test_websocket_chat_generate_response_stops_when_tool_send_fails(monkeypatch) -> None:
    class _ToolAgent(_RouteAgent):
        async def respond(self, _message: str):
            yield "\x00TOOL:search\x00"
            yield "late"

    async def _send_json_if_connected(_websocket, payload):
        ws.sent.append(payload)
        return False

    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "message", "message": "hello"}),
        ]
    )
    deps = _Deps(agent=_ToolAgent())
    monkeypatch.setattr(ws_chat, "send_json_if_connected", _send_json_if_connected)

    await ws_chat.websocket_chat(ws, deps)

    assert {"tool_call": "search"} in ws.sent
    assert {"chunk": "late"} not in ws.sent
    assert deps.event_bus.unsubscribed == ["sub-chat"]


@pytest.mark.asyncio
async def test_websocket_chat_generate_response_stops_when_thought_send_fails(monkeypatch) -> None:
    class _ThoughtAgent(_RouteAgent):
        async def respond(self, _message: str):
            yield "\x00THOUGHT:thinking\x00"
            yield "late"

    async def _send_json_if_connected(_websocket, payload):
        ws.sent.append(payload)
        return False

    ws = _Ws(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "message", "message": "hello"}),
        ]
    )
    deps = _Deps(agent=_ThoughtAgent())
    monkeypatch.setattr(ws_chat, "send_json_if_connected", _send_json_if_connected)

    await ws_chat.websocket_chat(ws, deps)

    assert {"thought": "thinking"} in ws.sent
    assert {"chunk": "late"} not in ws.sent
    assert deps.event_bus.unsubscribed == ["sub-chat"]


@pytest.mark.asyncio
async def test_websocket_chat_room_cancel_clears_existing_active_task() -> None:
    room = _Room("room-1")
    started = asyncio.Event()

    async def _slow() -> None:
        started.set()
        await asyncio.sleep(999)

    room.active_task = asyncio.create_task(_slow())

    class _CancelRoomWs(_Ws):
        async def receive_text(self) -> str:
            try:
                data = next(self._messages)
            except StopIteration as exc:
                raise ws_chat.WebSocketDisconnect() from exc
            if data == "__WAIT_CANCEL__":
                await asyncio.wait_for(started.wait(), timeout=1)
                return json.dumps({"action": "cancel"})
            return data

    ws = _CancelRoomWs(
        [
            json.dumps({"action": "auth", "token": "valid-token"}),
            json.dumps({"action": "join_room", "room_id": "room-1"}),
            "__WAIT_CANCEL__",
        ]
    )
    deps = _Deps()
    deps.collaboration_rooms["room-1"] = room

    await ws_chat.websocket_chat(ws, deps)

    assert room.active_task is None
