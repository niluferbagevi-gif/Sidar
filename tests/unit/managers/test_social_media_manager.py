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

        class TimeoutException(Exception):
            pass

        class RequestError(Exception):
            pass

        class _DummyAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):  # pragma: no cover
                raise RuntimeError("dummy client should be patched in tests")

        fake_httpx.TimeoutException = TimeoutException
        fake_httpx.RequestError = RequestError
        fake_httpx.AsyncClient = _DummyAsyncClient
        fake_httpx.Request = lambda method, url: (method, url)
        sys.modules["httpx"] = fake_httpx


_ensure_httpx_stub()

import httpx

from managers.social_media_manager import SocialMediaManager


def _run(coro):
    return asyncio.run(coro)


@dataclass
class _FakeResponse:
    status_code: int
    payload: Any = None
    text: str = ""

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class _FakeAsyncClient:
    def __init__(
        self, *, responses: list[_FakeResponse] | None = None, error: Exception | None = None
    ):
        self._responses = responses or []
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
        if not self._responses:
            raise RuntimeError("No fake response configured")
        return self._responses.pop(0)


class _ClientFactory:
    def __init__(self, client: _FakeAsyncClient):
        self.client = client
        self.kwargs: dict[str, Any] = {}

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.client


def test_ensure_httpx_stub_and_fake_async_client_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "httpx", raising=False)
    _ensure_httpx_stub()
    assert "httpx" in sys.modules
    client = sys.modules["httpx"].AsyncClient()
    entered = _run(client.__aenter__())
    exited = _run(client.__aexit__(None, None, None))

    assert entered is client
    assert exited is False

    with pytest.raises(RuntimeError, match="No fake response configured"):
        _run(_FakeAsyncClient().post("https://graph.example/test", json={}))


def test_is_available_by_platform_and_ids() -> None:
    mgr = SocialMediaManager()
    assert mgr.is_available() is False
    assert mgr.is_available("instagram") is False

    mgr = SocialMediaManager(graph_api_token="tkn", instagram_business_account_id="ig")
    assert mgr.is_available() is True
    assert mgr.is_available("instagram") is True
    assert mgr.is_available("facebook") is False

    mgr = SocialMediaManager(
        graph_api_token="tkn", facebook_page_id="fb", whatsapp_phone_number_id="wa"
    )
    assert mgr.is_available("facebook") is True
    assert mgr.is_available("whatsapp") is True


def test_url_and_build_content_preview() -> None:
    mgr = SocialMediaManager(api_version="v21.0")
    assert mgr._url("/x/y") == "https://graph.facebook.com/v21.0/x/y"
    preview = SocialMediaManager.build_content_preview(
        "Instagram", " text ", media_url=" m ", link_url=" l ", destination=" d "
    )
    assert '"platform": "instagram"' in preview
    assert '"text": "text"' in preview
    assert '"media_url": "m"' in preview


def test_post_requires_token() -> None:
    ok, err = _run(SocialMediaManager()._post("x", {"a": 1}))
    assert ok is False
    assert "META_GRAPH_API_TOKEN" in err


def test_post_success_and_error_variants() -> None:
    client = _FakeAsyncClient(
        responses=[
            _FakeResponse(status_code=200, payload={"id": "1"}),
            _FakeResponse(status_code=500, payload={"error": {"message": "boom"}}),
            _FakeResponse(status_code=400, payload="bad"),
            _FakeResponse(status_code=200, payload=ValueError("no json"), text="raw-body"),
        ]
    )
    factory = _ClientFactory(client)
    mgr = SocialMediaManager(graph_api_token="tkn", http_client_factory=factory)

    ok, body = _run(mgr._post("abc", {"q": 1}))
    assert ok is True
    assert body == {"id": "1"}
    assert factory.kwargs["timeout"] == 15.0
    assert factory.kwargs["follow_redirects"] is True
    assert client.calls[0]["json"]["access_token"] == "tkn"

    ok, err = _run(mgr._post("abc", {}))
    assert ok is False
    assert err == "boom"

    ok, err = _run(mgr._post("abc", {}))
    assert ok is False
    assert err == "bad"

    ok, body = _run(mgr._post("abc", {}))
    assert ok is True
    assert body == {"raw": "raw-body"}


def test_post_error_includes_meta_error_code_details() -> None:
    client = _FakeAsyncClient(
        responses=[
            _FakeResponse(
                status_code=401,
                payload={
                    "error": {
                        "message": "Error validating access token: Session has expired",
                        "code": 190,
                        "error_subcode": 463,
                        "type": "OAuthException",
                    }
                },
            )
        ]
    )
    mgr = SocialMediaManager(graph_api_token="tkn", http_client_factory=_ClientFactory(client))
    ok, err = _run(mgr._post("abc", {}))
    assert ok is False
    assert "Meta API hatası" in err
    assert "code=190" in err
    assert "subcode=463" in err
    assert "OAuthException" in err


def test_post_timeout_and_request_errors() -> None:
    timeout_client = _FakeAsyncClient(error=httpx.TimeoutException("late"))
    mgr_timeout = SocialMediaManager(
        graph_api_token="tkn", http_client_factory=_ClientFactory(timeout_client)
    )
    ok, err = _run(mgr_timeout._post("abc", {}))
    assert ok is False
    assert "zaman aşımı" in err

    req_error_client = _FakeAsyncClient(error=httpx.RequestError("net"))
    mgr_request = SocialMediaManager(
        graph_api_token="tkn", http_client_factory=_ClientFactory(req_error_client)
    )
    ok, err = _run(mgr_request._post("abc", {}))
    assert ok is False
    assert "HTTP isteği başarısız" in err


def test_publish_instagram_post_flow() -> None:
    mgr = SocialMediaManager(graph_api_token="tkn")
    ok, err = _run(mgr.publish_instagram_post(caption="c", image_url=" "))
    assert ok is False
    assert "INSTAGRAM_BUSINESS_ACCOUNT_ID" in err

    mgr = SocialMediaManager(graph_api_token="tkn", instagram_business_account_id="ig")
    ok, err = _run(mgr.publish_instagram_post(caption="c", image_url=" "))
    assert ok is False
    assert "image_url" in err

    async def fail_create(path: str, payload: dict[str, Any]):
        return False, "create failed"

    mgr._post = fail_create  # type: ignore[method-assign]
    ok, err = _run(mgr.publish_instagram_post(caption="c", image_url="https://img"))
    assert ok is False
    assert err == "create failed"

    async def no_creation_id(path: str, payload: dict[str, Any]):
        return True, {}

    mgr._post = no_creation_id  # type: ignore[method-assign]
    ok, err = _run(mgr.publish_instagram_post(caption="c", image_url="https://img"))
    assert ok is False
    assert "container" in err

    calls: list[str] = []

    async def ok_then_publish_fail(path: str, payload: dict[str, Any]):
        calls.append(path)
        if path.endswith("/media"):
            return True, {"id": "create123"}
        return False, "publish failed"

    mgr._post = ok_then_publish_fail  # type: ignore[method-assign]
    ok, err = _run(mgr.publish_instagram_post(caption="c", image_url="https://img"))
    assert ok is False
    assert err == "publish failed"
    assert calls[-1].endswith("/media_publish")

    async def ok_both(path: str, payload: dict[str, Any]):
        if path.endswith("/media"):
            return True, {"id": "create123"}
        return True, {"id": "publish789"}

    mgr._post = ok_both  # type: ignore[method-assign]
    ok, post_id = _run(mgr.publish_instagram_post(caption=" c ", image_url=" https://img "))
    assert ok is True
    assert post_id == "publish789"


def test_publish_facebook_and_whatsapp() -> None:
    fb = SocialMediaManager(graph_api_token="tkn")
    ok, err = _run(fb.publish_facebook_post(message="hi"))
    assert ok is False
    assert "FACEBOOK_PAGE_ID" in err

    fb = SocialMediaManager(graph_api_token="tkn", facebook_page_id="page")

    async def fb_fail(path: str, payload: dict[str, Any]):
        assert payload == {"message": "hi"}
        return False, "fb fail"

    fb._post = fb_fail  # type: ignore[method-assign]
    ok, err = _run(fb.publish_facebook_post(message=" hi "))
    assert ok is False
    assert err == "fb fail"

    async def fb_ok(path: str, payload: dict[str, Any]):
        assert payload["link"] == "https://l"
        return True, {"id": "fb123"}

    fb._post = fb_ok  # type: ignore[method-assign]
    ok, post_id = _run(fb.publish_facebook_post(message=" hi ", link_url=" https://l "))
    assert ok is True
    assert post_id == "fb123"

    wa = SocialMediaManager(graph_api_token="tkn")
    ok, err = _run(wa.send_whatsapp_message(to="123", text="x"))
    assert ok is False and "WHATSAPP_PHONE_NUMBER_ID" in err

    wa = SocialMediaManager(graph_api_token="tkn", whatsapp_phone_number_id="pn")
    ok, err = _run(wa.send_whatsapp_message(to=" ", text="x"))
    assert ok is False and "alıcı" in err

    async def wa_fail(path: str, payload: dict[str, Any]):
        return False, "wa fail"

    wa._post = wa_fail  # type: ignore[method-assign]
    ok, err = _run(wa.send_whatsapp_message(to="1", text="x"))
    assert ok is False and err == "wa fail"

    async def wa_ok(path: str, payload: dict[str, Any]):
        assert payload["text"]["preview_url"] is True
        return True, {"messages": [{"id": "wamid-1"}]}

    wa._post = wa_ok  # type: ignore[method-assign]
    ok, msg_id = _run(wa.send_whatsapp_message(to=" 905 ", text=" hi ", preview_url=True))
    assert ok is True and msg_id == "wamid-1"

    async def wa_ok_no_message(path: str, payload: dict[str, Any]):
        return True, {}

    wa._post = wa_ok_no_message  # type: ignore[method-assign]
    ok, msg_id = _run(wa.send_whatsapp_message(to="905", text="x"))
    assert ok is True and msg_id == ""


def test_publish_content_router(monkeypatch: pytest.MonkeyPatch) -> None:
    mgr = SocialMediaManager(graph_api_token="tkn")

    async def ig(**kwargs):
        return True, f"ig:{kwargs['caption']}:{kwargs['image_url']}"

    async def fb(**kwargs):
        return True, f"fb:{kwargs['message']}:{kwargs['link_url']}"

    async def wa(**kwargs):
        return True, f"wa:{kwargs['to']}:{kwargs['preview_url']}"

    monkeypatch.setattr(mgr, "publish_instagram_post", ig)
    monkeypatch.setattr(mgr, "publish_facebook_post", fb)
    monkeypatch.setattr(mgr, "send_whatsapp_message", wa)

    assert _run(mgr.publish_content(platform=" instagram ", text="t", media_url="m"))[1].startswith(
        "ig:t:m"
    )
    assert _run(mgr.publish_content(platform="facebook", text="t", link_url="l"))[1].startswith(
        "fb:t:l"
    )
    assert (
        _run(mgr.publish_content(platform="whatsapp", text="t", destination="d", link_url="x"))[1]
        == "wa:d:True"
    )

    ok, err = _run(mgr.publish_content(platform="x", text="t"))
    assert ok is False
    assert "Desteklenmeyen" in err


def test_publish_content_meta_token_expired_errors_by_platform() -> None:
    mgr = SocialMediaManager(
        graph_api_token="tkn",
        instagram_business_account_id="ig",
        facebook_page_id="fb",
        whatsapp_phone_number_id="wa",
    )

    async def expired_token(*_args, **_kwargs):
        return False, "Meta API hatası (code=190 subcode=463): Error validating access token"

    mgr._post = expired_token  # type: ignore[method-assign]

    ok_ig, err_ig = _run(
        mgr.publish_content(platform="instagram", text="caption", media_url="https://img")
    )
    ok_fb, err_fb = _run(mgr.publish_content(platform="facebook", text="message"))
    ok_wa, err_wa = _run(mgr.publish_content(platform="whatsapp", text="text", destination="905"))

    assert ok_ig is False and "code=190" in err_ig
    assert ok_fb is False and "code=190" in err_fb
    assert ok_wa is False and "code=190" in err_wa
