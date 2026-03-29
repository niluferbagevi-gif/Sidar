"""
managers/jira_manager.py için birim testleri.
JiraManager: constructor, is_available, disabled paths.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch


def _get_jira():
    if "managers.jira_manager" in sys.modules:
        del sys.modules["managers.jira_manager"]
    import managers.jira_manager as jira
    return jira


# ══════════════════════════════════════════════════════════════
# Constructor
# ══════════════════════════════════════════════════════════════

class TestJiraManagerInit:
    def test_empty_init_not_available(self):
        jira = _get_jira()
        mgr = jira.JiraManager()
        assert mgr.is_available() is False

    def test_no_token_not_available(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="")
        assert mgr.is_available() is False

    def test_no_url_not_available(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="", token="mytoken")
        assert mgr.is_available() is False

    def test_url_and_token_available(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="mytoken")
        assert mgr.is_available() is True

    def test_url_trailing_slash_stripped(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net/", token="tok")
        assert not mgr.url.endswith("/")

    def test_email_sets_basic_auth(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok", email="user@co.com")
        assert mgr._auth == ("user@co.com", "tok")

    def test_bearer_token_when_no_email(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")
        assert "Authorization" in mgr._headers
        assert "Bearer" in mgr._headers["Authorization"]

    def test_default_project_stored(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://co.atlassian.net", token="tok", default_project="PROJ")
        assert mgr.default_project == "PROJ"


# ══════════════════════════════════════════════════════════════
# _request — disabled path
# ══════════════════════════════════════════════════════════════

class TestJiraDisabledPath:
    def test_request_returns_false_when_not_available(self):
        jira = _get_jira()
        mgr = jira.JiraManager()
        ok, body, err = asyncio.run(mgr._request("GET", "issue/TEST-1"))
        assert ok is False
        assert "mevcut değil" in err or "Jira" in err


class _FakeJiraResponse:
    def __init__(self, status_code: int, body=None, text: str = ""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text
        self.content = b"x" if body is not None else b""

    def json(self):
        return self._body


class _FakeJiraAsyncClient:
    def __init__(self, *, response: _FakeJiraResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def request(self, *args, **kwargs):
        return self._response


class TestJiraRequestHttpResponses:
    def test_request_200_returns_success_body(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")
        fake_response = _FakeJiraResponse(200, body={"ok": True}, text="ok")

        with patch(
            "managers.jira_manager.httpx.AsyncClient",
            return_value=_FakeJiraAsyncClient(response=fake_response),
        ):
            ok, body, err = asyncio.run(mgr._request("GET", "issue/TEST-1"))

        assert ok is True
        assert body == {"ok": True}
        assert err == ""

    def test_request_400_returns_http_error(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")
        fake_response = _FakeJiraResponse(400, body=None, text="bad request")

        with patch(
            "managers.jira_manager.httpx.AsyncClient",
            return_value=_FakeJiraAsyncClient(response=fake_response),
        ):
            ok, body, err = asyncio.run(mgr._request("GET", "issue/TEST-1"))

        assert ok is False
        assert body is None
        assert "HTTP 400" in err

    def test_request_404_returns_http_error(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")
        fake_response = _FakeJiraResponse(404, body=None, text="not found")

        with patch(
            "managers.jira_manager.httpx.AsyncClient",
            return_value=_FakeJiraAsyncClient(response=fake_response),
        ):
            ok, body, err = asyncio.run(mgr._request("GET", "issue/UNKNOWN-1"))

        assert ok is False
        assert body is None
        assert "HTTP 404" in err

    def test_request_500_returns_http_error(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")
        fake_response = _FakeJiraResponse(500, body=None, text="server error")

        with patch(
            "managers.jira_manager.httpx.AsyncClient",
            return_value=_FakeJiraAsyncClient(response=fake_response),
        ):
            ok, body, err = asyncio.run(mgr._request("POST", "issue"))

        assert ok is False
        assert body is None
        assert "HTTP 500" in err
