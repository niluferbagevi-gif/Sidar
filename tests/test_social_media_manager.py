import asyncio
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_social_media_manager_module():
    spec = importlib.util.spec_from_file_location("managers.social_media_manager", ROOT / "managers" / "social_media_manager.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["managers.social_media_manager"] = mod
    spec.loader.exec_module(mod)
    return mod


social_mod = _load_social_media_manager_module()
SocialMediaManager = social_mod.SocialMediaManager


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, json=None):
        self.calls.append((url, json))
        return self.responses.pop(0)


class _TextResponse(_Response):
    def json(self):
        raise ValueError("invalid json")


class _ErrorClient:
    def __init__(self, exc):
        self.exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, json=None):
        raise self.exc


def test_publish_instagram_post_runs_container_then_publish_calls():
    client = _FakeClient([_Response(200, {"id": "creation-1"}), _Response(200, {"id": "publish-1"})])
    manager = SocialMediaManager(
        graph_api_token="token",
        instagram_business_account_id="ig-1",
        http_client_factory=lambda **_kwargs: client,
    )

    ok, result = asyncio.run(manager.publish_instagram_post(caption="Yeni gönderi", image_url="https://img.test/1.jpg"))

    assert ok is True
    assert result == "publish-1"
    assert client.calls[0][0].endswith("/ig-1/media")
    assert client.calls[1][0].endswith("/ig-1/media_publish")


def test_publish_facebook_post_includes_optional_link():
    client = _FakeClient([_Response(200, {"id": "fb-post-1"})])
    manager = SocialMediaManager(
        graph_api_token="token",
        facebook_page_id="page-1",
        http_client_factory=lambda **_kwargs: client,
    )

    ok, result = asyncio.run(manager.publish_facebook_post(message="Landing yayında", link_url="https://example.com"))

    assert ok is True
    assert result == "fb-post-1"
    assert client.calls[0][1]["link"] == "https://example.com"


def test_send_whatsapp_message_formats_business_payload():
    client = _FakeClient([_Response(200, {"messages": [{"id": "wamid-1"}]})])
    manager = SocialMediaManager(
        graph_api_token="token",
        whatsapp_phone_number_id="phone-1",
        http_client_factory=lambda **_kwargs: client,
    )

    ok, result = asyncio.run(manager.send_whatsapp_message(to="905551112233", text="Merhaba", preview_url=True))

    assert ok is True
    assert result == "wamid-1"
    payload = client.calls[0][1]
    assert payload["messaging_product"] == "whatsapp"
    assert payload["text"]["preview_url"] is True


def test_publish_content_routes_platforms_and_handles_unknown():
    manager = SocialMediaManager(graph_api_token="token")

    async def _fake_ig(*, caption, image_url):
        return True, f"ig:{caption}:{image_url}"

    async def _fake_fb(*, message, link_url=""):
        return True, f"fb:{message}:{link_url}"

    async def _fake_wa(*, to, text, preview_url=False):
        return True, f"wa:{to}:{text}:{preview_url}"

    manager.publish_instagram_post = _fake_ig
    manager.publish_facebook_post = _fake_fb
    manager.send_whatsapp_message = _fake_wa

    ok_ig, out_ig = asyncio.run(manager.publish_content(platform="instagram", text="Post", media_url="https://img"))
    ok_fb, out_fb = asyncio.run(manager.publish_content(platform="facebook", text="Post", link_url="https://site"))
    ok_wa, out_wa = asyncio.run(manager.publish_content(platform="whatsapp", text="Mesaj", destination="9055"))
    bad_ok, bad_out = asyncio.run(manager.publish_content(platform="x", text="noop"))

    assert ok_ig is True and out_ig.startswith("ig:")
    assert ok_fb is True and out_fb.startswith("fb:")
    assert ok_wa is True and out_wa.startswith("wa:")
    assert bad_ok is False and "Desteklenmeyen" in bad_out


def test_social_media_manager_http_error_and_invalid_json_paths():
    client_4xx = _FakeClient([_Response(400, {"error": {"message": "invalid media"}})])
    manager_4xx = SocialMediaManager(
        graph_api_token="token",
        instagram_business_account_id="ig-1",
        http_client_factory=lambda **_kwargs: client_4xx,
    )
    ok_4xx, out_4xx = asyncio.run(
        manager_4xx.publish_instagram_post(caption="Yeni gönderi", image_url="https://img.test/1.jpg")
    )

    client_5xx = _FakeClient([_TextResponse(500, "server exploded")])
    manager_5xx = SocialMediaManager(
        graph_api_token="token",
        facebook_page_id="page-1",
        http_client_factory=lambda **_kwargs: client_5xx,
    )
    ok_5xx, out_5xx = asyncio.run(manager_5xx.publish_facebook_post(message="Landing yayında"))

    client_publish_fail = _FakeClient([_Response(200, {"id": "creation-1"}), _Response(503, {"error": {"message": "publish down"}})])
    manager_publish_fail = SocialMediaManager(
        graph_api_token="token",
        instagram_business_account_id="ig-1",
        http_client_factory=lambda **_kwargs: client_publish_fail,
    )
    ok_publish_fail, out_publish_fail = asyncio.run(
        manager_publish_fail.publish_instagram_post(caption="Yeni gönderi", image_url="https://img.test/1.jpg")
    )

    assert ok_4xx is False and out_4xx == "invalid media"
    assert ok_5xx is False and "server exploded" in out_5xx
    assert ok_publish_fail is False and out_publish_fail == "publish down"


def test_social_media_manager_request_error_timeout_and_validation_paths():
    class _TimeoutError(social_mod.httpx.TimeoutException):
        pass

    class _RequestError(social_mod.httpx.RequestError):
        pass

    timeout_manager = SocialMediaManager(
        graph_api_token="token",
        whatsapp_phone_number_id="phone-1",
        http_client_factory=lambda **_kwargs: _ErrorClient(_TimeoutError("timeout")),
    )
    request_error_manager = SocialMediaManager(
        graph_api_token="token",
        facebook_page_id="page-1",
        http_client_factory=lambda **_kwargs: _ErrorClient(_RequestError("network down")),
    )
    missing_media_manager = SocialMediaManager(graph_api_token="token", instagram_business_account_id="ig-1")
    missing_to_manager = SocialMediaManager(graph_api_token="token", whatsapp_phone_number_id="phone-1")

    timeout_ok, timeout_out = asyncio.run(
        timeout_manager.send_whatsapp_message(to="905551112233", text="Merhaba", preview_url=False)
    )
    req_ok, req_out = asyncio.run(request_error_manager.publish_facebook_post(message="Landing yayında"))
    missing_media_ok, missing_media_out = asyncio.run(
        missing_media_manager.publish_instagram_post(caption="Yeni gönderi", image_url=" ")
    )
    missing_to_ok, missing_to_out = asyncio.run(
        missing_to_manager.send_whatsapp_message(to=" ", text="Merhaba", preview_url=False)
    )

    assert timeout_ok is False and "İstek zaman aşımı" in timeout_out
    assert req_ok is False and "HTTP isteği başarısız" in req_out
    assert missing_media_ok is False and "image_url gerekli" in missing_media_out
    assert missing_to_ok is False and "alıcı numarası gerekli" in missing_to_out


def test_is_available_and_build_content_preview_cover_configuration_branches():
    unavailable = SocialMediaManager()
    assert unavailable.is_available() is False
    assert unavailable.is_available("instagram") is False
    assert unavailable.is_available("facebook") is False
    assert unavailable.is_available("whatsapp") is False

    partially_available = SocialMediaManager(
        graph_api_token="token",
        instagram_business_account_id=" ig-1 ",
        facebook_page_id=" page-1 ",
        whatsapp_phone_number_id=" phone-1 ",
    )
    assert partially_available.is_available() is True
    assert partially_available.is_available("instagram") is True
    assert partially_available.is_available("facebook") is True
    assert partially_available.is_available("whatsapp") is True

    preview = SocialMediaManager.build_content_preview(
        " Instagram ",
        " Yeni içerik ",
        media_url=" https://img.test/post.jpg ",
        link_url=" https://example.test ",
        destination=" +905551112233 ",
    )
    assert json.loads(preview) == {
        "platform": "instagram",
        "text": "Yeni içerik",
        "media_url": "https://img.test/post.jpg",
        "link_url": "https://example.test",
        "destination": "+905551112233",
    }


def test_missing_credentials_and_missing_instagram_creation_id_paths():
    no_token_manager = SocialMediaManager(instagram_business_account_id="ig-1")
    no_token_ok, no_token_out = asyncio.run(
        no_token_manager.publish_instagram_post(caption="Yeni gönderi", image_url="https://img.test/1.jpg")
    )

    missing_instagram_id_manager = SocialMediaManager(graph_api_token="token")
    missing_instagram_ok, missing_instagram_out = asyncio.run(
        missing_instagram_id_manager.publish_instagram_post(caption="Yeni gönderi", image_url="https://img.test/1.jpg")
    )

    missing_facebook_id_manager = SocialMediaManager(graph_api_token="token")
    missing_facebook_ok, missing_facebook_out = asyncio.run(
        missing_facebook_id_manager.publish_facebook_post(message="Landing yayında")
    )

    missing_whatsapp_id_manager = SocialMediaManager(graph_api_token="token")
    missing_whatsapp_ok, missing_whatsapp_out = asyncio.run(
        missing_whatsapp_id_manager.send_whatsapp_message(to="905551112233", text="Merhaba")
    )

    client_missing_creation = _FakeClient([_Response(200, {"status": "created-without-id"})])
    missing_creation_manager = SocialMediaManager(
        graph_api_token="token",
        instagram_business_account_id="ig-1",
        http_client_factory=lambda **_kwargs: client_missing_creation,
    )
    missing_creation_ok, missing_creation_out = asyncio.run(
        missing_creation_manager.publish_instagram_post(caption="Yeni gönderi", image_url="https://img.test/1.jpg")
    )

    assert no_token_ok is False and no_token_out == "META_GRAPH_API_TOKEN ayarlanmamış"
    assert missing_instagram_ok is False and "INSTAGRAM_BUSINESS_ACCOUNT_ID ayarlanmamış" in missing_instagram_out
    assert missing_facebook_ok is False and "FACEBOOK_PAGE_ID ayarlanmamış" in missing_facebook_out
    assert missing_whatsapp_ok is False and "WHATSAPP_PHONE_NUMBER_ID ayarlanmamış" in missing_whatsapp_out
    assert missing_creation_ok is False and missing_creation_out == "Instagram media container oluşturulamadı"
