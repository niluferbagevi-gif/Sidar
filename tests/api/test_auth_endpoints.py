from __future__ import annotations

from types import SimpleNamespace
import pytest
from httpx import ASGITransport, AsyncClient

import web_server


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.mark.asyncio
async def test_auth_me_requires_authorization_header() -> None:
    transport = ASGITransport(app=web_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"] == "Yetkisiz erişim"


@pytest.mark.asyncio
async def test_auth_me_returns_current_user(
    monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    async def _fake_resolve_user_from_token(_agent, _token: str) -> SimpleNamespace:
        return SimpleNamespace(
            id="user-1",
            username="test-user",
            role="user",
            tenant_id="default",
        )

    async def _fake_get_agent() -> SimpleNamespace:
        return SimpleNamespace(
            memory=SimpleNamespace(set_active_user=lambda *_args, **_kwargs: None)
        )

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

    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve_user_from_token)
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    transport = ASGITransport(app=web_server.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin/stats", headers=auth_headers)

    assert response.status_code == 403
    assert "admin" in response.json()["error"].lower()
