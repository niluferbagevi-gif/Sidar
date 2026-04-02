import asyncio
import sys
import types


class _DummyAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *_args, **_kwargs):
        return types.SimpleNamespace(status_code=200, text="ok")


sys.modules.setdefault("httpx", types.SimpleNamespace(AsyncClient=_DummyAsyncClient))

from managers.slack_manager import SlackManager, _is_valid_webhook_url


def test_slack_webhook_url_validation():
    assert _is_valid_webhook_url("https://hooks.slack.com/services/A/B/C")
    assert not _is_valid_webhook_url("https://example.com")


def test_send_message_unavailable():
    manager = SlackManager()
    ok, err = asyncio.run(manager.send_message("hello"))
    assert not ok
    assert "mevcut değil" in err


def test_send_webhook_invalid_url():
    manager = SlackManager(webhook_url="https://example.com")
    ok, err = asyncio.run(manager.send_webhook("hello"))
    assert not ok
    assert "Geçersiz" in err


def test_build_notification_blocks():
    blocks = SlackManager.build_notification_blocks(
        title="Deploy",
        body="Başarılı",
        status="success",
        fields=[{"key": "Repo", "value": "sidar"}],
    )
    assert blocks[0]["type"] == "header"
    assert blocks[-1]["type"] == "divider"


def test_list_channels_requires_sdk():
    manager = SlackManager(webhook_url="https://hooks.slack.com/services/A/B/C")
    ok, channels, err = asyncio.run(manager.list_channels())
    assert not ok
    assert channels == []
    assert "slack-sdk" in err
