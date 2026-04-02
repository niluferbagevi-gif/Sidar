from __future__ import annotations

import asyncio
import importlib.util
import sys
import types

_httpx_spec = None
if "httpx" not in sys.modules:
    _httpx_spec = importlib.util.find_spec("httpx")
if _httpx_spec is None and "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")

    class TimeoutException(Exception):
        pass

    class RequestError(Exception):
        pass

    fake_httpx.TimeoutException = TimeoutException
    fake_httpx.RequestError = RequestError
    fake_httpx.AsyncClient = type("AsyncClient", (), {})
    sys.modules["httpx"] = fake_httpx

import httpx
import pytest

from managers.social_media_manager import SocialMediaManager


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    def __init__(self, posts=None, exc: Exception | None = None, *args, **kwargs) -> None:
        self.posts = list(posts or [])
        self.exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, _url, json=None):
        if self.exc is not None:
            raise self.exc
        return self.posts.pop(0)


def test_post_returns_timeout_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    timeout_exc_cls = getattr(httpx, "TimeoutException", None)
    if timeout_exc_cls is None:
        class _TimeoutException(Exception):
            pass

        monkeypatch.setattr(httpx, "TimeoutException", _TimeoutException, raising=False)
        timeout_exc_cls = _TimeoutException

    manager = SocialMediaManager(
        graph_api_token="token",
        http_client_factory=lambda **kwargs: _FakeClient(exc=timeout_exc_cls("t/o"), **kwargs),
    )

    ok, message = asyncio.run(manager._post("123/feed", {"message": "hello"}))

    assert ok is False
    assert "zaman aşımı" in message


def test_publish_instagram_post_handles_invalid_token_error() -> None:
    manager = SocialMediaManager(
        graph_api_token="bad-token",
        instagram_business_account_id="ig-1",
        http_client_factory=lambda **kwargs: _FakeClient(
            posts=[_FakeResponse(401, {"error": {"message": "Invalid OAuth access token."}})], **kwargs
        ),
    )

    ok, result = asyncio.run(manager.publish_instagram_post(caption="deneme", image_url="https://img"))

    assert ok is False
    assert "Invalid OAuth" in result


def test_publish_facebook_post_handles_non_json_error_body() -> None:
    manager = SocialMediaManager(
        graph_api_token="token",
        facebook_page_id="page-1",
        http_client_factory=lambda **kwargs: _FakeClient(
            posts=[_FakeResponse(500, payload=ValueError("bad json"), text="upstream unavailable")], **kwargs
        ),
    )

    ok, result = asyncio.run(manager.publish_facebook_post(message="merhaba"))

    assert ok is False
    assert "upstream unavailable" in result


def test_send_whatsapp_message_returns_empty_id_when_messages_missing() -> None:
    manager = SocialMediaManager(
        graph_api_token="token",
        whatsapp_phone_number_id="wa-1",
        http_client_factory=lambda **kwargs: _FakeClient(posts=[_FakeResponse(200, {"contacts": []})], **kwargs),
    )

    ok, message_id = asyncio.run(manager.send_whatsapp_message(to="+905551112233", text="Selam"))

    assert ok is True
    assert message_id == ""


def test_publish_content_rejects_unknown_platform() -> None:
    manager = SocialMediaManager(graph_api_token="token")

    ok, result = asyncio.run(manager.publish_content(platform="linkedin", text="hello"))

    assert ok is False
    assert "Desteklenmeyen" in result


def test_post_returns_http_request_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    request_error_cls = getattr(httpx, "RequestError", None)
    if request_error_cls is None:
        class _RequestError(Exception):
            pass

        monkeypatch.setattr(httpx, "RequestError", _RequestError, raising=False)
        request_error_cls = _RequestError

    manager = SocialMediaManager(
        graph_api_token="token",
        http_client_factory=lambda **kwargs: _FakeClient(exc=request_error_cls("boom"), **kwargs),
    )

    ok, message = asyncio.run(manager._post("123/feed", {"message": "hello"}))

    assert ok is False
    assert "HTTP isteği başarısız" in message


def test_publish_methods_return_missing_configuration_errors() -> None:
    manager = SocialMediaManager(graph_api_token="token")

    ig_ok, ig_reason = asyncio.run(manager.publish_instagram_post(caption="test", image_url="https://img"))
    fb_ok, fb_reason = asyncio.run(manager.publish_facebook_post(message="test"))
    wa_ok, wa_reason = asyncio.run(manager.send_whatsapp_message(to="+90", text="test"))

    assert ig_ok is False and "INSTAGRAM_BUSINESS_ACCOUNT_ID" in ig_reason
    assert fb_ok is False and "FACEBOOK_PAGE_ID" in fb_reason
    assert wa_ok is False and "WHATSAPP_PHONE_NUMBER_ID" in wa_reason
