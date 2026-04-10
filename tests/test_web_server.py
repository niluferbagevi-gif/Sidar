from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web_server


class _FakeWebSocket:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.messages = []

    async def send_json(self, payload):
        if self.should_fail:
            raise RuntimeError("socket closed")
        self.messages.append(payload)


@pytest.fixture(autouse=True)
def _clear_rooms():
    web_server._collaboration_rooms.clear()
    yield
    web_server._collaboration_rooms.clear()


def test_normalize_room_id_valid_and_invalid():
    assert web_server._normalize_room_id("team:alpha") == "team:alpha"

    with pytest.raises(web_server.HTTPException) as exc:
        web_server._normalize_room_id("invalid room id!")

    assert exc.value.status_code == 400


def test_collaboration_write_scopes_for_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server.cfg, "BASE_DIR", str(tmp_path), raising=False)

    admin_scopes = web_server._collaboration_write_scopes_for_role("admin", "workspace:room")
    editor_scopes = web_server._collaboration_write_scopes_for_role("editor", "workspace:room")
    user_scopes = web_server._collaboration_write_scopes_for_role("user", "workspace:room")

    assert admin_scopes == [str(tmp_path.resolve())]
    assert editor_scopes == [str((tmp_path / "workspaces" / "workspace/room").resolve())]
    assert user_scopes == []


def test_append_room_telemetry_masks_and_limits(monkeypatch):
    room = web_server._CollaborationRoom(room_id="workspace:default")
    monkeypatch.setattr(web_server, "_mask_collaboration_text", lambda text: f"MASKED:{text}")

    web_server._append_room_telemetry(room, {"content": "secret", "error": "boom"}, limit=1)
    web_server._append_room_telemetry(room, {"content": "last"}, limit=1)

    assert len(room.telemetry) == 1
    assert room.telemetry[0]["content"] == "MASKED:last"


@pytest.mark.asyncio
async def test_broadcast_room_payload_removes_stale_participants():
    alive_ws = _FakeWebSocket(should_fail=False)
    stale_ws = _FakeWebSocket(should_fail=True)

    room = web_server._CollaborationRoom(room_id="workspace:default")
    room.participants = {
        1: web_server._CollaborationParticipant(alive_ws, "u1", "user1", "User One"),
        2: web_server._CollaborationParticipant(stale_ws, "u2", "user2", "User Two"),
    }

    await web_server._broadcast_room_payload(room, {"type": "ping"})

    assert 1 in room.participants
    assert 2 not in room.participants
    assert alive_ws.messages == [{"type": "ping"}]


@pytest.mark.asyncio
async def test_join_collaboration_room_sets_presence_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server.cfg, "BASE_DIR", str(tmp_path), raising=False)
    ws = _FakeWebSocket()

    room = await web_server._join_collaboration_room(
        ws,
        room_id="workspace:alpha",
        user_id="u1",
        username="alice",
        display_name="Alice",
        user_role="editor",
    )

    participant = room.participants[web_server._socket_key(ws)]
    assert participant.can_write is True
    assert participant.write_scopes
    assert ws.messages[0]["type"] == "room_state"
    assert ws.messages[-1]["type"] == "presence"


@pytest.mark.asyncio
async def test_leave_collaboration_room_removes_last_participant():
    ws = _FakeWebSocket()
    await web_server._join_collaboration_room(
        ws,
        room_id="workspace:solo",
        user_id="u1",
        username="alice",
        display_name="Alice",
    )

    assert "workspace:solo" in web_server._collaboration_rooms
    await web_server._leave_collaboration_room(ws)
    assert "workspace:solo" not in web_server._collaboration_rooms


@pytest.mark.asyncio
async def test_health_endpoint_returns_503_when_ollama_offline(monkeypatch):
    fake_agent = SimpleNamespace(
        cfg=SimpleNamespace(AI_PROVIDER="ollama"),
        health=SimpleNamespace(
            get_health_summary=lambda: {"status": "ok", "ollama_online": False}
        ),
    )

    async def _fake_get_agent():
        return fake_agent

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    with TestClient(web_server.app) as client:
        resp = client.get("/health")

    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"


def test_health_endpoint_returns_503_when_agent_crashes(monkeypatch):
    async def _boom_get_agent():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(web_server, "get_agent", _boom_get_agent)

    with TestClient(web_server.app) as client:
        resp = client.get("/health")

    assert resp.status_code == 503
    assert resp.json()["error"] == "health_check_failed"
