"""Collaboration room state and helper routines for Sidar web routes."""

from __future__ import annotations

import asyncio
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, WebSocket

COLLAB_ROOM_RE = re.compile(r"^[a-zA-Z0-9:_./-]{2,96}$")
COLLAB_WRITE_INTENT_RE = re.compile(
    r"(?i)\b("
    r"write|edit|patch|modify|delete|remove|rename|commit|push|create file|save file|"
    r"yaz|düzenle|değiştir|sil|kaldır|yeniden adlandır|commit at|dosya oluştur|dosya kaydet"
    r")\b"
)
COLLAB_WRITE_ROLES = {"admin", "maintainer", "developer", "editor"}


class CollaborationParticipant:
    """Participant metadata tracked for a collaboration WebSocket."""

    def __init__(
        self,
        websocket: WebSocket,
        user_id: str,
        username: str,
        display_name: str,
        role: str = "user",
        can_write: bool = False,
        write_scopes: list[str] | None = None,
        joined_at: str = "",
        *,
        now_iso: Callable[[], str] | None = None,
    ) -> None:
        normalized_role = normalize_collaboration_role(role)
        normalized_joined_at = joined_at

        # Legacy test helpers/calls passed joined_at as the 5th positional argument.
        if (
            not joined_at
            and not can_write
            and write_scopes is None
            and isinstance(role, str)
            and role
            and ("T" in role or "+" in role or role.endswith("Z") or role.lower() == "now")
        ):
            normalized_role = "user"
            normalized_joined_at = role

        self.websocket = websocket
        self.user_id = user_id
        self.username = username
        self.display_name = display_name
        self.role = normalized_role
        self.can_write = bool(can_write)
        self.write_scopes = list(write_scopes or [])
        self.joined_at = normalized_joined_at or (now_iso or collaboration_now_iso)()


class CollaborationRoom:
    """In-memory collaboration room state."""

    def __init__(
        self,
        room_id: str,
        participants: dict[int, CollaborationParticipant] | None = None,
        messages: list[dict[str, Any]] | None = None,
        telemetry: list[dict[str, Any]] | None = None,
        active_task: asyncio.Task[Any] | None = None,
    ) -> None:
        self.room_id = room_id
        self.participants = participants if participants is not None else {}
        self.messages = messages if messages is not None else []
        self.telemetry = telemetry if telemetry is not None else []
        self.active_task = active_task


def collaboration_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_room_id(room_id: str) -> str:
    normalized = (room_id or "").strip() or "workspace:default"
    if not COLLAB_ROOM_RE.match(normalized):
        raise HTTPException(status_code=400, detail="Geçersiz room_id")
    return normalized


def socket_key(websocket: WebSocket) -> int:
    return id(websocket)


def serialize_collaboration_participant(
    participant: CollaborationParticipant,
) -> dict[str, Any]:
    return {
        "user_id": participant.user_id,
        "username": participant.username,
        "display_name": participant.display_name,
        "role": participant.role,
        "can_write": "true" if participant.can_write else "false",
        "write_scopes": list(participant.write_scopes),
        "joined_at": participant.joined_at,
    }


def normalize_collaboration_role(role: str) -> str:
    allowed_roles = {"admin", "maintainer", "developer", "editor", "user"}
    normalized = (role or "").strip().lower()
    return normalized if normalized in allowed_roles else "user"


def collaboration_write_scopes_for_role(role: str, room_id: str, *, base_dir: Path) -> list[str]:
    normalized_role = normalize_collaboration_role(role)
    resolved_base_dir = base_dir.resolve()
    if normalized_role == "admin":
        return [str(resolved_base_dir)]
    if normalized_role in COLLAB_WRITE_ROLES:
        return [str(resolved_base_dir / "workspaces" / room_id.replace(":", "/"))]
    return []


def collaboration_command_requires_write(command: str) -> bool:
    return bool(COLLAB_WRITE_INTENT_RE.search(str(command or "")))


def mask_collaboration_text(
    text: str,
    *,
    import_module: Callable[[str], Any],
    logger_obj: Any,
) -> str:
    try:
        dlp_module = import_module("core.dlp")
        mask_pii = getattr(dlp_module, "mask_pii", None)
        if callable(mask_pii):
            return str(mask_pii(str(text or "")))
    except Exception as exc:
        logger_obj.debug("DLP maskeleme uygulanamadı, ham metin döndürüldü: %s", exc)
    return str(text or "")


def serialize_collaboration_room(room: CollaborationRoom) -> dict[str, Any]:
    return {
        "room_id": room.room_id,
        "participants": [
            serialize_collaboration_participant(item)
            for item in sorted(
                room.participants.values(), key=lambda value: value.display_name.lower()
            )
        ],
        "messages": list(room.messages[-120:]),
        "telemetry": list(room.telemetry[-120:]),
    }


def append_room_message(room: CollaborationRoom, payload: dict[str, Any], *, limit: int = 200) -> None:
    room.messages.append(payload)
    if len(room.messages) > limit:
        room.messages = room.messages[-limit:]


def append_room_telemetry(
    room: CollaborationRoom,
    payload: dict[str, Any],
    *,
    mask_text: Callable[[str], str],
    limit: int = 200,
) -> None:
    safe_payload = dict(payload)
    if "content" in safe_payload:
        safe_payload["content"] = mask_text(str(safe_payload.get("content", "") or ""))
    if "error" in safe_payload:
        safe_payload["error"] = mask_text(str(safe_payload.get("error", "") or ""))
    room.telemetry.append(safe_payload)
    if len(room.telemetry) > limit:
        room.telemetry = room.telemetry[-limit:]


def build_room_message(
    *,
    room_id: str,
    role: str,
    content: str,
    author_name: str,
    author_id: str,
    mask_text: Callable[[str], str],
    now_iso: Callable[[], str],
    kind: str = "message",
    request_id: str = "",
) -> dict[str, Any]:
    return {
        "id": secrets.token_hex(8),
        "room_id": room_id,
        "role": role,
        "kind": kind,
        "content": mask_text(content),
        "author_name": author_name,
        "author_id": author_id,
        "request_id": request_id,
        "ts": now_iso(),
    }


async def broadcast_room_payload(room: CollaborationRoom, payload: dict[str, Any]) -> None:
    stale: list[int] = []
    for key, participant in list(room.participants.items()):
        try:
            await participant.websocket.send_json(payload)
        except Exception:
            stale.append(key)
    for key in stale:
        room.participants.pop(key, None)


async def emit_control_room_event(
    rooms: dict[str, CollaborationRoom],
    room_id: str,
    *,
    kind: str,
    source: str,
    content: str,
    payload: dict[str, Any] | None = None,
    mask_text: Callable[[str], str],
    now_iso: Callable[[], str],
) -> None:
    """Mirror REST-triggered operation/QA events into collaboration rooms."""

    normalized = normalize_room_id(room_id or "ops:control")
    room = rooms.setdefault(normalized, CollaborationRoom(room_id=normalized))
    event = {
        "id": secrets.token_hex(8),
        "room_id": normalized,
        "kind": kind or "status",
        "source": source or "api",
        "content": mask_text(content),
        "payload": payload or {},
        "ts": now_iso(),
    }
    append_room_telemetry(room, event, mask_text=mask_text)
    await broadcast_room_payload(room, {"type": "collaboration_event", "event": event})


async def join_collaboration_room(
    rooms: dict[str, CollaborationRoom],
    websocket: WebSocket,
    *,
    room_id: str,
    user_id: str,
    username: str,
    display_name: str,
    user_role: str = "user",
    base_dir: Path,
    socket_key_func: Callable[[WebSocket], int] = socket_key,
    leave_room: Callable[[WebSocket], Awaitable[None]] | None = None,
    now_iso: Callable[[], str] = collaboration_now_iso,
) -> CollaborationRoom:
    normalized = normalize_room_id(room_id)
    current_room_id = str(getattr(websocket, "_sidar_room_id", "") or "")
    if current_room_id and current_room_id != normalized and leave_room is not None:
        await leave_room(websocket)

    room = rooms.setdefault(normalized, CollaborationRoom(room_id=normalized))
    write_scopes = collaboration_write_scopes_for_role(user_role, normalized, base_dir=base_dir)
    room.participants[socket_key_func(websocket)] = CollaborationParticipant(
        websocket=websocket,
        user_id=user_id,
        username=username,
        display_name=(display_name or username or user_id or "Anonim").strip()[:80],
        role=normalize_collaboration_role(user_role),
        can_write=bool(write_scopes),
        write_scopes=write_scopes,
        joined_at=now_iso(),
        now_iso=now_iso,
    )
    websocket._sidar_room_id = normalized  # type: ignore[attr-defined, unused-ignore]
    await websocket.send_json({"type": "room_state", **serialize_collaboration_room(room)})
    await broadcast_room_payload(
        room,
        {
            "type": "presence",
            "room_id": normalized,
            "participants": serialize_collaboration_room(room)["participants"],
        },
    )
    return room


async def leave_collaboration_room(
    rooms: dict[str, CollaborationRoom],
    websocket: WebSocket,
    *,
    socket_key_func: Callable[[WebSocket], int] = socket_key,
) -> None:
    room_id = str(getattr(websocket, "_sidar_room_id", "") or "")
    if not room_id:
        return
    room = rooms.get(room_id)
    websocket._sidar_room_id = ""  # type: ignore[attr-defined, unused-ignore]
    if room is None:
        return
    room.participants.pop(socket_key_func(websocket), None)
    if room.participants:
        await broadcast_room_payload(
            room,
            {
                "type": "presence",
                "room_id": room.room_id,
                "participants": serialize_collaboration_room(room)["participants"],
            },
        )
        return
    if room.active_task and not room.active_task.done():
        room.active_task.cancel()
    rooms.pop(room_id, None)


def is_sidar_mention(message: str) -> bool:
    return bool(re.search(r"(^|\s)@sidar\b", message, flags=re.IGNORECASE))


def strip_sidar_mention(message: str) -> str:
    stripped = re.sub(r"(^|\s)@sidar\b", " ", message, count=1, flags=re.IGNORECASE)
    return " ".join(stripped.split()).strip()


def build_collaboration_prompt(room: CollaborationRoom, *, actor_name: str, command: str) -> str:
    transcript: list[str] = []
    for item in room.messages[-10:]:
        transcript.append(
            f"[{item.get('role', 'user')}] {item.get('author_name', 'Anonim')}: {str(item.get('content', '')).strip()[:240]}"
        )
    recent_context = "\n".join(transcript) if transcript else "(henüz ortak geçmiş yok)"
    participants = ", ".join(
        f"{participant.display_name}<{participant.role}>"
        for participant in sorted(
            room.participants.values(), key=lambda value: value.display_name.lower()
        )
    )
    actor = next(
        (item for item in room.participants.values() if item.display_name == actor_name),
        None,
    )
    actor_role = actor.role if actor else "user"
    actor_scopes = ", ".join(actor.write_scopes) if actor and actor.write_scopes else "read-only"
    return (
        "[COLLABORATION WORKSPACE]\n"
        f"room_id={room.room_id}\n"
        f"participants={participants or 'unknown'}\n"
        f"requesting_user={actor_name}\n"
        f"requesting_role={actor_role}\n"
        f"requesting_write_scopes={actor_scopes}\n"
        "recent_transcript=\n"
        f"{recent_context}\n\n"
        "Kullanıcılar ortak bir çalışma alanında SİDAR ile iş birliği yapıyor. "
        "Yanıtında ekip bağlamını koru ve gerekiyorsa kimin ne istediğini netleştir. "
        "Yazma işlemlerinde sadece requesting_write_scopes kapsamındaki dizinleri kullan.\n\n"
        f"Current command:\n{command}"
    )
