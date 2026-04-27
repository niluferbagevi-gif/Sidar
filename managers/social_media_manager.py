"""Meta Graph API ve WhatsApp Business API tabanlı sosyal medya yöneticisi."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx


class SocialMediaManager:
    """Instagram, Facebook ve WhatsApp gönderimlerini tek noktadan yöneten istemci."""

    API_BASE = "https://graph.facebook.com"
    TIMEOUT = 15.0

    def __init__(
        self,
        *,
        graph_api_token: str = "",
        instagram_business_account_id: str = "",
        facebook_page_id: str = "",
        whatsapp_phone_number_id: str = "",
        api_version: str = "v20.0",
        http_client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.graph_api_token = (graph_api_token or "").strip()
        self.instagram_business_account_id = (instagram_business_account_id or "").strip()
        self.facebook_page_id = (facebook_page_id or "").strip()
        self.whatsapp_phone_number_id = (whatsapp_phone_number_id or "").strip()
        self.api_version = (api_version or "v20.0").strip()
        self.http_client_factory = http_client_factory or httpx.AsyncClient

    def is_available(self, platform: str = "") -> bool:
        normalized = (platform or "").strip().lower()
        if not self.graph_api_token:
            return False
        if normalized == "instagram":
            return bool(self.instagram_business_account_id)
        if normalized == "facebook":
            return bool(self.facebook_page_id)
        if normalized == "whatsapp":
            return bool(self.whatsapp_phone_number_id)
        return any(
            (
                self.instagram_business_account_id,
                self.facebook_page_id,
                self.whatsapp_phone_number_id,
            )
        )

    def _url(self, path: str) -> str:
        return f"{self.API_BASE}/{self.api_version}/{path.lstrip('/')}"

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[bool, dict[str, Any] | str]:
        if not self.graph_api_token:
            return False, "META_GRAPH_API_TOKEN ayarlanmamış"

        data = {**payload, "access_token": self.graph_api_token}
        try:
            async with self.http_client_factory(
                timeout=self.TIMEOUT, follow_redirects=True
            ) as client:
                response = await client.post(self._url(path), json=data)
        except httpx.TimeoutException as exc:
            return False, f"İstek zaman aşımı: {exc}"
        except httpx.RequestError as exc:
            return False, f"HTTP isteği başarısız: {exc}"

        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text}

        if response.status_code >= 400:
            if isinstance(body, dict):
                err = body.get("error") or {}
                message = str(err.get("message") or body)
                code = err.get("code")
                subcode = err.get("error_subcode")
                err_type = err.get("type")
                details = []
                if code is not None:
                    details.append(f"code={code}")
                if subcode is not None:
                    details.append(f"subcode={subcode}")
                if err_type:
                    details.append(f"type={err_type}")
                if details:
                    message = f"Meta API hatası ({' '.join(details)}): {message}"
            else:
                message = str(body)
            return False, message
        return True, body if isinstance(body, dict) else {"raw": body}

    async def publish_instagram_post(self, *, caption: str, image_url: str) -> tuple[bool, str]:
        if not self.instagram_business_account_id:
            return False, "INSTAGRAM_BUSINESS_ACCOUNT_ID ayarlanmamış"
        if not image_url.strip():
            return False, "Instagram paylaşımı için image_url gerekli"

        ok, creation = await self._post(
            f"{self.instagram_business_account_id}/media",
            {"image_url": image_url.strip(), "caption": caption.strip()},
        )
        if not ok:
            return False, str(creation)

        creation_id = str((creation or {}).get("id") or "")
        if not creation_id:
            return False, "Instagram media container oluşturulamadı"

        ok, publish = await self._post(
            f"{self.instagram_business_account_id}/media_publish",
            {"creation_id": creation_id},
        )
        if not ok:
            return False, str(publish)
        return True, str((publish or {}).get("id") or creation_id)

    async def publish_facebook_post(self, *, message: str, link_url: str = "") -> tuple[bool, str]:
        if not self.facebook_page_id:
            return False, "FACEBOOK_PAGE_ID ayarlanmamış"

        payload: dict[str, Any] = {"message": message.strip()}
        if link_url.strip():
            payload["link"] = link_url.strip()
        ok, response = await self._post(f"{self.facebook_page_id}/feed", payload)
        if not ok:
            return False, str(response)
        return True, str((response or {}).get("id") or "")

    async def send_whatsapp_message(
        self, *, to: str, text: str, preview_url: bool = False
    ) -> tuple[bool, str]:
        if not self.whatsapp_phone_number_id:
            return False, "WHATSAPP_PHONE_NUMBER_ID ayarlanmamış"
        if not to.strip():
            return False, "WhatsApp mesajı için alıcı numarası gerekli"

        payload = {
            "messaging_product": "whatsapp",
            "to": to.strip(),
            "type": "text",
            "text": {"body": text.strip(), "preview_url": bool(preview_url)},
        }
        ok, response = await self._post(f"{self.whatsapp_phone_number_id}/messages", payload)
        if not ok:
            return False, str(response)
        messages = response.get("messages") if isinstance(response, dict) else []
        first = messages[0] if isinstance(messages, list) and messages else {}
        return True, str(first.get("id") or "")

    async def publish_content(
        self,
        *,
        platform: str,
        text: str,
        media_url: str = "",
        link_url: str = "",
        destination: str = "",
    ) -> tuple[bool, str]:
        normalized = (platform or "").strip().lower()
        if normalized == "instagram":
            return await self.publish_instagram_post(caption=text, image_url=media_url)
        if normalized == "facebook":
            return await self.publish_facebook_post(message=text, link_url=link_url)
        if normalized == "whatsapp":
            return await self.send_whatsapp_message(
                to=destination, text=text, preview_url=bool(link_url.strip())
            )
        return False, f"Desteklenmeyen sosyal medya platformu: {platform}"

    @staticmethod
    def build_content_preview(
        platform: str, text: str, *, media_url: str = "", link_url: str = "", destination: str = ""
    ) -> str:
        payload = {
            "platform": (platform or "").strip().lower(),
            "text": (text or "").strip(),
            "media_url": (media_url or "").strip(),
            "link_url": (link_url or "").strip(),
            "destination": (destination or "").strip(),
        }
        return json.dumps(payload, ensure_ascii=False)
