"""Unit tests for ``plugins.slack_notification_agent``."""

import asyncio
import sys
import types
from types import SimpleNamespace

# Test ortamında ağır bağımlılıkları atlamak için minimal BaseAgent stub'ı.
if "agent.base_agent" not in sys.modules:  # pragma: no cover
    fake_base_agent = types.ModuleType("agent.base_agent")

    class BaseAgent:  # pragma: no cover - test helper
        """Minimal stand-in for ``agent.base_agent.BaseAgent`` when it is not importable."""

        pass

    fake_base_agent.BaseAgent = BaseAgent
    sys.modules["agent.base_agent"] = fake_base_agent

from plugins.slack_notification_agent import SlackNotificationAgent


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _agent(webhook: str = "https://hooks.slack.test") -> SlackNotificationAgent:
    agent = SlackNotificationAgent.__new__(SlackNotificationAgent)
    agent.cfg = SimpleNamespace(SLACK_DEFAULT_CHANNEL="general", SLACK_WEBHOOK_URL=webhook)
    return agent


def test_extract_channel_finds_hashtag_without_hash() -> None:
    """Extract channel finds hashtag without hash."""
    assert SlackNotificationAgent._extract_channel("deploy #dev_ops now") == "dev_ops"


def test_extract_message_removes_channel_and_strips() -> None:
    """Extract message removes channel and strips."""
    assert SlackNotificationAgent._extract_message("  #alerts build bitti  ") == "build bitti"


def test_extract_message_returns_default_when_only_channel_given() -> None:
    """Extract message returns default when only channel given."""
    assert (
        SlackNotificationAgent._extract_message(" #alerts ")
        == "SİDAR tarafından tetiklenen Slack bildirimi."
    )


def test_format_response_success_and_failure() -> None:
    """Format response success and failure."""
    ok_text = SlackNotificationAgent._format_response(True, "ok", "ops", "hello")
    fail_text = SlackNotificationAgent._format_response(False, "boom", "", "hello")

    assert "#ops kanalına bildirim gönderildi" in ok_text
    assert "varsayılan Slack kanalına bildirim gönderilemedi" in fail_text


def test_run_task_requires_message() -> None:
    """Run task requires message."""
    agent = _agent()

    assert asyncio.run(agent.run_task("   ")) == "Slack bildirimi göndermek için mesaj gerekli."


def test_run_task_requires_webhook_config() -> None:
    """Run task requires webhook config."""
    agent = _agent(webhook="")

    result = asyncio.run(agent.run_task("merhaba"))

    assert "SLACK_WEBHOOK_URL" in result


def test_run_task_posts_payload_and_uses_default_channel(monkeypatch) -> None:
    """Run task posts payload and uses default channel."""
    agent = _agent()

    async def _fake_to_thread(func, req, **kwargs):
        assert req.full_url == "https://hooks.slack.test"
        assert req.method == "POST"
        assert kwargs.get("timeout") == 10
        assert req.data == b'{"text": "hello world"}'
        return _FakeResponse(b"ok")

    monkeypatch.setattr("plugins.slack_notification_agent.asyncio.to_thread", _fake_to_thread)

    result = asyncio.run(agent.run_task("hello world"))

    assert "#general kanalına bildirim gönderildi" in result


def test_run_task_uses_explicit_channel_and_handles_failure(monkeypatch) -> None:
    """Run task uses explicit channel and handles failure."""
    agent = _agent()

    async def _fake_to_thread(_func, _req, **kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr("plugins.slack_notification_agent.asyncio.to_thread", _fake_to_thread)

    result = asyncio.run(agent.run_task("#qa release fail"))

    assert result == "#qa kanalına bildirim gönderilemedi: timeout"
