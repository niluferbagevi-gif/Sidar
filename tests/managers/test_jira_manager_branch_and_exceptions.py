from __future__ import annotations

import importlib.util
import asyncio
import sys
import types

def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("httpx"):
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.AsyncClient = object
    sys.modules["httpx"] = fake_httpx

from managers.jira_manager import JiraManager


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "", content: bytes = b"{}"): 
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.content = content

    def json(self):
        return self._payload


def test_request_returns_unavailable_when_client_not_configured() -> None:
    manager = JiraManager(url="", token="")

    ok, data, err = asyncio.run(manager._request("GET", "issue/ABC-1"))

    assert ok is False
    assert data is None
    assert "mevcut değil" in err


def test_request_handles_http_error_payload(monkeypatch) -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="dev@example.com")

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, method: str, url: str, **kwargs):
            assert method == "GET"
            assert url.endswith("/rest/api/3/issue/ABC-1")
            return _FakeResponse(status_code=401, text="Unauthorized", content=b"bad")

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _FakeAsyncClient)

    ok, data, err = asyncio.run(manager._request("GET", "issue/ABC-1"))

    assert ok is False
    assert data is None
    assert "HTTP 401" in err


def test_transition_issue_posts_matching_transition_id() -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="dev@example.com")
    calls: list[tuple[str, str, dict]] = []

    async def _fake_request(method: str, endpoint: str, **kwargs):
        calls.append((method, endpoint, kwargs))
        if method == "GET":
            return True, {"transitions": [{"id": "11", "name": "In Progress"}]}, ""
        return True, {}, ""

    manager._request = _fake_request  # type: ignore[method-assign]

    ok, err = asyncio.run(manager.transition_issue("ABC-1", "In Progress"))

    assert ok is True
    assert err == ""
    assert calls[1][0] == "POST"
    assert calls[1][1] == "issue/ABC-1/transitions"
    assert calls[1][2]["json"] == {"transition": {"id": "11"}}


def test_request_handles_client_exception(monkeypatch) -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="dev@example.com")

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, method: str, url: str, **kwargs):
            raise RuntimeError("jira timeout")

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _FakeAsyncClient)

    ok, data, err = asyncio.run(manager._request("POST", "issue", json={"fields": {}}))

    assert ok is False
    assert data is None
    assert "jira timeout" in err
