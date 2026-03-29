"""
managers/social_media_manager.py için birim testleri.
SocialMediaManager: constructor, is_available, _url, build_content_preview,
disabled path (no token), platform routing.
"""
from __future__ import annotations

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


def _get_sm():
    if "managers.social_media_manager" in sys.modules:
        del sys.modules["managers.social_media_manager"]
    import managers.social_media_manager as sm
    return sm


# ══════════════════════════════════════════════════════════════
# Constructor
# ══════════════════════════════════════════════════════════════

class TestSocialMediaManagerInit:
    def test_empty_init_stores_empty_strings(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager()
        assert mgr.graph_api_token == ""
        assert mgr.instagram_business_account_id == ""

    def test_tokens_stripped(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(graph_api_token="  mytoken  ")
        assert mgr.graph_api_token == "mytoken"

    def test_api_version_default(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager()
        assert mgr.api_version == "v20.0"

    def test_custom_api_version(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(api_version="v21.0")
        assert mgr.api_version == "v21.0"


# ══════════════════════════════════════════════════════════════
# is_available
# ══════════════════════════════════════════════════════════════

class TestIsAvailable:
    def test_false_when_no_token(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager()
        assert mgr.is_available() is False

    def test_false_for_instagram_without_account_id(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(graph_api_token="tok")
        assert mgr.is_available("instagram") is False

    def test_true_for_instagram_with_account_id(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            instagram_business_account_id="123",
        )
        assert mgr.is_available("instagram") is True

    def test_true_for_facebook_with_page_id(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            facebook_page_id="456",
        )
        assert mgr.is_available("facebook") is True

    def test_true_for_whatsapp_with_phone_id(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            whatsapp_phone_number_id="789",
        )
        assert mgr.is_available("whatsapp") is True

    def test_general_true_if_any_platform(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            facebook_page_id="456",
        )
        assert mgr.is_available() is True

    def test_false_when_no_platform_ids(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(graph_api_token="tok")
        assert mgr.is_available() is False


# ══════════════════════════════════════════════════════════════
# _url
# ══════════════════════════════════════════════════════════════

class TestUrl:
    def test_url_construction(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager()
        url = mgr._url("123456789/media")
        assert url == "https://graph.facebook.com/v20.0/123456789/media"

    def test_leading_slash_stripped(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager()
        url = mgr._url("/messages")
        assert "//" not in url.replace("https://", "")

    def test_custom_version_in_url(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(api_version="v21.0")
        url = mgr._url("me/feed")
        assert "v21.0" in url


# ══════════════════════════════════════════════════════════════
# build_content_preview (static)
# ══════════════════════════════════════════════════════════════

class TestBuildContentPreview:
    def test_returns_valid_json(self):
        sm = _get_sm()
        result = sm.SocialMediaManager.build_content_preview("instagram", "Hello world")
        parsed = json.loads(result)
        assert parsed["platform"] == "instagram"
        assert parsed["text"] == "Hello world"

    def test_platform_lowercased(self):
        sm = _get_sm()
        result = sm.SocialMediaManager.build_content_preview("FACEBOOK", "text")
        parsed = json.loads(result)
        assert parsed["platform"] == "facebook"

    def test_empty_platform(self):
        sm = _get_sm()
        result = sm.SocialMediaManager.build_content_preview("", "text")
        parsed = json.loads(result)
        assert parsed["platform"] == ""

    def test_media_url_included(self):
        sm = _get_sm()
        result = sm.SocialMediaManager.build_content_preview(
            "instagram", "caption", media_url="https://img.example.com/photo.jpg"
        )
        parsed = json.loads(result)
        assert parsed["media_url"] == "https://img.example.com/photo.jpg"


# ══════════════════════════════════════════════════════════════
# publish_content — unsupported platform
# ══════════════════════════════════════════════════════════════

class TestPublishContentDisabled:
    def test_no_token_post_fails(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager()
        ok, err = asyncio.run(mgr._post("some/path", {}))
        assert ok is False
        assert "META_GRAPH_API_TOKEN" in err

    def test_unsupported_platform(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(graph_api_token="tok")
        ok, err = asyncio.run(mgr.publish_content(platform="tiktok", text="hi"))
        assert ok is False
        assert "tiktok" in err.lower() or "Desteklenmeyen" in err

    def test_instagram_without_account_id(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(graph_api_token="tok")
        ok, err = asyncio.run(mgr.publish_instagram_post(caption="hi", image_url="https://img.example.com/a.jpg"))
        assert ok is False
        assert "INSTAGRAM_BUSINESS_ACCOUNT_ID" in err

    def test_facebook_without_page_id(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(graph_api_token="tok")
        ok, err = asyncio.run(mgr.publish_facebook_post(message="hello"))
        assert ok is False

    def test_whatsapp_without_phone_id(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(graph_api_token="tok")
        ok, err = asyncio.run(mgr.send_whatsapp_message(to="+90555", text="hi"))
        assert ok is False

    def test_whatsapp_without_recipient(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            whatsapp_phone_number_id="123",
        )
        ok, err = asyncio.run(mgr.send_whatsapp_message(to="", text="hi"))
        assert ok is False
        assert "alıcı" in err.lower() or "to" in err.lower() or "gerekli" in err


class TestSocialMediaApiMocking:
    def test_post_success_with_mocked_http_client(self):
        sm = _get_sm()

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"id": "post_1"}

        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            facebook_page_id="page_1",
            http_client_factory=lambda **kwargs: _FakeClientCM(),
        )
        ok, payload = asyncio.run(mgr._post("page_1/feed", {"message": "Merhaba"}))

        assert ok is True
        assert payload == {"id": "post_1"}
        client.post.assert_awaited_once()

    def test_post_timeout_returns_error_with_mocked_http_client(self):
        sm = _get_sm()
        httpx = __import__("httpx")

        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            http_client_factory=lambda **kwargs: _FakeClientCM(),
        )
        ok, err = asyncio.run(mgr._post("me/feed", {"message": "x"}))

        assert ok is False
        assert "zaman aşımı" in str(err).lower()

    def test_post_request_error_returns_http_failure_message(self):
        sm = _get_sm()
        httpx = __import__("httpx")

        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.RequestError("network down"))

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            http_client_factory=lambda **kwargs: _FakeClientCM(),
        )
        ok, err = asyncio.run(mgr._post("me/feed", {"message": "x"}))

        assert ok is False
        assert "http isteği başarısız" in str(err).lower()

    def test_post_http_error_with_non_json_body_falls_back_to_raw_text(self):
        sm = _get_sm()

        response = MagicMock()
        response.status_code = 500
        response.text = "internal server error"
        response.json.side_effect = ValueError("not json")

        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            http_client_factory=lambda **kwargs: _FakeClientCM(),
        )
        ok, err = asyncio.run(mgr._post("me/feed", {"message": "x"}))

        assert ok is False
        assert "internal server error" in str(err).lower()

    def test_post_401_unauthorized_returns_api_error_message(self):
        sm = _get_sm()

        response = MagicMock()
        response.status_code = 401
        response.json.return_value = {"error": {"message": "Invalid OAuth access token"}}
        response.text = ""

        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            http_client_factory=lambda **kwargs: _FakeClientCM(),
        )
        ok, err = asyncio.run(mgr._post("me/feed", {"message": "x"}))

        assert ok is False
        assert "invalid oauth access token" in str(err).lower()

    def test_post_200_with_broken_json_returns_raw_payload(self):
        sm = _get_sm()

        response = MagicMock()
        response.status_code = 200
        response.text = "{broken-json"
        response.json.side_effect = ValueError("bad json")

        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            http_client_factory=lambda **kwargs: _FakeClientCM(),
        )
        ok, payload = asyncio.run(mgr._post("me/feed", {"message": "x"}))

        assert ok is True
        assert payload == {"raw": "{broken-json"}


class TestSocialMediaPlatformIntegrationMocking:
    @pytest.mark.parametrize(
        "method_name, kwargs, mock_side_effect, expected_ok, expected_fragment",
        [
            (
                "publish_instagram_post",
                {"caption": "merhaba", "image_url": "https://img/x.jpg"},
                [(True, {"id": "creation_1"}), (True, {"id": "ig_1"})],
                True,
                "ig_1",
            ),
            (
                "publish_instagram_post",
                {"caption": "merhaba", "image_url": "https://img/x.jpg"},
                [(True, {}), (True, {"id": "ig_1"})],
                False,
                "container",
            ),
            (
                "publish_facebook_post",
                {"message": "fb merhaba", "link_url": "https://example.com"},
                [(True, {"id": "fb_1"})],
                True,
                "fb_1",
            ),
            (
                "publish_facebook_post",
                {"message": "fb merhaba", "link_url": ""},
                [(False, "permission denied")],
                False,
                "permission denied",
            ),
            (
                "send_whatsapp_message",
                {"to": "+90555", "text": "selam", "preview_url": True},
                [(True, {"messages": [{"id": "wa_1"}]})],
                True,
                "wa_1",
            ),
            (
                "send_whatsapp_message",
                {"to": "+90555", "text": "selam", "preview_url": False},
                [(False, "template not approved")],
                False,
                "template not approved",
            ),
        ],
    )
    def test_platform_publish_paths_with_json_mock_responses(
        self,
        method_name,
        kwargs,
        mock_side_effect,
        expected_ok,
        expected_fragment,
    ):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            instagram_business_account_id="ig_account",
            facebook_page_id="fb_page",
            whatsapp_phone_number_id="wa_phone",
        )
        mgr._post = AsyncMock(side_effect=mock_side_effect)
        ok, payload = asyncio.run(getattr(mgr, method_name)(**kwargs))
        assert ok is expected_ok
        assert expected_fragment.lower() in str(payload).lower()


class TestSocialMediaUncoveredBranches:
    def test_post_http_error_with_non_dict_json_body_uses_stringified_message(self):
        sm = _get_sm()

        response = MagicMock()
        response.status_code = 429
        response.json.return_value = ["rate", "limited"]
        response.text = ""

        client = MagicMock()
        client.post = AsyncMock(return_value=response)

        class _FakeClientCM:
            async def __aenter__(self_inner):
                return client

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            http_client_factory=lambda **kwargs: _FakeClientCM(),
        )
        ok, err = asyncio.run(mgr._post("me/feed", {"message": "x"}))

        assert ok is False
        assert "rate" in str(err).lower()

    def test_publish_instagram_post_requires_non_empty_image_url(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            instagram_business_account_id="ig_account",
        )

        ok, err = asyncio.run(mgr.publish_instagram_post(caption="merhaba", image_url="   "))

        assert ok is False
        assert "image_url" in err

    def test_publish_instagram_post_returns_first_post_error(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            instagram_business_account_id="ig_account",
        )
        mgr._post = AsyncMock(return_value=(False, "creation failed"))

        ok, err = asyncio.run(mgr.publish_instagram_post(caption="merhaba", image_url="https://img/x.jpg"))

        assert ok is False
        assert "creation failed" in err

    def test_publish_instagram_post_returns_publish_error(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(
            graph_api_token="tok",
            instagram_business_account_id="ig_account",
        )
        mgr._post = AsyncMock(side_effect=[(True, {"id": "creation_1"}), (False, "publish failed")])

        ok, err = asyncio.run(mgr.publish_instagram_post(caption="merhaba", image_url="https://img/x.jpg"))

        assert ok is False
        assert "publish failed" in err

    def test_publish_content_routes_to_platform_specific_methods(self):
        sm = _get_sm()
        mgr = sm.SocialMediaManager(graph_api_token="tok")
        mgr.publish_instagram_post = AsyncMock(return_value=(True, "ig_1"))
        mgr.publish_facebook_post = AsyncMock(return_value=(True, "fb_1"))
        mgr.send_whatsapp_message = AsyncMock(return_value=(True, "wa_1"))

        ig = asyncio.run(mgr.publish_content(platform="instagram", text="caption", media_url="https://img/x.jpg"))
        fb = asyncio.run(mgr.publish_content(platform="facebook", text="message", link_url="https://example.com"))
        wa = asyncio.run(mgr.publish_content(platform="whatsapp", text="hello", destination="+90555", link_url=" https://preview "))

        assert ig == (True, "ig_1")
        assert fb == (True, "fb_1")
        assert wa == (True, "wa_1")
        mgr.publish_instagram_post.assert_awaited_once_with(caption="caption", image_url="https://img/x.jpg")
        mgr.publish_facebook_post.assert_awaited_once_with(message="message", link_url="https://example.com")
        mgr.send_whatsapp_message.assert_awaited_once_with(to="+90555", text="hello", preview_url=True)
