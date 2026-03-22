import asyncio
import sys
import types

from tests.test_web_server_runtime import _FakeRequest, _load_web_server


def test_register_exception_handlers_cover_dict_http_detail_and_unhandled_exception(monkeypatch):
    mod = _load_web_server()

    class _App:
        def __init__(self):
            self.handlers = {}

        def exception_handler(self, exc_type):
            def _decorator(fn):
                self.handlers[exc_type] = fn
                return fn

            return _decorator

    app = _App()
    mod._register_exception_handlers(app)

    http_handler = app.handlers[mod.HTTPException]
    http_exc = mod.HTTPException(status_code=422, detail={"detail": "eksik alan", "hint": "username"})
    http_resp = asyncio.run(http_handler(_FakeRequest(path="/api/login"), http_exc))

    assert http_resp.status_code == 422
    assert http_resp.content == {
        "success": False,
        "detail": "eksik alan",
        "hint": "username",
        "error": "İstek işlenemedi.",
    }

    logged = {}
    monkeypatch.setattr(mod.logger, "exception", lambda *args: logged.setdefault("args", args))

    exc_handler = app.handlers[Exception]
    resp = asyncio.run(exc_handler(_FakeRequest(path="/api/boom"), RuntimeError("patladı")))

    assert logged["args"][1] == "/api/boom"
    assert isinstance(logged["args"][2], RuntimeError)
    assert resp.status_code == 500
    assert resp.content == {
        "success": False,
        "error": "İç sunucu hatası",
        "detail": "patladı",
    }


def test_health_response_returns_degraded_when_agent_health_lookup_fails(monkeypatch):
    mod = _load_web_server()
    warnings = []

    async def _boom():
        raise RuntimeError("health unavailable")

    monkeypatch.setattr(mod, "get_agent", _boom)
    monkeypatch.setattr(mod.logger, "warning", lambda *args: warnings.append(args))

    resp = asyncio.run(mod._health_response())

    assert warnings and warnings[0][1].args[0] == "health unavailable"
    assert resp.status_code == 503
    assert resp.content["status"] == "degraded"
    assert resp.content["error"] == "health_check_failed"
    assert resp.content["detail"] == "health unavailable"


def test_spa_fallback_uses_html_response_when_index_returns_server_error(monkeypatch):
    mod = _load_web_server()

    async def _broken_index():
        return mod.HTMLResponse("broken", status_code=500)

    monkeypatch.setattr(mod, "index", _broken_index)

    reserved = asyncio.run(mod.spa_fallback("webhook/retry"))
    recovered = asyncio.run(mod.spa_fallback("workspace/dashboard"))

    assert reserved.status_code == 404
    assert recovered.status_code == 200
    assert "SPA fallback etkin" in recovered.content


def test_list_child_ollama_pids_skips_non_matching_direct_children(monkeypatch):
    mod = _load_web_server()

    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(mod.os, "name", "posix")
    monkeypatch.setattr(mod.os, "getpid", lambda: 7)
    monkeypatch.setattr(
        mod.subprocess,
        "check_output",
        lambda *a, **k: (
            b"12 7 python python worker.py\n"
            b"13 7 bash bash -lc echo test\n"
            b"14 7 ollama ollama serve\n"
        ),
    )

    assert mod._list_child_ollama_pids() == [14]


def test_async_force_shutdown_without_processes_or_reaped_children_skips_logging(monkeypatch):
    mod = _load_web_server()
    mod._shutdown_cleanup_done = False
    mod.cfg.AI_PROVIDER = "ollama"
    mod.cfg.OLLAMA_FORCE_KILL_ON_SHUTDOWN = True

    log_calls = []

    monkeypatch.setattr(mod, "_list_child_ollama_pids", lambda: [])
    monkeypatch.setattr(mod, "_reap_child_processes_nonblocking", lambda: 0)
    monkeypatch.setattr(mod.logger, "info", lambda *args: log_calls.append(args))

    asyncio.run(mod._async_force_shutdown_local_llm_processes())

    assert mod._shutdown_cleanup_done is True
    assert log_calls == []


def test_github_webhook_unknown_event_returns_success_without_memory_side_effects(monkeypatch):
    mod = _load_web_server()
    mod.cfg.GITHUB_WEBHOOK_SECRET = ""

    adds = []

    async def _add(role, text):
        adds.append((role, text))

    async def _get_agent():
        return types.SimpleNamespace(memory=types.SimpleNamespace(add=_add))

    monkeypatch.setattr(mod, "get_agent", _get_agent)
    monkeypatch.setattr(mod, "_resolve_ci_failure_context", lambda *_a, **_k: {})
    monkeypatch.setattr(mod, "_dispatch_autonomy_trigger", lambda **_k: (_ for _ in ()).throw(AssertionError("should not dispatch")))

    response = asyncio.run(
        mod.github_webhook(
            _FakeRequest(body_bytes=b'{"zen": "keep it logically awesome"}'),
            x_github_event="ping",
            x_hub_signature_256="",
        )
    )

    assert response.status_code == 200
    assert response.content == {"success": True, "event": "ping", "message": "İşlendi"}
    assert adds == []
