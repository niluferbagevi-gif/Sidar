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


def test_init_client_sets_bearer_and_is_available() -> None:
    manager = JiraManager(url="https://jira.example.com/", token=" secret-token ", email="")

    assert manager.is_available() is True
    assert manager._auth is None
    assert manager._headers["Authorization"] == "Bearer secret-token"
    assert manager.url == "https://jira.example.com"


def test_request_success_returns_json_body(monkeypatch) -> None:
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
            return _FakeResponse(
                status_code=200,
                payload={"id": "10001"},
                content=b'{"id":"10001"}',
            )

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _FakeAsyncClient)

    ok, data, err = asyncio.run(manager._request("GET", "issue/ABC-1"))

    assert ok is True
    assert data == {"id": "10001"}
    assert err == ""


def test_request_success_without_content_returns_empty_dict(monkeypatch) -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="dev@example.com")

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, method: str, url: str, **kwargs):
            return _FakeResponse(status_code=204, payload={}, content=b"")

    monkeypatch.setattr("managers.jira_manager.httpx.AsyncClient", _FakeAsyncClient)

    ok, data, err = asyncio.run(manager._request("DELETE", "issue/ABC-1"))

    assert ok is True
    assert data == {}
    assert err == ""


def test_create_get_update_and_add_comment_payloads() -> None:
    manager = JiraManager(
        url="https://jira.example.com",
        token="token",
        email="dev@example.com",
        default_project="PRJ",
    )
    calls: list[tuple[str, str, dict]] = []

    async def _fake_request(method: str, endpoint: str, **kwargs):
        calls.append((method, endpoint, kwargs))
        if endpoint == "issue" and method == "POST":
            return True, {"key": "PRJ-12"}, ""
        if endpoint == "issue/PRJ-12" and method == "GET":
            return True, {"key": "PRJ-12", "fields": {}}, ""
        if endpoint == "issue/PRJ-12" and method == "PUT":
            return True, None, ""
        if endpoint == "issue/PRJ-12/comment" and method == "POST":
            return True, {"id": "5001"}, ""
        return False, None, "unexpected"

    manager._request = _fake_request  # type: ignore[method-assign]

    ok_create, issue, err_create = asyncio.run(
        manager.create_issue(
            summary="Örnek hata",
            description="Detaylı açıklama",
            labels=["backend", "urgent"],
            assignee_account_id="acc-123",
        )
    )
    ok_get, issue_detail, err_get = asyncio.run(manager.get_issue("PRJ-12"))
    ok_update, err_update = asyncio.run(manager.update_issue("PRJ-12", {"summary": "Yeni özet"}))
    ok_comment, comment_result, err_comment = asyncio.run(
        manager.add_comment("PRJ-12", "İlk inceleme tamamlandı")
    )

    assert ok_create is True
    assert issue == {"key": "PRJ-12"}
    assert err_create == ""
    create_payload = calls[0][2]["json"]["fields"]
    assert create_payload["project"] == {"key": "PRJ"}
    assert create_payload["summary"] == "Örnek hata"
    assert create_payload["issuetype"] == {"name": "Task"}
    assert create_payload["priority"] == {"name": "Medium"}
    assert create_payload["labels"] == ["backend", "urgent"]
    assert create_payload["assignee"] == {"accountId": "acc-123"}
    assert create_payload["description"]["content"][0]["content"][0]["text"] == "Detaylı açıklama"

    assert ok_get is True
    assert issue_detail["key"] == "PRJ-12"
    assert err_get == ""

    assert ok_update is True
    assert err_update == ""
    assert calls[2][2]["json"] == {"fields": {"summary": "Yeni özet"}}

    assert ok_comment is True
    assert comment_result == {"id": "5001"}
    assert err_comment == ""
    comment_payload = calls[3][2]["json"]
    assert comment_payload["body"]["content"][0]["content"][0]["text"] == "İlk inceleme tamamlandı"


def test_transition_issue_returns_error_when_fetch_transitions_fails() -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="dev@example.com")

    async def _fake_request(method: str, endpoint: str, **kwargs):
        return False, None, "transition fetch failed"

    manager._request = _fake_request  # type: ignore[method-assign]

    ok, err = asyncio.run(manager.transition_issue("ABC-1", "Done"))

    assert ok is False
    assert err == "transition fetch failed"


def test_search_issues_returns_error_when_request_fails() -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="dev@example.com")

    async def _fake_request(method: str, endpoint: str, **kwargs):
        return False, None, "search failed"

    manager._request = _fake_request  # type: ignore[method-assign]

    ok, issues, err = asyncio.run(manager.search_issues("project = PRJ"))

    assert ok is False
    assert issues == []
    assert err == "search failed"


def test_list_projects_success_and_failure_paths() -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="dev@example.com")

    async def _ok_request(method: str, endpoint: str, **kwargs):
        assert method == "GET"
        assert endpoint == "project"
        return True, [{"key": "PRJ", "name": "Proje", "id": "101"}], ""

    manager._request = _ok_request  # type: ignore[method-assign]
    ok, projects, err = asyncio.run(manager.list_projects())
    assert ok is True
    assert err == ""
    assert projects == [{"key": "PRJ", "name": "Proje", "id": "101"}]

    async def _fail_request(method: str, endpoint: str, **kwargs):
        return False, None, "project list failed"

    manager._request = _fail_request  # type: ignore[method-assign]
    ok, projects, err = asyncio.run(manager.list_projects())
    assert ok is False
    assert projects == []
    assert err == "project list failed"


def test_get_project_statuses_unique_and_failure_paths() -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="dev@example.com")

    async def _ok_request(method: str, endpoint: str, **kwargs):
        assert endpoint == "project/PRJ/statuses"
        return True, [
            {"statuses": [{"name": "To Do"}, {"name": "In Progress"}, {"name": "To Do"}]},
            {"statuses": [{"name": "Done"}, {"name": ""}]},
        ], ""

    manager._request = _ok_request  # type: ignore[method-assign]
    ok, statuses, err = asyncio.run(manager.get_project_statuses("PRJ"))
    assert ok is True
    assert err == ""
    assert statuses == ["To Do", "In Progress", "Done"]

    async def _fail_request(method: str, endpoint: str, **kwargs):
        return False, None, "status fetch failed"

    manager._request = _fail_request  # type: ignore[method-assign]
    ok, statuses, err = asyncio.run(manager.get_project_statuses("PRJ"))
    assert ok is False
    assert statuses == []
    assert err == "status fetch failed"
