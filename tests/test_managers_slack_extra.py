"""
Additional tests for managers/slack_manager.py to improve coverage.

Targets missing lines:
  64-65, 67, 90, 94-95, 142, 144, 147, 153-158, 170, 176, 178,
  200-217, 231-248
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch


def _get_slack(with_sdk: bool = True):
    """Reload slack_manager, optionally with a stub slack_sdk."""
    if "managers.slack_manager" in sys.modules:
        del sys.modules["managers.slack_manager"]

    if with_sdk:
        # Provide a minimal slack_sdk stub so the import succeeds
        stub = types.ModuleType("slack_sdk")
        stub.WebClient = MagicMock
        sys.modules["slack_sdk"] = stub
    else:
        # Remove any existing slack_sdk so ImportError is triggered
        sys.modules.pop("slack_sdk", None)

    import managers.slack_manager as sl
    return sl


# ══════════════════════════════════════════════════════════════
# _init_client — line 64-65, 67
# ══════════════════════════════════════════════════════════════

class TestInitClientPaths:
    def test_token_with_valid_sdk_sets_client_and_returns(self):
        """Lines 61-65: token + working SDK → _client is set, no webhook mode."""
        sl = _get_slack(with_sdk=True)
        mgr = sl.SlackManager(token="xoxb-test-token")
        # _client should be set (WebClient instance from stub)
        assert mgr._client is not None
        # Not in webhook-only mode
        assert mgr._webhook_only is False

    def test_token_with_import_error_logs_warning(self):
        """Line 67: slack_sdk missing → ImportError path → falls through to webhook check."""
        sl = _get_slack(with_sdk=False)
        # Patch the import inside _init_client to raise ImportError
        with patch.dict(sys.modules, {"slack_sdk": None}):
            if "managers.slack_manager" in sys.modules:
                del sys.modules["managers.slack_manager"]
            import managers.slack_manager as sl2
            mgr = sl2.SlackManager(token="xoxb-missing-sdk")
        # No client set because SDK not available
        assert mgr._client is None
        # Not available because no webhook either
        assert mgr._available is False

    def test_token_with_sdk_exception_falls_through(self):
        """Line 68-69: SDK raises generic Exception → manager still gracefully continues."""
        if "managers.slack_manager" in sys.modules:
            del sys.modules["managers.slack_manager"]

        bad_sdk = types.ModuleType("slack_sdk")

        def _raising_webclient(token):
            raise RuntimeError("SDK init failed")

        bad_sdk.WebClient = _raising_webclient
        sys.modules["slack_sdk"] = bad_sdk

        import managers.slack_manager as sl2
        mgr = sl2.SlackManager(token="xoxb-bad")
        # Exception was caught; no client set
        assert mgr._client is None


# ══════════════════════════════════════════════════════════════
# initialize() — lines 89-95
# ══════════════════════════════════════════════════════════════

class TestInitialize:
    def test_initialize_no_client_returns_early(self):
        """Line 89-90: no _client → initialize() exits immediately, no state change."""
        sl = _get_slack()
        mgr = sl.SlackManager()  # no token, no webhook
        mgr._client = None
        mgr._available = False
        asyncio.run(mgr.initialize())
        assert mgr._available is False

    def test_initialize_webhook_only_returns_early(self):
        """Line 89-90: _webhook_only=True → initialize() exits immediately."""
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/wh")
        assert mgr._webhook_only is True
        original_available = mgr._available
        asyncio.run(mgr.initialize())
        # State unchanged
        assert mgr._available == original_available

    def test_initialize_ok_response_sets_available(self):
        """Lines 93-95: auth_test returns ok=True → _available=True."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._webhook_only = False
        mgr._available = False

        class _OkClient:
            def auth_test(self):
                return {"ok": True, "team": "MyWorkspace"}

        mgr._client = _OkClient()
        asyncio.run(mgr.initialize())
        assert mgr._available is True

    def test_initialize_not_ok_response_sets_unavailable(self):
        """Lines 97-98: auth_test returns ok=False, no webhook → _available=False."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._webhook_only = False
        mgr._available = False
        mgr.webhook_url = ""  # no webhook fallback

        class _NotOkClient:
            def auth_test(self):
                return {"ok": False, "error": "invalid_auth"}

        mgr._client = _NotOkClient()
        asyncio.run(mgr.initialize())
        assert mgr._available is False

    def test_initialize_exception_sets_unavailable(self):
        """Lines 103-105: auth_test raises → _available=False."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._webhook_only = False
        mgr._available = False
        mgr.webhook_url = ""  # ensure no webhook fallback

        class _ErrorClient:
            def auth_test(self):
                raise ConnectionError("network failure")

        mgr._client = _ErrorClient()
        asyncio.run(mgr.initialize())
        assert mgr._available is False


# ══════════════════════════════════════════════════════════════
# send_message — SDK path, lines 140-158
# ══════════════════════════════════════════════════════════════

class TestSendMessageSdkPath:
    def test_send_message_success_returns_ts(self):
        """Lines 145-147: chat_postMessage ok=True → returns (True, ts)."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._available = True
        mgr._webhook_only = False

        class _GoodClient:
            def chat_postMessage(self, **kwargs):
                return {"ok": True, "ts": "1234567890.000001"}

        mgr._client = _GoodClient()
        ok, ts = asyncio.run(mgr.send_message("hello", channel="#general"))
        assert ok is True
        assert ts == "1234567890.000001"

    def test_send_message_with_blocks_and_thread_ts(self):
        """Line 142, 144: blocks and thread_ts kwargs are forwarded."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._available = True
        mgr._webhook_only = False
        captured = {}

        class _CapturingClient:
            def chat_postMessage(self, **kwargs):
                captured.update(kwargs)
                return {"ok": True, "ts": "999"}

        mgr._client = _CapturingClient()
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]
        asyncio.run(mgr.send_message("hi", channel="#dev", blocks=blocks, thread_ts="parent.ts"))
        assert "blocks" in captured
        assert captured["thread_ts"] == "parent.ts"

    def test_send_message_ok_false_without_status(self):
        """Lines 148-152: ok=False, no 500 status → returns plain error."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._available = True
        mgr._webhook_only = False

        class _ErrClient:
            def chat_postMessage(self, **kwargs):
                return {"ok": False, "error": "channel_not_found"}

        mgr._client = _ErrClient()
        ok, err = asyncio.run(mgr.send_message("hi", channel="#missing"))
        assert ok is False
        assert err == "channel_not_found"

    def test_send_message_raises_exception(self):
        """Lines 153-155: SDK raises → returns (False, str(exc))."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._available = True
        mgr._webhook_only = False

        class _RaisingClient:
            def chat_postMessage(self, **kwargs):
                raise OSError("network error")

        mgr._client = _RaisingClient()
        ok, err = asyncio.run(mgr.send_message("hi", channel="#general"))
        assert ok is False
        assert "network error" in err

    def test_send_message_no_channel_webhook_only_fallback(self):
        """Line 158: webhook-only mode without explicit channel → falls through to send_webhook."""
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/wh")
        # _webhook_only is True, no channel needed
        assert mgr._webhook_only is True

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.text = "ok"

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *args, **kwargs):
                return fake_resp

        with patch("managers.slack_manager.httpx.AsyncClient", return_value=_FakeClient()):
            ok, err = asyncio.run(mgr.send_message("hello"))
        assert ok is True


# ══════════════════════════════════════════════════════════════
# send_webhook — line 170, 176, 178
# ══════════════════════════════════════════════════════════════

class TestSendWebhookEdgeCases:
    def test_send_webhook_invalid_url_returns_error(self):
        """Line 170: webhook_url present but invalid format → returns error."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr.webhook_url = "https://evil.com/webhook"  # set directly, bypassing validation
        ok, err = asyncio.run(mgr.send_webhook(text="test"))
        assert ok is False
        assert "Geçersiz" in err

    def test_send_webhook_with_blocks_and_attachments(self):
        """Lines 175-178: blocks and attachments are added to payload."""
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/wh")
        captured_payload = {}

        import json as _json

        class _CapturingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, content=None, headers=None):
                captured_payload.update(_json.loads(content))
                resp = MagicMock()
                resp.status_code = 200
                resp.text = "ok"
                return resp

        blocks = [{"type": "divider"}]
        attachments = [{"text": "attachment text"}]

        with patch("managers.slack_manager.httpx.AsyncClient", return_value=_CapturingClient()):
            ok, err = asyncio.run(
                mgr.send_webhook(text="", blocks=blocks, attachments=attachments)
            )
        assert ok is True
        assert "blocks" in captured_payload
        assert "attachments" in captured_payload


# ══════════════════════════════════════════════════════════════
# list_channels — lines 200-217
# ══════════════════════════════════════════════════════════════

class TestListChannels:
    def test_list_channels_no_client_returns_error(self):
        """Lines 200-201: no client or webhook-only → error tuple."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._client = None
        ok, channels, err = asyncio.run(mgr.list_channels())
        assert ok is False
        assert channels == []
        assert "slack-sdk" in err.lower() or "token" in err.lower() or "gerekli" in err.lower()

    def test_list_channels_webhook_only_returns_error(self):
        """Lines 200-201: _webhook_only=True → error."""
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/wh")
        assert mgr._webhook_only is True
        ok, channels, err = asyncio.run(mgr.list_channels())
        assert ok is False
        assert channels == []

    def test_list_channels_success(self):
        """Lines 203-214: conversations_list ok=True → returns channel list."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._client = MagicMock()
        mgr._webhook_only = False

        fake_resp = {
            "ok": True,
            "channels": [
                {"id": "C001", "name": "general", "is_private": False},
                {"id": "C002", "name": "dev", "is_private": True},
            ],
        }

        class _ChannelClient:
            def conversations_list(self, limit=50, types=""):
                return fake_resp

        mgr._client = _ChannelClient()
        ok, channels, err = asyncio.run(mgr.list_channels(limit=10))
        assert ok is True
        assert len(channels) == 2
        assert channels[0]["name"] == "general"
        assert channels[1]["is_private"] is True
        assert err == ""

    def test_list_channels_api_error(self):
        """Line 215: ok=False → returns error string from response."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._webhook_only = False

        class _ErrorClient:
            def conversations_list(self, limit=50, types=""):
                return {"ok": False, "error": "missing_scope"}

        mgr._client = _ErrorClient()
        ok, channels, err = asyncio.run(mgr.list_channels())
        assert ok is False
        assert channels == []
        assert err == "missing_scope"

    def test_list_channels_exception(self):
        """Lines 216-217: exception during list → returns error string."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._webhook_only = False

        class _ExceptionClient:
            def conversations_list(self, **kwargs):
                raise RuntimeError("SDK crash")

        mgr._client = _ExceptionClient()
        ok, channels, err = asyncio.run(mgr.list_channels())
        assert ok is False
        assert channels == []
        assert "SDK crash" in err

    def test_list_channels_limit_capped_at_200(self):
        """Lines 204-208: limit is capped at 200."""
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._webhook_only = False
        captured_limit = {}

        class _LimitCapturingClient:
            def conversations_list(self, limit=50, types=""):
                captured_limit["limit"] = limit
                return {"ok": True, "channels": []}

        mgr._client = _LimitCapturingClient()
        asyncio.run(mgr.list_channels(limit=999))
        assert captured_limit["limit"] == 200


# ══════════════════════════════════════════════════════════════
# build_notification_blocks — lines 231-248
# ══════════════════════════════════════════════════════════════

class TestBuildNotificationBlocks:
    def test_returns_list(self):
        """Lines 231-248: build_notification_blocks returns a list."""
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("Title", "Body")
        assert isinstance(blocks, list)
        assert len(blocks) >= 2

    def test_has_header_block(self):
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("My Title", "Some body")
        header = next(b for b in blocks if b["type"] == "header")
        assert "My Title" in header["text"]["text"]

    def test_has_section_block(self):
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("T", "Body text here")
        sections = [b for b in blocks if b["type"] == "section"]
        assert len(sections) >= 1
        assert "Body text here" in sections[0]["text"]["text"]

    def test_has_divider_at_end(self):
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("T", "B")
        assert blocks[-1]["type"] == "divider"

    def test_status_emoji_info(self):
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("T", "B", status="info")
        header_text = blocks[0]["text"]["text"]
        assert "ℹ️" in header_text

    def test_status_emoji_success(self):
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("T", "B", status="success")
        header_text = blocks[0]["text"]["text"]
        assert "✅" in header_text

    def test_status_emoji_warning(self):
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("T", "B", status="warning")
        header_text = blocks[0]["text"]["text"]
        assert "⚠️" in header_text

    def test_status_emoji_error(self):
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("T", "B", status="error")
        header_text = blocks[0]["text"]["text"]
        assert "❌" in header_text

    def test_status_unknown_falls_back_to_info_emoji(self):
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("T", "B", status="unknown_xyz")
        header_text = blocks[0]["text"]["text"]
        assert "ℹ️" in header_text

    def test_fields_adds_section(self):
        """Lines 239-246: if fields provided, a fields section is appended."""
        sl = _get_slack()
        fields = [{"key": "Env", "value": "Production"}, {"key": "Version", "value": "1.0.0"}]
        blocks = sl.SlackManager.build_notification_blocks("T", "B", fields=fields)
        field_sections = [b for b in blocks if b["type"] == "section" and "fields" in b]
        assert len(field_sections) == 1
        assert any("Env" in f["text"] for f in field_sections[0]["fields"])
        assert any("Production" in f["text"] for f in field_sections[0]["fields"])

    def test_no_fields_no_extra_section(self):
        """Lines 239: fields=None → no extra section."""
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("T", "B", fields=None)
        field_sections = [b for b in blocks if b["type"] == "section" and "fields" in b]
        assert len(field_sections) == 0

    def test_block_count_with_fields(self):
        """Total blocks: header + body section + fields section + divider = 4."""
        sl = _get_slack()
        fields = [{"key": "K", "value": "V"}]
        blocks = sl.SlackManager.build_notification_blocks("T", "B", fields=fields)
        assert len(blocks) == 4

    def test_block_count_without_fields(self):
        """Total blocks: header + body section + divider = 3."""
        sl = _get_slack()
        blocks = sl.SlackManager.build_notification_blocks("T", "B")
        assert len(blocks) == 3
