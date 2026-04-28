"""Basit kripto fiyat ajanı (marketplace plugin demosu)."""

from __future__ import annotations

import re

import httpx

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
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
            usd = payload.get(coin_id, {}).get("usd")
            if usd is None:
                return f"{symbol.upper()} için fiyat verisi alınamadı."
            return f"{symbol.upper()} güncel fiyatı: ${usd}"
        except Exception as exc:
            return f"{symbol.upper()} fiyatı alınamadı: {exc}"

    @staticmethod
    def _extract_symbol(task_prompt: str) -> str:
        lower = (task_prompt or "").lower()
        matches: list[str] = re.findall(r"[a-z]{3,10}", lower)
        return str(matches[0]) if matches else "btc"
