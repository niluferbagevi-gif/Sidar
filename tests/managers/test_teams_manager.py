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

from managers.teams_manager import TeamsManager


def test_teams_availability():
    assert not TeamsManager().is_available()
    assert TeamsManager(webhook_url="https://example.com").is_available()


def test_send_message_requires_webhook():
    ok, err = asyncio.run(TeamsManager().send_message("hello"))
    assert not ok
    assert "TEAMS_WEBHOOK_URL" in err


def test_build_cards_helpers():
    approval = TeamsManager.build_approval_card(
        request_id="1",
        title="Onay",
        description="Açıklama",
        requester="tester",
        approve_url="https://approve",
        reject_url="https://reject",
    )
    assert approval["type"] == "AdaptiveCard"
    assert len(approval["actions"]) == 2

    summary = TeamsManager.build_summary_card(
        title="Özet",
        metrics=[{"key": "pass", "value": "10"}],
        description="desc",
    )
    assert summary["body"][0]["text"] == "Özet"


def test_send_notification_delegates(monkeypatch):
    manager = TeamsManager(webhook_url="https://example.com")

    async def _fake_send_message(**kwargs):
        assert kwargs["theme_color"] == "107C10"
        return True, ""

    monkeypatch.setattr(manager, "send_message", _fake_send_message)
    ok, err = asyncio.run(manager.send_notification("t", "b", status="success"))
    assert ok
    assert err == ""
