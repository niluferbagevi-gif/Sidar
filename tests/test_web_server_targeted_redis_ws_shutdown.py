import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

from tests.test_web_server_runtime import _install_web_server_stubs, _restore_modules


def _load_web_server():
    replaced_modules = _install_web_server_stubs()
    hitl_mod = types.ModuleType("core.hitl")
    hitl_mod.get_hitl_gate = lambda: types.SimpleNamespace()
    hitl_mod.get_hitl_store = lambda: types.SimpleNamespace()
    hitl_mod.set_hitl_broadcast_hook = lambda _hook: None
    previous_hitl = sys.modules.get("core.hitl")
    sys.modules["core.hitl"] = hitl_mod

    spec = importlib.util.spec_from_file_location("web_server_targeted_under_test", Path("web_server.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    try:
        spec.loader.exec_module(mod)
    finally:
        if previous_hitl is None:
            sys.modules.pop("core.hitl", None)
        else:
            sys.modules["core.hitl"] = previous_hitl
        _restore_modules(
            replaced_modules,
            names=("core.llm_metrics", "core.llm_client"),
        )
    return mod


class _DB:
    async def get_user_by_token(self, token):
        if token:
            return types.SimpleNamespace(id="u1", username="alice")
        return None


class _Memory:
    def __init__(self):
        self.db = _DB()
        self.active_users = []

    async def set_active_user(self, user_id, username=None):
        self.active_users.append((user_id, username))

    def __len__(self):
        return 1

    def update_title(self, _title):
        return None


class _Agent:
    def __init__(self):
        self.memory = _Memory()

    async def respond(self, _msg):
        if False:
            yield "unused"


async def _not_limited(*_args, **_kwargs):
    return False


class _Bus:
    def subscribe(self):
        return "sub-1", asyncio.Queue()

    def unsubscribe(self, _sub_id):
        return None


def test_websocket_chat_uses_local_fallback_when_redis_is_unavailable(monkeypatch):
    mod = _load_web_server()
    agent = _Agent()

    async def _get_agent():
        return agent

    async def _get_redis_none():
        return None

    local_calls = []

    async def _local_limit(key, limit, window):
        local_calls.append((key, limit, window))
        return True

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}
            self.sent = []
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "merhaba"}),
            ]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: _Bus())
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: None)
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _token: None)
    monkeypatch.setattr(mod, "_get_redis", _get_redis_none)
    monkeypatch.setattr(mod, "_local_is_rate_limited", _local_limit)

    ws = _WebSocket()
    asyncio.run(mod.websocket_chat(ws))

    assert local_calls and local_calls[0][0].startswith("sidar:rl:chat_ws:127.0.0.1:")
    assert {"auth_ok": True} in ws.sent
    assert any(item.get("done") is True and "Hız Sınırı" in item.get("chunk", "") for item in ws.sent)
    assert agent.memory.active_users == [("u1", "alice")]


def test_websocket_chat_cancels_active_task_on_anyio_closed_resource(monkeypatch):
    mod = _load_web_server()
    agent = _Agent()

    async def _get_agent():
        return agent

    class _ClosedResourceError(Exception):
        pass

    class _FakeTask:
        def __init__(self):
            self.cancel_called = False

        def done(self):
            return False

        def cancel(self):
            self.cancel_called = True

    fake_task = _FakeTask()

    def _create_task_stub(coro):
        coro.close()
        return fake_task

    class _WebSocket:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {"sec-websocket-protocol": "valid-token"}
            self.accepted = None
            self._payloads = [json.dumps({"action": "send", "message": "selam"})]

        async def accept(self, subprotocol=None):
            self.accepted = subprotocol

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            raise _ClosedResourceError("socket closed")

        async def send_json(self, _payload):
            return None

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: _Bus())
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)
    monkeypatch.setattr(mod.asyncio, "create_task", _create_task_stub)
    monkeypatch.setattr(mod, "_ANYIO_CLOSED", _ClosedResourceError)

    ws = _WebSocket()
    asyncio.run(mod.websocket_chat(ws))

    assert ws.accepted == "valid-token"
    assert fake_task.cancel_called is True
    assert agent.memory.active_users == [("u1", "alice")]


def test_async_shutdown_cleanup_terminates_listed_ollama_children(monkeypatch):
    mod = _load_web_server()
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "ollama"
    mod.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = True

    killed = []
    reaped = {"count": 0}

    monkeypatch.setattr(mod, "_list_child_ollama_pids", lambda: [111, 222])
    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", lambda: reaped.__setitem__("count", reaped["count"] + 1) or 2)

    real_sleep = asyncio.sleep

    async def _fast_sleep(*_args, **_kwargs):
        await real_sleep(0)

    monkeypatch.setattr(mod.asyncio, "sleep", _fast_sleep)

    asyncio.run(mod._async_force_shutdown_local_llm_processes())

    assert mod._shutdown_cleanup_done is True
    assert reaped["count"] == 1
    assert killed == [
        (111, mod.signal.SIGTERM),
        (222, mod.signal.SIGTERM),
        (111, mod.signal.SIGKILL),
        (222, mod.signal.SIGKILL),
    ]
