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


def test_send_message_builds_full_message_card(monkeypatch):
    manager = TeamsManager(webhook_url="https://example.com")
    captured = {}

    async def _fake_post(payload):
        captured["payload"] = payload
        return True, ""

    monkeypatch.setattr(manager, "_post", _fake_post)

    facts = [{"key": "env", "value": "prod"}, {"key": "version", "value": "1.2.3"}]
    actions = [{"@type": "OpenUri", "name": "Open", "targets": [{"os": "default", "uri": "https://example.com"}]}]
    ok, err = asyncio.run(
        manager.send_message(
            text="Body",
            title="Title",
            subtitle="Subtitle",
            facts=facts,
            actions=actions,
            theme_color="ABCDEF",
        )
    )

    assert (ok, err) == (True, "")
    payload = captured["payload"]
    assert payload["@type"] == "MessageCard"
    assert payload["summary"] == "Title"
    assert payload["title"] == "Title"
    assert payload["themeColor"] == "ABCDEF"
    assert payload["text"] == "**Subtitle**\n\nBody"
    assert payload["sections"][0]["facts"] == [
        {"name": "env", "value": "prod"},
        {"name": "version", "value": "1.2.3"},
    ]
    assert payload["potentialAction"] == actions


def test_send_message_summary_falls_back_to_text(monkeypatch):
    manager = TeamsManager(webhook_url="https://example.com")

    async def _fake_post(payload):
        assert payload["summary"] == "a" * 100
        assert payload["text"] == "a" * 120
        assert "title" not in payload
        assert "sections" not in payload
        assert "potentialAction" not in payload
        return True, ""

    monkeypatch.setattr(manager, "_post", _fake_post)
    ok, err = asyncio.run(manager.send_message("a" * 120))
    assert (ok, err) == (True, "")


def test_send_adaptive_card_requires_webhook_and_wraps_payload(monkeypatch):
    ok, err = asyncio.run(TeamsManager().send_adaptive_card({"type": "AdaptiveCard"}))
    assert (ok, err) == (False, "TEAMS_WEBHOOK_URL ayarlanmamış")

    manager = TeamsManager(webhook_url="https://example.com")

    async def _fake_post(payload):
        assert payload["type"] == "message"
        attachment = payload["attachments"][0]
        assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert attachment["contentUrl"] is None
        assert attachment["content"] == {"type": "AdaptiveCard", "version": "1.4"}
        return True, ""

    monkeypatch.setattr(manager, "_post", _fake_post)
    assert asyncio.run(manager.send_adaptive_card({"type": "AdaptiveCard", "version": "1.4"})) == (True, "")


def test_send_notification_unknown_status_and_link(monkeypatch):
    manager = TeamsManager(webhook_url="https://example.com")

    async def _fake_send_message(**kwargs):
        assert kwargs["theme_color"] == "0078D4"
        assert kwargs["facts"] == [{"key": "k", "value": "v"}]
        assert kwargs["actions"] == [
            {
                "@type": "OpenUri",
                "name": "Dokümantasyon",
                "targets": [{"os": "default", "uri": "https://docs.example.com"}],
            }
        ]
        return True, ""

    monkeypatch.setattr(manager, "send_message", _fake_send_message)
    assert asyncio.run(
        manager.send_notification(
            "Başlık",
            "Gövde",
            status="custom",
            details=[{"key": "k", "value": "v"}],
            link_url="https://docs.example.com",
            link_label="Dokümantasyon",
        )
    ) == (True, "")


def test_build_approval_card_without_optional_fields():
    card = TeamsManager.build_approval_card(
        request_id="42",
        title="Onay Bekliyor",
        description="İşlemi gözden geçirin",
    )
    assert card["body"][0]["text"] == "Onay Bekliyor"
    assert len(card["body"]) == 2
    assert card["actions"] == []


def test_build_summary_card_without_description_or_metrics():
    card = TeamsManager.build_summary_card(title="Sadece Başlık", metrics=[])
    assert card["type"] == "AdaptiveCard"
    assert len(card["body"]) == 1
    assert card["body"][0]["text"] == "Sadece Başlık"


def test_post_handles_all_http_branches(monkeypatch):
    manager = TeamsManager(webhook_url="https://example.com")

    class _Resp:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

    responses = [
        _Resp(202, "1"),
        _Resp(201, "unexpected-but-success"),
        _Resp(500, "x" * 400),
    ]

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return responses.pop(0)

    monkeypatch.setattr("managers.teams_manager.httpx.AsyncClient", _Client)

    assert asyncio.run(manager._post({"a": 1})) == (True, "")
    assert asyncio.run(manager._post({"a": 2})) == (True, "")

    ok, err = asyncio.run(manager._post({"a": 3}))
    assert not ok
    assert err.startswith("HTTP 500: ")
    assert len(err) == len("HTTP 500: ") + 300


def test_post_returns_exception_message(monkeypatch):
    manager = TeamsManager(webhook_url="https://example.com")

    class _ClientRaises:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr("managers.teams_manager.httpx.AsyncClient", _ClientRaises)
    assert asyncio.run(manager._post({"hello": "world"})) == (False, "network down")
