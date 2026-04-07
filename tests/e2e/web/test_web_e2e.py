import pytest

fastapi = pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient

from web_server import app


def test_healthz_endpoint_responds_with_structured_payload() -> None:
    client = TestClient(app)

    response = client.get("/healthz")

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
