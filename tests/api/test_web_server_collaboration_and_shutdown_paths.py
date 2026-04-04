from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

try:
    import web_server
except ModuleNotFoundError as exc:
    pytest.skip(f"web_server import dependency missing: {exc}", allow_module_level=True)


class _Socket:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(payload)


class _TaskStub:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


@pytest.mark.asyncio
async def test_broadcast_room_payload_removes_stale_participants() -> None:
    good = _Socket()
    stale = _Socket(fail=True)
    room = web_server._CollaborationRoom(
        room_id="workspace:default",
        participants={1: web_server._CollaborationParticipant(good, "1", "alice", "Alice"), 2: web_server._CollaborationParticipant(stale, "2", "bob", "Bob")},
    )

    await web_server._broadcast_room_payload(room, {"type": "ping"})

    assert good.sent == [{"type": "ping"}]
    assert 2 not in room.participants


@pytest.mark.asyncio
async def test_join_and_leave_collaboration_room_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    web_server._collaboration_rooms.clear()
    ws = _Socket()

    room = await web_server._join_collaboration_room(
        ws,
        room_id="workspace:alpha",
        user_id="u1",
        username="alice",
        display_name="Alice",
        user_role="developer",
    )

    assert room.room_id == "workspace:alpha"
    assert getattr(ws, "_sidar_room_id") == "workspace:alpha"
    assert any(payload.get("type") == "room_state" for payload in ws.sent)

    await web_server._leave_collaboration_room(ws)

    assert getattr(ws, "_sidar_room_id") == ""
    assert "workspace:alpha" not in web_server._collaboration_rooms


@pytest.mark.asyncio
async def test_leave_collaboration_room_cancels_active_task_when_last_participant() -> None:
    web_server._collaboration_rooms.clear()
    ws = _Socket()
    task = _TaskStub()
    room = web_server._CollaborationRoom(
        room_id="workspace:solo",
        participants={id(ws): web_server._CollaborationParticipant(ws, "u", "u", "U")},
        active_task=task,
    )
    web_server._collaboration_rooms["workspace:solo"] = room
    setattr(ws, "_sidar_room_id", "workspace:solo")

    await web_server._leave_collaboration_room(ws)

    assert task.cancelled is True
    assert "workspace:solo" not in web_server._collaboration_rooms


def test_build_prompt_and_message_helpers_mask_and_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server, "_mask_collaboration_text", lambda text: f"MASKED:{text}")
    p1 = web_server._CollaborationParticipant(_Socket(), "1", "alice", "Alice", role="developer", write_scopes=["/tmp/ws"])
    p2 = web_server._CollaborationParticipant(_Socket(), "2", "bob", "Bob", role="user")
    room = web_server._CollaborationRoom(
        room_id="workspace:default",
        participants={1: p1, 2: p2},
        messages=[{"role": "user", "author_name": "Alice", "content": "secret"}],
    )

    payload = web_server._build_room_message(
        room_id=room.room_id,
        role="assistant",
        content="secret",
        author_name="Sidar",
        author_id="sidar",
        kind="telemetry",
    )
    prompt = web_server._build_collaboration_prompt(room, actor_name="Alice", command="write file")

    assert payload["content"] == "MASKED:secret"
    assert "requesting_role=developer" in prompt
    assert "requesting_write_scopes=/tmp/ws" in prompt
    assert web_server._iter_stream_chunks("abcdef", size=2) == ["ab", "cd", "ef"]
    assert web_server._iter_stream_chunks("") == []


def test_append_room_buffers_apply_limits_and_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server, "_mask_collaboration_text", lambda text: text.replace("secret", "***"))
    room = web_server._CollaborationRoom(room_id="workspace:default")

    for idx in range(5):
        web_server._append_room_message(room, {"idx": idx}, limit=3)
    assert [item["idx"] for item in room.messages] == [2, 3, 4]

    for idx in range(4):
        web_server._append_room_telemetry(room, {"idx": idx, "content": "secret", "error": "secret"}, limit=2)
    assert len(room.telemetry) == 2
    assert room.telemetry[-1]["content"] == "***"
    assert room.telemetry[-1]["error"] == "***"


def test_sync_force_shutdown_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: calls.setdefault("reap", 2))
    monkeypatch.setattr(web_server, "_list_child_ollama_pids", lambda: [10, 20])
    monkeypatch.setattr(web_server, "_terminate_ollama_child_pids", lambda pids: calls.setdefault("terminated", list(pids)))

    web_server._shutdown_cleanup_done = False
    monkeypatch.setattr(web_server, "cfg", SimpleNamespace(AI_PROVIDER="openai", OLLAMA_FORCE_KILL_ON_SHUTDOWN=True))
    web_server._force_shutdown_local_llm_processes()
    assert calls.get("reap") == 2

    calls.clear()
    web_server._shutdown_cleanup_done = False
    monkeypatch.setattr(web_server, "cfg", SimpleNamespace(AI_PROVIDER="ollama", OLLAMA_FORCE_KILL_ON_SHUTDOWN=True))
    web_server._force_shutdown_local_llm_processes()
    assert calls.get("terminated") == [10, 20]


@pytest.mark.asyncio
async def test_async_force_shutdown_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    kill_calls: list[tuple[int, int]] = []

    monkeypatch.setattr(web_server, "_list_child_ollama_pids", lambda: [11])
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: 1)
    monkeypatch.setattr(web_server, "cfg", SimpleNamespace(AI_PROVIDER="ollama", OLLAMA_FORCE_KILL_ON_SHUTDOWN=True))
    monkeypatch.setattr(web_server.os, "kill", lambda pid, sig: kill_calls.append((pid, sig)))

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(web_server.asyncio, "sleep", _no_sleep)
    web_server._shutdown_cleanup_done = False

    await web_server._async_force_shutdown_local_llm_processes()

    assert web_server._shutdown_cleanup_done is True
    assert [pid for pid, _ in kill_calls] == [11, 11]
