import asyncio
import json
import sys
import types

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

    # line 274
    with pytest.raises(mod.HTTPException) as exc2:
        asyncio.run(mod.register_user({"username": "ab", "password": "123"}))
    assert exc2.value.status_code == 400

    async def _auth(**_):
        return types.SimpleNamespace(id="u1", username="alice", role="user")

    async def _token(_uid):
        return types.SimpleNamespace(token="tok-1")

    db = types.SimpleNamespace(
        authenticate_user=_auth,
        create_auth_token=_token,
    )
    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=db))

    async def _get_agent():
        return agent

    monkeypatch.setattr(mod, "get_agent", _get_agent)

    # lines 295-296
    login_resp = asyncio.run(mod.login_user({"username": "alice", "password": "123456"}))
    assert login_resp.content["access_token"] == "tok-1"

    # line 301
    user = types.SimpleNamespace(id="u1", username="alice", role="user")
    me_resp = asyncio.run(mod.auth_me(_FakeRequest(), user=user))
    assert me_resp.content == {"id": "u1", "username": "alice", "role": "user"}


def test_rate_limit_redis_success_and_fallback_paths(mod, monkeypatch):
    mod._redis_client = None
    mod._redis_lock = None

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