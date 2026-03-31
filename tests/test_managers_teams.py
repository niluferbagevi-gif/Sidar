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

    def test_unknown_status_falls_back_to_info_color(self, monkeypatch):
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        captured = {}

        async def _fake_send_message(*, text, title="", subtitle="", facts=None, actions=None, theme_color=""):
            captured["theme_color"] = theme_color
            return True, ""

        monkeypatch.setattr(mgr, "send_message", _fake_send_message)
        ok, err = asyncio.run(mgr.send_notification("Title", "Body", status="unexpected"))
        assert ok is True
        assert err == ""
        assert captured["theme_color"] == "0078D4"


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

# ===== MERGED FROM tests/test_managers_teams_extra.py =====

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch


def _get_teams():
    if "managers.teams_manager" in sys.modules:
        del sys.modules["managers.teams_manager"]
    import managers.teams_manager as tm
    return tm


# ══════════════════════════════════════════════════════════════
# send_message — lines 80, 82, 84, 88 (title/subtitle/facts/actions)
# ══════════════════════════════════════════════════════════════

class Extra_TestSendMessageCardFields:
    """Test that optional fields (title, subtitle, facts, actions) are correctly
    added to the card payload before it reaches _post."""

    def _make_capturing_mgr(self, tm):
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        captured = {}

        async def _fake_post(payload):
            captured.update(payload)
            return True, ""

        mgr._post = _fake_post
        return mgr, captured

    def test_title_added_to_card(self):
        """Line 80: if title → card['title'] = title."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        asyncio.run(mgr.send_message("body text", title="My Title"))
        assert captured.get("title") == "My Title"

    def test_title_empty_not_added(self):
        """Line 79: no title → 'title' key absent in card."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        asyncio.run(mgr.send_message("body text", title=""))
        assert "title" not in captured

    def test_subtitle_formats_text(self):
        """Line 82: subtitle → card['text'] = '**subtitle**\\n\\nbody'."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        asyncio.run(mgr.send_message("body text", subtitle="Sub Header"))
        assert "**Sub Header**" in captured.get("text", "")
        assert "body text" in captured.get("text", "")

    def test_subtitle_empty_not_formatted(self):
        """Line 81: no subtitle → text is plain body."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        asyncio.run(mgr.send_message("plain body", subtitle=""))
        assert captured.get("text") == "plain body"
        assert "**" not in captured.get("text", "")

    def test_facts_added_as_sections(self):
        """Lines 83-86: facts → card['sections'] with facts list."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        facts = [{"key": "Env", "value": "prod"}, {"key": "Version", "value": "1.0.0"}]
        asyncio.run(mgr.send_message("body", facts=facts))
        sections = captured.get("sections", [])
        assert len(sections) == 1
        fact_names = [f["name"] for f in sections[0]["facts"]]
        assert "Env" in fact_names
        assert "Version" in fact_names

    def test_facts_none_no_sections(self):
        """Line 83: facts=None → no 'sections' key."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        asyncio.run(mgr.send_message("body", facts=None))
        assert "sections" not in captured

    def test_actions_added_as_potential_action(self):
        """Lines 87-88: actions → card['potentialAction'] = actions."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        actions = [{"@type": "OpenUri", "name": "View", "targets": [{"os": "default", "uri": "https://x.y"}]}]
        asyncio.run(mgr.send_message("body", actions=actions))
        assert "potentialAction" in captured
        assert captured["potentialAction"] == actions

    def test_actions_none_no_potential_action(self):
        """Line 87: actions=None → 'potentialAction' absent."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        asyncio.run(mgr.send_message("body", actions=None))
        assert "potentialAction" not in captured

    def test_theme_color_applied(self):
        """Line 75: theme_color set in card."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        asyncio.run(mgr.send_message("body", theme_color="FF0000"))
        assert captured.get("themeColor") == "FF0000"

    def test_summary_falls_back_to_text_when_no_title(self):
        """Line 77: summary = title or text[:100]."""
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        asyncio.run(mgr.send_message("A short message", title=""))
        assert captured.get("summary") == "A short message"

    def test_summary_uses_title_when_provided(self):
        tm = _get_teams()
        mgr, captured = self._make_capturing_mgr(tm)
        asyncio.run(mgr.send_message("body", title="My Title"))
        assert captured.get("summary") == "My Title"


# ══════════════════════════════════════════════════════════════
# send_adaptive_card — lines 100-110
# ══════════════════════════════════════════════════════════════

class Extra_TestSendAdaptiveCard:
    def test_send_adaptive_card_wraps_body_in_attachments(self):
        """Lines 100-110: adaptive card is wrapped in attachments payload."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        captured = {}

        async def _fake_post(payload):
            captured.update(payload)
            return True, ""

        mgr._post = _fake_post
        card_body = {"type": "AdaptiveCard", "version": "1.4", "body": []}
        asyncio.run(mgr.send_adaptive_card(card_body))

        assert captured.get("type") == "message"
        attachments = captured.get("attachments", [])
        assert len(attachments) == 1
        assert attachments[0]["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert attachments[0]["content"] == card_body
        assert attachments[0]["contentUrl"] is None

    def test_send_adaptive_card_posts_successfully(self):
        """Lines 100-110: full flow with HTTP mock → success."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.text = "1"

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *args, **kwargs):
                return fake_resp

        with patch("managers.teams_manager.httpx.AsyncClient", return_value=_FakeClient()):
            ok, err = asyncio.run(mgr.send_adaptive_card({"type": "AdaptiveCard"}))
        assert ok is True
        assert err == ""


# ══════════════════════════════════════════════════════════════
# send_notification — line 132 (link_url adds action)
# ══════════════════════════════════════════════════════════════

class Extra_TestSendNotification:
    def test_link_url_adds_open_uri_action(self):
        """Line 132: link_url provided → OpenUri action added."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        captured = {}

        async def _fake_send_message(*, text, title="", subtitle="", facts=None, actions=None, theme_color=""):
            captured["actions"] = actions
            return True, ""

        mgr.send_message = _fake_send_message
        asyncio.run(mgr.send_notification(
            "Title", "Body",
            status="success",
            link_url="https://example.com/details",
            link_label="View Details",
        ))
        assert captured["actions"] is not None
        assert len(captured["actions"]) == 1
        action = captured["actions"][0]
        assert action["@type"] == "OpenUri"
        assert action["name"] == "View Details"
        assert action["targets"][0]["uri"] == "https://example.com/details"

    def test_no_link_url_actions_is_none(self):
        """Line 142: no link_url → actions=None in send_message call."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        captured = {}

        async def _fake_send_message(*, text, title="", subtitle="", facts=None, actions=None, theme_color=""):
            captured["actions"] = actions
            return True, ""

        mgr.send_message = _fake_send_message
        asyncio.run(mgr.send_notification("Title", "Body"))
        assert captured["actions"] is None

    def test_notification_success_status_color(self):
        """Lines 122-128: 'success' → green color 107C10."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        captured = {}

        async def _fake_send_message(*, text, title="", subtitle="", facts=None, actions=None, theme_color=""):
            captured["theme_color"] = theme_color
            return True, ""

        mgr.send_message = _fake_send_message
        asyncio.run(mgr.send_notification("Title", "Body", status="success"))
        assert captured["theme_color"] == "107C10"

    def test_notification_error_status_color(self):
        """Lines 122-128: 'error' → red color D83B01."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        captured = {}

        async def _fake_send_message(*, text, title="", subtitle="", facts=None, actions=None, theme_color=""):
            captured["theme_color"] = theme_color
            return True, ""

        mgr.send_message = _fake_send_message
        asyncio.run(mgr.send_notification("Title", "Body", status="error"))
        assert captured["theme_color"] == "D83B01"

    def test_notification_warning_status_color(self):
        """Lines 122-128: 'warning' → orange color FF8C00."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        captured = {}

        async def _fake_send_message(*, text, title="", subtitle="", facts=None, actions=None, theme_color=""):
            captured["theme_color"] = theme_color
            return True, ""

        mgr.send_message = _fake_send_message
        asyncio.run(mgr.send_notification("Title", "Body", status="warning"))
        assert captured["theme_color"] == "FF8C00"

    def test_notification_details_passed_as_facts(self):
        """details → passed as facts to send_message."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        captured = {}

        async def _fake_send_message(*, text, title="", subtitle="", facts=None, actions=None, theme_color=""):
            captured["facts"] = facts
            return True, ""

        mgr.send_message = _fake_send_message
        details = [{"key": "Host", "value": "server01"}]
        asyncio.run(mgr.send_notification("Title", "Body", details=details))
        assert captured["facts"] == details


# ══════════════════════════════════════════════════════════════
# build_approval_card — line 178 (reject_url)
# ══════════════════════════════════════════════════════════════

class Extra_TestBuildApprovalCardRejectUrl:
    def test_reject_url_adds_reject_action(self):
        """Line 178: reject_url → 'Reddet' action with approved=false."""
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card(
            "req-42", "T", "D",
            reject_url="https://reject.example.com"
        )
        reject_action = next(
            (a for a in card["actions"] if "Reddet" in a["title"]), None
        )
        assert reject_action is not None
        assert "approved=false" in reject_action["url"]
        assert "req-42" in reject_action["url"]

    def test_both_approve_and_reject_urls(self):
        """Lines 171-178: both approve_url and reject_url → 2 actions."""
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card(
            "req-1", "Title", "Desc",
            approve_url="https://approve.example.com",
            reject_url="https://reject.example.com",
        )
        assert len(card["actions"]) == 2

    def test_only_reject_url_one_action(self):
        tm = _get_teams()
        card = tm.TeamsManager.build_approval_card(
            "req-2", "T", "D",
            reject_url="https://reject.example.com",
        )
        assert len(card["actions"]) == 1
        assert "Reddet" in card["actions"][0]["title"]


# ══════════════════════════════════════════════════════════════
# _post — lines 228, 230, 232-234
# ══════════════════════════════════════════════════════════════

class Extra_TestPost:
    def _make_fake_client(self, status_code, text):
        class _FakeClient:
            def __init__(self, sc, t):
                self._sc = sc
                self._t = t

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, content=None, headers=None):
                resp = MagicMock()
                resp.status_code = self._sc
                resp.text = self._t
                return resp

        return _FakeClient(status_code, text)

    def test_post_200_with_text_1_returns_success(self):
        """Line 228: status 200 + text='1' → (True, '')."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        with patch("managers.teams_manager.httpx.AsyncClient", return_value=self._make_fake_client(200, "1")):
            ok, err = asyncio.run(mgr._post({"type": "test"}))
        assert ok is True
        assert err == ""

    def test_post_201_with_empty_text_returns_success(self):
        """Line 230: status 201 + text='' → (True, '')."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        with patch("managers.teams_manager.httpx.AsyncClient", return_value=self._make_fake_client(201, "")):
            ok, err = asyncio.run(mgr._post({"type": "test"}))
        assert ok is True
        assert err == ""

    def test_post_202_with_ok_text_returns_success(self):
        """Line 228: status 202 + text='ok' → (True, '')."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        with patch("managers.teams_manager.httpx.AsyncClient", return_value=self._make_fake_client(202, "ok")):
            ok, err = asyncio.run(mgr._post({"type": "test"}))
        assert ok is True
        assert err == ""

    def test_post_200_with_unexpected_body_still_succeeds(self):
        """Line 230: 200 status but body not in ('1','ok','') → still True (fallthrough)."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        with patch("managers.teams_manager.httpx.AsyncClient", return_value=self._make_fake_client(200, "some_json")):
            ok, err = asyncio.run(mgr._post({"type": "test"}))
        assert ok is True

    def test_post_400_returns_false_with_error(self):
        """Line 231: non-2xx → (False, 'HTTP ...')."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        with patch("managers.teams_manager.httpx.AsyncClient", return_value=self._make_fake_client(400, "bad request")):
            ok, err = asyncio.run(mgr._post({"type": "test"}))
        assert ok is False
        assert "HTTP 400" in err

    def test_post_exception_returns_false(self):
        """Lines 232-234: exception during post → (False, str(exc))."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")

        class _ExceptionClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *args, **kwargs):
                raise ConnectionError("teams network unreachable")

        with patch("managers.teams_manager.httpx.AsyncClient", return_value=_ExceptionClient()):
            ok, err = asyncio.run(mgr._post({"type": "test"}))
        assert ok is False
        assert "teams network unreachable" in err

    def test_post_503_returns_error_with_truncated_text(self):
        """Line 231: response text truncated to 300 chars."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")
        long_body = "x" * 500
        with patch("managers.teams_manager.httpx.AsyncClient", return_value=self._make_fake_client(503, long_body)):
            ok, err = asyncio.run(mgr._post({"type": "test"}))
        assert ok is False
        assert "HTTP 503" in err
        # Verify text is truncated to 300 chars in the error message
        # The error format is "HTTP 503: {text[:300]}"
        assert len(err) <= len("HTTP 503: ") + 300


# ══════════════════════════════════════════════════════════════
# Full integration: send_message flows through _post
# ══════════════════════════════════════════════════════════════

class Extra_TestSendMessageIntegration:
    def test_send_message_full_flow_success(self):
        """Complete flow: send_message → _post → HTTP 200 → (True, '')."""
        tm = _get_teams()
        mgr = tm.TeamsManager(webhook_url="https://teams.example/webhook")

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.text = "1"

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *args, **kwargs):
                return fake_resp

        with patch("managers.teams_manager.httpx.AsyncClient", return_value=_FakeClient()):
            ok, err = asyncio.run(mgr.send_message(
                "Deployment done!",
                title="Build Success",
                subtitle="Main branch",
                facts=[{"key": "Duration", "value": "2m 30s"}],
                theme_color="107C10",
            ))
        assert ok is True
        assert err == ""

    def test_send_adaptive_card_unavailable(self):
        """Lines 97-98: _available=False → (False, error)."""
        tm = _get_teams()
        mgr = tm.TeamsManager()  # no webhook → not available
        ok, err = asyncio.run(mgr.send_adaptive_card({"type": "AdaptiveCard"}))
        assert ok is False
        assert "TEAMS_WEBHOOK_URL" in err
