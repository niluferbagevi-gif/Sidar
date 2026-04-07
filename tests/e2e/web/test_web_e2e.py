import pytest
from types import SimpleNamespace

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from web_server import app
import web_server


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer e2e-test-token"}


def test_healthz_endpoint_responds_with_structured_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_resolve_user_from_token(_agent, token: str):
        if token == "e2e-test-token":
            return SimpleNamespace(id="u-e2e", username="e2e-user", role="user")
        return None

    async def _fake_set_active_user(*_args, **_kwargs):
        return None

    async def _fake_get_agent():
        return SimpleNamespace(memory=SimpleNamespace(set_active_user=_fake_set_active_user))

    monkeypatch.setattr(web_server, "_resolve_user_from_token", _fake_resolve_user_from_token)
    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    client = TestClient(app)

    response = client.get("/healthz", headers=_auth_headers())

    assert response.status_code in {200, 503}
    payload = response.json()
    assert isinstance(payload, dict)
    assert "uptime_seconds" in payload


def test_root_endpoint_serves_html_or_clear_build_error_message() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code in {200, 500}
    assert "text/html" in response.headers.get("content-type", "")

    body = response.text
    assert body
    if response.status_code == 500:
        assert "React dist bulunamadı" in body
