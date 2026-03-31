"""
managers/slack_manager.py için birim testleri.
_is_valid_webhook_url, SlackManager constructor (webhook mode/no config),
is_available, send_message disabled path, send_webhook disabled path.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch


def _get_slack():
    if "managers.slack_manager" in sys.modules:
        del sys.modules["managers.slack_manager"]
    # Stub slack_sdk so imports don't fail
    if "slack_sdk" not in sys.modules:
        import types
        stub = types.ModuleType("slack_sdk")
        stub.WebClient = None
        sys.modules["slack_sdk"] = stub
    import managers.slack_manager as sl
    return sl


# ══════════════════════════════════════════════════════════════
# _is_valid_webhook_url
# ══════════════════════════════════════════════════════════════

class TestIsValidWebhookUrl:
    def test_valid_hooks_slack_url(self):
        sl = _get_slack()
        assert sl._is_valid_webhook_url("https://hooks.slack.com/services/T/B/xxx") is True

    def test_valid_gov_url(self):
        sl = _get_slack()
        assert sl._is_valid_webhook_url("https://hooks.slack-gov.com/services/T/B/xxx") is True

    def test_invalid_domain(self):
        sl = _get_slack()
        assert sl._is_valid_webhook_url("https://hooks.notslack.com/services") is False

    def test_http_not_https(self):
        sl = _get_slack()
        assert sl._is_valid_webhook_url("http://hooks.slack.com/services") is False

    def test_empty_string(self):
        sl = _get_slack()
        assert sl._is_valid_webhook_url("") is False

    def test_whitespace_only(self):
        sl = _get_slack()
        assert sl._is_valid_webhook_url("   ") is False


# ══════════════════════════════════════════════════════════════
# SlackManager — constructor
# ══════════════════════════════════════════════════════════════

class TestSlackManagerInit:
    def test_no_credentials_not_available(self):
        sl = _get_slack()
        mgr = sl.SlackManager()
        assert mgr.is_available() is False

    def test_valid_webhook_sets_available(self):
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/xxx")
        assert mgr.is_available() is True
        assert mgr._webhook_only is True

    def test_invalid_webhook_not_available(self):
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://notslack.com/webhook")
        assert mgr.is_available() is False

    def test_default_channel_stored(self):
        sl = _get_slack()
        mgr = sl.SlackManager(default_channel="#general")
        assert mgr.default_channel == "#general"

    def test_tokens_stripped(self):
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="  https://hooks.slack.com/services/T/B/xxx  ")
        assert mgr.webhook_url == "https://hooks.slack.com/services/T/B/xxx"


# ══════════════════════════════════════════════════════════════
# send_message — disabled path
# ══════════════════════════════════════════════════════════════

class TestSendMessageDisabled:
    def test_returns_false_when_not_available(self):
        sl = _get_slack()
        mgr = sl.SlackManager()
        ok, err = asyncio.run(mgr.send_message("hello"))
        assert ok is False
        assert err  # error message non-empty


# ══════════════════════════════════════════════════════════════
# send_webhook — disabled path
# ══════════════════════════════════════════════════════════════

class TestSendWebhookDisabled:
    def test_returns_false_when_no_webhook(self):
        sl = _get_slack()
        mgr = sl.SlackManager()
        ok, err = asyncio.run(mgr.send_webhook(text="test"))
        assert ok is False


class _FakeSlackResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class _FakeSlackAsyncClient:
    def __init__(self, *, response: _FakeSlackResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return self._response


class TestSlackWebhookHttpResponses:
    def test_send_webhook_200_returns_success(self):
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/ok")
        fake_response = _FakeSlackResponse(200, "ok")

        with patch(
            "managers.slack_manager.httpx.AsyncClient",
            return_value=_FakeSlackAsyncClient(response=fake_response),
        ):
            ok, err = asyncio.run(mgr.send_webhook(text="hello"))

        assert ok is True
        assert err == ""

    def test_send_webhook_400_returns_error(self):
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/bad")
        fake_response = _FakeSlackResponse(400, "bad request")

        with patch(
            "managers.slack_manager.httpx.AsyncClient",
            return_value=_FakeSlackAsyncClient(response=fake_response),
        ):
            ok, err = asyncio.run(mgr.send_webhook(text="hello"))

        assert ok is False
        assert "HTTP 400" in err

    def test_send_webhook_500_returns_error(self):
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/fail")
        fake_response = _FakeSlackResponse(500, "internal error")

        with patch(
            "managers.slack_manager.httpx.AsyncClient",
            return_value=_FakeSlackAsyncClient(response=fake_response),
        ):
            ok, err = asyncio.run(mgr.send_webhook(text="hello"))

        assert ok is False
        assert "HTTP 500" in err

    def test_send_webhook_timeout_exception_returns_error_text(self):
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/timeout")

        class _RaisingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *_args, **_kwargs):
                raise TimeoutError("webhook timeout")

        with patch("managers.slack_manager.httpx.AsyncClient", return_value=_RaisingClient()):
            ok, err = asyncio.run(mgr.send_webhook(text="hello"))

        assert ok is False
        assert "timeout" in err.lower()


class TestSlackSdkTokenFailures:
    def test_send_message_invalid_token_returns_api_error(self):
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._available = True
        mgr._webhook_only = False

        class _FakeClient:
            def chat_postMessage(self, **_kwargs):
                return {"ok": False, "error": "invalid_auth"}

        mgr._client = _FakeClient()
        ok, err = asyncio.run(mgr.send_message("hello", channel="#general"))
        assert ok is False
        assert err == "invalid_auth"

    def test_send_message_500_status_returns_formatted_error(self):
        sl = _get_slack()
        mgr = sl.SlackManager()
        mgr._available = True
        mgr._webhook_only = False

        class _FakeClient:
            def chat_postMessage(self, **_kwargs):
                return {"ok": False, "error": "internal_error", "status": 500}

        mgr._client = _FakeClient()
        ok, err = asyncio.run(mgr.send_message("hello", channel="#general"))
        assert ok is False
        assert "Slack API hatası (500)" in err

    def test_send_message_missing_channel_returns_error(self):
        sl = _get_slack()
        mgr = sl.SlackManager(token="xoxb-token")
        mgr._available = True
        mgr._webhook_only = False
        mgr._client = object()

        ok, err = asyncio.run(mgr.send_message("hello", channel=""))
        assert ok is False
        assert "Kanal belirtilmedi" in err


class TestSlackInitializeGracefulDegradation:
    def test_initialize_falls_back_to_webhook_when_sdk_auth_raises(self):
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/fallback")
        mgr._webhook_only = False
        mgr._available = False

        class _FailingClient:
            def auth_test(self):
                raise RuntimeError("slack auth crashed")

        mgr._client = _FailingClient()
        asyncio.run(mgr.initialize())
        assert mgr._available is True
        assert mgr._webhook_only is True

    def test_initialize_falls_back_to_webhook_when_sdk_auth_not_ok(self):
        sl = _get_slack()
        mgr = sl.SlackManager(webhook_url="https://hooks.slack.com/services/T/B/fallback2")
        mgr._webhook_only = False
        mgr._available = False

        class _InvalidTokenClient:
            def auth_test(self):
                return {"ok": False, "error": "invalid_auth"}

        mgr._client = _InvalidTokenClient()
        asyncio.run(mgr.initialize())
        assert mgr._available is True
        assert mgr._webhook_only is True
