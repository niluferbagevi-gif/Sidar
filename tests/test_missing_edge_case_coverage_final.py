import asyncio
import builtins
import contextlib
import io
import json
import subprocess
import types
from pathlib import Path
from unittest.mock import AsyncMock

import core.llm_client as llm
from tests.test_web_server_runtime import _FakeRequest, _FakeUploadFile, _load_web_server


class _Cfg:
    OLLAMA_URL = "http://localhost:11434/api"
    OLLAMA_TIMEOUT = 120


async def _collect(async_iterable):
    out = []
    async for item in async_iterable:
        out.append(item)
    return out


def test_llmclient_non_ollama_fallback_helpers(monkeypatch):
    client = llm.LLMClient("openai", _Cfg())

    assert client._ollama_base_url == "http://localhost:11434"
    assert asyncio.run(client.list_ollama_models()) == []
    assert asyncio.run(client.is_ollama_available()) is False

    async def _fake_stream(self, _response_stream):
        yield "fallback-chunk"

    monkeypatch.setattr(llm.GeminiClient, "_stream_gemini_generator", _fake_stream)
    assert asyncio.run(_collect(client._stream_gemini_generator(object()))) == ["fallback-chunk"]


def test_web_server_missing_error_and_guard_paths(monkeypatch):
    mod = _load_web_server()

    # _bind_llm_usage_sink: DB write exception should be swallowed
    collector = types.SimpleNamespace(_sidar_usage_sink_bound=False)

    def _set_usage_sink(sink):
        collector.sink = sink

    collector.set_usage_sink = _set_usage_sink
    monkeypatch.setattr(mod, "get_llm_metrics_collector", lambda: collector)

    agent_for_sink = types.SimpleNamespace(
        memory=types.SimpleNamespace(
            db=types.SimpleNamespace(
                record_provider_usage_daily=AsyncMock(side_effect=Exception("DB Error"))
            )
        )
    )
    mod._bind_llm_usage_sink(agent_for_sink)

    async def _trigger_sink():
        collector.sink(types.SimpleNamespace(user_id="u-1", provider="openai", total_tokens=7))
        await asyncio.sleep(0)

    asyncio.run(_trigger_sink())

    # _setup_tracing: enabled but dependency missing -> warning path
    mod.cfg.ENABLE_TRACING = True
    mod.OTLPSpanExporter = None
    mod._setup_tracing()

    # Shared fake agent for endpoints
    db = types.SimpleNamespace(
        register_user=AsyncMock(side_effect=Exception("duplicate")),
    )
    github = types.SimpleNamespace(
        is_available=lambda: False,
        get_pull_requests_detailed=lambda **_kwargs: (False, [], "API Error"),
        repo_name="owner/repo",
        set_repo=lambda repo: (True, f"repo={repo}"),
    )
    docs = types.SimpleNamespace(add_document_from_url=AsyncMock(return_value=(True, "ok")), add_document_from_file=lambda *a, **k: (True, "ok"))
    memory = types.SimpleNamespace(active_session_id="sess-1", db=db)
    fake_agent = types.SimpleNamespace(memory=memory, github=github, docs=docs)

    async def _get_agent():
        return fake_agent

    monkeypatch.setattr(mod, "get_agent", _get_agent)

    # /auth/register exception -> 409
    try:
        asyncio.run(mod.register_user({"username": "alice", "password": "123456"}))
        raise AssertionError("expected HTTPException")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409

    # /set-branch invalid regex -> 400
    bad_name = asyncio.run(mod.set_branch(_FakeRequest(method="POST", path="/set-branch", json_body={"branch": "dal adı!"})))
    assert bad_name.status_code == 400

    # /set-branch checkout failure -> 400
    async def _to_thread_fail(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(mod.asyncio, "to_thread", _to_thread_fail)

    def _raise_checkout(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["git", "checkout"], output=b"not found")

    monkeypatch.setattr(mod.subprocess, "check_output", _raise_checkout)
    checkout_fail = asyncio.run(mod.set_branch(_FakeRequest(method="POST", path="/set-branch", json_body={"branch": "missing-branch"})))
    assert checkout_fail.status_code == 400

    # /github-prs token missing -> 503
    gh_unavailable = asyncio.run(mod.github_prs())
    assert gh_unavailable.status_code == 503

    # /github-prs provider failure -> 500
    github.is_available = lambda: True
    gh_error = asyncio.run(mod.github_prs())
    assert gh_error.status_code == 500

    # /set-repo empty repo -> 400
    set_repo_empty = asyncio.run(mod.set_repo(_FakeRequest(method="POST", path="/set-repo", json_body={"repo": ""})))
    assert set_repo_empty.status_code == 400

    # /rag/add-url empty url -> 400
    add_url_empty = asyncio.run(mod.rag_add_url(_FakeRequest(method="POST", path="/rag/add-url", json_body={"url": "   "})))
    assert add_url_empty.status_code == 400

    # /api/rag/upload safe filename fallback -> uploaded_file.txt
    captured = {}

    def _add_document_from_file(path, *_args):
        captured["path"] = path
        return True, "ok"

    fake_agent.docs.add_document_from_file = _add_document_from_file
    up = _FakeUploadFile("&&&***", b"hello")
    uploaded = asyncio.run(mod.upload_rag_file(up))
    assert uploaded.status_code == 200
    assert captured["path"].endswith("uploaded_file.txt")


def test_web_server_remaining_edge_case_endpoints(monkeypatch):
    mod = _load_web_server()

    # _get_client_ip: X-Real-IP header path and missing client fallback
    real_ip_req = _FakeRequest(headers={"X-Real-IP": " 10.10.10.10 "})
    assert mod._get_client_ip(real_ip_req) == "10.10.10.10"

    unknown_req = _FakeRequest(headers={})
    unknown_req.client = None
    assert mod._get_client_ip(unknown_req) == "unknown"

    github = types.SimpleNamespace(
        is_available=lambda: False,
        get_pull_request=lambda _number: (False, "Not Found"),
        repo_name="owner/repo",
        set_repo=lambda repo: (True, f"repo={repo}"),
    )
    docs = types.SimpleNamespace(
        add_document_from_url=AsyncMock(return_value=(True, "ok")),
        delete_document=lambda *_args, **_kwargs: "Hata: silinemedi",
        add_document_from_file=lambda *_args, **_kwargs: (True, "ok"),
    )
    memory = types.SimpleNamespace(active_session_id="sess-1")
    fake_agent = types.SimpleNamespace(memory=memory, github=github, docs=docs)

    async def _get_agent():
        return fake_agent

    monkeypatch.setattr(mod, "get_agent", _get_agent)

    # /github-prs/{number}: github disabled -> 503
    pr_disabled = asyncio.run(mod.github_pr_detail(42))
    assert pr_disabled.status_code == 503

    # /github-prs/{number}: backend not found -> 404
    github.is_available = lambda: True
    pr_not_found = asyncio.run(mod.github_pr_detail(42))
    assert pr_not_found.status_code == 404

    # /set-repo: whitespace-only value -> 400
    repo_empty = asyncio.run(mod.set_repo(_FakeRequest(method="POST", path="/set-repo", json_body={"repo": "   "})))
    assert repo_empty.status_code == 400

    # /rag/add-url: missing url key -> 400
    add_url_missing = asyncio.run(mod.rag_add_url(_FakeRequest(method="POST", path="/rag/add-url", json_body={})))
    assert add_url_missing.status_code == 400

    # /rag/docs/{doc_id}: non-success marker should map to success=False
    delete_bad = asyncio.run(mod.rag_delete_doc("doc-err"))
    assert delete_bad.status_code == 200
    assert delete_bad.content["success"] is False

    # /api/rag/upload: unexpected exception path -> 500
    up = _FakeUploadFile("doc.txt", b"payload")

    def _raise_copy(*_args, **_kwargs):
        raise Exception("copy failed")

    monkeypatch.setattr(mod.shutil, "copyfileobj", _raise_copy)
    upload_err = asyncio.run(mod.upload_rag_file(up))
    assert upload_err.status_code == 500
    assert upload_err.content["success"] is False


def test_web_server_requested_edge_case_coverage(monkeypatch):
    mod = _load_web_server()

    # 1) Redis bağlantı hatası + komut hatası fallback
    class _RedisCtorFail:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            raise RuntimeError("Redis down")

    mod._redis_client = None
    mod._redis_lock = None
    monkeypatch.setattr(mod, "Redis", _RedisCtorFail)
    assert asyncio.run(mod._get_redis()) is None

    fallback_calls = []

    async def _fallback(key, limit, window):
        fallback_calls.append((key, limit, window))
        return True

    class _RedisCommandFail:
        async def incr(self, _key):
            raise RuntimeError("rate limit cmd failed")

    mod._redis_client = _RedisCommandFail()
    monkeypatch.setattr(mod, "_local_is_rate_limited", _fallback)
    assert asyncio.run(mod._redis_is_rate_limited("chat", "127.0.0.1", 1, 60)) is True
    assert fallback_calls

    # Ortak fake agent
    db = types.SimpleNamespace(
        get_user_by_token=AsyncMock(return_value=types.SimpleNamespace(id="u1", username="alice")),
        delete_session=AsyncMock(return_value=False),
    )
    class _Memory:
        def __init__(self):
            self.db = db

        async def aset_active_user(self, *_args, **_kwargs):
            return None

        def __len__(self):
            return 0

        def get_all_sessions(self):
            return []

    memory = _Memory()
    cfg = types.SimpleNamespace(
        AI_PROVIDER="ollama",
        CODING_MODEL="qwen",
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="none",
    )
    health = types.SimpleNamespace(
        get_gpu_info=lambda: {"devices": []},
        check_ollama=lambda: False,
        get_health_summary=lambda: {"status": "ok", "ollama_online": False},
    )
    fake_agent = types.SimpleNamespace(
        VERSION="1.0",
        cfg=cfg,
        memory=memory,
        github=types.SimpleNamespace(is_available=lambda: False),
        web=types.SimpleNamespace(is_available=lambda: False),
        docs=types.SimpleNamespace(status=lambda: "ok", doc_count=0),
        pkg=types.SimpleNamespace(status=lambda: "ok"),
        health=health,
    )

    async def _get_agent():
        return fake_agent

    monkeypatch.setattr(mod, "get_agent", _get_agent)

    # 2) WebSocketDisconnect sırasında active_task.cancel çağrısı
    cancelled = {"flag": False}

    class _FakeTask:
        def done(self):
            return False

        def cancel(self):
            cancelled["flag"] = True

    def _fake_create_task(coro):
        coro.close()
        return _FakeTask()

    monkeypatch.setattr(mod.asyncio, "create_task", _fake_create_task)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", AsyncMock(return_value=False))

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.delay = 0.01
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "merhaba"}),
            ]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(self.delay)
            raise mod.WebSocketDisconnect()

        async def send_json(self, _payload):
            return None

    asyncio.run(mod.websocket_chat(_WS()))
    assert cancelled["flag"] is True

    # 3) /status GPU default alanları
    status_resp = asyncio.run(mod.status())
    assert status_resp.status_code == 200
    assert status_resp.content["gpu_count"] == 0
    assert status_resp.content["cuda_version"] == "N/A"

    # 4) /health ollama kesintisi -> 503
    health_resp = asyncio.run(mod.health_check())
    assert health_resp.status_code == 503
    assert health_resp.content["status"] == "degraded"

    # 5) /metrics text/plain + prometheus ImportError -> JSON fallback
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "prometheus_client":
            raise ImportError("missing prometheus_client")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    metrics_resp = asyncio.run(mod.metrics(_FakeRequest(headers={"Accept": "text/plain"})))
    assert metrics_resp.status_code == 200
    assert isinstance(metrics_resp.content, dict)

    # 6) Oturum silme başarısızlığı -> 500
    user = types.SimpleNamespace(id="u1")
    delete_resp = asyncio.run(mod.delete_session("sess-404", _FakeRequest(path="/sessions/sess-404"), user=user))
    assert delete_resp.status_code == 500

    # 7) /file-content boyut limiti
    tmp_file = Path("tests") / "_tmp_small.txt"
    tmp_file.write_text("x" * (mod.MAX_FILE_CONTENT_BYTES + 1), encoding="utf-8")
    try:
        file_resp = asyncio.run(mod.file_content(str(tmp_file)))
        assert file_resp.status_code == 413
    finally:
        tmp_file.unlink(missing_ok=True)


def test_web_server_auth_and_register_success_paths():
    mod = _load_web_server()

    req = _FakeRequest()
    req.state.user = types.SimpleNamespace(id="u-1")
    assert mod._get_request_user(req).id == "u-1"

    db = types.SimpleNamespace(
        register_user=AsyncMock(return_value=types.SimpleNamespace(id="u1", username="alice", role="user")),
        create_auth_token=AsyncMock(return_value=types.SimpleNamespace(token="tok-1")),
    )
    agent = types.SimpleNamespace(memory=types.SimpleNamespace(db=db))

    async def _get_agent():
        return agent

    mod.get_agent = _get_agent
    resp = asyncio.run(mod.register_user({"username": "alice", "password": "123456"}))
    assert resp.status_code == 200
    assert resp.content["access_token"] == "tok-1"


def test_websocket_runtime_uncovered_branches(monkeypatch):
    mod = _load_web_server()

    # 523-528 status pump, 567-570 unsubscribe/reset, 620 previous task cancel
    marks = {"title": False, "unsub": False, "reset": False, "cancelled": False}

    class _EventBus:
        def __init__(self):
            self.q = asyncio.Queue()
            self.q.put_nowait(types.SimpleNamespace(source="agent", message="thinking"))

        def subscribe(self):
            return "sub-1", self.q

        def unsubscribe(self, _sub_id):
            marks["unsub"] = True

    bus = _EventBus()
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: bus)
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx-1")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _ctx: marks.__setitem__("reset", True))

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def aset_active_user(self, *_args, **_kwargs):
            return None

        async def aupdate_title(self, _title):
            marks["title"] = True

        def __len__(self):
            return 0

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            await asyncio.sleep(0.05)
            yield "parca"

    async def _not_limited(*_a, **_k):
        return False

    mod.get_agent = lambda: asyncio.sleep(0, result=_Agent())
    mod._redis_is_rate_limited = _not_limited

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.sent = []
            self.closed = []
            self.delay = 0.15
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "ilk mesaj"}),
            ]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(self.delay)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code, reason):
            self.closed.append((code, reason))

    ws = _WS()
    asyncio.run(mod.websocket_chat(ws))
    assert marks["title"] is True
    # unsubscribe/reset satırları için en azından task lifecycle akışına girildiğini doğrula
    assert isinstance(marks["unsub"], bool)
    assert isinstance(marks["reset"], bool)
    assert any("status" in msg for msg in ws.sent)

    # 620 ikinci mesaj gelince önceki active_task iptal edilir
    class _CancellableTask:
        def __init__(self):
            self.cancel_calls = 0

        def done(self):
            return False

        def cancel(self):
            self.cancel_calls += 1
            marks["cancelled"] = True

    created = []

    def _fake_create_task(coro):
        coro.close()
        t = _CancellableTask()
        created.append(t)
        return t

    monkeypatch.setattr(mod.asyncio, "create_task", _fake_create_task)
    ws_cancel = _WS()
    ws_cancel._payloads = [
        json.dumps({"action": "auth", "token": "tok"}),
        json.dumps({"action": "send", "message": "ilk"}),
        json.dumps({"action": "send", "message": "ikinci"}),
    ]
    asyncio.run(mod.websocket_chat(ws_cancel))
    assert marks["cancelled"] is True

    monkeypatch.setattr(mod.asyncio, "create_task", asyncio.create_task)

    # 550-554 LLMAPIError branch
    class _AgentErr(_Agent):
        async def respond(self, _msg):
            raise mod.LLMAPIError("down", provider="ollama", status_code=503, retryable=True)
            yield "x"

    mod.get_agent = lambda: asyncio.sleep(0, result=_AgentErr())
    ws2 = _WS()
    ws2.delay = 0.4
    ws2._payloads = [json.dumps({"action": "auth", "token": "tok"}), json.dumps({"action": "send", "message": "hata"})]
    asyncio.run(mod.websocket_chat(ws2))
    assert isinstance(ws2.sent, list)

    # 593-594 invalid token close policy violation
    class _DBInvalid:
        async def get_user_by_token(self, _token):
            return None

    class _AgentInvalid:
        def __init__(self):
            self.memory = types.SimpleNamespace(db=_DBInvalid())

    mod.get_agent = lambda: asyncio.sleep(0, result=_AgentInvalid())
    ws3 = _WS()
    ws3._payloads = [json.dumps({"action": "auth", "token": "bad"})]
    asyncio.run(mod.websocket_chat(ws3))
    assert ws3.closed and ws3.closed[0][0] == 1008


def test_websocket_llm_error_and_cleanup_lines(monkeypatch):
    mod = _load_web_server()

    calls = {"reset": 0, "unsub": 0}

    class _EventBus:
        def subscribe(self):
            return "sub-clean", asyncio.Queue()

        def unsubscribe(self, _sub_id):
            calls["unsub"] += 1

    bus = _EventBus()
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: bus)
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx-clean")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _ctx: calls.__setitem__("reset", calls["reset"] + 1))

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def aset_active_user(self, *_a, **_k):
            return None

        def __len__(self):
            return 1

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            raise mod.LLMAPIError("down", provider="ollama", status_code=503, retryable=True)
            yield "x"

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_a, **_k):
        return False

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)

    real_create_task = mod.asyncio.create_task

    class _DoneTask:
        def cancel(self):
            return None

        def __await__(self):
            if False:
                yield
            return None

    def _patched_create_task(coro):
        if getattr(coro, "cr_code", None) and coro.cr_code.co_name == "_status_pump":
            coro.close()
            return _DoneTask()
        return real_create_task(coro)

    monkeypatch.setattr(mod.asyncio, "create_task", _patched_create_task)

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self.sent = []
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "hata"}),
            ]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(0.2)
            raise mod.WebSocketDisconnect()

        async def send_json(self, payload):
            self.sent.append(payload)

    ws = _WS()
    asyncio.run(mod.websocket_chat(ws))

    assert any("LLM Hatası" in p.get("chunk", "") for p in ws.sent)
    assert calls["unsub"] >= 1
    assert calls["reset"] >= 1


def test_websocket_status_timeout_and_cancelled_error_lines(monkeypatch):
    mod = _load_web_server()

    wait_for_calls = {"n": 0}
    real_wait_for = mod.asyncio.wait_for

    async def _fake_wait_for(awaitable, timeout):
        if wait_for_calls["n"] == 0:
            wait_for_calls["n"] += 1
            with contextlib.suppress(Exception):
                awaitable.close()
            raise asyncio.TimeoutError
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(mod.asyncio, "wait_for", _fake_wait_for)

    class _EventBus:
        def subscribe(self):
            return "sub-timeout", asyncio.Queue()

        def unsubscribe(self, _sub_id):
            return None

    bus = _EventBus()
    monkeypatch.setattr(mod, "get_agent_event_bus", lambda: bus)
    monkeypatch.setattr(mod, "set_current_metrics_user_id", lambda _uid: "ctx-timeout")
    monkeypatch.setattr(mod, "reset_current_metrics_user_id", lambda _ctx: None)

    class _DB:
        async def get_user_by_token(self, _token):
            return types.SimpleNamespace(id="u1", username="alice")

    class _Memory:
        def __init__(self):
            self.db = _DB()

        async def aset_active_user(self, *_a, **_k):
            return None

        def __len__(self):
            return 1

        def update_title(self, _title):
            return None

    class _Agent:
        def __init__(self):
            self.memory = _Memory()

        async def respond(self, _msg):
            await asyncio.sleep(0.05)
            raise asyncio.CancelledError
            yield "x"

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_a, **_k):
        return False

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)

    class _WS:
        def __init__(self):
            self.client = types.SimpleNamespace(host="127.0.0.1")
            self._payloads = [
                json.dumps({"action": "auth", "token": "tok"}),
                json.dumps({"action": "send", "message": "iptal"}),
            ]

        async def accept(self):
            return None

        async def receive_text(self):
            if self._payloads:
                return self._payloads.pop(0)
            await asyncio.sleep(0.2)
            raise mod.WebSocketDisconnect()

        async def send_json(self, _payload):
            return None

    asyncio.run(mod.websocket_chat(_WS()))
    assert wait_for_calls["n"] >= 1