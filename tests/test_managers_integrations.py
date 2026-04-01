from __future__ import annotations

from types import SimpleNamespace

import pytest

httpx = pytest.importorskip("httpx")

from managers.github_manager import GitHubManager
from managers.jira_manager import JiraManager
from managers.slack_manager import SlackManager


class _FakeResp:
    def __init__(self, status_code: int, payload=None, text: str = "", content: bytes = b"1"):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = content

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_jira_request_handles_200_401_500(monkeypatch):
    jira = JiraManager(url="https://jira.example.com", token="tkn", email="u@example.com")

    responses = [
        _FakeResp(200, payload={"ok": True}),
        _FakeResp(401, text="unauthorized"),
        _FakeResp(500, text="server error"),
    ]

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, **kwargs):
            return responses.pop(0)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    ok1, body1, err1 = await jira._request("GET", "project")
    ok2, body2, err2 = await jira._request("GET", "project")
    ok3, body3, err3 = await jira._request("GET", "project")

    assert ok1 is True and body1["ok"] is True and err1 == ""
    assert ok2 is False and body2 is None and "401" in err2
    assert ok3 is False and body3 is None and "500" in err3


@pytest.mark.asyncio
async def test_slack_webhook_handles_success_and_server_error(monkeypatch):
    slack = SlackManager(token="", webhook_url="https://hooks.slack.com/services/T/B/X")

    responses = [
        _FakeResp(200, text="ok"),
        _FakeResp(500, text="boom"),
    ]

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return responses.pop(0)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    ok1, err1 = await slack.send_webhook(text="hello")
    ok2, err2 = await slack.send_webhook(text="hello")

    assert ok1 is True and err1 == ""
    assert ok2 is False and "500" in err2


def test_github_manager_list_repos_success_and_forbidden(monkeypatch):
    mgr = GitHubManager(token="", require_token=False)

    class _Repo:
        def __init__(self, name):
            self.full_name = name
            self.default_branch = "main"
            self.private = False

    class _User:
        type = "User"

        def get_repos(self, **kwargs):
            return [_Repo("acme/a"), _Repo("acme/b")]

    class _GH:
        def __init__(self):
            self.fail = False

        def get_user(self, owner=None):
            if self.fail:
                exc = RuntimeError("forbidden")
                setattr(exc, "status", 403)
                raise exc
            return _User()

    fake = _GH()
    mgr._gh = fake

    ok, repos = mgr.list_repos(owner="acme", limit=5)
    assert ok is True
    assert len(repos) == 2

    fake.fail = True
    ok2, repos2 = mgr.list_repos(owner="acme", limit=5)
    assert ok2 is False
    assert repos2 == []
