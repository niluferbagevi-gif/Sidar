from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass
from typing import Any

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

from managers.teams_manager import TeamsManager


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _FakeResponse:
    status_code: int
    text: str


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self._error is not None:
            raise self._error
        return self._response


def test_init_and_is_available_flag() -> None:
    assert TeamsManager().is_available() is False
    assert TeamsManager(webhook_url=" https://example.test/hook ").is_available() is True


def test_ensure_httpx_stub_adds_stub_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "httpx", raising=False)
    _ensure_httpx_stub()
    assert "httpx" in sys.modules


def test_httpx_stub_async_client_context_manager_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "httpx", raising=False)
    _ensure_httpx_stub()

    client = sys.modules["httpx"].AsyncClient()
    entered = _run(client.__aenter__())
    exited = _run(client.__aexit__(None, None, None))

    assert entered is client
    assert exited is False


def test_send_message_requires_webhook() -> None:
    ok, err = _run(TeamsManager().send_message("hello"))
    assert ok is False
    assert "TEAMS_WEBHOOK_URL" in err


def test_send_message_builds_payload_with_all_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeAsyncClient(response=_FakeResponse(status_code=200, text="1"))

    def _factory(*args, **kwargs):
        return client

    monkeypatch.setattr("managers.teams_manager.httpx.AsyncClient", _factory)

    mgr = TeamsManager(webhook_url="https://example.test/hook")
    ok, err = _run(
        mgr.send_message(
            text="Body content",
            title="Alert",
            subtitle="Sub",
            facts=[{"key": "Service", "value": "API"}],
            actions=[{"@type": "OpenUri", "name": "Open"}],
            theme_color="ABCDEF",
        )
    )

    assert ok is True
    assert err == ""

    call = client.calls[0]
    assert call["url"] == "https://example.test/hook"
    assert call["headers"]["Content-Type"] == "application/json"
    assert '"themeColor": "ABCDEF"' in call["content"]
    assert '"title": "Alert"' in call["content"]
    assert '"**Sub**\\n\\nBody content"' in call["content"]
    assert '"potentialAction"' in call["content"]


def test_send_message_omits_optional_fields_when_not_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeAsyncClient(response=_FakeResponse(status_code=200, text="1"))
    monkeypatch.setattr("managers.teams_manager.httpx.AsyncClient", lambda *args, **kwargs: client)

    mgr = TeamsManager(webhook_url="https://example.test/hook")
    ok, err = _run(mgr.send_message(text="Body content"))

    assert ok is True
    assert err == ""

    call = client.calls[0]
    assert call["url"] == "https://example.test/hook"
    assert '"summary": "Body content"' in call["content"]
    assert '"title"' not in call["content"]
    assert '"sections"' not in call["content"]
    assert '"potentialAction"' not in call["content"]


def test_send_adaptive_card_wraps_body(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeAsyncClient(response=_FakeResponse(status_code=201, text="ok"))
    monkeypatch.setattr("managers.teams_manager.httpx.AsyncClient", lambda *args, **kwargs: client)

    mgr = TeamsManager(webhook_url="https://example.test/hook")
    ok, err = _run(mgr.send_adaptive_card({"type": "AdaptiveCard", "body": []}))

    assert ok is True
    assert err == ""
    assert '"contentType": "application/vnd.microsoft.card.adaptive"' in client.calls[0]["content"]


def test_send_adaptive_card_requires_webhook() -> None:
    ok, err = _run(TeamsManager().send_adaptive_card({"type": "AdaptiveCard", "body": []}))
    assert ok is False
    assert "TEAMS_WEBHOOK_URL" in err


def test_send_notification_status_and_link(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _fake_send_message(**kwargs):
        captured.update(kwargs)
        return True, ""

    mgr = TeamsManager(webhook_url="https://example.test/hook")
    monkeypatch.setattr(mgr, "send_message", _fake_send_message)

    ok, err = _run(
        mgr.send_notification(
            title="Deploy",
            body="Completed",
            status="error",
            details=[{"key": "env", "value": "prod"}],
            link_url="https://example.test/detail",
            link_label="Open",
        )
    )

    assert ok is True
    assert err == ""
    assert captured["theme_color"] == "D83B01"
    assert captured["actions"][0]["targets"][0]["uri"] == "https://example.test/detail"


def test_send_notification_uses_default_color_for_unknown_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_send_message(**kwargs):
        captured.update(kwargs)
        return True, ""

    mgr = TeamsManager(webhook_url="https://example.test/hook")
    monkeypatch.setattr(mgr, "send_message", _fake_send_message)

    _run(mgr.send_notification(title="A", body="B", status="unknown"))

    assert captured["theme_color"] == "0078D4"
    assert captured["actions"] is None


def test_build_approval_card_and_summary_card() -> None:
    approval = TeamsManager.build_approval_card(
        request_id="42",
        title="Need approval",
        description="Please review",
        requester="alice",
        approve_url="https://ok.test/approve",
        reject_url="https://ok.test/reject",
    )
    assert approval["type"] == "AdaptiveCard"
    assert len(approval["actions"]) == 2
    assert "request_id=42&approved=true" in approval["actions"][0]["url"]

    summary = TeamsManager.build_summary_card(
        title="Run Summary",
        metrics=[{"key": "passed", "value": "12"}],
        description="Nightly pipeline",
    )
    assert summary["version"] == "1.4"
    assert summary["body"][1]["text"] == "Nightly pipeline"
    assert summary["body"][2]["facts"][0]["title"] == "passed"


def test_build_cards_without_optional_fields() -> None:
    approval = TeamsManager.build_approval_card(
        request_id="7",
        title="T",
        description="D",
    )
    assert approval["actions"] == []
    assert len(approval["body"]) == 2

    summary = TeamsManager.build_summary_card(title="Only title", metrics=[])
    assert len(summary["body"]) == 1


def test_post_non_success_http(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeAsyncClient(response=_FakeResponse(status_code=500, text="server exploded"))
    monkeypatch.setattr("managers.teams_manager.httpx.AsyncClient", lambda *args, **kwargs: client)

    ok, err = _run(TeamsManager(webhook_url="https://example.test/hook")._post({"a": 1}))

    assert ok is False
    assert err.startswith("HTTP 500")


def test_post_success_for_accepted_empty_text(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeAsyncClient(response=_FakeResponse(status_code=202, text=""))
    monkeypatch.setattr("managers.teams_manager.httpx.AsyncClient", lambda *args, **kwargs: client)

    ok, err = _run(TeamsManager(webhook_url="https://example.test/hook")._post({"a": 1}))

    assert ok is True
    assert err == ""


def test_post_success_for_nonstandard_success_body(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeAsyncClient(response=_FakeResponse(status_code=200, text="accepted"))
    monkeypatch.setattr("managers.teams_manager.httpx.AsyncClient", lambda *args, **kwargs: client)

    ok, err = _run(TeamsManager(webhook_url="https://example.test/hook")._post({"a": 1}))

    assert ok is True
    assert err == ""


def test_post_exception_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeAsyncClient(error=RuntimeError("network down"))
    monkeypatch.setattr("managers.teams_manager.httpx.AsyncClient", lambda *args, **kwargs: client)

    ok, err = _run(TeamsManager(webhook_url="https://example.test/hook")._post({"a": 1}))

    assert ok is False
    assert "network down" in err
