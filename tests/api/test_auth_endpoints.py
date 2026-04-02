from __future__ import annotations

import importlib.util
from types import SimpleNamespace
import sys
import types
import pytest

_HAS_HTTPX = importlib.util.find_spec("httpx") is not None
if not _HAS_HTTPX:
    fake_httpx = types.ModuleType("httpx")

    class ASGITransport:
        def __init__(self, *args, **kwargs) -> None:
            return None

    class AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_args, **_kwargs):
            raise RuntimeError("httpx yok")

        async def post(self, *_args, **_kwargs):
            raise RuntimeError("httpx yok")

    fake_httpx.ASGITransport = ASGITransport
    fake_httpx.AsyncClient = AsyncClient
    sys.modules["httpx"] = fake_httpx

from httpx import ASGITransport, AsyncClient

if importlib.util.find_spec("jwt") is None:
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.encode = lambda payload, *_args, **_kwargs: f"token:{payload.get('sub', '')}"
    fake_jwt.decode = lambda *_args, **_kwargs: {"sub": "stub"}
    sys.modules["jwt"] = fake_jwt

if importlib.util.find_spec("uvicorn") is None or importlib.util.find_spec("fastapi") is None:
    pytest.skip("fastapi/uvicorn stack not installed in test environment", allow_module_level=True)

import web_server

pytestmark = pytest.mark.skipif(not _HAS_HTTPX, reason="httpx not installed in test environment")


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.mark.asyncio
async def test_auth_me_requires_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_redis_is_rate_limited(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _fake_redis_is_rate_limited)

    transport = ASGITransport(app=web_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"] == "Yetkisiz erişim"


@pytest.mark.asyncio
async def test_auth_me_returns_current_user(
    monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    async def _fake_redis_is_rate_limited(*_args, **_kwargs) -> bool:
        return False

    async def _fake_resolve_user_from_token(_agent, _token: str) -> SimpleNamespace:
        return SimpleNamespace(
            id="user-1",
            username="test-user",
            role="user",
            tenant_id="default",
        )

    async def _fake_get_agent() -> SimpleNamespace:
        async def _fake_set_active_user(*_args, **_kwargs) -> None:
            return None

        return SimpleNamespace(
            memory=SimpleNamespace(set_active_user=_fake_set_active_user)
        )

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _fake_redis_is_rate_limited)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve_user_from_token)
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    transport = ASGITransport(app=web_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/auth/me", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "user-1"
    assert body["username"] == "test-user"
    assert body["role"] == "user"


@pytest.mark.asyncio
async def test_admin_stats_requires_admin_role(
    monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    async def _fake_redis_is_rate_limited(*_args, **_kwargs) -> bool:
        return False

    async def _fake_resolve_user_from_token(_agent, _token: str) -> SimpleNamespace:
        return SimpleNamespace(
            id="user-1",
            username="test-user",
            role="user",
            tenant_id="default",
        )

    class _Memory:
        db = SimpleNamespace(get_admin_stats=lambda: {"users": 1})

        async def set_active_user(self, *_args, **_kwargs) -> None:
            return None

    async def _fake_get_agent() -> SimpleNamespace:
        return SimpleNamespace(memory=_Memory())

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _fake_redis_is_rate_limited)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve_user_from_token)
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    transport = ASGITransport(app=web_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin/stats", headers=auth_headers)

    assert response.status_code == 403
    assert "admin" in response.json()["error"].lower()


@pytest.mark.asyncio
async def test_auth_login_returns_401_for_wrong_password(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_agent() -> SimpleNamespace:
        db = SimpleNamespace(authenticate_user=lambda **_kwargs: __import__("asyncio").sleep(0, result=None))
        return SimpleNamespace(memory=SimpleNamespace(db=db))

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    transport = ASGITransport(app=web_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/auth/login", json={"username": "demo", "password": "wrong-pass"})

    assert response.status_code == 401
    assert "şifre hatalı" in response.json()["error"].lower()


@pytest.mark.asyncio
async def test_auth_login_returns_500_when_db_authentication_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raise_auth_error(**_kwargs):
        raise RuntimeError("db connection lost")

    async def _fake_get_agent() -> SimpleNamespace:
        db = SimpleNamespace(authenticate_user=_raise_auth_error)
        return SimpleNamespace(memory=SimpleNamespace(db=db))

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    transport = ASGITransport(app=web_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/auth/login", json={"username": "demo", "password": "secret"})

    assert response.status_code == 500
    assert response.json()["error"] == "Veritabanı hatası nedeniyle giriş yapılamadı"


@pytest.mark.asyncio
async def test_auth_login_returns_422_for_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_redis_is_rate_limited(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _fake_redis_is_rate_limited)

    transport = ASGITransport(app=web_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/login",
            content=b'{"username":"demo","password":"secret"',
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["detail"][0]["type"] in {"json_invalid", "value_error.jsondecode"}
