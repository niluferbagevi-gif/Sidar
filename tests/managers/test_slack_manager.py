from __future__ import annotations

import asyncio
import sys
import types


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        self._response = kwargs.get("response")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *_args, **_kwargs):
        return self._response or types.SimpleNamespace(status_code=200, text="ok")


sys.modules.setdefault("httpx", types.SimpleNamespace(AsyncClient=_DummyAsyncClient))

import managers.slack_manager as slack_mod
from managers.slack_manager import SlackManager, _is_valid_webhook_url


def test_slack_webhook_url_validation():
    assert _is_valid_webhook_url("https://hooks.slack.com/services/A/B/C")
    assert _is_valid_webhook_url("https://hooks.slack-gov.com/services/A/B/C")
    assert not _is_valid_webhook_url("https://example.com")


def test_send_message_unavailable():
    manager = SlackManager()
    ok, err = asyncio.run(manager.send_message("hello"))
    assert not ok
    assert "mevcut değil" in err


def test_send_message_requires_channel_when_sdk_mode(monkeypatch):
    manager = SlackManager()
    manager._available = True
    manager._webhook_only = False
    manager._client = object()
    ok, err = asyncio.run(manager.send_message("hello", channel=""))
    assert ok is False
    assert "Kanal" in err


def test_send_webhook_invalid_url():
    manager = SlackManager(webhook_url="https://example.com")
    ok, err = asyncio.run(manager.send_webhook("hello"))
    assert not ok
    assert "Geçersiz" in err


def test_send_webhook_http_error(monkeypatch):
    class _Client(_DummyAsyncClient):
        async def post(self, *_args, **_kwargs):
            return types.SimpleNamespace(status_code=500, text="fail")

    monkeypatch.setattr(slack_mod.httpx, "AsyncClient", _Client)
    manager = SlackManager(webhook_url="https://hooks.slack.com/services/A/B/C")
    ok, err = asyncio.run(manager.send_webhook("hello"))
    assert ok is False
    assert "HTTP 500" in err


def test_send_message_sdk_success_and_server_error(monkeypatch):
    class _Client:
        def __init__(self):
            self.calls = 0

        def chat_postMessage(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"ok": True, "ts": "123.4"}
            return {"ok": False, "status": 503, "error": "down"}

    manager = SlackManager()
    manager._available = True
    manager._client = _Client()

    async def _to_thread(fn, **kwargs):
        return fn(**kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _to_thread)

    ok, value = asyncio.run(manager.send_message("hello", channel="#dev"))
    assert ok is True and value == "123.4"

    ok, value = asyncio.run(manager.send_message("again", channel="#dev"))
    assert ok is False and "503" in value


def test_initialize_sets_available_and_webhook_fallback(monkeypatch):
    manager = SlackManager(webhook_url="https://hooks.slack.com/services/A/B/C")

    class _GoodClient:
        def auth_test(self):
            return {"ok": True, "team": "SIDAR"}

    manager._client = _GoodClient()
    manager._webhook_only = False
    monkeypatch.setattr(asyncio, "to_thread", lambda fn, *args, **kwargs: fn(*args, **kwargs))
    asyncio.run(manager.initialize())
    assert manager.is_available() is True

    class _BadClient:
        def auth_test(self):
            raise RuntimeError("auth failed")

    manager._client = _BadClient()
    manager._available = False
    manager._webhook_only = False
    asyncio.run(manager.initialize())
    assert manager.is_available() is True
    assert manager._webhook_only is True


def test_build_notification_blocks():
    blocks = SlackManager.build_notification_blocks(
        title="Deploy",
        body="Başarılı",
        status="success",
        fields=[{"key": "Repo", "value": "sidar"}],
    )
    assert blocks[0]["type"] == "header"
    assert blocks[-1]["type"] == "divider"


def test_list_channels_requires_sdk_and_success(monkeypatch):
    manager = SlackManager(webhook_url="https://hooks.slack.com/services/A/B/C")
    ok, channels, err = asyncio.run(manager.list_channels())
    assert not ok
    assert channels == []
    assert "slack-sdk" in err

    class _Client:
        def conversations_list(self, **_kwargs):
            return {"ok": True, "channels": [{"id": "C1", "name": "genel", "is_private": False}]}

    manager._client = _Client()
    manager._webhook_only = False
    async def _to_thread(fn, **kwargs):
        return fn(**kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _to_thread)
    ok, channels, err = asyncio.run(manager.list_channels(limit=999))
    assert ok is True and err == ""
    assert channels[0]["id"] == "C1"
