"""Microsoft Teams Entegrasyon Yöneticisi (v6.0)

Incoming Webhook veya Azure Bot Service üzerinden Microsoft Teams
kanallarına mesaj ve Adaptive Card gönderir.

Kullanım:
    mgr = TeamsManager(webhook_url=cfg.TEAMS_WEBHOOK_URL)
    ok, err = await mgr.send_message("Deployment başarılı! 🚀")
    ok, err = await mgr.send_adaptive_card(card_payload)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0


class TeamsManager:
    """
    Microsoft Teams Incoming Webhook istemcisi.

    Teams Incoming Webhook URL'si Power Automate veya Teams kanalı
    ayarlarından oluşturulur.
    """

    def __init__(
        self,
        webhook_url: str = "",
        tenant_id: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> None:
        self.webhook_url = (webhook_url or "").strip()
        self.tenant_id = (tenant_id or "").strip()
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self._available = bool(self.webhook_url)
        if self._available:
            logger.info("Teams Webhook bağlantısı yapılandırıldı.")
        else:
            logger.debug("Teams webhook URL ayarlanmamış. Teams özellikleri devre dışı.")

    def is_available(self) -> bool:
        return self._available

    # ─────────────────────────────────────────────
    #  MESAJ GÖNDERME
    # ─────────────────────────────────────────────

    async def send_message(
        self,
        text: str,
        title: str = "",
        subtitle: str = "",
        facts: list[dict[str, str]] | None = None,
        actions: list[dict[str, Any]] | None = None,
        theme_color: str = "0078D4",
    ) -> tuple[bool, str]:
        """
        MessageCard formatında mesaj gönderir.
        Döner: (success, error_message)
        """
        if not self._available:
            return False, "TEAMS_WEBHOOK_URL ayarlanmamış"

        card: dict[str, Any] = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": theme_color,
            "summary": title or text[:100],
            "text": text,
        }
        if title:
            card["title"] = title
        if subtitle:
            card["text"] = f"**{subtitle}**\n\n{text}"
        if facts:
            card["sections"] = [{"facts": [{"name": f["key"], "value": f["value"]} for f in facts]}]
        if actions:
            card["potentialAction"] = actions

        return await self._post(card)

    async def send_adaptive_card(self, card_body: dict[str, Any]) -> tuple[bool, str]:
        """
        Adaptive Card v1.4 gönderir.
        card_body: Adaptive Card JSON (type, body, actions vb. içerir)
        """
        if not self._available:
            return False, "TEAMS_WEBHOOK_URL ayarlanmamış"

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": card_body,
                }
            ],
        }
        return await self._post(payload)

    async def send_notification(
        self,
        title: str,
        body: str,
        status: str = "info",
        details: list[dict[str, str]] | None = None,
        link_url: str = "",
        link_label: str = "Detaylar",
    ) -> tuple[bool, str]:
        """Hazır bildirim kartı gönderir."""
        colors = {
            "info": "0078D4",  # Mavi
            "success": "107C10",  # Yeşil
            "warning": "FF8C00",  # Turuncu
            "error": "D83B01",  # Kırmızı
        }
        theme_color = colors.get(status, "0078D4")

        actions = []
        if link_url:
            actions.append(
                {
                    "@type": "OpenUri",
                    "name": link_label,
                    "targets": [{"os": "default", "uri": link_url}],
                }
            )

        return await self.send_message(
            text=body,
            title=title,
            facts=details,
            actions=actions if actions else None,
            theme_color=theme_color,
        )

    # ─────────────────────────────────────────────
    #  ADAPTIVE CARD YARDIMCILARI
    # ─────────────────────────────────────────────

    @staticmethod
    def build_approval_card(
        request_id: str,
        title: str,
        description: str,
        requester: str = "",
        approve_url: str = "",
        reject_url: str = "",
    ) -> dict[str, Any]:
        """HITL onay akışı için Adaptive Card şablonu."""
        body: list[dict[str, Any]] = [
            {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": title},
            {"type": "TextBlock", "text": description, "wrap": True},
        ]
        if requester:
            body.append(
                {
                    "type": "FactSet",
                    "facts": [{"title": "İsteyen", "value": requester}],
                }
            )

        actions = []
        if approve_url:
            actions.append(
                {
                    "type": "Action.OpenUrl",
                    "title": "✅ Onayla",
                    "url": f"{approve_url}?request_id={request_id}&approved=true",
                }
            )
        if reject_url:
            actions.append(
                {
                    "type": "Action.OpenUrl",
                    "title": "❌ Reddet",
                    "url": f"{reject_url}?request_id={request_id}&approved=false",
                }
            )

        return {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": body,
            "actions": actions,
        }

    @staticmethod
    def build_summary_card(
        title: str,
        metrics: list[dict[str, str]],
        description: str = "",
    ) -> dict[str, Any]:
        """Metrik özeti için Adaptive Card şablonu."""
        body: list[dict[str, Any]] = [
            {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": title},
        ]
        if description:
            body.append({"type": "TextBlock", "text": description, "wrap": True})
        if metrics:
            body.append(
                {
                    "type": "FactSet",
                    "facts": [{"title": m["key"], "value": m["value"]} for m in metrics],
                }
            )
        return {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": body,
        }

    # ─────────────────────────────────────────────
    #  ÖZEL HTTP POST
    # ─────────────────────────────────────────────

    async def _post(self, payload: dict[str, Any]) -> tuple[bool, str]:
        """Webhook URL'ye JSON POST atar."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    self.webhook_url,
                    content=json.dumps(payload),
                    headers={"Content-Type": "application/json"},
                )
            # Teams webhook başarıda "1" döner
            if resp.status_code in (200, 201, 202) and resp.text.strip() in ("1", "ok", ""):
                return True, ""
            if resp.status_code in (200, 201, 202):
                return True, ""
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as exc:
            logger.error("Teams._post hatası: %s", exc)
            return False, str(exc)
