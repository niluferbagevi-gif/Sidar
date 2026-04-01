"""Poyraz pazarlama workflow E2E senaryosu."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from agent.roles.poyraz_agent import PoyrazAgent
from config import Config


async def test_poyraz_research_copy_and_publish_campaign_flow():
    agent = PoyrazAgent(cfg=Config())

    agent.web.search = AsyncMock(return_value=(True, "trend: kısa video + UGC"))

    async def _mock_llm_response(*args, **kwargs):
        prompt_payload = f"{args} {kwargs}".lower()
        if "research" in prompt_payload or "trend" in prompt_payload:
            return "trend: kısa video + UGC"
        if "kampanya" in prompt_payload or "metin" in prompt_payload:
            return "Kampanya metni: Yeni ürün şimdi yayında!"
        return "ok"

    agent.call_llm = AsyncMock(side_effect=_mock_llm_response)
    agent.social.publish_content = AsyncMock(return_value=(True, "post_id=demo-123"))

    research = await asyncio.wait_for(
        agent.run_task("web_search|instagram kampanya trendleri"), timeout=30
    )
    campaign_copy = await asyncio.wait_for(
        agent.run_task("generate_campaign_copy|Yeni ürün lansmanı için metin hazırla"), timeout=30
    )
    publish = await asyncio.wait_for(
        agent.run_task(
            "publish_social|instagram|||Kampanya metni: Yeni ürün şimdi yayında!|||demo-account|||"
        ),
        timeout=30,
    )

    assert "trend:" in research
    assert "Kampanya metni" in campaign_copy
    assert "[SOCIAL:PUBLISHED]" in publish
    agent.web.search.assert_awaited_once()
    assert agent.call_llm.await_count == 1
    agent.social.publish_content.assert_awaited_once()
