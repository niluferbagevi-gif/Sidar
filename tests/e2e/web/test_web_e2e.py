from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

import web_server
from web_server import app


def test_healthz_endpoint_responds_with_structured_payload(monkeypatch) -> None:
    async def _healthy_response(*, require_dependencies: bool = False):
        return web_server.JSONResponse({"status": "ok", "uptime_seconds": 1}, status_code=200)

    monkeypatch.setattr(web_server, "_health_response", _healthy_response)

    client = TestClient(app)
    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    assert "uptime_seconds" in payload


def test_healthz_endpoint_returns_503_when_degraded(monkeypatch) -> None:
    async def _degraded_response(*, require_dependencies: bool = False):
        return web_server.JSONResponse({"status": "degraded", "uptime_seconds": 1}, status_code=503)

    monkeypatch.setattr(web_server, "_health_response", _degraded_response)

    client = TestClient(app)
    response = client.get("/healthz")

    assert response.status_code == 503


def test_root_endpoint_serves_html(monkeypatch, tmp_path: Path) -> None:
    index_file = tmp_path / "index.html"
    index_file.write_text("<html><head></head><body>ok</body></html>", encoding="utf-8")
    monkeypatch.setattr(web_server, "WEB_DIR", tmp_path)

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert response.text


def test_root_endpoint_returns_500_when_react_dist_missing(monkeypatch, tmp_path: Path) -> None:
    missing_dist = tmp_path / "missing-dist"
    monkeypatch.setattr(web_server, "WEB_DIR", missing_dist)

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 500
    assert "text/html" in response.headers.get("content-type", "")
    assert "React dist bulunamadı" in response.text
