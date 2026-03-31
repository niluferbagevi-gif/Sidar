"""Poyraz pazarlama workflow E2E senaryosu."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from agent.roles.poyraz_agent import PoyrazAgent
from config import Config


def test_poyraz_research_copy_and_publish_campaign_flow():
    async def _run_case() -> None:
        agent = PoyrazAgent(cfg=Config())

        agent.web.search = AsyncMock(return_value=(True, "trend: kısa video + UGC"))
        agent.call_llm = AsyncMock(return_value="Kampanya metni: Yeni ürün şimdi yayında!")
        agent.social.publish_content = AsyncMock(return_value=(True, "post_id=demo-123"))

        research = await agent.run_task("web_search|instagram kampanya trendleri")
        campaign_copy = await agent.run_task("generate_campaign_copy|Yeni ürün lansmanı için metin hazırla")
        publish = await agent.run_task(
            "publish_social|instagram|||Kampanya metni: Yeni ürün şimdi yayında!|||demo-account|||"
        )

        assert "trend:" in research
        assert "Kampanya metni" in campaign_copy
        assert "[SOCIAL:PUBLISHED]" in publish
        agent.web.search.assert_awaited_once()
        agent.call_llm.assert_awaited_once()
        agent.social.publish_content.assert_awaited_once()

    asyncio.run(_run_case())
