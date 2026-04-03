from __future__ import annotations

import importlib.util
import subprocess
from types import SimpleNamespace
from typing import Iterator

import pytest

if importlib.util.find_spec("fastapi") is None:
    pytest.skip("fastapi not installed in test environment", allow_module_level=True)

from fastapi.testclient import TestClient

import web_server


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    class _MemoryStub:
        async def set_active_user(self, _id, _usr):
            return None

    class _AgentStub:
        def __init__(self) -> None:
            self.memory = _MemoryStub()

    async def _fake_get_agent():
        return _AgentStub()

    async def _no_rate_limit(*_args, **_kwargs) -> bool:
        return False

    async def _mock_user_from_token(*_args, **_kwargs):
        return SimpleNamespace(id="u1", username="test_user", role="user", tenant_id="default")

    monkeypatch.setattr(web_server, "get_agent", _fake_get_agent)
    monkeypatch.setattr(web_server, "_redis_is_rate_limited", _no_rate_limit)
    monkeypatch.setattr(web_server, "_resolve_user_from_token", _mock_user_from_token)
    with TestClient(web_server.app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_auth_register_returns_422_for_short_username(client: TestClient) -> None:
    response = client.post("/auth/register", json={"username": "ab", "password": "123456", "tenant_id": "t1"})

    assert response.status_code == 422
    body = response.json()
    assert "detail" in body


def test_set_branch_rejects_invalid_branch_name(client: TestClient) -> None:
    response = client.post("/set-branch", json={"branch": "bad branch name"}, headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert "Geçersiz dal adı" in response.json()["error"]


def test_set_branch_returns_400_when_checkout_fails(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    async def _raise_called_process_error(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, ["git", "checkout", "feature/x"], output=b"checkout failed")

    monkeypatch.setattr("web_server.asyncio.to_thread", _raise_called_process_error)

    response = client.post("/set-branch", json={"branch": "feature/x"}, headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert "checkout failed" in response.json()["error"]


def test_file_content_blocks_path_traversal(client: TestClient) -> None:
    response = client.get("/file-content", params={"path": "../etc/passwd"})

    assert response.status_code == 403
    assert "proje dışına çıkılamaz" in response.json()["error"]


def test_git_branches_returns_500_on_unhandled_error(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    async def _raise_runtime_error(*_args, **_kwargs):
        raise RuntimeError("simulated git failure")

    monkeypatch.setattr("web_server.asyncio.to_thread", _raise_runtime_error)

    response = client.get("/git-branches", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"] == "İç sunucu hatası"
    assert "simulated git failure" in body["detail"]
