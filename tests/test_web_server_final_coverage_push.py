import asyncio
import json
import sys
import types

from tests.test_web_server_runtime import _FakeRequest, _load_web_server


def test_get_jwt_secret_returns_configured_value_without_fallback(monkeypatch):
    mod = _load_web_server()

    critical_logs = []
    monkeypatch.setattr(mod.cfg, "JWT_SECRET_KEY", "prod-secret", raising=False)
    monkeypatch.setattr(mod.logger, "critical", lambda msg, *args: critical_logs.append(msg % args if args else msg))

    assert mod._get_jwt_secret() == "prod-secret"
    assert critical_logs == []


def test_install_marketplace_plugin_can_skip_persisted_state(monkeypatch, tmp_path):
    mod = _load_web_server()
    source_path = tmp_path / "plugin_agent.py"
    source_path.write_text("class DemoAgent:\n    pass\n", encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "_get_plugin_marketplace_entry",
        lambda plugin_id: {
            "plugin_id": plugin_id,
            "name": "Demo",
            "summary": "demo",
            "description": "demo plugin",
            "category": "tests",
            "role_name": "demo-role",
            "class_name": "DemoAgent",
            "capabilities": ["demo"],
            "version": "1.0.0",
            "entrypoint": str(source_path),
        },
    )
    monkeypatch.setattr(mod.AgentRegistry, "unregister", lambda _role: None)
    monkeypatch.setattr(
        mod,
        "_register_plugin_agent",
        lambda **kwargs: {"role_name": kwargs["role_name"], "version": kwargs["version"]},
    )
    monkeypatch.setattr(mod, "_serialize_marketplace_plugin", lambda plugin_id: {"plugin_id": plugin_id, "installed": False})

    writes = []
    monkeypatch.setattr(mod, "_write_plugin_marketplace_state", lambda state: writes.append(state))

    result = mod._install_marketplace_plugin("demo-plugin", persist=False)

    assert result["success"] is True
    assert result["plugin"] == {"plugin_id": "demo-plugin", "installed": False}
    assert writes == []


def test_get_redis_reuses_client_initialized_inside_lock(monkeypatch):
    mod = _load_web_server()
    existing_client = object()
    mod._redis_client = None

    class _Lock:
        async def __aenter__(self):
            mod._redis_client = existing_client
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    from_url_calls = []
    monkeypatch.setattr(mod, "_redis_lock", _Lock())
    monkeypatch.setattr(
        mod.Redis,
        "from_url",
        classmethod(lambda cls, *_args, **_kwargs: from_url_calls.append(True) or cls()),
    )

    assert asyncio.run(mod._get_redis()) is existing_client
    assert from_url_calls == []


def test_get_client_ip_falls_back_to_direct_ip_when_proxy_headers_are_blank():
    mod = _load_web_server()
    original = list(mod.Config.TRUSTED_PROXIES)
    mod.Config.TRUSTED_PROXIES = ["127.0.0.1"]
    try:
        request = _FakeRequest(
            headers={"X-Forwarded-For": "   ", "X-Real-IP": ""},
            host="127.0.0.1",
        )
        assert mod._get_client_ip(request) == "127.0.0.1"
    finally:
        mod.Config.TRUSTED_PROXIES = original


def test_rate_limit_middleware_allows_non_limited_chat_and_non_io_get(monkeypatch):
    mod = _load_web_server()

    calls = []

    async def _not_limited(bucket, client_ip, limit, window):
        calls.append((bucket, client_ip, limit, window))
        return False

    async def _next(_request):
        return "ok"

    monkeypatch.setattr(mod, "_redis_is_rate_limited", _not_limited)

    chat_req = _FakeRequest(path="/ws/chat", method="GET")
    normal_get_req = _FakeRequest(path="/healthz", method="GET")

    assert asyncio.run(mod.rate_limit_middleware(chat_req, _next)) == "ok"
    assert asyncio.run(mod.rate_limit_middleware(normal_get_req, _next)) == "ok"
    assert calls[0][0] == "chat"
    assert len(calls) == 1


def test_set_level_endpoint_awaits_coroutine_result_from_background_thread(monkeypatch):
    mod = _load_web_server()

    async def _async_result():
        return "async-level-updated"

    agent = types.SimpleNamespace(
        set_access_level=lambda level: _async_result(),
        security=types.SimpleNamespace(level_name="full"),
    )

    monkeypatch.setattr(mod, "get_agent", lambda: asyncio.sleep(0, result=agent))

    response = asyncio.run(mod.set_level_endpoint(_FakeRequest(json_body={"level": "full"})))

    assert response.status_code == 200
    assert response.content["message"] == "async-level-updated"
    assert response.content["current_level"] == "full"


def test_github_repos_preserves_explicit_owner_and_sorts_without_query(monkeypatch):
    mod = _load_web_server()

    class _Github:
        repo_name = "acme/internal"

        def list_repos(self, owner, limit):
            assert owner == "explicit-owner"
            assert limit == 200
            return True, [
                {"full_name": "explicit-owner/zeta"},
                {"full_name": "explicit-owner/alpha"},
            ]

    monkeypatch.setattr(mod, "get_agent", lambda: asyncio.sleep(0, result=types.SimpleNamespace(github=_Github())))

    response = asyncio.run(mod.github_repos(owner="explicit-owner", q=""))

    assert response.status_code == 200
    assert [repo["full_name"] for repo in response.content["repos"]] == [
        "explicit-owner/alpha",
        "explicit-owner/zeta",
    ]
    assert response.content["owner"] == "explicit-owner"


def test_github_webhook_skips_autonomy_dispatch_when_event_webhooks_are_disabled(monkeypatch):
    mod = _load_web_server()
    mod.cfg.ENABLE_EVENT_WEBHOOKS = False

    adds = []

    class _Memory:
        async def add(self, role, message):
            adds.append((role, message))

    monkeypatch.setattr(mod, "get_agent", lambda: asyncio.sleep(0, result=types.SimpleNamespace(memory=_Memory())))
    monkeypatch.setattr(
        mod,
        "_dispatch_autonomy_trigger",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("dispatch should not run")),
    )

    payload = {"action": "opened", "issue": {"number": 7, "title": "Coverage"}}
    response = asyncio.run(
        mod.github_webhook(
            _FakeRequest(body_bytes=json.dumps(payload).encode("utf-8")),
            x_github_event="issues",
            x_hub_signature_256="",
        )
    )

    assert response.status_code == 200
    assert len(adds) == 2


def test_main_skips_asyncio_run_when_initialize_result_is_not_awaitable(monkeypatch):
    mod = _load_web_server()
    observed = {"asyncio_run": 0, "uvicorn": None}

    class _Agent:
        VERSION = "1.2.3"

        def __init__(self, cfg):
            self.cfg = cfg

        def initialize(self):
            return "already-initialized"

    monkeypatch.setattr(mod, "SidarAgent", _Agent)
    monkeypatch.setattr(mod.uvicorn, "run", lambda app, host, port, log_level: observed.__setitem__("uvicorn", (app, host, port, log_level)))
    monkeypatch.setattr(mod.asyncio, "run", lambda coro: observed.__setitem__("asyncio_run", observed["asyncio_run"] + 1))
    monkeypatch.setattr(sys, "argv", ["web_server.py", "--host", "127.0.0.1", "--port", "9000"])

    mod.main()

    assert observed["asyncio_run"] == 0
    assert observed["uvicorn"] == (mod.app, "127.0.0.1", 9000, "info")