from pathlib import Path

import pytest

TestClient = pytest.importorskip("fastapi.testclient").TestClient

import web_server
from web_server import app


def test_healthz_endpoint_returns_http_response() -> None:
    client = TestClient(app)
    response = client.get("/healthz")

    assert response.status_code in {200, 503}
    payload = response.json()
    assert isinstance(payload, dict)
    assert "uptime_seconds" in payload


def test_metrics_token_authenticates_through_full_middleware_chain(monkeypatch) -> None:
    monkeypatch.setattr(web_server.cfg, "METRICS_TOKEN", "integration-metrics-token")
    client = TestClient(app)

    response = client.get(
        "/metrics/llm", headers={"Authorization": "Bearer integration-metrics-token"}
    )

    assert response.status_code == 200
    assert "totals" in response.json()

    denied = client.get(
        "/admin/stats", headers={"Authorization": "Bearer integration-metrics-token"}
    )
    assert denied.status_code == 401


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
