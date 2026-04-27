"""Basit kripto fiyat ajanı (marketplace plugin demosu)."""

from __future__ import annotations

import json
import re
import urllib.request

from agent.base_agent import BaseAgent


class CryptoPriceAgent(BaseAgent):
    """Kullanıcı mesajından coin sembolü çıkarıp anlık USD fiyatı döndürür."""

    SYMBOL_MAP = {
        "btc": "bitcoin",
        "bitcoin": "bitcoin",
        "eth": "ethereum",
        "ethereum": "ethereum",
        "sol": "solana",
        "solana": "solana",
    }

    async def run_task(self, task_prompt: str) -> str:
        symbol = self._extract_symbol(task_prompt)
        coin_id = self.SYMBOL_MAP.get(symbol)
        if not coin_id:
            supported = ", ".join(sorted({"btc", "eth", "sol"}))
            return f"Desteklenmeyen sembol: {symbol}. Desteklenenler: {supported}."

        url = "https://api.coingecko.com/api/v3/simple/price" f"?ids={coin_id}&vs_currencies=usd"

        try:
            with urllib.request.urlopen(url, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
                usd = payload.get(coin_id, {}).get("usd")
                if usd is None:
                    return f"{symbol.upper()} için fiyat verisi alınamadı."
                return f"{symbol.upper()} güncel fiyatı: ${usd}"
        except Exception as exc:
            return f"{symbol.upper()} fiyatı alınamadı: {exc}"

    @staticmethod
    def _extract_symbol(task_prompt: str) -> str:
        lower = (task_prompt or "").lower()
        matches = re.findall(r"[a-z]{3,10}", lower)
        return matches[0] if matches else "btc"
