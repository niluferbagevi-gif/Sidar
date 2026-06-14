from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from web.routes import collaboration


class _Logger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, message: str, *args: object) -> None:
        self.messages.append(message % args if args else message)


class _WebSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict[str, object]] = []
        self.fail = fail
        self._sidar_room_id = ""

    async def send_json(self, payload: dict[str, object]) -> None:
        if self.fail:
            raise RuntimeError("closed")
        self.sent.append(payload)


def test_collaboration_model_normalization_serialization_and_prompt(tmp_path: Path) -> None:
    with pytest.raises(HTTPException):
        collaboration.normalize_room_id("<bad>")

    assert collaboration.normalize_room_id("") == "workspace:default"
    assert collaboration.normalize_collaboration_role("ADMIN") == "admin"
    assert collaboration.normalize_collaboration_role("guest") == "user"
    assert collaboration.collaboration_write_scopes_for_role("user", "team:one", base_dir=tmp_path) == []
    assert collaboration.collaboration_write_scopes_for_role("admin", "team:one", base_dir=tmp_path) == [
        str(tmp_path.resolve())
    ]
    assert collaboration.collaboration_command_requires_write("please edit file")
    assert not collaboration.collaboration_command_requires_write("sadece oku")

    ws = _WebSocket()
    participant = collaboration.CollaborationParticipant(
        ws, "u-1", "ada", "Ada", "2026-01-01T00:00:00+00:00"
    )
    assert participant.role == "user"
    assert participant.joined_at == "2026-01-01T00:00:00+00:00"
    assert collaboration.serialize_collaboration_participant(participant)["display_name"] == "Ada"

    room = collaboration.CollaborationRoom("team:one", participants={1: participant})
    collaboration.append_room_message(
        room,
        {
            "role": "user",
            "author_name": "Ada",
            "content": "hello",
        },
    )
    prompt = collaboration.build_collaboration_prompt(room, actor_name="Ada", command="@sidar özetle")
    assert "room_id=team:one" in prompt
    assert "Ada<user>" in prompt
    assert "hello" in prompt


def test_mask_append_and_message_builder_use_injected_dependencies() -> None:
    logger = _Logger()

    def _import_module(_name: str):
        return SimpleNamespace(mask_pii=lambda text: text.replace("secret", "***"))

    assert (
        collaboration.mask_collaboration_text(
            "secret", import_module=_import_module, logger_obj=logger
        )
        == "***"
    )

    room = collaboration.CollaborationRoom("ops:control")
    collaboration.append_room_telemetry(
        room,
        {"content": "secret", "error": "secret"},
        mask_text=lambda text: text.replace("secret", "***"),
    )
    assert room.telemetry == [{"content": "***", "error": "***"}]

    message = collaboration.build_room_message(
        room_id="ops:control",
        role="assistant",
        content="secret",
        author_name="Sidar",
        author_id="sidar",
        mask_text=lambda text: text.replace("secret", "***"),
        now_iso=lambda: "now",
    )
    assert message["content"] == "***"
    assert message["ts"] == "now"


@pytest.mark.asyncio
async def test_join_leave_broadcast_and_emit_control_room_event(tmp_path: Path) -> None:
    rooms: dict[str, collaboration.CollaborationRoom] = {}
    ws = _WebSocket()

    room = await collaboration.join_collaboration_room(
        rooms,
        ws,  # type: ignore[arg-type]
        room_id="team:room",
        user_id="u-1",
        username="ada",
        display_name="Ada",
        user_role="developer",
        base_dir=tmp_path,
        now_iso=lambda: "now",
    )

    assert room.room_id == "team:room"
    assert ws._sidar_room_id == "team:room"
    assert ws.sent[0]["type"] == "room_state"
    assert room.participants

    failing_ws = _WebSocket(fail=True)
    room.participants[999] = collaboration.CollaborationParticipant(
        failing_ws, "u-2", "lin", "Lin"
    )
    await collaboration.broadcast_room_payload(room, {"type": "presence"})
    assert 999 not in room.participants

    await collaboration.emit_control_room_event(
        rooms,
        "team:room",
        kind="status",
        source="test",
        content="hello",
        mask_text=lambda text: text,
        now_iso=lambda: "now",
    )
    assert room.telemetry[-1]["kind"] == "status"

    await collaboration.leave_collaboration_room(rooms, ws)  # type: ignore[arg-type]
    assert "team:room" not in rooms
