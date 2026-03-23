import asyncio
import json
import sys
import types
from pathlib import Path

import pytest

def _load_web_server_for_extra_tests():
    from tests.test_web_server_runtime import _load_web_server

    return _load_web_server()


class _Socket:
    def __init__(self, payloads=None):
        self._payloads = list(payloads or [])
        self.sent = []
        self.client = types.SimpleNamespace(host="127.0.0.1")
        self.headers = {}
        self._sidar_room_id = ""

    async def accept(self, subprotocol=None):
        self.subprotocol = subprotocol
        return None

    async def receive_text(self):
        if self._payloads:
            item = self._payloads.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        await asyncio.sleep(0.02)
        raise RuntimeError("socket-boom")

    async def send_json(self, payload):
        self.sent.append(payload)
        return None


class _PendingTask:
    def __init__(self):
        self.cancelled = False

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True

    def __await__(self):
        if False:
            yield None
        return None


def test_collaboration_helpers_trim_stale_participants_and_switch_rooms(monkeypatch):
    mod = _load_web_server_for_extra_tests()
    mod._collaboration_rooms.clear()

    with pytest.raises(mod.HTTPException) as exc:
        mod._normalize_room_id("bad room id!")
    assert exc.value.status_code == 400

    room = mod._CollaborationRoom(room_id="workspace:demo")
    mod._append_room_message(room, {"n": 1}, limit=1)
    mod._append_room_message(room, {"n": 2}, limit=1)
    mod._append_room_telemetry(room, {"t": 1}, limit=1)
    mod._append_room_telemetry(room, {"t": 2}, limit=1)
    assert room.messages == [{"n": 2}]
    assert room.telemetry == [{"t": 2}]
    assert mod._iter_stream_chunks("") == []

    class _GoodSocket(_Socket):
        pass

    class _BadSocket(_Socket):
        async def send_json(self, payload):
            raise RuntimeError("send failed")

    good = _GoodSocket()
    bad = _BadSocket()
    room.participants = {
        1: mod._CollaborationParticipant(good, "u1", "good", "Good", "now"),
        2: mod._CollaborationParticipant(bad, "u2", "bad", "Bad", "now"),
    }
    asyncio.run(mod._broadcast_room_payload(room, {"type": "ping"}))
    assert 1 in room.participants
    assert 2 not in room.participants

    old_ws = _Socket()
    old_task = _PendingTask()
    old_room = mod._CollaborationRoom(
        room_id="workspace:old",
        participants={
            mod._socket_key(old_ws): mod._CollaborationParticipant(old_ws, "u-old", "old", "Old", "now")
        },
        active_task=old_task,
    )
    mod._collaboration_rooms["workspace:old"] = old_room
    old_ws._sidar_room_id = "workspace:old"

    asyncio.run(
        mod._join_collaboration_room(
            old_ws,
            room_id="workspace:new",
            user_id="u-new",
            username="alice",
            display_name="Alice",
        )
    )
    assert old_task.cancelled is True
    assert "workspace:old" not in mod._collaboration_rooms
    assert old_ws._sidar_room_id == "workspace:new"

    orphan = _Socket()
    orphan._sidar_room_id = "workspace:missing"
    asyncio.run(mod._leave_collaboration_room(orphan))
    assert orphan._sidar_room_id == ""


def test_collaboration_masking_falls_back_to_raw_text_and_masks_error_fields(monkeypatch):
    mod = _load_web_server_for_extra_tests()
    room = mod._CollaborationRoom(room_id="workspace:mask")

    fake_dlp = types.ModuleType("core.dlp")

    def _boom(_text):
        raise RuntimeError("mask boom")

    fake_dlp.mask_pii = _boom
    monkeypatch.setitem(sys.modules, "core.dlp", fake_dlp)

    assert mod._mask_collaboration_text("api-key=123") == "api-key=123"

    monkeypatch.setattr(mod, "_mask_collaboration_text", lambda text: f"masked::{text}")
    mod._append_room_telemetry(room, {"content": "secret", "error": "token leaked"})

    assert room.telemetry[-1]["content"] == "masked::secret"
    assert room.telemetry[-1]["error"] == "masked::token leaked"


def test_event_driven_federation_specs_cover_jira_and_system_paths():
    mod = _load_web_server_for_extra_tests()

    jira = mod._build_event_driven_federation_spec(
        "jira",
        "issue_created",
        {
            "action": "created",
            "issue": {
                "key": "OPS-42",
                "summary": "Prod incident",
                "fields": {
                    "project": {"key": "OPS"},
                    "status": {"name": "Open"},
                    "issuetype": {"name": "Bug"},
                    "description": "CPU spike observed",
                },
            },
        },
    )
    assert jira["workflow_type"] == "jira_issue"
    assert jira["context"]["project_key"] == "OPS"
    assert any("issue_key=OPS-42" == item for item in jira["inputs"])

    system = mod._build_event_driven_federation_spec(
        "system",
        "incident",
        {
            "severity": "critical",
            "alert_name": "api-latency",
            "message": "Timeout yükseldi",
            "stacktrace": "trace",
        },
    )
    assert system["workflow_type"] == "system_error"
    assert system["context"]["severity"] == "critical"
    assert system["context"]["alert_name"] == "api-latency"


def test_nightly_memory_loop_disabled_success_and_warning_paths(monkeypatch):
    mod = _load_web_server_for_extra_tests()
    infos = []
    warnings = []
    monkeypatch.setattr(mod.logger, "info", lambda msg, *args: infos.append(msg % args if args else msg))
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    mod.cfg.ENABLE_NIGHTLY_MEMORY_PRUNING = False
    asyncio.run(mod._nightly_memory_loop(asyncio.Event()))
    assert any("devre dışı" in item for item in infos)

    async def _success_agent():
        return types.SimpleNamespace(
            run_nightly_memory_maintenance=lambda **_kw: asyncio.sleep(0, result={"status": "ok"})
        )

    calls = {"count": 0}

    async def _fake_wait_for(waitable, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            if hasattr(waitable, "close"):
                waitable.close()
            raise asyncio.TimeoutError()
        result = await waitable
        return result

    mod.cfg.ENABLE_NIGHTLY_MEMORY_PRUNING = True
    stop_success = asyncio.Event()
    monkeypatch.setattr(mod, "get_agent", _success_agent)
    monkeypatch.setattr(mod.asyncio, "wait_for", _fake_wait_for)

    async def _run_success():
        task = asyncio.create_task(mod._nightly_memory_loop(stop_success))
        await asyncio.sleep(0)
        stop_success.set()
        await task

    asyncio.run(_run_success())
    assert any("maintenance sonucu: ok" in item for item in infos)

    async def _failing_agent():
        async def _boom(**_kw):
            raise RuntimeError("nightly boom")

        return types.SimpleNamespace(run_nightly_memory_maintenance=_boom)

    calls["count"] = 0
    stop_fail = asyncio.Event()
    monkeypatch.setattr(mod, "get_agent", _failing_agent)

    async def _run_fail():
        task = asyncio.create_task(mod._nightly_memory_loop(stop_fail))
        await asyncio.sleep(0)
        stop_fail.set()
        await task

    asyncio.run(_run_fail())
    assert any("nightly boom" in item for item in warnings)


def test_app_lifespan_cancels_autonomy_and_nightly_tasks(monkeypatch):
    mod = _load_web_server_for_extra_tests()
    cancelled = {"prewarm": 0, "cron": 0, "nightly": 0}

    async def _prewarm():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled["prewarm"] += 1
            raise

    async def _cron(_stop):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled["cron"] += 1
            raise

    async def _nightly(_stop):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled["nightly"] += 1
            raise

    async def _to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(mod, "_prewarm_rag_embeddings", _prewarm)
    monkeypatch.setattr(mod, "_autonomous_cron_loop", _cron)
    monkeypatch.setattr(mod, "_nightly_memory_loop", _nightly)
    monkeypatch.setattr(mod.asyncio, "to_thread", _to_thread)
    monkeypatch.setattr(mod, "_close_redis_client", lambda: asyncio.sleep(0))
    monkeypatch.setattr(mod, "_async_force_shutdown_local_llm_processes", lambda: asyncio.sleep(0))
    mod.cfg.ENABLE_AUTONOMOUS_CRON = True
    mod.cfg.ENABLE_NIGHTLY_MEMORY_PRUNING = True

    async def _run():
        async with mod._app_lifespan(mod.app):
            await asyncio.sleep(0)

    asyncio.run(_run())
    assert cancelled == {"prewarm": 1, "cron": 1, "nightly": 1}


def test_app_lifespan_skips_done_prewarm_task_and_still_runs_cleanup(monkeypatch):
    mod = _load_web_server_for_extra_tests()
    events = []

    async def _prewarm():
        events.append("prewarm")

    async def _close():
        events.append("close_redis")

    async def _shutdown():
        events.append("shutdown_llm")

    monkeypatch.setattr(mod, "_prewarm_rag_embeddings", _prewarm)
    monkeypatch.setattr(mod, "_close_redis_client", _close)
    monkeypatch.setattr(mod, "_async_force_shutdown_local_llm_processes", _shutdown)
    mod.cfg.ENABLE_AUTONOMOUS_CRON = False
    mod.cfg.ENABLE_NIGHTLY_MEMORY_PRUNING = False

    async def _run():
        async with mod._app_lifespan(mod.app):
            await asyncio.sleep(0)

    asyncio.run(_run())

    assert events == ["prewarm", "close_redis", "shutdown_llm"]


def test_plugin_marketplace_state_and_reload_error_paths(tmp_path, monkeypatch):
    mod = _load_web_server_for_extra_tests()
    warnings = []
    state_path = tmp_path / ".marketplace_state.json"
    monkeypatch.setattr(mod, "_plugin_marketplace_state_path", lambda: state_path)
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warnings.append(msg % args if args else msg))

    state_path.write_text("{broken", encoding="utf-8")
    assert mod._read_plugin_marketplace_state() == {}
    assert warnings and "okunamadı" in warnings[-1]

    state_path.write_text("[]", encoding="utf-8")
    assert mod._read_plugin_marketplace_state() == {}

    with pytest.raises(mod.HTTPException) as exc:
        mod._get_plugin_marketplace_entry("missing-plugin")
    assert exc.value.status_code == 404

    known_keys = list(mod.PLUGIN_MARKETPLACE_CATALOG)
    assert len(known_keys) >= 2
    missing_entry = dict(mod.PLUGIN_MARKETPLACE_CATALOG[known_keys[0]])
    missing_entry["entrypoint"] = str(tmp_path / "missing_plugin.py")
    monkeypatch.setitem(mod.PLUGIN_MARKETPLACE_CATALOG, known_keys[0], missing_entry)

    with pytest.raises(mod.HTTPException) as exc2:
        mod._install_marketplace_plugin(known_keys[0])
    assert exc2.value.status_code == 500
    assert "Plugin kaynağı bulunamadı" in exc2.value.detail

    state_path.write_text(json.dumps({"unknown-plugin": {}, known_keys[0]: {}, known_keys[1]: {}}), encoding="utf-8")

    def _install(plugin_id):
        if plugin_id == known_keys[0]:
            raise mod.HTTPException(status_code=409, detail="conflict")
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "_install_marketplace_plugin", _install)
    results = mod._reload_persisted_marketplace_plugins()
    assert results == []
    assert any("conflict" in item for item in warnings)
    assert any("boom" in item for item in warnings)


def test_websocket_chat_collaboration_status_pump_and_empty_mention(monkeypatch):
    mod = _load_web_server_for_extra_tests()
    mod._collaboration_rooms.clear()
    warning_logs = []
    monkeypatch.setattr(mod.logger, "warning", lambda msg, *args: warning_logs.append(msg % args if args else msg))

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def _try_multi_agent(self, prompt):
            await asyncio.sleep(0.02)
            return "ok:" + prompt.split("Current command:\n", 1)[-1].strip()

    class _Bus:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.queue.put_nowait(types.SimpleNamespace(source="reviewer", message="çalışıyor"))
            self.unsubscribed = []

        def subscribe(self):
            return "sub-1", self.queue

        def unsubscribe(self, sub_id):
            self.unsubscribed.append(sub_id)

    async def _not_limited(*_args, **_kwargs):
        return False

    bus = _Bus()
    monkeypatch.setattr(mod, "get_agent", lambda: asyncio.sleep(0, result=_Agent()))
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: bus)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)

    class _CollabSocket(_Socket):
        async def receive_text(self):
            if self._payloads:
                item = self._payloads.pop(0)
                if isinstance(item, Exception):
                    await asyncio.sleep(0.05)
                    raise item
                return item
            raise mod.WebSocketDisconnect()

    ws = _CollabSocket(
        [
            json.dumps({"action": "auth", "token": "tok"}),
            json.dumps({"action": "join_room", "room_id": "workspace:demo", "display_name": "Alice"}),
            json.dumps({"action": "message", "message": "@Sidar planı hazırla", "display_name": "Alice"}),
            json.dumps({"action": "message", "message": "@Sidar", "display_name": "Alice"}),
            mod.WebSocketDisconnect(),
        ]
    )

    asyncio.run(mod.websocket_chat(ws))

    assert any(item.get("type") == "collaboration_event" for item in ws.sent)
    assert any(item.get("type") == "assistant_done" for item in ws.sent)
    assert any(item.get("type") == "room_error" and "komut bulunamadı" in item.get("error", "") for item in ws.sent)

    ws_boom = _Socket([RuntimeError("socket-boom")])
    asyncio.run(mod.websocket_chat(ws_boom))
    assert any("socket-boom" in item for item in warning_logs)


def test_websocket_chat_room_cancel_and_retrigger_cancel_existing_room_task(monkeypatch):
    mod = _load_web_server_for_extra_tests()
    mod._collaboration_rooms.clear()

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def set_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 1

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def _try_multi_agent(self, prompt):
            return prompt

    async def _not_limited(*_args, **_kwargs):
        return False

    pending_tasks = []

    def _create_task(coro):
        coro.close()
        task = _PendingTask()
        pending_tasks.append(task)
        return task

    monkeypatch.setattr(mod, "get_agent", lambda: asyncio.sleep(0, result=_Agent()))
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)
    monkeypatch.setattr(mod.asyncio, "create_task", _create_task)

    ws_cancel = _Socket(
        [
            json.dumps({"action": "auth", "token": "tok"}),
            json.dumps({"action": "join_room", "room_id": "workspace:cancel", "display_name": "Alice"}),
            json.dumps({"action": "message", "message": "@Sidar ilk görev", "display_name": "Alice"}),
            json.dumps({"action": "cancel"}),
            mod.WebSocketDisconnect(),
        ]
    )
    asyncio.run(mod.websocket_chat(ws_cancel))
    assert pending_tasks[0].cancelled is True

    pending_tasks.clear()
    ws_retrigger = _Socket(
        [
            json.dumps({"action": "auth", "token": "tok"}),
            json.dumps({"action": "join_room", "room_id": "workspace:retry", "display_name": "Alice"}),
            json.dumps({"action": "message", "message": "@Sidar ilk görev", "display_name": "Alice"}),
            json.dumps({"action": "message", "message": "@Sidar ikinci görev", "display_name": "Alice"}),
            mod.WebSocketDisconnect(),
        ]
    )
    asyncio.run(mod.websocket_chat(ws_retrigger))
    assert len(pending_tasks) >= 2
    assert pending_tasks[0].cancelled is True


def test_spa_fallback_covers_root_and_asset_like_paths(monkeypatch):
    mod = _load_web_server_for_extra_tests()
    monkeypatch.setattr(mod, "index", lambda: asyncio.sleep(0, result=types.SimpleNamespace(content="INDEX", status_code=200)))

    root = asyncio.run(mod.spa_fallback(""))
    page = asyncio.run(mod.spa_fallback("workspace/dashboard"))
    asset = asyncio.run(mod.spa_fallback("favicon.ico"))

    assert root.content == "INDEX"
    assert page.content == "INDEX"
    assert asset.status_code == 404