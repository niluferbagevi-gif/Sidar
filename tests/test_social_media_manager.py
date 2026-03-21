import asyncio
import importlib.util
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