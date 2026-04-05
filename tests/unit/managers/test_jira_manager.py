"""Unit tests for JiraManager HTTP flows and response shaping."""

from __future__ import annotations

import httpx
import pytest
import respx

from managers.jira_manager import JiraManager


@pytest.fixture
def jira_manager() -> JiraManager:
    return JiraManager(
        url="https://test.atlassian.net",
        token="fake-token",
        email="test@example.com",
        default_project="TEST",
    )


def test_initialization_requires_url_and_token() -> None:
    assert JiraManager().is_available() is False
    assert JiraManager(url="https://x", token="").is_available() is False


def test_initialization_bearer_token_mode_sets_auth_header() -> None:
    mgr = JiraManager(url="https://jira.local", token="secret", email="")

    assert mgr.is_available() is True
    assert mgr._auth is None
    assert mgr._headers["Authorization"] == "Bearer secret"


def test_initialization_basic_auth_mode_uses_email_token(jira_manager: JiraManager) -> None:
    assert jira_manager.is_available() is True
    assert jira_manager._auth == ("test@example.com", "fake-token")


@pytest.mark.asyncio
async def test_request_returns_unavailable_error_when_not_configured() -> None:
    ok, data, err = await JiraManager().get_issue("TEST-1")

    assert ok is False
    assert data == {}
    assert err == "Jira bağlantısı mevcut değil"


@respx.mock
@pytest.mark.asyncio
async def test_request_handles_http_exception(jira_manager: JiraManager) -> None:
    respx.get("https://test.atlassian.net/rest/api/3/issue/TEST-1").mock(
        side_effect=httpx.ConnectError("boom")
    )

    ok, data, err = await jira_manager.get_issue("TEST-1")

    assert ok is False
    assert data == {}
    assert "boom" in err


@respx.mock
@pytest.mark.asyncio
async def test_create_issue_builds_payload_and_returns_issue(jira_manager: JiraManager) -> None:
    create_route = respx.post("https://test.atlassian.net/rest/api/3/issue").mock(
        return_value=httpx.Response(201, json={"id": "10000", "key": "TEST-2"})
    )

    ok, data, err = await jira_manager.create_issue(
        summary="Test summary",
        description="Test description",
        labels=["backend", "qa"],
        assignee_account_id="acct-1",
    )

    assert ok is True
    assert data["key"] == "TEST-2"
    assert err == ""

    request_payload = create_route.calls.last.request.content.decode()
    assert '"project":{"key":"TEST"}' in request_payload
    assert '"summary":"Test summary"' in request_payload
    assert '"labels":["backend","qa"]' in request_payload
    assert '"assignee":{"accountId":"acct-1"}' in request_payload


@pytest.mark.asyncio
async def test_create_issue_requires_project_key() -> None:
    mgr = JiraManager(url="https://test.atlassian.net", token="t", email="e@example.com")

    ok, data, err = await mgr.create_issue("Summary")

    assert ok is False
    assert data == {}
    assert err == "Proje anahtarı belirtilmedi"


@respx.mock
@pytest.mark.asyncio
async def test_update_issue_reports_success(jira_manager: JiraManager) -> None:
    respx.put("https://test.atlassian.net/rest/api/3/issue/TEST-1").mock(
        return_value=httpx.Response(204)
    )

    ok, err = await jira_manager.update_issue("TEST-1", fields={"summary": "updated"})

    assert ok is True
    assert err == ""


@respx.mock
@pytest.mark.asyncio
async def test_transition_issue_validates_transition_name(jira_manager: JiraManager) -> None:
    respx.get("https://test.atlassian.net/rest/api/3/issue/TEST-1/transitions").mock(
        return_value=httpx.Response(
            200,
            json={"transitions": [{"id": "31", "name": "In Progress"}]},
        )
    )
    respx.post("https://test.atlassian.net/rest/api/3/issue/TEST-1/transitions").mock(
        return_value=httpx.Response(204)
    )

    ok, err = await jira_manager.transition_issue("TEST-1", "In Progress")
    assert ok is True
    assert err == ""

    missing_ok, missing_err = await jira_manager.transition_issue("TEST-1", "Done")
    assert missing_ok is False
    assert "Geçiş bulunamadı" in missing_err


@respx.mock
@pytest.mark.asyncio
async def test_search_list_comment_and_project_status_flows(jira_manager: JiraManager) -> None:
    respx.get("https://test.atlassian.net/rest/api/3/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "TEST-1",
                        "fields": {
                            "summary": "Issue summary",
                            "status": {"name": "To Do"},
                            "assignee": {"displayName": "Alex"},
                            "priority": {"name": "Medium"},
                            "issuetype": {"name": "Bug"},
                        },
                    }
                ]
            },
        )
    )
    respx.post("https://test.atlassian.net/rest/api/3/issue/TEST-1/comment").mock(
        return_value=httpx.Response(201, json={"id": "c1"})
    )
    respx.get("https://test.atlassian.net/rest/api/3/project").mock(
        return_value=httpx.Response(200, json=[{"id": "1", "key": "TEST", "name": "Test"}])
    )
    respx.get("https://test.atlassian.net/rest/api/3/project/TEST/statuses").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"statuses": [{"name": "To Do"}, {"name": "Done"}]},
                {"statuses": [{"name": "Done"}, {"name": "In Progress"}]},
            ],
        )
    )

    ok_search, issues, err_search = await jira_manager.search_issues('project = "TEST"', max_results=500)
    assert ok_search is True
    assert err_search == ""
    assert issues == [
        {
            "key": "TEST-1",
            "summary": "Issue summary",
            "status": "To Do",
            "assignee": "Alex",
            "priority": "Medium",
            "type": "Bug",
        }
    ]

    ok_comment, comment_data, err_comment = await jira_manager.add_comment("TEST-1", "Looks good")
    assert ok_comment is True
    assert comment_data == {"id": "c1"}
    assert err_comment == ""

    ok_projects, projects, err_projects = await jira_manager.list_projects()
    assert ok_projects is True
    assert projects == [{"id": "1", "key": "TEST", "name": "Test"}]
    assert err_projects == ""

    ok_status, statuses, err_status = await jira_manager.get_project_statuses("TEST")
    assert ok_status is True
    assert statuses == ["To Do", "Done", "In Progress"]
    assert err_status == ""
