"""Smoke tests for application boot sanity."""

from types import SimpleNamespace

import pytest

from agent.registry import AgentCatalog


def test_boot_agent_catalog_api_available() -> None:
    """Boot sonrası AgentCatalog API'sinin çalıştığını doğrular."""
    specs = AgentCatalog.list_all()
    assert isinstance(specs, list)


def test_boot_agent_catalog_unknown_role_returns_none() -> None:
    """Kayıtlı olmayan rol sorgusunda None dönüldüğünü doğrular."""
    assert AgentCatalog.get("__missing_role__") is None


def test_boot_fastapi_app_healthz_starts_with_mocked_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """FastAPI uygulamasının temel boot akışında çökmeden ayağa kalktığını doğrular."""
    testclient_mod = pytest.importorskip("fastapi.testclient")
    web_server = pytest.importorskip("web_server")
    TestClient = testclient_mod.TestClient

    fake_agent = SimpleNamespace(
        cfg=SimpleNamespace(AI_PROVIDER="ollama"),
        health=SimpleNamespace(get_health_summary=lambda: {"status": "ok", "ollama_online": True}),
    )

    async def _fake_get_agent():
        return fake_agent

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)

    client = TestClient(web_server.app)
    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "uptime_seconds" in payload
