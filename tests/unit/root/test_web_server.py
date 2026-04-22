from pathlib import Path
import re

import pytest
from fastapi import HTTPException

import web_server


_DECORATOR_RE = re.compile(r'@app\.(get|post|put|delete|patch)\(\s*"([^"]+)"')


class _DummyWebSocket:
    def __init__(self, fail: bool = False):
        self.messages = []
        self.fail = fail

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError("send failure")
        self.messages.append(payload)


def _collect_app_routes() -> set[tuple[str, str]]:
    source = Path("web_server.py").read_text(encoding="utf-8")
    return {(method.upper(), path) for method, path in _DECORATOR_RE.findall(source)}


def test_auth_and_admin_endpoints_are_declared():
    routes = _collect_app_routes()
    expected = {
        ("POST", "/auth/register"),
        ("POST", "/auth/login"),
        ("GET", "/auth/me"),
        ("GET", "/admin/stats"),
        ("GET", "/admin/prompts"),
        ("POST", "/admin/prompts"),
        ("POST", "/admin/prompts/activate"),
    }
    assert expected.issubset(routes)


def test_agent_plugin_swarm_and_hitl_endpoints_are_declared():
    routes = _collect_app_routes()
    expected = {
        ("POST", "/api/agents/register"),
        ("POST", "/api/agents/register-file"),
        ("GET", "/api/plugin-marketplace/catalog"),
        ("POST", "/api/plugin-marketplace/install"),
        ("DELETE", "/api/plugin-marketplace/install/{plugin_id}"),
        ("POST", "/api/swarm/execute"),
        ("GET", "/api/hitl/pending"),
        ("POST", "/api/hitl/request"),
        ("POST", "/api/hitl/respond/{request_id}"),
    }
    assert expected.issubset(routes)


def test_observability_and_health_endpoints_are_declared():
    routes = _collect_app_routes()
    expected = {
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("GET", "/metrics"),
        ("GET", "/metrics/llm/prometheus"),
        ("GET", "/metrics/llm"),
        ("GET", "/api/budget"),
    }
    assert expected.issubset(routes)


def test_session_file_git_and_rag_endpoints_are_declared():
    routes = _collect_app_routes()
    expected = {
        ("GET", "/sessions/{session_id}"),
        ("POST", "/sessions/new"),
        ("DELETE", "/sessions/{session_id}"),
        ("GET", "/files"),
        ("GET", "/file-content"),
        ("GET", "/git-info"),
        ("GET", "/git-branches"),
        ("POST", "/set-branch"),
        ("GET", "/github-repos"),
        ("POST", "/set-repo"),
        ("GET", "/rag/docs"),
        ("POST", "/rag/add-url"),
        ("DELETE", "/rag/docs/{doc_id}"),
        ("POST", "/api/rag/upload"),
    }
    assert expected.issubset(routes)


def test_web_server_route_table_has_no_duplicate_method_path_pairs():
    source = Path("web_server.py").read_text(encoding="utf-8")
    matches = [(method.upper(), path) for method, path in _DECORATOR_RE.findall(source)]
    assert len(matches) == len(set(matches))


@pytest.fixture(autouse=True)
def _reset_collaboration_state(monkeypatch, tmp_path):
    web_server._collaboration_rooms.clear()
    web_server._hitl_ws_clients.clear()
    monkeypatch.setattr(web_server.cfg, "BASE_DIR", str(tmp_path))
    yield
    web_server._collaboration_rooms.clear()
    web_server._hitl_ws_clients.clear()


def test_room_id_normalization_and_validation():
    assert web_server._normalize_room_id("  team:alpha  ") == "team:alpha"
    assert web_server._normalize_room_id("") == "workspace:default"
    with pytest.raises(HTTPException):
        web_server._normalize_room_id("<bad>")


def test_collaboration_role_and_write_scope_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server.cfg, "BASE_DIR", str(tmp_path))

    assert web_server._normalize_collaboration_role("ADMIN") == "admin"
    assert web_server._normalize_collaboration_role("unknown") == "user"

    admin_scopes = web_server._collaboration_write_scopes_for_role("admin", "room:one")
    assert admin_scopes == [str(tmp_path.resolve())]

    dev_scopes = web_server._collaboration_write_scopes_for_role("developer", "room:one")
    assert dev_scopes == [str((tmp_path / "workspaces" / "room/one").resolve())]

    assert web_server._collaboration_write_scopes_for_role("user", "room:one") == []


def test_command_detection_message_build_and_chunking(monkeypatch):
    monkeypatch.setattr(web_server, "_collaboration_now_iso", lambda: "2026-01-01T00:00:00+00:00")
    monkeypatch.setattr(web_server, "_mask_collaboration_text", lambda text: f"masked:{text}")

    assert web_server._collaboration_command_requires_write("please edit file")
    assert web_server._collaboration_command_requires_write("dosya oluştur")
    assert not web_server._collaboration_command_requires_write("sadece oku")

    payload = web_server._build_room_message(
        room_id="room:a",
        role="user",
        content="secret",
        author_name="Ada",
        author_id="u1",
    )
    assert payload["content"] == "masked:secret"
    assert payload["ts"] == "2026-01-01T00:00:00+00:00"

    assert web_server._iter_stream_chunks("", size=2) == []
    assert web_server._iter_stream_chunks("abcdef", size=2) == ["ab", "cd", "ef"]


def test_append_and_serialize_room_data(monkeypatch):
    monkeypatch.setattr(web_server, "_mask_collaboration_text", lambda text: text.replace("123", "***"))

    ws_b = _DummyWebSocket()
    ws_a = _DummyWebSocket()
    participant_b = web_server._CollaborationParticipant(ws_b, "u2", "beta", "Beta", "maintainer")
    participant_a = web_server._CollaborationParticipant(ws_a, "u1", "alpha", "Alpha", "user")
    room = web_server._CollaborationRoom(
        room_id="workspace:default",
        participants={2: participant_b, 1: participant_a},
    )

    web_server._append_room_message(room, {"content": "m1"}, limit=2)
    web_server._append_room_message(room, {"content": "m2"}, limit=2)
    web_server._append_room_message(room, {"content": "m3"}, limit=2)
    assert [m["content"] for m in room.messages] == ["m2", "m3"]

    web_server._append_room_telemetry(room, {"content": "pii123", "error": "boom123"}, limit=1)
    assert room.telemetry[0]["content"] == "pii***"
    assert room.telemetry[0]["error"] == "boom***"

    serialized = web_server._serialize_collaboration_room(room)
    assert serialized["participants"][0]["display_name"] == "Alpha"
    assert serialized["participants"][1]["display_name"] == "Beta"


@pytest.mark.asyncio
async def test_join_leave_and_broadcast_room_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(web_server.cfg, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(web_server, "_collaboration_now_iso", lambda: "now")

    ws_ok = _DummyWebSocket()
    ws_fail = _DummyWebSocket(fail=True)

    room = await web_server._join_collaboration_room(
        ws_ok,
        room_id="team:room",
        user_id="u1",
        username="ada",
        display_name="Ada",
        user_role="developer",
    )
    assert room.room_id == "team:room"
    assert getattr(ws_ok, "_sidar_room_id") == "team:room"
    assert ws_ok.messages[0]["type"] == "room_state"

    # failing participant is pruned during broadcast
    room.participants[999] = web_server._CollaborationParticipant(ws_fail, "u2", "lin", "Lin")
    await web_server._broadcast_room_payload(room, {"type": "presence"})
    assert 999 not in room.participants

    # moving to another room should leave old room
    await web_server._join_collaboration_room(
        ws_ok,
        room_id="team:other",
        user_id="u1",
        username="ada",
        display_name="Ada",
        user_role="user",
    )
    assert "team:room" not in web_server._collaboration_rooms
    assert getattr(ws_ok, "_sidar_room_id") == "team:other"

    await web_server._leave_collaboration_room(ws_ok)
    assert getattr(ws_ok, "_sidar_room_id") == ""
    assert "team:other" not in web_server._collaboration_rooms


@pytest.mark.asyncio
async def test_hitl_broadcast_and_prompt_helpers():
    ws_ok = _DummyWebSocket()
    ws_fail = _DummyWebSocket(fail=True)
    web_server._hitl_ws_clients.update({ws_ok, ws_fail})

    await web_server._hitl_broadcast({"event": "x"})
    assert ws_ok.messages == [{"event": "x"}]
    assert ws_fail not in web_server._hitl_ws_clients

    assert web_server._is_sidar_mention("Merhaba @sidar nasılsın")
    assert not web_server._is_sidar_mention("Merhaba sidar")
    assert web_server._strip_sidar_mention("  @SIDAR   test komutu  ") == "test komutu"

    ws_actor = _DummyWebSocket()
    room = web_server._CollaborationRoom(
        room_id="workspace:default",
        participants={
            1: web_server._CollaborationParticipant(
                ws_actor,
                "u1",
                "ada",
                "Ada",
                role="editor",
                can_write=True,
                write_scopes=["/tmp/workspaces/a"],
            )
        },
        messages=[
            {"role": "user", "author_name": "Ada", "content": "İlk mesaj"},
            {"role": "assistant", "author_name": "Sidar", "content": "Yanıt"},
        ],
    )
    prompt = web_server._build_collaboration_prompt(room, actor_name="Ada", command="README güncelle")
    assert "room_id=workspace:default" in prompt
    assert "requesting_write_scopes=/tmp/workspaces/a" in prompt
    assert "Current command:\nREADME güncelle" in prompt


def test_collaboration_participant_backward_compat_and_serialization(monkeypatch):
    monkeypatch.setattr(web_server, "_collaboration_now_iso", lambda: "now")

    ws = _DummyWebSocket()
    participant = web_server._CollaborationParticipant(
        ws,
        "u1",
        "ada",
        "Ada",
        "2026-01-01T00:00:00+00:00",
    )
    assert participant.role == "user"
    assert participant.joined_at == "2026-01-01T00:00:00+00:00"

    serialized = web_server._serialize_collaboration_participant(participant)
    assert serialized["can_write"] == "false"

    participant_write = web_server._CollaborationParticipant(
        ws,
        "u2",
        "lin",
        "Lin",
        role="editor",
        can_write=True,
        write_scopes=["/tmp/ws"],
    )
    serialized_write = web_server._serialize_collaboration_participant(participant_write)
    assert serialized_write["can_write"] == "true"
    assert serialized_write["write_scopes"] == ["/tmp/ws"]


@pytest.mark.asyncio
async def test_leave_collaboration_room_edge_cases(monkeypatch):
    ws = _DummyWebSocket()

    # no room bound
    await web_server._leave_collaboration_room(ws)

    # room id set but room not found
    setattr(ws, "_sidar_room_id", "missing")
    await web_server._leave_collaboration_room(ws)
    assert getattr(ws, "_sidar_room_id") == ""

    # non-empty room should broadcast presence instead of deleting
    ws2 = _DummyWebSocket()
    room = web_server._CollaborationRoom(room_id="r1")
    room.participants = {
        web_server._socket_key(ws): web_server._CollaborationParticipant(ws, "u1", "a", "A"),
        web_server._socket_key(ws2): web_server._CollaborationParticipant(ws2, "u2", "b", "B"),
    }
    web_server._collaboration_rooms["r1"] = room
    setattr(ws, "_sidar_room_id", "r1")

    await web_server._leave_collaboration_room(ws)
    assert "r1" in web_server._collaboration_rooms
    assert web_server._socket_key(ws) not in room.participants


def test_build_collaboration_prompt_defaults():
    room = web_server._CollaborationRoom(room_id="workspace:default")
    prompt = web_server._build_collaboration_prompt(room, actor_name="Ghost", command="Oku")

    assert "(henüz ortak geçmiş yok)" in prompt
    assert "participants=unknown" in prompt
    assert "requesting_role=user" in prompt
    assert "requesting_write_scopes=read-only" in prompt


def test_reap_child_processes_nonblocking(monkeypatch):
    calls = iter([(123, 0), (0, 0)])
    monkeypatch.setattr(web_server.os, "waitpid", lambda *_args: next(calls))
    assert web_server._reap_child_processes_nonblocking() == 1



def test_terminate_ollama_child_pids_calls_signals(monkeypatch):
    sent = []
    monkeypatch.setattr(web_server.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(web_server.time, "sleep", lambda _s: None)

    web_server._terminate_ollama_child_pids([10, 20], grace_seconds=0.01)

    assert sent[:2] == [
        (10, web_server.signal.SIGTERM),
        (20, web_server.signal.SIGTERM),
    ]
    assert sent[2:] == [
        (10, web_server.signal.SIGKILL),
        (20, web_server.signal.SIGKILL),
    ]


def test_force_shutdown_local_llm_processes_branches(monkeypatch):
    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)

    reaped = []
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: reaped.append(True) or 0)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "openai")
    web_server._force_shutdown_local_llm_processes()
    assert reaped == [True]

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", False)
    web_server._force_shutdown_local_llm_processes()
    assert reaped == [True, True]

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    terminated = []
    monkeypatch.setattr(web_server, "_list_child_ollama_pids", lambda: [7])
    monkeypatch.setattr(web_server, "_terminate_ollama_child_pids", lambda pids: terminated.append(pids))
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", True)
    web_server._force_shutdown_local_llm_processes()
    assert terminated == [[7]]


@pytest.mark.asyncio
async def test_async_force_shutdown_local_llm_processes_branches(monkeypatch):
    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    reaped = []
    monkeypatch.setattr(web_server, "_reap_child_processes_nonblocking", lambda: reaped.append(True) or 0)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "openai")
    await web_server._async_force_shutdown_local_llm_processes()
    assert reaped == [True]

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", False)
    await web_server._async_force_shutdown_local_llm_processes()
    assert reaped == [True, True]

    monkeypatch.setattr(web_server, "_shutdown_cleanup_done", False)
    monkeypatch.setattr(web_server.cfg, "OLLAMA_FORCE_KILL_ON_SHUTDOWN", True)
    monkeypatch.setattr(web_server, "_list_child_ollama_pids", lambda: [111])
    sent = []
    monkeypatch.setattr(web_server.os, "kill", lambda pid, sig: sent.append((pid, sig)))

    await web_server._async_force_shutdown_local_llm_processes()

    assert (111, web_server.signal.SIGTERM) in sent
    assert (111, web_server.signal.SIGKILL) in sent


def test_list_child_ollama_pids_with_psutil_stub(monkeypatch):
    class _Child:
        def __init__(self, pid, name, cmd):
            self.pid = pid
            self._name = name
            self._cmd = cmd

        def name(self):
            return self._name

        def cmdline(self):
            return self._cmd

    class _Process:
        def __init__(self, _pid):
            pass

        def children(self, recursive=False):
            assert recursive is False
            return [
                _Child(1, "ollama", ["ollama", "serve"]),
                _Child(2, "python", ["python", "x.py"]),
                _Child(3, "bash", ["ollama serve"]),
            ]

    class _Psutil:
        Process = _Process

    monkeypatch.setitem(__import__("sys").modules, "psutil", _Psutil)
    monkeypatch.setattr(web_server.os, "getpid", lambda: 999)

    pids = web_server._list_child_ollama_pids()
    assert pids == [1, 3]
