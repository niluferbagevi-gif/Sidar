"""Supervisor -> Poyraz -> tool -> LLM uçtan uca workflow testi."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

from agent.core.supervisor import SupervisorAgent
from agent.roles.poyraz_agent import PoyrazAgent
from config import Config


def _build_cfg(tmp_path):
    cfg = Config()
    cfg.AI_PROVIDER = "ollama"
    cfg.CODING_MODEL = "qwen2.5-coder:7b"
    cfg.TEXT_MODEL = "qwen2.5-coder:7b"
    cfg.REACT_TIMEOUT = 30
    cfg.MAX_QA_RETRIES = 2
    cfg.RAG_DIR = str(tmp_path / "rag")
    cfg.RAG_TOP_K = 3
    cfg.RAG_CHUNK_SIZE = 256
    cfg.RAG_CHUNK_OVERLAP = 24
    cfg.USE_GPU = False
    cfg.GPU_DEVICE = 0
    cfg.GPU_MIXED_PRECISION = False
    cfg.META_GRAPH_API_TOKEN = ""
    cfg.INSTAGRAM_BUSINESS_ACCOUNT_ID = ""
    cfg.FACEBOOK_PAGE_ID = ""
    cfg.WHATSAPP_PHONE_NUMBER_ID = ""
    cfg.META_GRAPH_API_VERSION = "v20.0"
    return cfg


def test_supervisor_routes_marketing_prompt_to_poyraz_and_returns_llm_text(tmp_path):
    cfg = _build_cfg(tmp_path)

    async def _run_case() -> None:
        supervisor = SupervisorAgent(cfg=cfg)
        poyraz = PoyrazAgent(cfg=cfg)

        # Dış bağımlılıkları izole et: web araması + LLM çağrısı
        poyraz.web.search = AsyncMock(return_value=(True, "[WEB] trendler"))
        poyraz.call_llm = AsyncMock(return_value=json.dumps({
            "channel": "instagram",
            "headline": "Kampanya açılış metni",
            "cta": "Hemen incele",
        }, ensure_ascii=False))

        supervisor.registry.register("poyraz", poyraz)
        supervisor.poyraz = poyraz

        result = await supervisor.run_task("Landing page kampanya metni oluştur")

        assert "instagram" in result
        assert "Kampanya açılış metni" in result
        poyraz.call_llm.assert_awaited_once()

    asyncio.run(_run_case())