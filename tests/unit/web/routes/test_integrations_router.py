import inspect
import sys
import types

import pytest
from fastapi import HTTPException

from web.routes.integrations import (
    JiraCreateRequest,
    SlackSendRequest,
    TeamsSendRequest,
    build_integrations_router,
)


class _Slack:
    def __init__(self, *, available=True, send_ok=True, channels_ok=True):
        self.available = available
        self.send_ok = send_ok
        self.channels_ok = channels_ok

    def is_available(self):
        return self.available

    async def send_message(self, **_):
        return self.send_ok, None if self.send_ok else "send failed"

    async def list_channels(self):
        return self.channels_ok, ["general"], None if self.channels_ok else "channels failed"


class _Jira:
    def __init__(self, *, available=True, create_ok=True, search_ok=True):
        self.available = available
        self.create_ok = create_ok
        self.search_ok = search_ok

    def is_available(self):
        return self.available

    async def create_issue(self, **kwargs):
        return (
            self.create_ok,
            {"key": f"{kwargs['project_key']}-1"},
            None if self.create_ok else "create failed",
        )

    async def search_issues(self, **_):
        return self.search_ok, [{"key": "SIDAR-1"}], None if self.search_ok else "search failed"


class _Teams:
    def __init__(self, *, available=True, send_ok=True):
        self.available = available
        self.send_ok = send_ok

    def is_available(self):
        return self.available

    async def send_message(self, **_):
        return self.send_ok, None if self.send_ok else "teams failed"


def _exports(*, slack=None, jira=None, teams=None):
    router = build_integrations_router(
        cfg_provider=object,
        slack_cache={"instance": slack},
        jira_cache={"instance": jira},
        teams_cache={"instance": teams},
        require_admin_user=lambda: None,
    )
    return router.legacy_exports


def test_integrations_router_endpoints_require_admin_dependency():
    exports = _exports(slack=_Slack(), jira=_Jira(), teams=_Teams())
    protected = {
        "api_slack_send": "_user",
        "api_slack_channels": "_user",
        "api_jira_create_issue": "_user",
        "api_jira_search_issues": "_user",
        "api_teams_send": "_user",
    }

    for export_name, parameter_name in protected.items():
        default = inspect.signature(exports[export_name]).parameters[parameter_name].default
        assert getattr(default, "dependency", None) is not None


@pytest.mark.asyncio
async def test_integrations_router_legacy_exports_success_paths():
    exports = _exports(slack=_Slack(), jira=_Jira(), teams=_Teams())

    slack_send = await exports["api_slack_send"](SlackSendRequest(text="hello", channel="#general"))
    slack_channels = await exports["api_slack_channels"]()
    jira_create = await exports["api_jira_create_issue"](
        JiraCreateRequest(project_key="SIDAR", summary="s")
    )
    jira_search = await exports["api_jira_search_issues"](jql="project=SIDAR", max_results=5)
    teams_send = await exports["api_teams_send"](TeamsSendRequest(text="hello", title="t"))

    assert slack_send.status_code == 200
    assert b'"general"' in slack_channels.body
    assert b'"SIDAR-1"' in jira_create.body
    assert b'"total":1' in jira_search.body
    assert teams_send.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("export_name", "payload", "kwargs"),
    [
        ("api_slack_send", SlackSendRequest(text="hello"), {"slack": _Slack(available=False)}),
        ("api_slack_channels", None, {"slack": _Slack(available=False)}),
        (
            "api_jira_create_issue",
            JiraCreateRequest(project_key="SIDAR", summary="s"),
            {"jira": _Jira(available=False)},
        ),
        ("api_jira_search_issues", None, {"jira": _Jira(available=False)}),
        ("api_teams_send", TeamsSendRequest(text="hello"), {"teams": _Teams(available=False)}),
    ],
)
async def test_integrations_router_legacy_exports_unavailable_paths(export_name, payload, kwargs):
    exports = _exports(**kwargs)

    with pytest.raises(HTTPException) as exc_info:
        if export_name == "api_jira_search_issues":
            await exports[export_name](jql="project=SIDAR", max_results=5)
        elif payload is None:
            await exports[export_name]()
        else:
            await exports[export_name](payload)

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("export_name", "payload", "kwargs"),
    [
        ("api_slack_send", SlackSendRequest(text="hello"), {"slack": _Slack(send_ok=False)}),
        ("api_slack_channels", None, {"slack": _Slack(channels_ok=False)}),
        (
            "api_jira_create_issue",
            JiraCreateRequest(project_key="SIDAR", summary="s"),
            {"jira": _Jira(create_ok=False)},
        ),
        ("api_jira_search_issues", None, {"jira": _Jira(search_ok=False)}),
        ("api_teams_send", TeamsSendRequest(text="hello"), {"teams": _Teams(send_ok=False)}),
    ],
)
async def test_integrations_router_legacy_exports_upstream_error_paths(
    export_name, payload, kwargs
):
    exports = _exports(**kwargs)

    with pytest.raises(HTTPException) as exc_info:
        if export_name == "api_jira_search_issues":
            await exports[export_name](jql="project=SIDAR", max_results=5)
        elif payload is None:
            await exports[export_name]()
        else:
            await exports[export_name](payload)

    assert exc_info.value.status_code == 502


def test_integrations_router_uses_live_cfg_provider_for_jira_manager(monkeypatch):
    class _JiraManager:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    cfg = type(
        "Cfg",
        (),
        {
            "JIRA_BASE_URL": "https://jira.example",
            "JIRA_EMAIL": "bot@example.com",
            "JIRA_API_TOKEN": "token",
            "JIRA_DEFAULT_PROJECT": "SID",
        },
    )()
    monkeypatch.setitem(
        sys.modules, "managers.jira_manager", types.SimpleNamespace(JiraManager=_JiraManager)
    )
    router = build_integrations_router(
        cfg_provider=lambda: cfg,
        slack_cache={},
        jira_cache={},
        teams_cache={},
        require_admin_user=lambda: None,
    )

    cfg.JIRA_DEFAULT_PROJECT = "SIDAR"

    manager = router.legacy_exports["_get_jira_manager"]()
    assert manager.kwargs["default_project"] == "SIDAR"
