from __future__ import annotations

import asyncio
import sys
import types
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
            raise RuntimeError("closed")
        self.sent.append(payload)


class _Collector:
    def __init__(self) -> None:
        self.sink = None

    def set_usage_sink(self, sink):
        self.sink = sink


@pytest.mark.asyncio
async def test_hitl_broadcast_removes_dead_clients() -> None:
    ok = _Socket()
    dead = _Socket(fail=True)
    web_server._hitl_ws_clients = {ok, dead}

    await web_server._hitl_broadcast({"type": "hitl"})

    assert ok.sent == [{"type": "hitl"}]
    assert dead not in web_server._hitl_ws_clients


def test_mask_collaboration_text_fallback_and_success(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.dlp":
            raise RuntimeError("no dlp")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    assert web_server._mask_collaboration_text("abc") == "abc"

    mod = types.ModuleType("core.dlp")
    mod.mask_pii = lambda value: f"masked::{value}"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.dlp", mod)
    monkeypatch.setattr("builtins.__import__", original_import)

    assert web_server._mask_collaboration_text("abc") == "masked::abc"


@pytest.mark.asyncio
async def test_join_room_switches_previous_room(monkeypatch: pytest.MonkeyPatch) -> None:
    web_server._collaboration_rooms.clear()
    calls: list[str] = []

    async def _fake_leave(ws) -> None:
        calls.append(str(getattr(ws, "_sidar_room_id", "")))
        setattr(ws, "_sidar_room_id", "")

    monkeypatch.setattr(web_server, "_leave_collaboration_room", _fake_leave)
    ws = _Socket()
    setattr(ws, "_sidar_room_id", "workspace:old")

    await web_server._join_collaboration_room(
        ws,
        room_id="workspace:new",
        user_id="u1",
        username="alice",
        display_name="Alice",
    )

    assert calls == ["workspace:old"]


@pytest.mark.asyncio
async def test_leave_room_none_and_presence_branch() -> None:
    ws_missing = _Socket()
    setattr(ws_missing, "_sidar_room_id", "workspace:missing")
    await web_server._leave_collaboration_room(ws_missing)
    assert getattr(ws_missing, "_sidar_room_id") == ""

    web_server._collaboration_rooms.clear()
    ws1 = _Socket()
    ws2 = _Socket()
    room = web_server._CollaborationRoom(
        room_id="workspace:pair",
        participants={
            id(ws1): web_server._CollaborationParticipant(ws1, "1", "a", "A"),
            id(ws2): web_server._CollaborationParticipant(ws2, "2", "b", "B"),
        },
    )
    web_server._collaboration_rooms[room.room_id] = room
    setattr(ws1, "_sidar_room_id", room.room_id)

    await web_server._leave_collaboration_room(ws1)

    assert room.room_id in web_server._collaboration_rooms
    assert any(item.get("type") == "presence" for item in ws2.sent)


def test_strip_sidar_mention_removes_first_mention() -> None:
    assert web_server._strip_sidar_mention("Merhaba @sidar nasılsın") == "Merhaba nasılsın"
    assert web_server._strip_sidar_mention("@SIDAR test @sidar") == "test @sidar"


def test_list_child_ollama_pids_fallback_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(web_server.os, "getpid", lambda: 500)
    sample = "501 500 ollama ollama serve\n502 500 bash bash run\n503 500 python python ollama serve\n"
    monkeypatch.setattr(web_server.subprocess, "check_output", lambda *args, **kwargs: sample.encode())

    assert web_server._list_child_ollama_pids() == [501, 503]


def test_reap_child_processes_nonblocking_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    seq = [(11, 0), (12, 0), (0, 0)]

    def _waitpid(_pid, _flags):
        return seq.pop(0)

    monkeypatch.setattr(web_server.os, "waitpid", _waitpid)
    assert web_server._reap_child_processes_nonblocking() == 2


def test_terminate_ollama_child_pids_term_and_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(web_server.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    monkeypatch.setattr(web_server.time, "sleep", lambda _sec: None)

    web_server._terminate_ollama_child_pids([1, 2], grace_seconds=0.01)

    assert calls == [
        (1, web_server.signal.SIGTERM),
        (2, web_server.signal.SIGTERM),
        (1, web_server.signal.SIGKILL),
        (2, web_server.signal.SIGKILL),
    ]


@pytest.mark.asyncio
async def test_bind_llm_usage_sink_and_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = _Collector()
    monkeypatch.setattr(web_server, "get_llm_metrics_collector", lambda: collector)

    saved: list[tuple[str, str, int, int]] = []

    class _Db:
        async def record_provider_usage_daily(self, *, user_id: str, provider: str, tokens_used: int, requests_inc: int) -> None:
            saved.append((user_id, provider, tokens_used, requests_inc))

    agent = SimpleNamespace(memory=SimpleNamespace(db=_Db()))

    web_server._bind_llm_usage_sink(agent)
    assert collector.sink is not None

    collector.sink(SimpleNamespace(user_id="u1", provider="openai", total_tokens=7))
    collector.sink(SimpleNamespace(user_id="", provider="openai", total_tokens=7))
    await asyncio.sleep(0)

    assert saved == [("u1", "openai", 7, 1)]

    # second bind should be ignored due to bound flag
    collector.sink = None
    web_server._bind_llm_usage_sink(agent)
    assert collector.sink is None


@pytest.mark.asyncio
async def test_prewarm_rag_embeddings_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    logs: list[str] = []
    monkeypatch.setattr(web_server.logger, "info", lambda msg, *args: logs.append(str(msg) % args if args else str(msg)))
    monkeypatch.setattr(web_server.logger, "warning", lambda msg, *args: logs.append(str(msg) % args if args else str(msg)))

    async def _agent_without_rag():
        return SimpleNamespace(rag=None)

    monkeypatch.setattr(web_server, "get_agent", _agent_without_rag)
    await web_server._prewarm_rag_embeddings()

    class _Rag:
        _chroma_available = False

    async def _agent_no_chroma():
        return SimpleNamespace(rag=_Rag())

    monkeypatch.setattr(web_server, "get_agent", _agent_no_chroma)
    await web_server._prewarm_rag_embeddings()

    class _RagOk:
        _chroma_available = True

        def __init__(self) -> None:
            self.called = False

        def _init_chroma(self) -> None:
            self.called = True

    rag_ok = _RagOk()

    async def _agent_ok():
        return SimpleNamespace(rag=rag_ok)

    monkeypatch.setattr(web_server, "get_agent", _agent_ok)
    await web_server._prewarm_rag_embeddings()
    assert rag_ok.called is True

    async def _agent_fail():
        raise RuntimeError("boom")

    monkeypatch.setattr(web_server, "get_agent", _agent_fail)
    await web_server._prewarm_rag_embeddings()

    assert any("RAG prewarm atlandı" in item for item in logs)
    assert any("RAG prewarm başarısız" in item for item in logs)
