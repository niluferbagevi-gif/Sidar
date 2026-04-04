from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


if "jwt" not in sys.modules:
    class _JwtStub:
        class PyJWTError(Exception):
            pass

        @staticmethod
        def decode(*_args, **_kwargs):
            raise _JwtStub.PyJWTError("stub")

    sys.modules["jwt"] = _JwtStub()

web_server = importlib.import_module("web_server")


class _FakeWebSocket:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.sent: list[dict] = []
        self._sidar_room_id = ""

    async def send_json(self, payload: dict) -> None:
        if self.should_fail:
            raise RuntimeError("socket closed")
        self.sent.append(payload)


@pytest.fixture(autouse=True)
def _reset_collaboration_state() -> None:
    web_server._collaboration_rooms.clear()
    yield
    web_server._collaboration_rooms.clear()


def test_collaboration_participant_backward_compat_timestamp_role() -> None:
    ws = _FakeWebSocket()
    participant = web_server._CollaborationParticipant(
        websocket=ws,
        user_id="u1",
        username="user",
        display_name="User",
        role="2026-01-01T00:00:00+00:00",
    )

    assert participant.role == "user"
    assert participant.joined_at == "2026-01-01T00:00:00+00:00"


def test_serialize_and_append_room_buffers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server, "_mask_collaboration_text", lambda text: f"masked::{text}")
    room = web_server._CollaborationRoom(room_id="workspace:alpha")

    web_server._append_room_message(room, {"id": 1}, limit=1)
    web_server._append_room_message(room, {"id": 2}, limit=1)

    web_server._append_room_telemetry(room, {"content": "secret", "error": "boom"}, limit=1)
    web_server._append_room_telemetry(room, {"content": "next"}, limit=1)

    assert room.messages == [{"id": 2}]
    assert room.telemetry == [{"content": "masked::next"}]


def test_build_collaboration_prompt_contains_actor_scope() -> None:
    ws = _FakeWebSocket()
    participant = web_server._CollaborationParticipant(
        websocket=ws,
        user_id="u1",
        username="alice",
        display_name="Alice",
        role="developer",
        can_write=True,
        write_scopes=["/tmp/workspace"],
        joined_at="now",
    )
    room = web_server._CollaborationRoom(
        room_id="workspace:alpha",
        participants={web_server._socket_key(ws): participant},
        messages=[{"role": "user", "author_name": "Alice", "content": "Refactor this please"}],
    )

    prompt = web_server._build_collaboration_prompt(room, actor_name="Alice", command="write tests")

    assert "requesting_role=developer" in prompt
    assert "requesting_write_scopes=/tmp/workspace" in prompt
    assert "Refactor this please" in prompt


def test_iter_stream_chunks_and_write_intent_regex() -> None:
    assert web_server._iter_stream_chunks("", size=5) == []
    assert web_server._iter_stream_chunks("abcdefgh", size=3) == ["abc", "def", "gh"]
    assert web_server._collaboration_command_requires_write("please edit file") is True
    assert web_server._collaboration_command_requires_write("sadece oku") is False


@pytest.mark.asyncio
async def test_broadcast_room_payload_removes_stale_participant() -> None:
    alive = _FakeWebSocket()
    dead = _FakeWebSocket(should_fail=True)

    room = web_server._CollaborationRoom(
        room_id="workspace:alpha",
        participants={
            web_server._socket_key(alive): web_server._CollaborationParticipant(alive, "1", "a", "A"),
            web_server._socket_key(dead): web_server._CollaborationParticipant(dead, "2", "b", "B"),
        },
    )

    await web_server._broadcast_room_payload(room, {"type": "ping"})

    assert alive.sent == [{"type": "ping"}]
    assert web_server._socket_key(dead) not in room.participants


@pytest.mark.asyncio
async def test_join_and_leave_collaboration_room(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(web_server, "cfg", SimpleNamespace(BASE_DIR=tmp_path))
    ws = _FakeWebSocket()

    room = await web_server._join_collaboration_room(
        ws,
        room_id="workspace:alpha",
        user_id="u1",
        username="alice",
        display_name="Alice",
        user_role="developer",
    )

    assert room.room_id == "workspace:alpha"
    assert ws._sidar_room_id == "workspace:alpha"
    assert ws.sent[0]["type"] == "room_state"

    await web_server._leave_collaboration_room(ws)

    assert ws._sidar_room_id == ""
    assert "workspace:alpha" not in web_server._collaboration_rooms
