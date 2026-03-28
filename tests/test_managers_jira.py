"""
managers/jira_manager.py için birim testleri.
JiraManager: constructor, is_available, disabled paths.
"""
from __future__ import annotations

import asyncio
import sys


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
