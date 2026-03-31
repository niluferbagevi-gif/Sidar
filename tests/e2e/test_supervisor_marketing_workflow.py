"""Supervisor -> Poyraz -> tool -> LLM uçtan uca workflow testi."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.core.supervisor import SupervisorAgent
from agent.roles.poyraz_agent import PoyrazAgent


def _build_cfg(tmp_path: Path):
    return SimpleNamespace(
        AI_PROVIDER="ollama",
        CODING_MODEL="qwen2.5-coder:7b",
        TEXT_MODEL="qwen2.5-coder:7b",
        REACT_TIMEOUT=30,
        MAX_QA_RETRIES=2,
        RAG_DIR=str(tmp_path / "rag"),
        RAG_TOP_K=3,
        RAG_CHUNK_SIZE=256,
        RAG_CHUNK_OVERLAP=24,
        USE_GPU=False,
        GPU_DEVICE=0,
        GPU_MIXED_PRECISION=False,
        META_GRAPH_API_TOKEN="",
        INSTAGRAM_BUSINESS_ACCOUNT_ID="",
        FACEBOOK_PAGE_ID="",
        WHATSAPP_PHONE_NUMBER_ID="",
        META_GRAPH_API_VERSION="v20.0",
    )


@pytest.mark.asyncio
async def test_supervisor_routes_marketing_prompt_to_poyraz_and_returns_llm_text(tmp_path: Path):
    cfg = _build_cfg(tmp_path)

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
