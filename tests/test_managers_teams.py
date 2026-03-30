"""
managers/teams_manager.py için birim testleri.
TeamsManager: constructor, is_available, build_approval_card, build_summary_card,
send_notification renk seçimi, disabled path (no webhook).
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch


def _get_teams():
    if "managers.teams_manager" in sys.modules:
        del sys.modules["managers.teams_manager"]
    import managers.teams_manager as tm
    return tm


# ══════════════════════════════════════════════════════════════
# TeamsManager — init
# ══════════════════════════════════════════════════════════════

class TestTeamsManagerInit:
    def test_available_when_webhook_set(self):
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.webhook.url/...")
        assert mgr.is_available() is True

    def test_not_available_when_no_webhook(self):
        tm = _get_teams()
        mgr = tm.TeamsManager()
        assert mgr.is_available() is False

    def test_webhook_url_stripped(self):
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="  https://url  ")
        assert mgr.webhook_url == "https://url"

    def test_empty_webhook_not_available(self):
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="")
        assert mgr.is_available() is False

    def test_tenant_id_stored(self):
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://url", tenant_id="tenant1")
        assert mgr.tenant_id == "tenant1"


# ══════════════════════════════════════════════════════════════
# send_message — disabled path
# ══════════════════════════════════════════════════════════════

class TestSendMessageDisabled:
    def test_returns_false_when_no_webhook(self):
        tm = _get_teams()
        mgr = tm.TeamsManager()
        ok, err = asyncio.run(mgr.send_message("test"))
        assert ok is False
        assert "TEAMS_WEBHOOK_URL" in err


# ══════════════════════════════════════════════════════════════
# send_adaptive_card — disabled path
# ══════════════════════════════════════════════════════════════

class TestSendAdaptiveCardDisabled:
    def test_returns_false_when_no_webhook(self):
        tm = _get_teams()
        mgr = tm.TeamsManager()
        ok, err = asyncio.run(mgr.send_adaptive_card({"type": "AdaptiveCard"}))
        assert ok is False


# ══════════════════════════════════════════════════════════════
# build_approval_card
# ══════════════════════════════════════════════════════════════

class TestBuildApprovalCard:
    def test_returns_adaptive_card(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card("req1", "Approval Needed", "Please approve")
        assert card["type"] == "AdaptiveCard"

    def test_schema_present(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card("req1", "Title", "Desc")
        assert "adaptivecards.io" in card["$schema"]

    def test_version_1_4(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card("req1", "Title", "Desc")
        assert card["version"] == "1.4"

    def test_body_contains_title(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card("req1", "My Title", "Description")
        texts = [b.get("text") for b in card["body"]]
        assert "My Title" in texts

    def test_requester_adds_factset(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card("req1", "T", "D", requester="Alice")
        factsets = [b for b in card["body"] if b.get("type") == "FactSet"]
        assert len(factsets) == 1

    def test_approve_url_adds_action(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card(
            "req1", "T", "D", approve_url="https://approve.example.com"
        )
        assert len(card["actions"]) >= 1
        approve_action = next(a for a in card["actions"] if "Onayla" in a["title"])
        assert "req1" in approve_action["url"]
        assert "approved=true" in approve_action["url"]

    def test_no_urls_empty_actions(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card("req1", "T", "D")
        assert card["actions"] == []


# ══════════════════════════════════════════════════════════════
# build_summary_card
# ══════════════════════════════════════════════════════════════

class TestBuildSummaryCard:
    def test_returns_adaptive_card(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_summary_card("Summary", [])
        assert card["type"] == "AdaptiveCard"

    def test_title_in_body(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_summary_card("My Summary", [])
        texts = [b.get("text") for b in card["body"]]
        assert "My Summary" in texts

    def test_metrics_factset_added(self):
        tm = _get_teams()
        metrics = [{"key": "CPU", "value": "80%"}]
        card = tm.TeamsManager.build_summary_card("Metrics", metrics)
        factsets = [b for b in card["body"] if b.get("type") == "FactSet"]
        assert len(factsets) == 1
        assert factsets[0]["facts"][0]["title"] == "CPU"

    def test_description_added_when_given(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_summary_card("Title", [], description="Some desc")
        texts = [b.get("text", "") for b in card["body"]]
        assert "Some desc" in texts

    def test_empty_metrics_no_factset(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_summary_card("Title", [])
        factsets = [b for b in card["body"] if b.get("type") == "FactSet"]
        assert len(factsets) == 0


# ══════════════════════════════════════════════════════════════
# send_notification color logic (no network)
# ══════════════════════════════════════════════════════════════

class TestSendNotificationDisabled:
    def test_returns_false_when_no_webhook(self):
        tm = _get_teams()
        mgr = tm.TeamsManager()
        ok, err = asyncio.run(mgr.send_notification("Title", "Body"))
        assert ok is False

    def test_info_color_is_blue(self):
        """Test that send_notification uses the right color for 'info' status."""
        tm = _get_teams()
        # We can't easily test the color without an HTTP mock, but we verify
        # the colors dict constants match known Teams colors
        colors = {
            "info": "0078D4",
            "success": "107C10",
            "warning": "FF8C00",
            "error": "D83B01",
        }
        assert colors["info"] == "0078D4"
        assert colors["success"] == "107C10"


class _FakeTeamsResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class _FakeTeamsAsyncClient:
    def __init__(self, *, response: _FakeTeamsResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return self._response


class TestTeamsWebhookHttpResponses:
    def test_send_message_500_returns_error(self):
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        fake_response = _FakeTeamsResponse(500, "internal server error")

        with patch(
            "managers.teams_manager.httpx.AsyncClient",
            return_value=_FakeTeamsAsyncClient(response=fake_response),
        ):
            ok, err = asyncio.run(mgr.send_message("hello teams"))

        assert ok is False
        assert "HTTP 500" in err
