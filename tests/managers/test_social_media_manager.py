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


class _RecorderClient(_FakeClient):
    def __init__(self, posts=None, exc: Exception | None = None, *args, **kwargs) -> None:
        super().__init__(posts=posts, exc=exc, *args, **kwargs)
        self.requests = []

    async def post(self, url, json=None):
        self.requests.append((url, json))
        return await super().post(url, json=json)


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


def test_is_available_branches_and_platform_normalization() -> None:
    manager = SocialMediaManager(
        graph_api_token=" token ",
        instagram_business_account_id=" ig ",
        facebook_page_id=" fb ",
        whatsapp_phone_number_id=" wa ",
    )

    assert manager.is_available("instagram") is True
    assert manager.is_available("facebook") is True
    assert manager.is_available("whatsapp") is True
    assert manager.is_available("x") is True

    manager_no_token = SocialMediaManager(instagram_business_account_id="ig")
    assert manager_no_token.is_available("instagram") is False


def test_post_returns_token_missing_error_without_http_call() -> None:
    manager = SocialMediaManager(graph_api_token="")
    ok, message = asyncio.run(manager._post("path", {"k": "v"}))
    assert ok is False
    assert "META_GRAPH_API_TOKEN" in message


def test_post_handles_non_dict_error_body_message_branch() -> None:
    manager = SocialMediaManager(
        graph_api_token="token",
        http_client_factory=lambda **kwargs: _FakeClient(posts=[_FakeResponse(400, ["bad", "payload"])], **kwargs),
    )
    ok, message = asyncio.run(manager._post("123/feed", {"message": "hello"}))
    assert ok is False
    assert "bad" in message


def test_publish_instagram_image_url_and_creation_id_validations() -> None:
    manager = SocialMediaManager(graph_api_token="token", instagram_business_account_id="ig-1")
    ok1, msg1 = asyncio.run(manager.publish_instagram_post(caption="c", image_url="   "))
    assert ok1 is False
    assert "image_url gerekli" in msg1

    manager_missing_creation_id = SocialMediaManager(
        graph_api_token="token",
        instagram_business_account_id="ig-1",
        http_client_factory=lambda **kwargs: _FakeClient(posts=[_FakeResponse(200, {"ok": True})], **kwargs),
    )
    ok2, msg2 = asyncio.run(manager_missing_creation_id.publish_instagram_post(caption="c", image_url="https://img"))
    assert ok2 is False
    assert "container oluşturulamadı" in msg2


def test_publish_instagram_publish_failure_and_success_paths() -> None:
    fail_client = _FakeClient(
        posts=[_FakeResponse(200, {"id": "cr1"}), _FakeResponse(400, {"error": {"message": "publish failed"}})]
    )
    manager_fail = SocialMediaManager(
        graph_api_token="token",
        instagram_business_account_id="ig-1",
        http_client_factory=lambda **kwargs: fail_client,
    )
    ok_fail, msg_fail = asyncio.run(manager_fail.publish_instagram_post(caption="c", image_url="https://img"))
    assert ok_fail is False
    assert "publish failed" in msg_fail

    success_client = _FakeClient(posts=[_FakeResponse(200, {"id": "cr2"}), _FakeResponse(200, {"id": "pub2"})])
    manager_success = SocialMediaManager(
        graph_api_token="token",
        instagram_business_account_id="ig-1",
        http_client_factory=lambda **kwargs: success_client,
    )
    ok_success, publish_id = asyncio.run(manager_success.publish_instagram_post(caption="c", image_url="https://img"))
    assert ok_success is True
    assert publish_id == "pub2"


def test_publish_facebook_success_and_link_payload_branch() -> None:
    recorder = _RecorderClient(posts=[_FakeResponse(200, {"id": "fb-post-1"})])
    manager = SocialMediaManager(
        graph_api_token="token",
        facebook_page_id="page-1",
        http_client_factory=lambda **kwargs: recorder,
    )

    ok, post_id = asyncio.run(manager.publish_facebook_post(message=" hello ", link_url=" https://example.com "))
    assert ok is True
    assert post_id == "fb-post-1"
    assert recorder.requests[0][1]["message"] == "hello"
    assert recorder.requests[0][1]["link"] == "https://example.com"


def test_send_whatsapp_message_validation_and_post_failure() -> None:
    manager = SocialMediaManager(graph_api_token="token", whatsapp_phone_number_id="wa-1")
    ok_empty, reason_empty = asyncio.run(manager.send_whatsapp_message(to=" ", text="selam"))
    assert ok_empty is False
    assert "alıcı numarası gerekli" in reason_empty

    manager_fail = SocialMediaManager(
        graph_api_token="token",
        whatsapp_phone_number_id="wa-1",
        http_client_factory=lambda **kwargs: _FakeClient(posts=[_FakeResponse(400, {"error": {"message": "wa fail"}})], **kwargs),
    )
    ok_fail, reason_fail = asyncio.run(manager_fail.send_whatsapp_message(to="+90", text="selam"))
    assert ok_fail is False
    assert "wa fail" in reason_fail


def test_publish_content_routes_to_all_supported_platforms_and_preview() -> None:
    shared_client = _FakeClient(
        posts=[
            _FakeResponse(200, {"id": "ig-creation"}),
            _FakeResponse(200, {"id": "ig-publish"}),
            _FakeResponse(200, {"id": "fb-post"}),
            _FakeResponse(200, {"messages": [{"id": "wa-msg"}]}),
        ],
    )
    manager = SocialMediaManager(
        graph_api_token="token",
        instagram_business_account_id="ig-1",
        facebook_page_id="fb-1",
        whatsapp_phone_number_id="wa-1",
        http_client_factory=lambda **kwargs: shared_client,
    )

    ig_ok, ig_id = asyncio.run(manager.publish_content(platform="instagram", text="t", media_url="https://img"))
    fb_ok, fb_id = asyncio.run(manager.publish_content(platform="facebook", text="t", link_url="https://x"))
    wa_ok, wa_id = asyncio.run(manager.publish_content(platform="whatsapp", text="t", destination="+90", link_url="https://x"))

    assert (ig_ok, ig_id) == (True, "ig-publish")
    assert (fb_ok, fb_id) == (True, "fb-post")
    assert (wa_ok, wa_id) == (True, "wa-msg")

    preview = SocialMediaManager.build_content_preview(
        " Instagram ", " test ", media_url=" https://img ", link_url=" https://x ", destination=" +90 "
    )
    payload = __import__("json").loads(preview)
    assert payload == {
        "platform": "instagram",
        "text": "test",
        "media_url": "https://img",
        "link_url": "https://x",
        "destination": "+90",
    }
