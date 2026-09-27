"""Unit tests for ``managers.slack_manager``."""

import asyncio
import sys
import types

import pytest


def _ensure_httpx_stub() -> None:
    if "httpx" not in sys.modules:
        fake_httpx = types.ModuleType("httpx")

        class _DummyAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):  # pragma: no cover
                raise RuntimeError("dummy client should be patched in tests")

        fake_httpx.AsyncClient = _DummyAsyncClient
        sys.modules["httpx"] = fake_httpx


_ensure_httpx_stub()

from managers.slack_manager import SlackManager, _is_valid_webhook_url


def _run(coro):
    return asyncio.run(coro)


def test_is_valid_webhook_url_accepts_supported_domains() -> None:
    """Is valid webhook url accepts supported domains."""
    assert _is_valid_webhook_url("https://hooks.slack.com/services/T000/B000/XXX") is True
    assert _is_valid_webhook_url(" https://hooks.slack-gov.com/services/T000/B000/XXX ") is True


def test_is_valid_webhook_url_rejects_other_urls() -> None:
    """Is valid webhook url rejects other urls."""
    assert _is_valid_webhook_url("") is False
    assert _is_valid_webhook_url("https://example.com/hook") is False


def test_init_client_uses_sdk_when_token_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Init client uses sdk when token present."""
    created = {}

    class FakeWebClient:
        def __init__(self, token: str) -> None:
            created["token"] = token

    fake_sdk = types.ModuleType("slack_sdk")
    fake_sdk.WebClient = FakeWebClient
    monkeypatch.setitem(sys.modules, "slack_sdk", fake_sdk)

    manager = SlackManager(token=" xoxb-token ")

    assert created["token"] == "xoxb-token"
    assert manager._client is not None
    assert manager.is_available() is False
    assert manager._webhook_only is False


def test_init_client_sdk_import_error_falls_back_to_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Init client sdk import error falls back to webhook."""
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "slack_sdk":
            raise ImportError("missing slack sdk")
        return original_import(name, globals, locals, fromlist, level)

    assert fake_import("json").__name__ == "json"
    monkeypatch.setattr("builtins.__import__", fake_import)

    manager = SlackManager(token="xoxb-token", webhook_url="https://hooks.slack.com/services/T/B/X")

    assert manager._client is None
    assert manager.is_available() is True
    assert manager._webhook_only is True


def test_ensure_httpx_stub_adds_stub_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure httpx stub adds stub when missing."""
    monkeypatch.delitem(sys.modules, "httpx", raising=False)
    _ensure_httpx_stub()
    assert "httpx" in sys.modules


def test_httpx_stub_async_client_context_manager_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    """Httpx stub async client context manager methods."""
    monkeypatch.delitem(sys.modules, "httpx", raising=False)
    _ensure_httpx_stub()

    client = sys.modules["httpx"].AsyncClient()
    entered = _run(client.__aenter__())
    exited = _run(client.__aexit__(None, None, None))

    assert entered is client
    assert exited is False


def test_init_client_sdk_other_exception_falls_back_to_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Init client sdk other exception falls back to webhook."""

    class BrokenWebClient:
        def __init__(self, token: str) -> None:
            raise RuntimeError("boom")

    fake_sdk = types.ModuleType("slack_sdk")
    fake_sdk.WebClient = BrokenWebClient
    monkeypatch.setitem(sys.modules, "slack_sdk", fake_sdk)

    manager = SlackManager(token="xoxb-token", webhook_url="https://hooks.slack.com/services/T/B/X")

    assert manager._client is None
    assert manager.is_available() is True
    assert manager._webhook_only is True


def test_init_client_rejects_invalid_webhook_url() -> None:
    """Init client rejects invalid webhook url."""
    manager = SlackManager(webhook_url="https://invalid.example.com/webhook")

    assert manager.is_available() is False
    assert manager._webhook_only is False


def test_initialize_noop_when_client_missing() -> None:
    """Initialize noop when client missing."""
    manager = SlackManager()
    _run(manager.initialize())
    assert manager.is_available() is False


def test_initialize_noop_when_webhook_only() -> None:
    """Initialize noop when webhook only."""
    manager = SlackManager(webhook_url="https://hooks.slack.com/services/T/B/X")
    _run(manager.initialize())
    assert manager.is_available() is True
    assert manager._webhook_only is True


def test_initialize_success_sets_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initialize success sets available."""

    class FakeClient:
        def auth_test(self):
            return {"ok": True, "team": "Acme"}

    manager = SlackManager()
    manager._client = FakeClient()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    _run(manager.initialize())

    assert manager.is_available() is True


def test_initialize_failed_auth_without_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initialize failed auth without webhook."""

    class FakeClient:
        def auth_test(self):
            return {"ok": False, "error": "invalid_auth"}

    manager = SlackManager()
    manager._client = FakeClient()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    _run(manager.initialize())

    assert manager.is_available() is False
    assert manager._webhook_only is False


def test_initialize_exception_with_webhook_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initialize exception with webhook fallback."""

    class FakeClient:
        def auth_test(self):
            raise RuntimeError("network")

    manager = SlackManager(webhook_url="https://hooks.slack.com/services/T/B/X")
    manager._client = FakeClient()
    manager._webhook_only = False
    manager._available = False

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    _run(manager.initialize())

    assert manager.is_available() is True
    assert manager._webhook_only is True


def test_send_message_returns_not_available_when_disabled() -> None:
    """Send message returns not available when disabled."""
    manager = SlackManager()

    ok, error = _run(manager.send_message(text="hello"))

    assert ok is False
    assert error == "Slack bağlantısı mevcut değil"


def test_send_message_requires_channel_for_sdk_mode() -> None:
    """Send message requires channel for sdk mode."""
    manager = SlackManager()
    manager._available = True
    manager._webhook_only = False

    ok, error = _run(manager.send_message(text="hello"))

    assert ok is False
    assert error == "Kanal belirtilmedi"


def test_send_message_sdk_success_with_blocks_and_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send message sdk success with blocks and thread."""
    captured = {}

    class FakeClient:
        def chat_postMessage(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True, "ts": "123.456"}

    manager = SlackManager(default_channel="#alerts")
    manager._available = True
    manager._client = FakeClient()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    ok, ts = _run(
        manager.send_message(
            text="hello",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}],
            thread_ts="111.222",
        )
    )

    assert ok is True
    assert ts == "123.456"
    assert captured["channel"] == "#alerts"
    assert captured["thread_ts"] == "111.222"


def test_send_message_sdk_returns_5xx_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send message sdk returns 5xx error."""

    class FakeClient:
        def chat_postMessage(self, **kwargs):
            return {"ok": False, "error": "server_error", "status": 503}

    manager = SlackManager(default_channel="#alerts")
    manager._available = True
    manager._client = FakeClient()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    ok, error = _run(manager.send_message(text="hello"))

    assert ok is False
    assert error == "Slack API hatası (503): server_error"


def test_send_message_sdk_returns_non_5xx_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send message sdk returns non 5xx error."""

    class FakeClient:
        def chat_postMessage(self, **kwargs):
            return {"ok": False, "error": "channel_not_found", "status": 404}

    manager = SlackManager(default_channel="#alerts")
    manager._available = True
    manager._client = FakeClient()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    ok, error = _run(manager.send_message(text="hello"))

    assert ok is False
    assert error == "channel_not_found"


def test_send_message_sdk_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send message sdk exception."""

    class FakeClient:
        def chat_postMessage(self, **kwargs):
            raise RuntimeError("send failed")

    manager = SlackManager(default_channel="#alerts")
    manager._available = True
    manager._client = FakeClient()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    ok, error = _run(manager.send_message(text="hello"))

    assert ok is False
    assert error == "send failed"


def test_send_message_webhook_fallback_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send message webhook fallback path."""
    manager = SlackManager(webhook_url="https://hooks.slack.com/services/T/B/X")
    manager._available = True
    manager._webhook_only = True

    async def fake_send_webhook(text, blocks=None, attachments=None):
        assert text == "hello"
        assert blocks == [{"type": "section"}]
        assert attachments is None
        return True, ""

    monkeypatch.setattr(manager, "send_webhook", fake_send_webhook)

    ok, err = _run(manager.send_message(text="hello", blocks=[{"type": "section"}]))

    assert ok is True
    assert err == ""


def test_send_webhook_requires_url() -> None:
    """Send webhook requires url."""
    manager = SlackManager()

    ok, err = _run(manager.send_webhook(text="x"))

    assert ok is False
    assert err == "SLACK_WEBHOOK_URL ayarlanmamış"


def test_send_webhook_rejects_invalid_url() -> None:
    """Send webhook rejects invalid url."""
    manager = SlackManager(webhook_url="https://example.com/not-slack")

    ok, err = _run(manager.send_webhook(text="x"))

    assert ok is False
    assert err == "Geçersiz Slack webhook URL formatı"


def test_send_webhook_success_and_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send webhook success and payload."""
    recorded = {}

    class FakeResponse:
        status_code = 200
        text = "ok"

    class FakeAsyncClient:
        def __init__(self, timeout):
            recorded["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, content, headers):
            recorded["url"] = url
            recorded["content"] = content
            recorded["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("managers.slack_manager.httpx.AsyncClient", FakeAsyncClient)

    manager = SlackManager(webhook_url="https://hooks.slack.com/services/T/B/X")
    ok, err = _run(
        manager.send_webhook(
            text="hello",
            blocks=[{"type": "section"}],
            attachments=[{"text": "a"}],
        )
    )

    assert ok is True
    assert err == ""
    assert recorded["url"] == "https://hooks.slack.com/services/T/B/X"
    assert '"text": "hello"' in recorded["content"]
    assert recorded["headers"]["Content-Type"] == "application/json"


def test_send_webhook_http_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send webhook http error response."""

    class FakeResponse:
        status_code = 500
        text = "failure"

    class FakeAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, content, headers):
            return FakeResponse()

    monkeypatch.setattr("managers.slack_manager.httpx.AsyncClient", FakeAsyncClient)

    manager = SlackManager(webhook_url="https://hooks.slack.com/services/T/B/X")
    ok, err = _run(manager.send_webhook(blocks=[{"type": "section"}]))

    assert ok is False
    assert err == "HTTP 500: failure"


def test_send_webhook_attachments_without_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send webhook attachments without blocks."""
    recorded = {}

    class FakeResponse:
        status_code = 400
        text = "bad payload"

    class FakeAsyncClient:
        def __init__(self, timeout):
            recorded["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, content, headers):
            recorded["url"] = url
            recorded["content"] = content
            recorded["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("managers.slack_manager.httpx.AsyncClient", FakeAsyncClient)

    manager = SlackManager(webhook_url="https://hooks.slack.com/services/T/B/X")
    ok, err = _run(manager.send_webhook(attachments=[{"text": "only attachment"}]))

    assert ok is False
    assert err == "HTTP 400: bad payload"
    assert '"attachments": [{"text": "only attachment"}]' in recorded["content"]
    assert '"blocks"' not in recorded["content"]


def test_send_webhook_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Send webhook exception."""

    class FakeAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, content, headers):
            raise RuntimeError("post failed")

    monkeypatch.setattr("managers.slack_manager.httpx.AsyncClient", FakeAsyncClient)

    manager = SlackManager(webhook_url="https://hooks.slack.com/services/T/B/X")
    ok, err = _run(manager.send_webhook(blocks=[{"type": "section"}]))

    assert ok is False
    assert err == "post failed"


def test_list_channels_requires_sdk() -> None:
    """List channels requires sdk."""
    manager = SlackManager(webhook_url="https://hooks.slack.com/services/T/B/X")

    ok, channels, err = _run(manager.list_channels())

    assert ok is False
    assert channels == []
    assert err == "Kanal listesi için slack-sdk ve bot token gerekli"


def test_list_channels_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """List channels success."""

    class FakeClient:
        def conversations_list(self, **kwargs):
            assert kwargs["limit"] == 200
            assert kwargs["types"] == "public_channel,private_channel"
            return {
                "ok": True,
                "channels": [
                    {"id": "C1", "name": "genel", "is_private": False},
                    {"id": "C2", "name": "gizli"},
                ],
            }

    manager = SlackManager()
    manager._client = FakeClient()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    ok, channels, err = _run(manager.list_channels(limit=999))

    assert ok is True
    assert err == ""
    assert channels == [
        {"id": "C1", "name": "genel", "is_private": False},
        {"id": "C2", "name": "gizli", "is_private": False},
    ]


def test_list_channels_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """List channels api error."""

    class FakeClient:
        def conversations_list(self, **kwargs):
            return {"ok": False, "error": "invalid_auth"}

    manager = SlackManager()
    manager._client = FakeClient()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    ok, channels, err = _run(manager.list_channels())

    assert ok is False
    assert channels == []
    assert err == "invalid_auth"


def test_list_channels_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """List channels exception."""

    class FakeClient:
        def conversations_list(self, **kwargs):
            raise RuntimeError("list failed")

    manager = SlackManager()
    manager._client = FakeClient()

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    ok, channels, err = _run(manager.list_channels())

    assert ok is False
    assert channels == []
    assert err == "list failed"


def test_build_notification_blocks_without_fields() -> None:
    """Build notification blocks without fields."""
    blocks = SlackManager.build_notification_blocks(
        title="Deploy",
        body="Dağıtım tamamlandı",
        status="success",
    )

    assert blocks[0]["type"] == "header"
    assert blocks[0]["text"]["text"].startswith("✅ Deploy")
    assert blocks[-1] == {"type": "divider"}


def test_build_notification_blocks_with_fields_and_unknown_status() -> None:
    """Build notification blocks with fields and unknown status."""
    blocks = SlackManager.build_notification_blocks(
        title="Durum",
        body="Özet",
        status="unknown",
        fields=[{"key": "Sürüm", "value": "v1.2.3"}],
    )

    assert blocks[0]["text"]["text"].startswith("ℹ️ Durum")
    assert blocks[2]["type"] == "section"
    assert blocks[2]["fields"][0]["text"] == "*Sürüm*\nv1.2.3"
