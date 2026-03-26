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


def test_operations_tables_cover_sqlite_validations_updates_and_listing_filters(tmp_path):
    async def _run():
        db = Database(cfg=_cfg(tmp_path))
        await db.connect()
        await db.init_schema()
        try:
            with __import__("pytest").raises(ValueError, match="campaign name is required"):
                await db.upsert_marketing_campaign(name="   ")

            with __import__("pytest").raises(ValueError, match="asset_type, title and content are required"):
                await db.add_content_asset(campaign_id=1, asset_type="", title="", content="")

            with __import__("pytest").raises(ValueError, match="title is required"):
                await db.add_operation_checklist(title=" ", items=[])

            with __import__("pytest").raises(ValueError, match="command is required"):
                await db.create_coverage_task(command=" ", pytest_output="")

            with __import__("pytest").raises(ValueError, match="finding_type and summary are required"):
                await db.add_coverage_finding(task_id=1, finding_type=" ", target_path="", summary=" ")

            created = await db.upsert_marketing_campaign(
                tenant_id="tenant-z",
                name="İlk Kampanya",
                channel="instagram",
                objective="lead",
                status="draft",
                owner_user_id="u-1",
                budget=100,
                metadata={"region": "TR"},
            )
            updated = await db.upsert_marketing_campaign(
                campaign_id=created.id,
                tenant_id="tenant-z",
                name="İkinci Kampanya",
                channel="linkedin",
                objective="pipeline",
                status="ACTIVE",
                owner_user_id="u-2",
                budget=250,
                metadata={"segment": "b2b"},
            )

            assert updated.id == created.id
            assert updated.name == "İkinci Kampanya"
            assert updated.status == "active"

            campaigns_all = await db.list_marketing_campaigns(tenant_id="tenant-z", limit=0)
            campaigns_active = await db.list_marketing_campaigns(tenant_id="tenant-z", status="ACTIVE", limit=1)
            assert campaigns_all[0].id == created.id
            assert campaigns_active[0].status == "active"

            asset = await db.add_content_asset(
                campaign_id=created.id,
                tenant_id="tenant-z",
                asset_type="Landing_Page",
                title="LP V2",
                content="<section>demo</section>",
                channel="web",
                metadata={"lang": "tr"},
            )
            assets_all = await db.list_content_assets(tenant_id="tenant-z", limit=0)
            assets_by_campaign = await db.list_content_assets(tenant_id="tenant-z", campaign_id=created.id, limit=1)
            assert asset.asset_type == "landing_page"
            assert assets_all[0].campaign_id == created.id
            assert assets_by_campaign[0].title == "LP V2"

            checklist = await db.add_operation_checklist(
                tenant_id="tenant-z",
                campaign_id=created.id,
                title="Operasyon",
                items=[{" type ": "vendor", "role": "DJ"}, "  ", "sahne kurulumu"],
                status="PLANNED",
                owner_user_id="u-3",
            )
            checklists_all = await db.list_operation_checklists(tenant_id="tenant-z", limit=0)
            checklists_by_campaign = await db.list_operation_checklists(tenant_id="tenant-z", campaign_id=created.id, limit=1)
            assert checklist.status == "planned"
            assert '"type": "vendor"' in checklist.items_json
            assert checklists_all[0].id == checklist.id
            assert checklists_by_campaign[0].campaign_id == created.id

            task = await db.create_coverage_task(
                tenant_id="tenant-z",
                requester_role="coverage",
                command="pytest tests/test_ops.py -q",
                pytest_output="1 failed",
                status="pending_review",
                target_path="core/db.py",
                suggested_test_path="tests/test_db_runtime.py",
                review_payload_json='{"decision":"pending"}',
            )
            finding = await db.add_coverage_finding(
                task_id=task.id,
                finding_type="missing_coverage",
                target_path="core/db.py",
                summary="Eksik satırlar",
                details={"lines": [1, 2]},
            )
            tasks_all = await db.list_coverage_tasks(tenant_id="tenant-z", limit=0)
            tasks_filtered = await db.list_coverage_tasks(tenant_id="tenant-z", status="pending_review", limit=1)

            assert finding.task_id == task.id
            assert tasks_all[0].id == task.id
            assert tasks_filtered[0].status == "pending_review"
        finally:
            await db.close()

    asyncio.run(_run())


def test_upsert_marketing_campaign_raises_when_sqlite_insert_row_cannot_be_loaded(tmp_path):
    async def _run():
        db = Database(cfg=_cfg(tmp_path))

        class _Cursor:
            def __init__(self, *, lastrowid=None, row=None):
                self.lastrowid = lastrowid
                self._row = row

            def fetchone(self):
                return self._row

        class _Conn:
            def __init__(self):
                self.calls = 0

            def execute(self, _sql, _params=()):
                self.calls += 1
                if self.calls == 1:
                    return _Cursor(lastrowid=91)
                return _Cursor(row=None)

            def commit(self):
                return None

        db._sqlite_conn = _Conn()
        db._run_sqlite_op = lambda fn: asyncio.sleep(0, result=fn())  # type: ignore[method-assign]

        try:
            await db.upsert_marketing_campaign(
                tenant_id="tenant-a",
                name="Launch",
                channel="instagram",
                objective="lead",
            )
        except ValueError as exc:
            assert str(exc) == "campaign not found"
        else:
            assert False, "expected ValueError"

    asyncio.run(_run())