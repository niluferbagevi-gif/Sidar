from __future__ import annotations

import asyncio
import importlib.util
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("fastapi") is None:
    pytest.skip("fastapi not installed in test environment", allow_module_level=True)

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import web_server


def _make_request(path: str, method: str = "GET", auth_header: str | None = None) -> Request:
    headers = []
    if auth_header is not None:
        headers.append((b"authorization", auth_header.encode("utf-8")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "root_path": "",
        "app": web_server.app,
    }
    return Request(scope)


def test_basic_auth_middleware_allows_open_paths_without_token() -> None:
    async def _run() -> None:
        request = _make_request("/health")

        async def _call_next(_request: Request) -> JSONResponse:
            return JSONResponse({"ok": True}, status_code=200)

        response = await web_server.basic_auth_middleware(request, _call_next)
        assert response.status_code == 200

    asyncio.run(_run())


def test_basic_auth_middleware_rejects_missing_or_empty_bearer() -> None:
    async def _run() -> None:
        request_no_header = _make_request("/private")
        request_empty_bearer = _make_request("/private", auth_header="Bearer   ")

        async def _call_next(_request: Request) -> JSONResponse:
            return JSONResponse({"ok": True}, status_code=200)

        response_no_header = await web_server.basic_auth_middleware(request_no_header, _call_next)
        response_empty_bearer = await web_server.basic_auth_middleware(request_empty_bearer, _call_next)

        assert response_no_header.status_code == 401
        assert b"Yetkisiz" in response_no_header.body
        assert response_empty_bearer.status_code == 401
        assert b"Ge\xc3\xa7ersiz token" in response_empty_bearer.body

    asyncio.run(_run())


def test_basic_auth_middleware_rejects_invalid_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        request = _make_request("/private", auth_header="Bearer invalid")

        async def _call_next(_request: Request) -> JSONResponse:
            return JSONResponse({"ok": True}, status_code=200)

        async def _fake_resolve_user(_agent, _token: str):
            return None

        monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve_user)

        response = await web_server.basic_auth_middleware(request, _call_next)

        assert response.status_code == 401
        assert b"Oturum ge\xc3\xa7ersiz" in response.body

    asyncio.run(_run())


def test_basic_auth_middleware_sets_user_and_metrics_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        request = _make_request("/private", auth_header="Bearer valid-token")
        calls: dict[str, object] = {}

        class _MemoryStub:
            async def set_active_user(self, user_id: str, username: str):
                calls["set_active_user"] = (user_id, username)

        async def _fake_get_agent():
            return SimpleNamespace(memory=_MemoryStub())

        async def _fake_resolve_user(_agent, _token: str):
            return SimpleNamespace(id="u-1", username="alice", role="admin", tenant_id="t-1")

        monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
        monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve_user)
        monkeypatch.setattr(web_server, "set_current_metrics_user_id", lambda user_id: f"ctx-{user_id}")
        monkeypatch.setattr(web_server, "reset_current_metrics_user_id", lambda token: calls.setdefault("reset", token))

        async def _call_next(req: Request) -> JSONResponse:
            calls["request_user"] = (req.state.user.id, req.state.user.username)
            return JSONResponse({"ok": True}, status_code=200)

        response = await web_server.basic_auth_middleware(request, _call_next)

        assert response.status_code == 200
        assert calls["set_active_user"] == ("u-1", "alice")
        assert calls["request_user"] == ("u-1", "alice")
        assert calls["reset"] == "ctx-u-1"

    asyncio.run(_run())


def test_require_metrics_access_allows_metrics_token_and_admin() -> None:
    request = _make_request("/metrics", auth_header="Bearer metrics-123")
    user = SimpleNamespace(role="user", username="bob")

    original_cfg = web_server.cfg
    web_server.cfg = SimpleNamespace(METRICS_TOKEN="metrics-123")
    try:
        assert web_server._require_metrics_access(request, user=user) is user
        assert web_server._require_metrics_access(_make_request("/metrics"), user=SimpleNamespace(role="admin", username="ops"))
    finally:
        web_server.cfg = original_cfg


def test_require_metrics_access_raises_for_non_admin_without_token() -> None:
    request = _make_request("/metrics")
    user = SimpleNamespace(role="user", username="bob")

    original_cfg = web_server.cfg
    web_server.cfg = SimpleNamespace(METRICS_TOKEN="secret")
    try:
        with pytest.raises(HTTPException) as exc:
            web_server._require_metrics_access(request, user=user)
        assert exc.value.status_code == 403
    finally:
        web_server.cfg = original_cfg
