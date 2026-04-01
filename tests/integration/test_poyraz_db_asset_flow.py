from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("httpx")
pytest.importorskip("jwt")

from agent.roles.poyraz_agent import PoyrazAgent



def _build_cfg(tmp_path: Path):
    return SimpleNamespace(
        AI_PROVIDER="ollama",
        BASE_DIR=str(tmp_path),
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'poyraz_integration.db'}",
        DB_POOL_SIZE=2,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        JWT_SECRET="integration-secret",
        JWT_ALGORITHM="HS256",
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


def test_poyraz_can_create_campaign_and_persist_content_asset(tmp_path):
    cfg = _build_cfg(tmp_path)

    async def _run_case() -> None:
        poyraz = PoyrazAgent(cfg=cfg)
        try:
            campaign_raw = await poyraz._tool_create_marketing_campaign(
                json.dumps(
                    {
                        "tenant_id": "tenant-a",
                        "name": "Bahar Kampanyası",
                        "channel": "instagram",
                        "objective": "lead_generation",
                        "status": "draft",
                        "owner_user_id": "owner-1",
                        "budget": 1250.0,
                        "metadata": {"segment": "b2c"},
                    },
                    ensure_ascii=False,
                )
            )
            campaign_payload = json.loads(campaign_raw)
            assert campaign_payload["success"] is True
            campaign_id = int(campaign_payload["campaign"]["id"])

            asset_raw = await poyraz._tool_store_content_asset(
                json.dumps(
                    {
                        "campaign_id": campaign_id,
                        "tenant_id": "tenant-a",
                        "asset_type": "campaign_copy",
                        "title": "Instagram açılış metni",
                        "content": "Bahar fırsatları başladı",
                        "channel": "instagram",
                        "metadata": {"cta": "Hemen keşfet"},
                    },
                    ensure_ascii=False,
                )
            )
            asset_payload = json.loads(asset_raw)
            assert asset_payload["success"] is True
            assert asset_payload["asset"]["campaign_id"] == campaign_id

            db = await poyraz._ensure_db()
            campaigns = await db.list_marketing_campaigns("tenant-a")
            assets = await db.list_content_assets("tenant-a", campaign_id=campaign_id)

            assert len(campaigns) == 1
            assert campaigns[0].name == "Bahar Kampanyası"
            assert len(assets) == 1
            assert assets[0].title == "Instagram açılış metni"
        finally:
            db = await poyraz._ensure_db()
            await db.close()

    asyncio.run(_run_case())