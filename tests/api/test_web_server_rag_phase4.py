from __future__ import annotations

import importlib.util
from io import BytesIO
from types import SimpleNamespace
from typing import Iterator

import pytest

if importlib.util.find_spec("fastapi") is None:
    pytest.skip("fastapi not installed", allow_module_level=True)

from fastapi.testclient import TestClient

import web_server


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    class _Memory:
        active_session_id = "s1"

        async def set_active_user(self, _id, _usr):
            return None

    class _Docs:
        async def add_document_from_url(self, url, title="", session_id="global"):
            return True, f"ok:{url}:{title}:{session_id}"

        def add_document_from_file(self, path, title, tags, session_id):
            return True, f"file:{path}:{title}:{session_id}"

        def delete_document(self, doc_id, session_id):
            return "✓ deleted"

        def get_index_info(self, session_id="global"):
            return [{"id": "d1", "session_id": session_id}]

    class _Agent:
        def __init__(self):
            self.memory = _Memory()
            self.docs = _Docs()

    async def _get_agent():
        return _Agent()

    async def _not_limited(*_args, **_kwargs):
        return False

    async def _resolve_user(*_args, **_kwargs):
        return SimpleNamespace(id="u1", username="user", role="user", tenant_id="default")

    monkeypatch.setattr(web_server, "get_agent", _get_agent)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _not_limited)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _resolve_user)

    with TestClient(web_server.app, raise_server_exceptions=False) as test_client:
        yield test_client


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def test_rag_add_file_validation_errors(client: TestClient) -> None:
    empty = client.post("/rag/add-file", json={}, headers=AUTH_HEADERS)
    assert empty.status_code == 400
    assert "Dosya yolu boş" in empty.json()["error"]

    traversal = client.post("/rag/add-file", json={"path": "../../etc/passwd"}, headers=AUTH_HEADERS)
    assert traversal.status_code == 403
    assert "proje dışına çıkılamaz" in traversal.json()["error"]


def test_rag_add_file_invalid_json_results_500(client: TestClient) -> None:
    response = client.post("/rag/add-file", data="not-json", headers={"Content-Type": "application/json", **AUTH_HEADERS})
    assert response.status_code == 500


def test_rag_add_url_empty_and_success(client: TestClient) -> None:
    empty = client.post("/rag/add-url", json={}, headers=AUTH_HEADERS)
    assert empty.status_code == 400
    assert "URL boş" in empty.json()["error"]

    ok = client.post("/rag/add-url", json={"url": "https://example.com/doc", "title": "Doc"}, headers=AUTH_HEADERS)
    assert ok.status_code == 200
    assert ok.json()["success"] is True


def test_rag_delete_and_list_docs(client: TestClient) -> None:
    listed = client.get("/rag/docs", headers=AUTH_HEADERS)
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    deleted = client.delete("/rag/docs/doc-1", headers=AUTH_HEADERS)
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True


def test_rag_upload_too_large_returns_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_server.Config, "MAX_RAG_UPLOAD_BYTES", 5)

    files = {"file": ("big.txt", BytesIO(b"123456789"), "text/plain")}
    response = client.post("/api/rag/upload", files=files, headers=AUTH_HEADERS)

    assert response.status_code == 413
    assert "Dosya çok büyük" in response.json()["detail"]
