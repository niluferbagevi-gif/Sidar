"""Slack Entegrasyon Yöneticisi (v6.0)

Bot token (xoxb-) ve/veya Webhook URL üzerinden Slack mesajlaşması sağlar.
slack-sdk paketi kurulu değilse Webhook-only moda düşer; her ikisi de
yoksa graceful degrade uygulanır.

Kullanım:
    mgr = SlackManager(token=cfg.SLACK_TOKEN, webhook_url=cfg.SLACK_WEBHOOK_URL)
    ok, err = await mgr.send_message(channel="#general", text="Merhaba!")
    ok, err = await mgr.send_webhook(text="Build başarılı ✅", blocks=[...])
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT = 10.0


def _is_valid_webhook_url(url: str) -> bool:
    normalized = (url or "").strip()
    return normalized.startswith("https://hooks.slack.com/") or normalized.startswith(
        "https://hooks.slack-gov.com/"
    )


class SlackManager:
    """
    Slack Bot API + Incoming Webhook entegrasyonu.

    Öncelik: Eğer slack-sdk kuruluysa ve token varsa → SDK kullanılır.
    Fallback: httpx ile doğrudan Webhook POST.
    """

    def __init__(
        self,
        token: str = "",  # nosec B107
        webhook_url: str = "",  # nosec B107
        default_channel: str = "",
    ) -> None:
        self.token = (token or "").strip()
        self.webhook_url = (webhook_url or "").strip()
        self.default_channel = (default_channel or "").strip()
        self._client: Any | None = None
        self._available = False
        self._webhook_only = False
        self._init_client()

    # ─────────────────────────────────────────────
    #  BAŞLATMA
    # ─────────────────────────────────────────────

    def _init_client(self) -> None:
        """SDK istemcisini hazırlar; token doğrulaması initialize() ile asenkron yapılır."""
        if self.token:
            try:
                from slack_sdk import WebClient

                self._client = WebClient(token=self.token)
                # Bulgu O-8: auth_test() burada çağrılmıyor — event loop'u bloklar.
                # Doğrulama initialize() içinde asyncio.to_thread ile yapılır.
                logger.debug(
                    "Slack SDK istemcisi oluşturuldu; token doğrulaması initialize() ile yapılacak."
                )
                return
            except ImportError:
                logger.warning("slack-sdk paketi kurulu değil. pip install slack-sdk")
            except Exception as exc:
                logger.error("Slack istemcisi oluşturma hatası: %s", exc)

        if self.webhook_url:
            if not _is_valid_webhook_url(self.webhook_url):
                logger.warning(
                    "Geçersiz Slack webhook URL formatı; webhook modu devre dışı bırakıldı."
                )
                return
            self._available = True
            self._webhook_only = True
            logger.info("Slack Webhook modu aktif.")
        elif not self.token:  # pragma: no cover
            logger.debug("Slack token ve webhook URL ayarlanmamış. Slack özellikleri devre dışı.")

    async def initialize(self) -> None:
        """Token doğrulamasını asyncio.to_thread ile asenkron yapar (event loop bloklanmaz).

        Bu metot, SlackManager oluşturulduktan sonra bir async bağlamda çağrılmalıdır.
        Örnek: await slack_manager.initialize()
        """
        import asyncio as _asyncio

        if not self._client or self._webhook_only:
            return
        try:
            resp = await _asyncio.to_thread(self._client.auth_test)
            if resp["ok"]:
                self._available = True
                logger.info("Slack bağlantısı kuruldu (SDK). Workspace: %s", resp.get("team"))
            else:
                self._available = False
                logger.error("Slack token doğrulama başarısız: %s", resp.get("error"))
                if self.webhook_url:  # pragma: no cover
                    self._available = True
                    self._webhook_only = True
                    logger.info("SDK doğrulama başarısız; Webhook moduna geçildi.")
        except Exception as exc:
            logger.error("Slack token doğrulama hatası: %s", exc)
            self._available = False
            if self.webhook_url:  # pragma: no cover
                self._available = True
                self._webhook_only = True
                logger.info("SDK doğrulama başarısız; Webhook moduna geçildi.")

    def is_available(self) -> bool:
        return self._available

    # ─────────────────────────────────────────────
    #  MESAJ GÖNDERME
    # ─────────────────────────────────────────────

    async def send_message(
        self,
        text: str,
        channel: str | None = None,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
    ) -> tuple[bool, str]:
        """
        Kanala mesaj gönderir (SDK veya Webhook fallback).
        Döner: (success: bool, error_or_ts: str)
        """
        if not self._available:
            return False, "Slack bağlantısı mevcut değil"

        ch = channel or self.default_channel
        if not ch and not self._webhook_only:
            return False, "Kanal belirtilmedi"

        # SDK yolu
        if self._client and not self._webhook_only:
            try:
                import asyncio

                kwargs: dict[str, Any] = {"channel": ch, "text": text}
                if blocks:
                    kwargs["blocks"] = blocks
                if thread_ts:
                    kwargs["thread_ts"] = thread_ts
                resp = await asyncio.to_thread(self._client.chat_postMessage, **kwargs)
                if resp["ok"]:
                    return True, resp.get("ts", "")
                error = resp.get("error", "Bilinmeyen hata")
                status_code = resp.get("status")
                if isinstance(status_code, int) and status_code >= 500:
                    return False, f"Slack API hatası ({status_code}): {error}"
                return False, error
            except Exception as exc:
                logger.error("Slack send_message SDK hatası: %s", exc)
                return False, str(exc)

        # Webhook fallback
        return await self.send_webhook(text=text, blocks=blocks)

    async def send_webhook(
        self,
        text: str = "",
        blocks: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> tuple[bool, str]:
        """Incoming Webhook URL'ye POST gönderir."""
        if not self.webhook_url:
            return False, "SLACK_WEBHOOK_URL ayarlanmamış"
        if not _is_valid_webhook_url(self.webhook_url):
            return False, "Geçersiz Slack webhook URL formatı"

        payload: dict[str, Any] = {}
        if text:  # pragma: no cover
            payload["text"] = text
        if blocks:
            payload["blocks"] = blocks
        if attachments:
            payload["attachments"] = attachments

        try:
            async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT) as client:
                resp = await client.post(
                    self.webhook_url,
                    content=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
            if resp.status_code == 200 and resp.text == "ok":
                return True, ""
            return False, f"HTTP {resp.status_code}: {resp.text}"
        except Exception as exc:
            logger.error("Slack webhook hatası: %s", exc)
            return False, str(exc)

    # ─────────────────────────────────────────────
    #  KANAL LİSTESİ
    # ─────────────────────────────────────────────

    async def list_channels(self, limit: int = 50) -> tuple[bool, list[dict[str, Any]], str]:
        """Workspace kanallarını listeler (SDK gerekli)."""
        if not self._client or self._webhook_only:
            return False, [], "Kanal listesi için slack-sdk ve bot token gerekli"
        try:
            import asyncio

            resp = await asyncio.to_thread(
                self._client.conversations_list,
                limit=min(limit, 200),
                types="public_channel,private_channel",
            )
            if resp["ok"]:
                channels = [
                    {"id": c["id"], "name": c["name"], "is_private": c.get("is_private", False)}
                    for c in resp.get("channels", [])
                ]
                return True, channels, ""
            return False, [], resp.get("error", "Bilinmeyen hata")
        except Exception as exc:
            return False, [], str(exc)

    # ─────────────────────────────────────────────
    #  BLOCK KIT YARDIMCILARI
    # ─────────────────────────────────────────────

    @staticmethod
    def build_notification_blocks(
        title: str,
        body: str,
        status: str = "info",
        fields: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Zengin bildirim için Block Kit JSON üretir."""
        emoji = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "❌"}.get(status, "ℹ️")
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} {title}", "emoji": True},
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        ]
        if fields:
            blocks.append(
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*{f['key']}*\n{f['value']}"} for f in fields
                    ],
                }
            )
        blocks.append({"type": "divider"})
        return blocks
