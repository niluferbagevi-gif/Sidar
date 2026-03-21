import asyncio
import contextlib
import json
import sys
import types
from unittest.mock import patch

import jwt
import pytest

from tests.test_web_server_runtime import _FakeRequest, _load_web_server


@pytest.fixture
def mod():
    return _load_web_server()


def test_auth_helpers_and_endpoints_success_and_validation(mod, monkeypatch):
    # line 253
    req = _FakeRequest()
    with pytest.raises(mod.HTTPException) as exc:
        mod._get_request_user(req)
    assert exc.value.status_code == 401

    # line 274 — payload Pydantic modeli gibi davranmalı (username/password attr)
    short_payload = types.SimpleNamespace(username="ab", password="123", tenant_id="default")
    with pytest.raises(mod.HTTPException) as exc2:
        asyncio.run(mod.register_user(short_payload))
    assert exc2.value.status_code == 400

    async def _auth(**_):
        return types.SimpleNamespace(id="u1", username="alice", role="user")

    db = types.SimpleNamespace(
        authenticate_user=_auth,
    )
    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=db))

    async def _get_agent():
        return agent

    monkeypatch.setattr(mod, "get_agent", _get_agent)

    # lines 295-296
    with patch.object(mod.jwt, "encode", return_value="sahte.jwt.token"):
        login_resp = asyncio.run(mod.login_user(types.SimpleNamespace(username="alice", password="123456")))
        assert login_resp.content["access_token"] == "sahte.jwt.token"

    # line 301
    user = types.SimpleNamespace(id="u1", username="alice", role="user")
    me_resp = asyncio.run(mod.auth_me(_FakeRequest(), user=user))
    assert me_resp.content == {"id": "u1", "username": "alice", "role": "user"}


def test_rate_limit_redis_success_and_fallback_paths(mod, monkeypatch):
    mod._redis_client = None
    mod._redis_lock = asyncio.Lock()

    class _RedisOK:
        async def ping(self):
            return True

        async def incr(self, key):
            return 1

        async def expire(self, key, ttl):
            return True

    monkeypatch.setattr(mod.Redis, "from_url", lambda *a, **k: _RedisOK())

    # lines 346-347
    r = asyncio.run(mod._get_redis())
    assert r is not None

    class _RedisBad:
        async def incr(self, key):
            raise RuntimeError("redis down")

    async def _get_bad():
        return _RedisBad()

    monkeypatch.setattr(mod, "_get_redis", _get_bad)
    monkeypatch.setattr(mod, "_local_is_rate_limited", lambda *a, **k: asyncio.sleep(0, result=True))
    blocked = asyncio.run(mod._redis_is_rate_limited("chat", "127.0.0.1", 1, 60))
    assert blocked is True


def test_ddos_middleware_pass_through_line_417(mod, monkeypatch):
    async def _not_limited(*_):
        return False

    async def _next(_req):
        return mod.JSONResponse({"ok": True})

    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)
    resp = asyncio.run(mod.ddos_rate_limit_middleware(_FakeRequest(path="/api/x"), _next))
    assert resp.content["ok"] is True


def test_metrics_prometheus_success_branch(mod, monkeypatch):
    class _Gauge:
        def __init__(self, *args, **kwargs):
            pass

        def set(self, _v):
            return None

    prom_mod = types.SimpleNamespace(
        CollectorRegistry=lambda: object(),
        Gauge=_Gauge,
        generate_latest=lambda _reg: b"m 1\n",
        CONTENT_TYPE_LATEST="text/plain; version=0.0.4",
    )
    monkeypatch.setitem(sys.modules, "prometheus_client", prom_mod)

    star_mod = types.SimpleNamespace(Response=lambda content, media_type=None: types.SimpleNamespace(content=content, media_type=media_type))
    monkeypatch.setitem(sys.modules, "starlette.responses", star_mod)

    class _Mem:
        def __len__(self):
            return 0

        async def aget_all_sessions(self):
            return []

    mem = _Mem()
    agent = types.SimpleNamespace(VERSION="3", docs=types.SimpleNamespace(doc_count=0), memory=mem, cfg=types.SimpleNamespace(AI_PROVIDER="ollama", USE_GPU=False))

    async def _ga():
        return agent

    monkeypatch.setattr(mod, "get_agent", _ga)

    resp = asyncio.run(mod.metrics(_FakeRequest(headers={"Accept": "text/plain"})))
    assert resp.media_type == "text/plain; version=0.0.4"


def test_github_endpoints_success_and_rag_search_to_thread(mod, monkeypatch):
    gh = types.SimpleNamespace(
        is_available=lambda: True,
        get_pull_requests_detailed=lambda **_: (True, [{"number": 1}], ""),
        get_pull_request=lambda n: (True, "detail"),
        repo_name="org/repo",
    )

    calls = {"thread": 0}

    def _search_sync(q, top_k, mode, sid):
        return True, f"{q}:{top_k}:{mode}:{sid}"

    async def _to_thread(fn, *args, **kwargs):
        calls["thread"] += 1
        return fn(*args, **kwargs)

    agent = types.SimpleNamespace(
        github=gh,
        docs=types.SimpleNamespace(search=_search_sync),
        memory=types.SimpleNamespace(active_session_id="s1"),
    )

    async def _ga():
        return agent

    monkeypatch.setattr(mod, "get_agent", _ga)
    monkeypatch.setattr(mod.asyncio, "to_thread", _to_thread)

    prs = asyncio.run(mod.github_prs())
    assert prs.content["success"] is True and prs.content["repo"] == "org/repo"

    prd = asyncio.run(mod.github_pr_detail(1))
    assert prd.content == {"success": True, "detail": "detail"}

    rag = asyncio.run(mod.rag_search(q="needle", mode="auto", top_k=9))
    assert rag.content["success"] is True
    assert calls["thread"] >= 1


def test_websocket_send_json_error_swallowed_and_disconnect(mod, monkeypatch):
    class _DB:
        async def get_user_by_token(self, _tok):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __len__(self):
            return 0

        async def set_active_user(self, *_):
            return None

        async def update_title(self, *_):
            return None

    async def _respond(_msg):
        raise RuntimeError("boom")
        yield "never"

    agent = types.SimpleNamespace(memory=_Memory(), respond=_respond)
    agent.memory.db = _DB()

    async def _ga():
        return agent

    async def _not_limited(*_):
        return False

    monkeypatch.setattr(mod, "get_agent", _ga)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.headers = {}
            self._i = 0

        async def accept(self):
            return None

        async def receive_text(self):
            self._i += 1
            if self._i == 1:
                return json.dumps({"action": "auth", "token": "t"})
            if self._i == 2:
                return json.dumps({"action": "message", "message": "hi"})
            await asyncio.sleep(0.05)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            if "chunk" in payload and "Sistem Hatası" in payload["chunk"]:
                raise RuntimeError("send failed")
            return None

    asyncio.run(mod.websocket_chat(_WS()))


def test_app_lifespan_prewarm_cancellederror_branch(mod, monkeypatch):
    flags = {"cancelled": False}

    async def _prewarm():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            flags["cancelled"] = True
            raise

    monkeypatch.setattr(mod, "_prewarm_rag_embeddings", _prewarm)
    monkeypatch.setattr(mod, "_close_redis_client", lambda: asyncio.sleep(0))

    async def _run():
        async with mod._app_lifespan(mod.app):
            await asyncio.sleep(0)

    asyncio.run(_run())
    assert flags["cancelled"] is True


def test_force_shutdown_local_llm_processes_kills_child_ollama(mod, monkeypatch):
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "ollama"
    mod.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = True

    monkeypatch.setattr(mod.os, "getpid", lambda: 999)
    monkeypatch.setattr(
        mod.subprocess,
        "check_output",
        lambda *a, **k: b" 123 999 ollama ollama serve\n 124 1 ollama ollama serve\n",
    )

    killed = []
    monkeypatch.setattr(mod.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    wait_calls = {"n": 0}

    def _waitpid(_pid, _flags):
        wait_calls["n"] += 1
        if wait_calls["n"] == 1:
            return (123, 0)
        return (0, 0)

    monkeypatch.setattr(mod.os, "waitpid", _waitpid)

    mod._force_shutdown_local_llm_processes()

    assert any(pid == 123 for pid, _ in killed)


def test_force_shutdown_local_llm_processes_noop_when_disabled(mod, monkeypatch):
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "ollama"
    mod.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = False

    wait_calls = {"n": 0}

    def _waitpid(_pid, _flags):
        wait_calls["n"] += 1
        return (0, 0)

    monkeypatch.setattr(mod.os, "waitpid", _waitpid)

    mod._force_shutdown_local_llm_processes()
    assert wait_calls["n"] >= 1

def test_admin_prompt_endpoints(mod, monkeypatch):
    active_record = types.SimpleNamespace(
        id=2,
        role_name="system",
        prompt_text="aktif",
        version=2,
        is_active=True,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )

    class _Db:
        async def list_prompts(self, role_name=None):
            return [active_record]

        async def get_active_prompt(self, role_name):
            return active_record if role_name == "system" else None

        async def upsert_prompt(self, role_name, prompt_text, activate=True):
            return types.SimpleNamespace(
                id=3,
                role_name=role_name,
                prompt_text=prompt_text,
                version=3,
                is_active=activate,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            )

        async def activate_prompt(self, prompt_id):
            if prompt_id != 3:
                return None
            return types.SimpleNamespace(
                id=3,
                role_name="system",
                prompt_text="v3",
                version=3,
                is_active=True,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            )

    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=_Db()), system_prompt="eski")

    async def _get_agent():
        return agent

    monkeypatch.setattr(mod, "get_agent", _get_agent)

    listed = asyncio.run(mod.admin_list_prompts(role_name="system", _user=types.SimpleNamespace(role="admin", username="x")))
    assert listed.status_code == 200
    assert listed.content["items"][0]["role_name"] == "system"

    active = asyncio.run(mod.admin_active_prompt(role_name="system", _user=types.SimpleNamespace(role="admin", username="x")))
    assert active.status_code == 200
    assert active.content["is_active"] is True

    created = asyncio.run(
        mod.admin_upsert_prompt(
            mod._PromptUpsertRequest(role_name="system", prompt_text="v3", activate=True),
            _user=types.SimpleNamespace(role="admin", username="x"),
        )
    )
    assert created.status_code == 200
    assert agent.system_prompt == "v3"

    activated = asyncio.run(
        mod.admin_activate_prompt(
            mod._PromptActivateRequest(prompt_id=3),
            _user=types.SimpleNamespace(role="admin", username="x"),
        )
    )
    assert activated.status_code == 200
    assert activated.content["id"] == 3


class _DoneTask:
    def done(self):
        return True

    def cancel(self):
        return None

    def __await__(self):
        if False:
            yield None
        return None


class _SafeCancelledTask:
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


class _CollabSocket:
    def __init__(self, mod, payloads, *, before_message=None):
        self._mod = mod
        self._payloads = list(payloads)
        self._before_message = before_message
        self.sent = []
        self.client = types.SimpleNamespace(host="127.0.0.1")
        self.headers = {}
        self._sidar_room_id = ""

    async def accept(self, subprotocol=None):
        self.subprotocol = subprotocol
        return None

    async def receive_text(self):
        if not self._payloads:
            raise self._mod.WebSocketDisconnect()
        item = self._payloads.pop(0)
        if self._before_message and isinstance(item, str):
            payload = json.loads(item)
            if payload.get("action") == "message":
                self._before_message()
                self._before_message = None
        if isinstance(item, Exception):
            await asyncio.sleep(0.05)
            raise item
        return item

    async def send_json(self, payload):
        self.sent.append(payload)
        return None


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

    def update_title(self, _title):
        return None


def test_trim_autonomy_text_truncates_suffix():
    mod = _load_web_server()

    trimmed = mod._trim_autonomy_text("x" * 12, limit=5)

    assert trimmed == "xxxxx …[truncated]"


def test_websocket_chat_recreates_missing_room_and_status_timeout(monkeypatch):
    mod = _load_web_server()
    mod._collaboration_rooms.clear()

    class _Bus:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.unsubscribed = []

        def subscribe(self):
            return "sub-timeout", self.queue

        def unsubscribe(self, sub_id):
            self.unsubscribed.append(sub_id)

    bus = _Bus()
    metrics = {"set": 0, "reset": 0}
    wait_calls = {"count": 0}
    join_calls = []
    room_ref = {"room": None}
    spectator = _CollabSocket(mod, [])
    real_wait_for = mod.asyncio.wait_for
    real_join_room = mod._join_collaboration_room

    async def _wait_for_once_timeout(awaitable, timeout):
        if wait_calls["count"] == 0:
            wait_calls["count"] += 1
            with contextlib.suppress(Exception):
                awaitable.close()
            raise asyncio.TimeoutError
        return await real_wait_for(awaitable, timeout)

    async def _join_wrapper(*args, **kwargs):
        join_calls.append(kwargs["room_id"])
        room = await real_join_room(*args, **kwargs)
        room_ref["room"] = room
        if len(join_calls) == 2:
            room.participants[mod._socket_key(spectator)] = mod._CollaborationParticipant(
                spectator,
                "u2",
                "bob",
                "Bob",
                mod._collaboration_now_iso(),
            )
        return room

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def _try_multi_agent(self, _prompt):
            bus.queue.put_nowait(types.SimpleNamespace(source="planner", message="hazır"))
            await asyncio.sleep(0.05)
            mod._collaboration_rooms["workspace:demo"].active_task = _DoneTask()
            return "tamamlandı"

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    def _drop_room():
        mod._collaboration_rooms.clear()

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: bus)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)
    monkeypatch.setattr(mod.asyncio, "wait_for", _wait_for_once_timeout)
    monkeypatch.setattr(mod, "_join_collaboration_room", _join_wrapper)
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: metrics.__setitem__("set", metrics["set"] + 1) or "ctx-token")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _tok: metrics.__setitem__("reset", metrics["reset"] + 1))

    ws = _CollabSocket(
        mod,
        [
            json.dumps({"action": "auth", "token": "tok"}),
            json.dumps({"action": "join_room", "room_id": "workspace:demo", "display_name": "Alice"}),
            json.dumps({"action": "message", "message": "@Sidar planı hazırla", "display_name": "Alice"}),
            mod.WebSocketDisconnect(),
        ],
        before_message=_drop_room,
    )

    asyncio.run(mod.websocket_chat(ws))

    assert join_calls == ["workspace:demo", "workspace:demo"]
    assert wait_calls["count"] == 1
    assert any(item.get("type") == "collaboration_event" for item in ws.sent)
    assert any(item.get("type") == "assistant_done" for item in spectator.sent)
    assert metrics["set"] == 1


def test_websocket_chat_room_task_cancelled_broadcasts_cancel_state(monkeypatch):
    mod = _load_web_server()
    mod._collaboration_rooms.clear()

    class _Bus:
        def __init__(self):
            self.unsubscribed = []

        def subscribe(self):
            return "sub-cancel", asyncio.Queue()

        def unsubscribe(self, sub_id):
            self.unsubscribed.append(sub_id)

    bus = _Bus()
    metrics = {"reset": 0}
    room_ref = {"room": None}

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def _try_multi_agent(self, _prompt):
            room_ref["room"] = mod._collaboration_rooms["workspace:cancel"]
            room_ref["room"].active_task = _DoneTask()
            raise asyncio.CancelledError

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    ws = _CollabSocket(
        mod,
        [
            json.dumps({"action": "auth", "token": "tok"}),
            json.dumps({"action": "join_room", "room_id": "workspace:cancel", "display_name": "Alice"}),
            json.dumps({"action": "message", "message": "@Sidar iptal", "display_name": "Alice"}),
            mod.WebSocketDisconnect(),
        ],
    )

    real_create_task = mod.asyncio.create_task

    def _create_task(coro):
        if getattr(coro, "cr_code", None) and coro.cr_code.co_name == "_status_pump":
            coro.close()
            return _SafeCancelledTask()
        return real_create_task(coro)

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: bus)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx-token")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _tok: metrics.__setitem__("reset", metrics["reset"] + 1))
    monkeypatch.setattr(mod.asyncio, "create_task", _create_task)

    asyncio.run(mod.websocket_chat(ws))

    cancelled = [item for item in ws.sent if item.get("type") == "assistant_done" and item.get("cancelled") is True]
    assert cancelled and cancelled[-1]["message"] is None
    assert bus.unsubscribed == ["sub-cancel"]
    assert metrics["reset"] == 1
    assert room_ref["room"].active_task is None


def test_websocket_chat_room_task_exception_broadcasts_room_error(monkeypatch):
    mod = _load_web_server()
    mod._collaboration_rooms.clear()

    class _Bus:
        def __init__(self):
            self.unsubscribed = []

        def subscribe(self):
            return "sub-error", asyncio.Queue()

        def unsubscribe(self, sub_id):
            self.unsubscribed.append(sub_id)

    bus = _Bus()
    metrics = {"reset": 0}
    room_ref = {"room": None}

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def _try_multi_agent(self, _prompt):
            room_ref["room"] = mod._collaboration_rooms["workspace:error"]
            room_ref["room"].active_task = _DoneTask()
            raise RuntimeError("multi-agent boom")

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    ws = _CollabSocket(
        mod,
        [
            json.dumps({"action": "auth", "token": "tok"}),
            json.dumps({"action": "join_room", "room_id": "workspace:error", "display_name": "Alice"}),
            json.dumps({"action": "message", "message": "@Sidar hata üret", "display_name": "Alice"}),
            mod.WebSocketDisconnect(),
        ],
    )

    real_create_task = mod.asyncio.create_task

    def _create_task(coro):
        if getattr(coro, "cr_code", None) and coro.cr_code.co_name == "_status_pump":
            coro.close()
            return _SafeCancelledTask()
        return real_create_task(coro)

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: bus)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx-token")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _tok: metrics.__setitem__("reset", metrics["reset"] + 1))
    monkeypatch.setattr(mod.asyncio, "create_task", _create_task)

    asyncio.run(mod.websocket_chat(ws))

    errors = [item for item in ws.sent if item.get("type") == "room_error"]
    assert errors and "multi-agent boom" in errors[-1]["error"]
    assert bus.unsubscribed == ["sub-error"]
    assert metrics["reset"] == 1
    assert room_ref["room"].active_task is None
