"""Testler: Slack, Jira, Teams Entegrasyon Yöneticileri (Özellik 10)"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── httpx stub (pytest ortamında yoksa mock ekle) ────────────────────────────

import importlib.util
import pathlib
import types

# httpx stub — pytest ortamında kurulu değilse mock ekle
if "httpx" not in sys.modules:
    _httpx_mock = MagicMock()
    _async_client = MagicMock()
    _httpx_mock.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=_async_client)
    _httpx_mock.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
    sys.modules["httpx"] = _httpx_mock

# managers paketi stub — __init__.py tetiklemeden alt modüller yüklensin
if "managers" not in sys.modules:
    _mgr_pkg = types.ModuleType("managers")
    _mgr_pkg.__path__ = []
    _mgr_pkg.__package__ = "managers"
    sys.modules["managers"] = _mgr_pkg


def _load_module(name: str, rel_path: str):
    """managers/__init__.py'yi tetiklemeden doğrudan dosyadan modül yükler."""
    root = pathlib.Path(__file__).parent.parent
    spec = importlib.util.spec_from_file_location(name, root / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_slack_mod = _load_module("managers.slack_manager", "managers/slack_manager.py")
_jira_mod = _load_module("managers.jira_manager", "managers/jira_manager.py")
_teams_mod = _load_module("managers.teams_manager", "managers/teams_manager.py")

SlackManager = _slack_mod.SlackManager
JiraManager = _jira_mod.JiraManager
TeamsManager = _teams_mod.TeamsManager


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════════════════
# SlackManager
# ═══════════════════════════════════════════════════════════════════════════════

class TestSlackManagerInit:
    def test_no_credentials_not_available(self):
        mgr = SlackManager()
        assert mgr.is_available() is False

    def test_webhook_only_mode(self):
        mgr = SlackManager(webhook_url="https://hooks.slack.com/test")
        assert mgr.is_available() is True
        assert mgr._webhook_only is True

    def test_token_without_sdk_falls_back_to_webhook(self):
        # slack_sdk kurulu değilse token yok sayılır
        with patch.dict(sys.modules, {"slack_sdk": None}):
            mgr = SlackManager(
                token="xoxb-fake",
                webhook_url="https://hooks.slack.com/test",
            )
        # Webhook olduğu için available olabilir
        assert mgr.is_available() is True

    def test_default_channel_stored(self):
        mgr = SlackManager(
            webhook_url="https://hooks.slack.com/test",
            default_channel="#genel",
        )
        assert mgr.default_channel == "#genel"


class TestSlackManagerSendMessage:
    def _webhook_mgr(self):
        mgr = SlackManager.__new__(SlackManager)
        mgr.token = ""
        mgr.webhook_url = "https://hooks.slack.com/test"
        mgr.default_channel = "#test"
        mgr._client = None
        mgr._available = True
        mgr._webhook_only = True
        return mgr

    def test_send_message_not_available(self):
        mgr = SlackManager()  # no credentials
        ok, err = _run(mgr.send_message("Merhaba"))
        assert ok is False
        assert "mevcut değil" in err

    def test_send_message_no_channel_webhook_only_ok(self):
        mgr = self._webhook_mgr()
        with patch.object(mgr, "send_webhook", new=AsyncMock(return_value=(True, ""))) as m:
            ok, _ = _run(mgr.send_message("test"))
            m.assert_called_once()
            assert ok is True

    def test_send_message_calls_webhook_fallback(self):
        mgr = self._webhook_mgr()
        with patch.object(mgr, "send_webhook", new=AsyncMock(return_value=(True, ""))):
            ok, _ = _run(mgr.send_message("Hi", channel="#channel"))
            assert ok is True


class TestSlackManagerSendWebhook:
    def test_no_webhook_url_returns_error(self):
        mgr = SlackManager.__new__(SlackManager)
        mgr.webhook_url = ""
        mgr._available = False
        mgr._webhook_only = False
        mgr._client = None
        ok, err = _run(mgr.send_webhook("test"))
        assert ok is False
        assert "SLACK_WEBHOOK_URL" in err

    def test_successful_webhook_post(self):
        mgr = SlackManager.__new__(SlackManager)
        mgr.webhook_url = "https://hooks.slack.com/test"
        mgr._available = True
        mgr._webhook_only = True
        mgr._client = None

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch.object(_slack_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, err = _run(mgr.send_webhook(text="Build OK"))
        assert ok is True
        assert err == ""

    def test_failed_webhook_post(self):
        mgr = SlackManager.__new__(SlackManager)
        mgr.webhook_url = "https://hooks.slack.com/test"
        mgr._available = True
        mgr._webhook_only = True
        mgr._client = None

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "channel_not_found"

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch.object(_slack_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, err = _run(mgr.send_webhook(text="Test"))
        assert ok is False
        assert "403" in err

    def test_webhook_exception_returns_error(self):
        mgr = SlackManager.__new__(SlackManager)
        mgr.webhook_url = "https://hooks.slack.com/test"
        mgr._available = True
        mgr._webhook_only = True
        mgr._client = None

        with patch.object(_slack_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(
                side_effect=ConnectionError("Connection refused")
            )
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, err = _run(mgr.send_webhook(text="Test"))
        assert ok is False


class TestSlackManagerListChannels:
    def test_list_channels_no_sdk(self):
        mgr = SlackManager.__new__(SlackManager)
        mgr._client = None
        mgr._webhook_only = True
        ok, channels, err = _run(mgr.list_channels())
        assert ok is False
        assert channels == []

    def test_list_channels_webhook_only(self):
        mgr = SlackManager.__new__(SlackManager)
        mgr._client = None
        mgr._webhook_only = True
        ok, channels, err = _run(mgr.list_channels())
        assert ok is False


class TestSlackManagerBuildBlocks:
    def test_basic_structure(self):
        blocks = SlackManager.build_notification_blocks("Başlık", "Gövde")
        # header + section + divider = 3 blok minimum
        assert len(blocks) >= 3
        assert blocks[0]["type"] == "header"

    def test_status_emoji_success(self):
        blocks = SlackManager.build_notification_blocks("Test", "Body", status="success")
        header_text = blocks[0]["text"]["text"]
        assert "✅" in header_text

    def test_status_emoji_error(self):
        blocks = SlackManager.build_notification_blocks("Test", "Body", status="error")
        header_text = blocks[0]["text"]["text"]
        assert "❌" in header_text

    def test_fields_added_as_section(self):
        fields = [{"key": "Ortam", "value": "Production"}, {"key": "Sürüm", "value": "1.2.3"}]
        blocks = SlackManager.build_notification_blocks("T", "B", fields=fields)
        section_types = [b["type"] for b in blocks]
        assert section_types.count("section") >= 2

    def test_no_fields_no_extra_section(self):
        blocks = SlackManager.build_notification_blocks("T", "B")
        sections = [b for b in blocks if b["type"] == "section"]
        assert len(sections) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# JiraManager
# ═══════════════════════════════════════════════════════════════════════════════

class TestJiraManagerInit:
    def test_no_url_not_available(self):
        mgr = JiraManager()
        assert mgr.is_available() is False

    def test_no_token_not_available(self):
        mgr = JiraManager(url="https://example.atlassian.net")
        assert mgr.is_available() is False

    def test_email_and_token_basic_auth(self):
        mgr = JiraManager(
            url="https://example.atlassian.net",
            token="api-token",
            email="user@example.com",
        )
        assert mgr.is_available() is True
        assert mgr._auth == ("user@example.com", "api-token")

    def test_bearer_token_no_email(self):
        mgr = JiraManager(url="https://example.atlassian.net", token="bearer-token")
        assert mgr.is_available() is True
        assert mgr._auth is None
        assert "Bearer bearer-token" in mgr._headers.get("Authorization", "")

    def test_default_project_stored(self):
        mgr = JiraManager(
            url="https://x.atlassian.net",
            token="t",
            default_project="PROJ",
        )
        assert mgr.default_project == "PROJ"


class TestJiraManagerNotAvailable:
    def _mgr(self):
        return JiraManager()  # no URL/token

    def test_request_returns_error(self):
        mgr = self._mgr()
        ok, data, err = _run(mgr._request("GET", "issue/TEST-1"))
        assert ok is False
        assert "mevcut değil" in err

    def test_get_issue_not_available(self):
        mgr = self._mgr()
        ok, data, err = _run(mgr.get_issue("TEST-1"))
        assert ok is False

    def test_create_issue_not_available(self):
        mgr = self._mgr()
        ok, data, err = _run(mgr.create_issue("Test", project="PROJ"))
        assert ok is False

    def test_search_issues_not_available(self):
        mgr = self._mgr()
        ok, issues, err = _run(mgr.search_issues('project = TEST'))
        assert ok is False
        assert issues == []

    def test_list_projects_not_available(self):
        mgr = self._mgr()
        ok, projects, err = _run(mgr.list_projects())
        assert ok is False
        assert projects == []


class TestJiraManagerCreateIssue:
    def _mgr(self):
        mgr = JiraManager.__new__(JiraManager)
        mgr.url = "https://example.atlassian.net"
        mgr.token = "t"
        mgr.email = "u@x.com"
        mgr.default_project = "PROJ"
        mgr._available = True
        mgr._auth = ("u@x.com", "t")
        mgr._headers = {"Accept": "application/json", "Content-Type": "application/json"}
        return mgr

    def test_missing_project_returns_error(self):
        mgr = self._mgr()
        mgr.default_project = ""
        ok, data, err = _run(mgr.create_issue("Test issue", project=None))
        assert ok is False
        assert "Proje" in err

    def test_create_issue_with_mock(self):
        mgr = self._mgr()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b'{"id":"10001","key":"PROJ-1"}'
        mock_resp.json.return_value = {"id": "10001", "key": "PROJ-1"}

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        with patch.object(_jira_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, data, err = _run(mgr.create_issue("Fix bug", issue_type="Bug"))
        assert ok is True
        assert data["key"] == "PROJ-1"

    def test_create_issue_with_description(self):
        mgr = self._mgr()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.content = b'{"key":"PROJ-2"}'
        mock_resp.json.return_value = {"key": "PROJ-2"}

        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        with patch.object(_jira_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, data, err = _run(mgr.create_issue("With desc", description="Some desc"))
        assert ok is True


class TestJiraManagerSearchIssues:
    def _mgr(self):
        mgr = JiraManager.__new__(JiraManager)
        mgr.url = "https://example.atlassian.net"
        mgr.token = "t"
        mgr.email = "u@x.com"
        mgr.default_project = ""
        mgr._available = True
        mgr._auth = ("u@x.com", "t")
        mgr._headers = {"Accept": "application/json", "Content-Type": "application/json"}
        return mgr

    def test_search_parses_issues(self):
        mgr = self._mgr()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"..."
        mock_resp.json.return_value = {
            "issues": [
                {
                    "key": "PROJ-1",
                    "fields": {
                        "summary": "Bug fix",
                        "status": {"name": "To Do"},
                        "assignee": {"displayName": "Alice"},
                        "priority": {"name": "High"},
                        "issuetype": {"name": "Bug"},
                    },
                }
            ]
        }
        mock_client = MagicMock()
        mock_client.request = AsyncMock(return_value=mock_resp)

        with patch.object(_jira_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, issues, err = _run(mgr.search_issues('project = PROJ'))
        assert ok is True
        assert len(issues) == 1
        assert issues[0]["key"] == "PROJ-1"
        assert issues[0]["status"] == "To Do"
        assert issues[0]["assignee"] == "Alice"


class TestJiraManagerTransitionIssue:
    def _mgr(self):
        mgr = JiraManager.__new__(JiraManager)
        mgr.url = "https://example.atlassian.net"
        mgr.token = "t"
        mgr.email = ""
        mgr.default_project = ""
        mgr._available = True
        mgr._auth = None
        mgr._headers = {"Authorization": "Bearer t", "Accept": "application/json", "Content-Type": "application/json"}
        return mgr

    def test_transition_not_found(self):
        mgr = self._mgr()
        with patch.object(mgr, "_request", new=AsyncMock(return_value=(
            True,
            {"transitions": [{"id": "11", "name": "In Progress"}]},
            "",
        ))):
            ok, err = _run(mgr.transition_issue("TEST-1", "Done"))
        assert ok is False
        assert "In Progress" in err

    def test_transition_found(self):
        mgr = self._mgr()

        async def fake_request(method, endpoint, **kwargs):
            if method == "GET":
                return True, {"transitions": [{"id": "31", "name": "Done"}]}, ""
            return True, {}, ""

        with patch.object(mgr, "_request", new=fake_request):
            ok, err = _run(mgr.transition_issue("TEST-1", "Done"))
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════════════
# TeamsManager
# ═══════════════════════════════════════════════════════════════════════════════

class TestTeamsManagerInit:
    def test_no_webhook_not_available(self):
        mgr = TeamsManager()
        assert mgr.is_available() is False

    def test_with_webhook_available(self):
        mgr = TeamsManager(webhook_url="https://outlook.office.com/webhook/test")
        assert mgr.is_available() is True

    def test_webhook_url_stripped(self):
        mgr = TeamsManager(webhook_url="  https://example.com/hook  ")
        assert mgr.webhook_url == "https://example.com/hook"


class TestTeamsManagerSendMessage:
    def test_send_message_not_available(self):
        mgr = TeamsManager()
        ok, err = _run(mgr.send_message("Hello"))
        assert ok is False
        assert "TEAMS_WEBHOOK_URL" in err

    def test_send_message_calls_post(self):
        mgr = TeamsManager(webhook_url="https://outlook.office.com/webhook/test")
        with patch.object(mgr, "_post", new=AsyncMock(return_value=(True, ""))) as mock_post:
            ok, err = _run(mgr.send_message("Test mesaj"))
        assert ok is True
        mock_post.assert_called_once()

    def test_send_message_with_title(self):
        mgr = TeamsManager(webhook_url="https://example.com/hook")
        with patch.object(mgr, "_post", new=AsyncMock(return_value=(True, ""))) as mock_post:
            _run(mgr.send_message("Body", title="Başlık"))
        call_args = mock_post.call_args[0][0]
        assert call_args.get("title") == "Başlık"

    def test_send_message_with_subtitle_prepends_text(self):
        mgr = TeamsManager(webhook_url="https://example.com/hook")
        captured = {}
        async def capture(payload):
            captured["payload"] = payload
            return True, ""
        mgr._post = capture
        _run(mgr.send_message("Gövde", subtitle="Alt başlık"))
        assert "Alt başlık" in captured["payload"]["text"]
        assert "Gövde" in captured["payload"]["text"]

    def test_send_message_with_facts(self):
        mgr = TeamsManager(webhook_url="https://example.com/hook")
        captured = {}
        async def capture(payload):
            captured["payload"] = payload
            return True, ""
        mgr._post = capture
        facts = [{"key": "Ortam", "value": "prod"}]
        _run(mgr.send_message("msg", facts=facts))
        assert "sections" in captured["payload"]


class TestTeamsManagerSendAdaptiveCard:
    def test_send_adaptive_card_not_available(self):
        mgr = TeamsManager()
        ok, err = _run(mgr.send_adaptive_card({"type": "AdaptiveCard"}))
        assert ok is False

    def test_send_adaptive_card_wraps_in_attachment(self):
        mgr = TeamsManager(webhook_url="https://example.com/hook")
        captured = {}
        async def capture(payload):
            captured["payload"] = payload
            return True, ""
        mgr._post = capture
        card = {"type": "AdaptiveCard", "body": []}
        _run(mgr.send_adaptive_card(card))
        p = captured["payload"]
        assert p["type"] == "message"
        assert p["attachments"][0]["content"] == card


class TestTeamsManagerSendNotification:
    def test_send_notification_colors(self):
        mgr = TeamsManager(webhook_url="https://example.com/hook")
        captured = {}
        async def capture(payload):
            captured["payload"] = payload
            return True, ""
        mgr._post = capture
        _run(mgr.send_notification("Test", "Body", status="error"))
        assert captured["payload"]["themeColor"] == "D83B01"

    def test_send_notification_with_link(self):
        mgr = TeamsManager(webhook_url="https://example.com/hook")
        captured = {}
        async def capture(payload):
            captured["payload"] = payload
            return True, ""
        mgr._post = capture
        _run(mgr.send_notification("T", "B", link_url="https://example.com"))
        assert "potentialAction" in captured["payload"]


class TestTeamsManagerBuildApprovalCard:
    def test_approval_card_structure(self):
        card = TeamsManager.build_approval_card(
            request_id="req-1",
            title="Deploy Onayı",
            description="Prod'a deploy yapılacak",
            requester="Alice",
            approve_url="https://api.example.com/approve",
            reject_url="https://api.example.com/reject",
        )
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.4"
        assert len(card["actions"]) == 2
        # İlk aksiyon: Onayla
        assert "Onayla" in card["actions"][0]["title"]
        # İkinci aksiyon: Reddet
        assert "Reddet" in card["actions"][1]["title"]

    def test_approval_card_requester_factset(self):
        card = TeamsManager.build_approval_card("r", "T", "D", requester="Bob")
        body_types = [b["type"] for b in card["body"]]
        assert "FactSet" in body_types

    def test_approval_card_no_actions_when_no_urls(self):
        card = TeamsManager.build_approval_card("r", "T", "D")
        assert card["actions"] == []

    def test_approve_url_contains_request_id(self):
        card = TeamsManager.build_approval_card(
            "my-req-123", "T", "D",
            approve_url="https://api.example.com/approve",
        )
        approve_url = card["actions"][0]["url"]
        assert "my-req-123" in approve_url
        assert "approved=true" in approve_url


class TestTeamsManagerBuildSummaryCard:
    def test_summary_card_structure(self):
        metrics = [{"key": "Total", "value": "42"}, {"key": "Errors", "value": "0"}]
        card = TeamsManager.build_summary_card("Özet", metrics)
        assert card["type"] == "AdaptiveCard"
        fact_blocks = [b for b in card["body"] if b.get("type") == "FactSet"]
        assert len(fact_blocks) == 1

    def test_summary_card_description_included(self):
        card = TeamsManager.build_summary_card("T", [], description="Açıklama")
        texts = [b.get("text", "") for b in card["body"] if b.get("type") == "TextBlock"]
        assert any("Açıklama" in t for t in texts)

    def test_summary_card_empty_metrics_no_factset(self):
        card = TeamsManager.build_summary_card("T", [])
        fact_blocks = [b for b in card["body"] if b.get("type") == "FactSet"]
        assert len(fact_blocks) == 0


class TestTeamsManagerPost:
    def test_post_success_status_200(self):
        mgr = TeamsManager(webhook_url="https://example.com/hook")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "1"

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch.object(_teams_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, err = _run(mgr._post({"text": "test"}))
        assert ok is True
        assert err == ""

    def test_post_http_error(self):
        mgr = TeamsManager(webhook_url="https://example.com/hook")
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch.object(_teams_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, err = _run(mgr._post({"text": "test"}))
        assert ok is False
        assert "400" in err

    def test_post_exception_returns_error(self):
        mgr = TeamsManager(webhook_url="https://example.com/hook")
        with patch.object(_teams_mod, "httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(
                side_effect=ConnectionError("Network down")
            )
            mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
            ok, err = _run(mgr._post({}))
        assert ok is False
        assert "Network down" in err
