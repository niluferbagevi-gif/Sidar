from __future__ import annotations

import asyncio
import importlib.machinery
import sys
import types

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    fake_httpx = types.ModuleType("httpx")

    class AsyncClient:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.AsyncClient = AsyncClient
    fake_httpx.__spec__ = importlib.machinery.ModuleSpec("httpx", loader=None)
    sys.modules["httpx"] = fake_httpx

from managers.jira_manager import JiraManager


def test_create_issue_requires_project_key() -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="user@example.com")

    ok, issue, err = asyncio.run(manager.create_issue(summary="Bug"))

    assert ok is False
    assert issue == {}
    assert "Proje anahtarı" in err


def test_transition_issue_returns_available_names_when_missing() -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="user@example.com")

    async def _fake_request(method: str, endpoint: str, **kwargs):
        if endpoint.endswith("/transitions") and method == "GET":
            return True, {"transitions": [{"id": "1", "name": "To Do"}, {"id": "2", "name": "Done"}]}, ""
        return True, {}, ""

    manager._request = _fake_request  # type: ignore[method-assign]
    ok, err = asyncio.run(manager.transition_issue("PROJ-1", "In Progress"))

    assert ok is False
    assert "Geçiş bulunamadı" in err
    assert "To Do" in err and "Done" in err


def test_search_issues_simplifies_fields() -> None:
    manager = JiraManager(url="https://jira.example.com", token="token", email="user@example.com")

    async def _fake_request(method: str, endpoint: str, **kwargs):
        assert method == "GET"
        assert endpoint == "search"
        return True, {
            "issues": [
                {
                    "key": "PROJ-42",
                    "fields": {
                        "summary": "Login bug",
                        "status": {"name": "To Do"},
                        "assignee": {"displayName": "Ada"},
                        "priority": {"name": "High"},
                        "issuetype": {"name": "Bug"},
                    },
                }
            ]
        }, ""

    manager._request = _fake_request  # type: ignore[method-assign]
    ok, issues, err = asyncio.run(manager.search_issues("project=PROJ", max_results=1000))

    assert ok is True
    assert err == ""
    assert issues[0]["key"] == "PROJ-42"
    assert issues[0]["type"] == "Bug"
