from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import web_server


class _Req:
    def __init__(self, *, path: str, method: str = "GET", client_ip: str = "10.0.0.1", headers: dict[str, str] | None = None):
        self.url = SimpleNamespace(path=path)
        self.method = method
        self.client = SimpleNamespace(host=client_ip)
        self.headers = headers or {}


def test_serialize_marketplace_plugin_includes_registry_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plugin_file = tmp_path / "demo_agent.py"
    plugin_file.write_text("class X: pass", encoding="utf-8")

    monkeypatch.setattr(
        web_server,
        "PLUGIN_MARKETPLACE_CATALOG",
        {
            "demo": {
                "plugin_id": "demo",
                "name": "Demo",
                "summary": "S",
                "description": "Demo plugin",
                "category": "Testing",
                "role_name": "demo_role",
                "class_name": "DemoAgent",
                "capabilities": ["a"],
                "version": "1.2.3",
                "entrypoint": plugin_file,
            }
        },
    )
    monkeypatch.setattr(
        web_server.AgentRegistry,
        "get",
        lambda _role: SimpleNamespace(
            role_name="demo_role",
            description="live description",
            capabilities=["x", "y"],
            version="9.9.9",
            is_builtin=False,
        ),
    )

    payload = web_server._serialize_marketplace_plugin(
        "demo",
        installed_state={"installed_at": "2026-01-01T00:00:00+00:00", "last_reloaded_at": "2026-01-02T00:00:00+00:00"},
    )

    assert payload["installed"] is True
    assert payload["entrypoint_exists"] is True
    assert payload["live_registered"] is True
    assert payload["agent"]["version"] == "9.9.9"


def test_install_marketplace_plugin_requires_existing_entrypoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.py"
    monkeypatch.setattr(
        web_server,
        "PLUGIN_MARKETPLACE_CATALOG",
        {
            "demo": {
                "plugin_id": "demo",
                "name": "Demo",
                "summary": "S",
                "description": "D",
                "category": "C",
                "role_name": "demo_role",
                "class_name": "DemoAgent",
                "capabilities": [],
                "version": "1.0.0",
                "entrypoint": missing,
            }
        },
    )

    with pytest.raises(web_server.HTTPException) as exc:
        web_server._install_marketplace_plugin("demo")

    assert exc.value.status_code == 500
    assert "Plugin kaynağı bulunamadı" in str(exc.value.detail)


def test_reload_persisted_marketplace_plugins_ignores_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server, "PLUGIN_MARKETPLACE_CATALOG", {"ok": {"plugin_id": "ok"}, "bad": {"plugin_id": "bad"}})
    monkeypatch.setattr(web_server, "_read_plugin_marketplace_state", lambda: {"ok": {}, "bad": {}, "ghost": {}})

    def _install(plugin_id: str):
        if plugin_id == "bad":
            raise web_server.HTTPException(status_code=400, detail="boom")
        return {"success": True, "plugin": plugin_id}

    monkeypatch.setattr(web_server, "_install_marketplace_plugin", _install)

    reloaded = web_server._reload_persisted_marketplace_plugins()

    assert reloaded == [{"success": True, "plugin": "ok"}]


def test_get_client_ip_prefers_forwarded_for_only_for_trusted_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server.Config, "TRUSTED_PROXIES", {"127.0.0.1"})

    trusted_req = _Req(path="/x", client_ip="127.0.0.1", headers={"X-Forwarded-For": "203.0.113.10, 10.0.0.2"})
    untrusted_req = _Req(path="/x", client_ip="198.51.100.5", headers={"X-Forwarded-For": "203.0.113.20"})

    assert web_server._get_client_ip(trusted_req) == "203.0.113.10"
    assert web_server._get_client_ip(untrusted_req) == "198.51.100.5"


@pytest.mark.asyncio
async def test_ddos_rate_limit_middleware_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def _next(_req):
        calls.append("next")
        return "ok"

    async def _limited(*_args, **_kwargs) -> bool:
        return True

    async def _not_limited(*_args, **_kwargs) -> bool:
        return False

    # static asset path bypasses limiter
    bypass_req = _Req(path="/static/app.js")
    result = await web_server.ddos_rate_limit_middleware(bypass_req, _next)
    assert result == "ok"
    assert calls == ["next"]

    # limited path returns 429 response
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _limited)
    blocked = await web_server.ddos_rate_limit_middleware(_Req(path="/api/x"), _next)
    assert blocked.status_code == 429

    # non-limited path passes through
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _not_limited)
    allowed = await web_server.ddos_rate_limit_middleware(_Req(path="/api/y"), _next)
    assert allowed == "ok"


@pytest.mark.asyncio
async def test_rate_limit_middleware_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _next(_req):
        return "ok"

    async def _limited(*_args, **_kwargs) -> bool:
        return True

    async def _not_limited(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _limited)

    ws_block = await web_server.rate_limit_middleware(_Req(path="/ws/chat"), _next)
    post_block = await web_server.rate_limit_middleware(_Req(path="/api/item", method="POST"), _next)

    assert ws_block.status_code == 429
    assert post_block.status_code == 429

    monkeypatch.setattr(web_server, "_RATE_GET_IO_PATHS", ["/file-content"])
    get_block = await web_server.rate_limit_middleware(_Req(path="/file-content", method="GET"), _next)
    assert get_block.status_code == 429

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _not_limited)
    allowed = await web_server.rate_limit_middleware(_Req(path="/health", method="GET"), _next)
    assert allowed == "ok"
