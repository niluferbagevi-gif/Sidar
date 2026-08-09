"""Integration coverage for WebSocket multi-turn persistence and session restore."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketState

from web.routes.ws_chat import websocket_chat


@dataclass
class _SessionRow:
    id: str
    user_id: str
    title: str
    updated_at: str = "2026-06-26T00:00:00+00:00"


@dataclass
class _MessageRow:
    role: str
    content: str
    tokens_used: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _PersistentChatDb:
    def __init__(self) -> None:
        self.sessions: dict[str, _SessionRow] = {}
        self.messages: dict[str, list[_MessageRow]] = {}

    async def create_session(self, user_id: str, title: str) -> _SessionRow:
        session = _SessionRow(id="session-1", user_id=user_id, title=title)
        self.sessions[session.id] = session
        self.messages.setdefault(session.id, [])
        return session

    async def load_session(self, session_id: str, user_id: str) -> _SessionRow | None:
        session = self.sessions.get(session_id)
        if session and session.user_id == user_id:
            return session
        return None

    async def get_session_messages(self, session_id: str) -> list[_MessageRow]:
        return list(self.messages.get(session_id, []))

    async def add_message(
        self, session_id: str, role: str, content: str, tokens_used: int = 0
    ) -> _MessageRow:
        message = _MessageRow(role=role, content=content, tokens_used=tokens_used)
        self.messages.setdefault(session_id, []).append(message)
        return message


class _PersistentMemory:
    def __init__(self, db: _PersistentChatDb, session_id: str) -> None:
        self.db = db
        self.active_session_id = session_id
        self.active_user: tuple[str, str] | None = None
        self.title = ""

    def __len__(self) -> int:
        return len(self.db.messages.get(self.active_session_id, []))

    async def set_active_user(self, user_id: str, username: str) -> None:
        self.active_user = (user_id, username)

    async def aupdate_title(self, title: str) -> None:
        self.title = title

    async def update_title(self, title: str) -> None:
        self.title = title

    def _safe_ts(self, value: datetime) -> str:
        return value.isoformat()


class _EventBus:
    def subscribe(self) -> tuple[str, asyncio.Queue]:
        return "sub-1", asyncio.Queue()

    def unsubscribe(self, _sub_id: str) -> None:
        return None


class _FakeWebSocket:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.client_state = WebSocketState.CONNECTED
        self.sent: list[dict[str, object]] = []
        self._receive_step = 0
        self._done_count = 0
        self._done_event = asyncio.Event()

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted_subprotocol = subprotocol

    async def receive_text(self) -> str:
        if self._receive_step == 0:
            self._receive_step += 1
            return '{"action":"auth","token":"persist-token"}'
        if self._receive_step == 1:
            self._receive_step += 1
            return '{"message":"İlk tur"}'
        if self._receive_step == 2:
            await self._wait_for_done_count(1)
            self._receive_step += 1
            return '{"message":"İkinci tur"}'
        await self._wait_for_done_count(2)
        self.client_state = WebSocketState.DISCONNECTED
        raise WebSocketDisconnect(code=1000)

    async def _wait_for_done_count(self, expected: int) -> None:
        while self._done_count < expected:
            await self._done_event.wait()
            self._done_event.clear()

    async def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)
        if payload.get("done"):
            self._done_count += 1
            self._done_event.set()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_websocket_multi_turn_conversation_persists_and_restores_session() -> None:
    db = _PersistentChatDb()
    session = await db.create_session("user-1", "Persisted chat")
    memory = _PersistentMemory(db, session.id)
    fake_agent = SimpleNamespace(memory=memory, system_prompt="")

    async def _respond(prompt: str, **_kwargs):
        await db.add_message(session.id, "user", prompt)
        reply = f"Yanıt: {prompt}"
        await db.add_message(session.id, "assistant", reply)
        yield reply

    fake_agent.respond = _respond

    async def _resolve_user_from_token(_agent, token: str):
        if token == "persist-token":
            return SimpleNamespace(id="user-1", username="persist_user", role="user")
        return None

    async def _await_if_needed(value):
        if asyncio.iscoroutine(value):
            return await value
        return value

    async def _never_rate_limited(*_args, **_kwargs):
        return False

    async def _leave_collaboration_room(_websocket):
        return None

    deps = SimpleNamespace(
        extract_ws_header_token=lambda _header: ("", None),
        resolve_agent_instance=lambda: asyncio.sleep(0, result=fake_agent),
        await_if_needed=_await_if_needed,
        resolve_user_from_token=_resolve_user_from_token,
        ws_close_policy_violation=lambda *_args, **_kwargs: None,
        normalize_collaboration_role=lambda role: str(role or "user"),
        set_current_metrics_user_id=lambda _user_id: object(),
        reset_current_metrics_user_id=lambda _token: None,
        get_agent_event_bus=lambda: _EventBus(),
        llm_api_error_cls=RuntimeError,
        logger=SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            exception=lambda *_args, **_kwargs: None,
            debug=lambda *_args, **_kwargs: None,
        ),
        redis_is_rate_limited=_never_rate_limited,
        rate_limit=100,
        rate_window=60,
        collaboration_rooms={},
        leave_collaboration_room=_leave_collaboration_room,
        anyio_closed=None,
    )
    websocket = _FakeWebSocket()

    await websocket_chat(websocket, deps)

    restored_session = await db.load_session(session.id, "user-1")
    restored_messages = await db.get_session_messages(session.id)
    history = [
        {
            "role": message.role,
            "content": message.content,
            "timestamp": memory._safe_ts(message.created_at),
            "tokens_used": message.tokens_used,
        }
        for message in restored_messages
    ]

    assert restored_session == session
    assert [(item["role"], item["content"]) for item in history] == [
        ("user", "İlk tur"),
        ("assistant", "Yanıt: İlk tur"),
        ("user", "İkinci tur"),
        ("assistant", "Yanıt: İkinci tur"),
    ]
    assert [item for item in websocket.sent if item.get("done")] == [{"done": True}, {"done": True}]
    assert memory.active_user == ("user-1", "persist_user")
