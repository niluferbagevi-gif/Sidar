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

    def test_request_401_returns_invalid_token_error(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="invalid-token")
        fake_response = _FakeJiraResponse(401, body=None, text="Unauthorized")

        with patch(
            "managers.jira_manager.httpx.AsyncClient",
            return_value=_FakeJiraAsyncClient(response=fake_response),
        ):
            ok, body, err = asyncio.run(mgr._request("GET", "issue/TEST-1"))

        assert ok is False
        assert body is None
        assert "HTTP 401" in err

    def test_request_429_returns_rate_limit_error(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")
        fake_response = _FakeJiraResponse(429, body=None, text="rate limit")

        with patch(
            "managers.jira_manager.httpx.AsyncClient",
            return_value=_FakeJiraAsyncClient(response=fake_response),
        ):
            ok, body, err = asyncio.run(mgr._request("GET", "search"))

        assert ok is False
        assert body is None
        assert "HTTP 429" in err

    def test_request_timeout_exception_returns_error_text(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        class _RaisingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, *_args, **_kwargs):
                raise TimeoutError("request timeout")

        with patch("managers.jira_manager.httpx.AsyncClient", return_value=_RaisingClient()):
            ok, body, err = asyncio.run(mgr._request("GET", "issue/TEST-1"))

        assert ok is False
        assert body is None
        assert "timeout" in err.lower()

    def test_request_permission_denied_exception_returns_error_text(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        class _RaisingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def request(self, *_args, **_kwargs):
                raise PermissionError("access denied")

        with patch("managers.jira_manager.httpx.AsyncClient", return_value=_RaisingClient()):
            ok, body, err = asyncio.run(mgr._request("GET", "issue/TEST-1"))

        assert ok is False
        assert body is None
        assert "access denied" in err.lower()


class TestJiraTransitionIssue:
    def test_transition_issue_returns_error_when_transition_not_found(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(method, endpoint, **kwargs):
            if method == "GET":
                return True, {"transitions": [{"id": "31", "name": "In Progress"}]}, ""
            return True, {}, ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, err = asyncio.run(mgr.transition_issue("TEST-1", "Done"))
        assert ok is False
        assert "Geçiş bulunamadı" in err

    def test_transition_issue_posts_transition_when_found(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")
        calls = []

        async def _fake_request(method, endpoint, **kwargs):
            calls.append((method, endpoint, kwargs))
            if method == "GET":
                return True, {"transitions": [{"id": "41", "name": "Done"}]}, ""
            return True, {}, ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, err = asyncio.run(mgr.transition_issue("TEST-2", "Done"))
        assert ok is True
        assert err == ""
        assert any(call[0] == "POST" and "transitions" in call[1] for call in calls)

    def test_transition_issue_graceful_when_transition_list_api_fails(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="bad-token")

        async def _fake_request(method, endpoint, **kwargs):
            if method == "GET":
                return False, None, "HTTP 401: Unauthorized"
            return True, {}, ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, err = asyncio.run(mgr.transition_issue("TEST-9", "Done"))
        assert ok is False
        assert "401" in err


class TestJiraProjectListGracefulDegradation:
    def test_list_projects_returns_empty_on_api_failure(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(_method, _endpoint, **_kwargs):
            return False, None, "HTTP 500: upstream down"

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, projects, err = asyncio.run(mgr.list_projects())
        assert ok is False
        assert projects == []
        assert "500" in err


class TestJiraIssueOperations:
    def test_create_issue_uses_default_project(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok", default_project="PROJ")

        async def _fake_request(method, endpoint, **kwargs):
            assert method == "POST"
            assert endpoint == "issue"
            fields = kwargs["json"]["fields"]
            assert fields["project"]["key"] == "PROJ"
            return True, {"key": "PROJ-1"}, ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, issue, err = asyncio.run(mgr.create_issue(summary="Bug bulundu"))
        assert ok is True
        assert issue["key"] == "PROJ-1"
        assert err == ""

    def test_create_issue_requires_project(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")
        ok, issue, err = asyncio.run(mgr.create_issue(summary="Bug bulundu"))
        assert ok is False
        assert issue == {}
        assert "Proje anahtarı" in err

    def test_get_issue_returns_empty_dict_when_data_none(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(_method, _endpoint, **_kwargs):
            return True, None, ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, issue, err = asyncio.run(mgr.get_issue("PROJ-2"))
        assert ok is True
        assert issue == {}
        assert err == ""

    def test_update_issue_returns_error_from_request(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(_method, _endpoint, **_kwargs):
            return False, None, "HTTP 400"

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, err = asyncio.run(mgr.update_issue("PROJ-2", {"summary": "x"}))
        assert ok is False
        assert "400" in err

    def test_add_comment_returns_empty_dict_when_none(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(_method, _endpoint, **_kwargs):
            return True, None, ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, body, err = asyncio.run(mgr.add_comment("PROJ-2", "yorum"))
        assert ok is True
        assert body == {}
        assert err == ""


class TestJiraSearchAndStatuses:
    def test_search_issues_simplifies_fields(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(_method, _endpoint, **_kwargs):
            return True, {
                "issues": [
                    {
                        "key": "PROJ-3",
                        "fields": {
                            "summary": "Deneme",
                            "status": {"name": "To Do"},
                            "assignee": {"displayName": "Ada"},
                            "priority": {"name": "High"},
                            "issuetype": {"name": "Bug"},
                        },
                    }
                ]
            }, ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, issues, err = asyncio.run(mgr.search_issues("project = PROJ", max_results=500))
        assert ok is True
        assert issues[0]["key"] == "PROJ-3"
        assert issues[0]["assignee"] == "Ada"
        assert err == ""

    def test_search_issues_propagates_failure(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(_method, _endpoint, **_kwargs):
            return False, None, "HTTP 429"

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, issues, err = asyncio.run(mgr.search_issues("project = PROJ"))
        assert ok is False
        assert issues == []
        assert "429" in err

    def test_get_project_statuses_deduplicates_names(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(_method, _endpoint, **_kwargs):
            return True, [
                {"statuses": [{"name": "To Do"}, {"name": "Done"}]},
                {"statuses": [{"name": "Done"}, {"name": "In Progress"}]},
            ], ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, statuses, err = asyncio.run(mgr.get_project_statuses("PROJ"))
        assert ok is True
        assert statuses == ["To Do", "Done", "In Progress"]
        assert err == ""

    def test_get_project_statuses_propagates_failure(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(_method, _endpoint, **_kwargs):
            return False, None, "HTTP 403"

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, statuses, err = asyncio.run(mgr.get_project_statuses("PROJ"))
        assert ok is False
        assert statuses == []
        assert "403" in err

class TestJiraPayloadShapeCoverage:
    def test_create_issue_includes_optional_fields(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok", default_project="PROJ")

        captured = {}

        async def _fake_request(method, endpoint, **kwargs):
            captured["method"] = method
            captured["endpoint"] = endpoint
            captured["json"] = kwargs.get("json", {})
            return True, {"key": "PROJ-11"}, ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, issue, err = asyncio.run(
            mgr.create_issue(
                summary="Bug",
                description="detay",
                labels=["triage", "backend"],
                assignee_account_id="acc-1",
            )
        )

        fields = captured["json"]["fields"]
        assert ok is True
        assert issue["key"] == "PROJ-11"
        assert err == ""
        assert fields["labels"] == ["triage", "backend"]
        assert fields["assignee"]["accountId"] == "acc-1"
        assert fields["description"]["type"] == "doc"

    def test_list_projects_maps_payload(self):
        jira = _get_jira()
        mgr = jira.JiraManager(url="https://company.atlassian.net", token="tok")

        async def _fake_request(_method, _endpoint, **_kwargs):
            return True, [{"key": "PROJ", "name": "Project", "id": "10001"}], ""

        mgr._request = _fake_request  # type: ignore[assignment]
        ok, projects, err = asyncio.run(mgr.list_projects())

        assert ok is True
        assert projects == [{"key": "PROJ", "name": "Project", "id": "10001"}]
        assert err == ""
