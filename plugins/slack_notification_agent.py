"""Slack bildirimleri için hot-loadable marketplace plugin'i."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.request

from agent.base_agent import BaseAgent


class SlackNotificationAgent(BaseAgent):
    """Slack webhook veya bot token ile kanal bildirimi gönderen ajan."""

    ROLE_NAME = "slack_notifications"

    async def run_task(self, task_prompt: str) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "Slack bildirimi göndermek için mesaj gerekli."

        channel = self._extract_channel(prompt) or self.cfg.SLACK_DEFAULT_CHANNEL
        message = self._extract_message(prompt)

        webhook = (self.cfg.SLACK_WEBHOOK_URL or "").strip()
        if not webhook:
            return "SLACK_WEBHOOK_URL veya SLACK_TOKEN ayarlanmamış. Önce Slack bağlantısını yapılandırın."

        try:
            req = urllib.request.Request(
                webhook,
                data=json.dumps({"text": message}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            response = await asyncio.to_thread(urllib.request.urlopen, req, timeout=10)
            with response:
                body = response.read().decode("utf-8", errors="replace").strip()
            return self._format_response(True, body or "ok", channel, message)
        except Exception as exc:
            return self._format_response(False, str(exc), channel, message)

    @staticmethod
    def _extract_channel(prompt: str) -> str:
        match = re.search(r"#([a-z0-9._-]{2,80})", prompt.lower())
        return match.group(1) if match else ""

    @staticmethod
    def _extract_message(prompt: str) -> str:
        cleaned = re.sub(r"#([a-z0-9._-]{2,80})", "", prompt, flags=re.IGNORECASE).strip()
        return cleaned or "SİDAR tarafından tetiklenen Slack bildirimi."

    @staticmethod
    def _format_response(ok: bool, detail: str, channel: str, message: str) -> str:
        prefix = f"#{channel} kanalına" if channel else "varsayılan Slack kanalına"
        if ok:
            return f"{prefix} bildirim gönderildi: {message[:140]} ({detail})"
        return f"{prefix} bildirim gönderilemedi: {detail}"
