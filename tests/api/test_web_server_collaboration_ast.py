from __future__ import annotations

from pathlib import Path


WEB_SERVER_PATH = Path(__file__).resolve().parents[2] / "web_server.py"


def _source() -> str:
    return WEB_SERVER_PATH.read_text(encoding="utf-8")


def test_collaboration_helpers_have_core_guards_and_normalizers() -> None:
    source = _source()

    assert "def _normalize_room_id(room_id: str) -> str:" in source
    assert 'normalized = (room_id or "").strip() or "workspace:default"' in source
    assert "if not _COLLAB_ROOM_RE.match(normalized):" in source
    assert 'raise HTTPException(status_code=400, detail="Geçersiz room_id")' in source

    assert "def _normalize_collaboration_role(role: str) -> str:" in source
    assert 'allowed_roles = {"admin", "maintainer", "developer", "editor", "user"}' in source
    assert 'return normalized if normalized in allowed_roles else "user"' in source


def test_collaboration_write_scope_and_command_intent_paths_present() -> None:
    source = _source()

    assert "def _collaboration_write_scopes_for_role(role: str, room_id: str) -> List[str]:" in source
    assert "if normalized_role == \"admin\":" in source
    assert "if normalized_role in _COLLAB_WRITE_ROLES:" in source
    assert 'return [str(base_dir / "workspaces" / room_id.replace(":", "/"))]' in source
    assert "return []" in source

    assert "def _collaboration_command_requires_write(command: str) -> bool:" in source
    assert "return bool(_COLLAB_WRITE_INTENT_RE.search(str(command or \"\")))" in source


def test_collaboration_message_prompt_and_stream_helpers_exist() -> None:
    source = _source()

    assert "def _mask_collaboration_text(text: str) -> str:" in source
    assert "from core.dlp import mask_pii as _mask_pii" in source
    assert "return _mask_pii(str(text or \"\"))" in source

    assert "def _build_collaboration_prompt(room: _CollaborationRoom, *, actor_name: str, command: str) -> str:" in source
    assert "[COLLABORATION WORKSPACE]" in source
    assert "Kullanıcılar ortak bir çalışma alanında SİDAR ile iş birliği yapıyor." in source
    assert "Current command:" in source

    assert "def _iter_stream_chunks(text: str, *, size: int = 180) -> List[str]:" in source
    assert "if not clean:" in source
    assert "return [clean[index:index + size] for index in range(0, len(clean), size)]" in source


def test_collaboration_join_leave_and_broadcast_paths_present() -> None:
    source = _source()

    assert "async def _broadcast_room_payload(room: _CollaborationRoom, payload: dict[str, Any]) -> None:" in source
    assert "for key, participant in list(room.participants.items()):" in source
    assert "stale: list[int] = []" in source
    assert "room.participants.pop(key, None)" in source

    assert "async def _join_collaboration_room(" in source
    assert "room = _collaboration_rooms.setdefault(normalized, _CollaborationRoom(room_id=normalized))" in source
    assert "room.participants[_socket_key(websocket)] = _CollaborationParticipant(" in source
    assert "await websocket.send_json({\"type\": \"room_state\", **_serialize_collaboration_room(room)})" in source

    assert "async def _leave_collaboration_room(websocket: WebSocket) -> None:" in source
    assert "if room.active_task and not room.active_task.done():" in source
    assert "room.active_task.cancel()" in source
    assert "_collaboration_rooms.pop(room_id, None)" in source
