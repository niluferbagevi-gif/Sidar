import asyncio
from pathlib import Path
from types import SimpleNamespace

from core.db import Database


def _cfg(tmp_path: Path):
    return SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'ops.db'}",
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        BASE_DIR=tmp_path,
    )


def test_operations_tables_support_campaign_asset_and_checklist_workflows(tmp_path):
    async def _run():
        db = Database(cfg=_cfg(tmp_path))
        await db.connect()
        await db.init_schema()
        try:
            campaign = await db.upsert_marketing_campaign(
                tenant_id="tenant-a",
                name="Bahar Kampanyası",
                channel="instagram",
                objective="lead",
                owner_user_id="u-1",
                budget=1500,
                metadata={"region": "TR"},
            )
            asset = await db.add_content_asset(
                campaign_id=campaign.id,
                tenant_id="tenant-a",
                asset_type="landing_page",
                title="Ana sayfa taslağı",
                content="<section>demo</section>",
                channel="web",
                metadata={"locale": "tr-TR"},
            )
            checklist = await db.add_operation_checklist(
                campaign_id=campaign.id,
                tenant_id="tenant-a",
                title="Yayın öncesi kontrol",
                items=["UTM ekle", "Meta piksel doğrula"],
                owner_user_id="u-1",
            )

            campaigns = await db.list_marketing_campaigns(tenant_id="tenant-a", status="draft")
            assets = await db.list_content_assets(tenant_id="tenant-a", campaign_id=campaign.id)
            checklists = await db.list_operation_checklists(tenant_id="tenant-a", campaign_id=campaign.id)

            assert campaigns[0].name == "Bahar Kampanyası"
            assert asset.asset_type == "landing_page"
            assert assets[0].title == "Ana sayfa taslağı"
            assert "Meta piksel doğrula" in checklists[0].items_json
            assert checklist.owner_user_id == "u-1"
        finally:
            await db.close()

    asyncio.run(_run())


def test_operation_checklist_supports_structured_service_plans(tmp_path):
    async def _run():
        db = Database(cfg=_cfg(tmp_path))
        await db.connect()
        await db.init_schema()
        try:
            checklist = await db.add_operation_checklist(
                tenant_id="tenant-b",
                title="Etkinlik Operasyon Planı",
                items=[
                    {"type": "menu_plan", "group": "adult", "options": ["Izgara", "Meze"]},
                    {"type": "menu_plan", "group": "child", "options": ["Mini pizza"]},
                    {"type": "vendor_assignment", "role": "DJ", "assignee": "Deniz Prodüksiyon"},
                ],
                status="planned",
                owner_user_id="planner-1",
            )

            assert '"group": "adult"' in checklist.items_json
            assert '"role": "DJ"' in checklist.items_json
            assert checklist.status == "planned"
        finally:
            await db.close()

    asyncio.run(_run())
