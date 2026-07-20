"""Marketing persistence boundary for the phased ``core.db`` split."""

from __future__ import annotations

from typing import Any

from core.db.records import ContentAssetRecord, MarketingCampaignRecord, OperationChecklistRecord

__all__ = [
    "ContentAssetRecord",
    "MarketingCampaignRecord",
    "OperationChecklistRecord",
    "list_content_assets",
    "list_marketing_campaigns",
    "list_operation_checklists",
]


async def list_marketing_campaigns(
    db: Any,
    *,
    tenant_id: str,
    status: str | None = None,
    limit: int = 100,
) -> list[MarketingCampaignRecord]:
    tenant = (tenant_id or "default").strip() or "default"
    normalized_status = (status or "").strip().lower() or None
    max_items = max(1, min(int(limit or 100), 500))
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        query = (
            "SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at "
            "FROM marketing_campaigns WHERE tenant_id=$1"
        )
        args: list[Any] = [tenant]
        if normalized_status:
            query += " AND status=$2"
            args.append(normalized_status)
        query += f" ORDER BY updated_at DESC LIMIT ${len(args) + 1}"
        args.append(max_items)
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
    else:
        assert db._sqlite_conn is not None

        def _run() -> list[Any]:
            assert db._sqlite_conn is not None
            if normalized_status:
                cur = db._sqlite_conn.execute(
                    """
                    SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at
                    FROM marketing_campaigns
                    WHERE tenant_id=? AND status=?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (tenant, normalized_status, max_items),
                )
            else:
                cur = db._sqlite_conn.execute(
                    """
                    SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget, metadata_json, created_at, updated_at
                    FROM marketing_campaigns
                    WHERE tenant_id=?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (tenant, max_items),
                )
            return cur.fetchall()

        rows = await db._run_sqlite_op(_run, write=False)
    return [
        MarketingCampaignRecord(
            id=int(row["id"]),
            tenant_id=str(row["tenant_id"]),
            name=str(row["name"]),
            channel=str(row["channel"]),
            objective=str(row["objective"]),
            status=str(row["status"]),
            owner_user_id=str(row["owner_user_id"]),
            budget=float(row["budget"] or 0.0),
            metadata_json=str(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    ]


async def list_content_assets(
    db: Any,
    *,
    tenant_id: str,
    campaign_id: int | None = None,
    limit: int = 100,
) -> list[ContentAssetRecord]:
    tenant = (tenant_id or "default").strip() or "default"
    max_items = max(1, min(int(limit or 100), 500))
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        query = (
            "SELECT id, campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at "
            "FROM content_assets WHERE tenant_id=$1"
        )
        args: list[Any] = [tenant]
        if campaign_id is not None:
            query += " AND campaign_id=$2"
            args.append(int(campaign_id))
        query += f" ORDER BY created_at DESC LIMIT ${len(args) + 1}"
        args.append(max_items)
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
    else:
        assert db._sqlite_conn is not None

        def _run() -> list[Any]:
            assert db._sqlite_conn is not None
            if campaign_id is not None:
                cur = db._sqlite_conn.execute(
                    """
                    SELECT id, campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at
                    FROM content_assets
                    WHERE tenant_id=? AND campaign_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (tenant, int(campaign_id), max_items),
                )
            else:
                cur = db._sqlite_conn.execute(
                    """
                    SELECT id, campaign_id, tenant_id, asset_type, title, content, channel, metadata_json, created_at, updated_at
                    FROM content_assets
                    WHERE tenant_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (tenant, max_items),
                )
            return cur.fetchall()

        rows = await db._run_sqlite_op(_run, write=False)
    return [
        ContentAssetRecord(
            id=int(row["id"]),
            campaign_id=int(row["campaign_id"]),
            tenant_id=str(row["tenant_id"]),
            asset_type=str(row["asset_type"]),
            title=str(row["title"]),
            content=str(row["content"]),
            channel=str(row["channel"]),
            metadata_json=str(row["metadata_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    ]


async def list_operation_checklists(
    db: Any,
    *,
    tenant_id: str,
    campaign_id: int | None = None,
    limit: int = 100,
) -> list[OperationChecklistRecord]:
    tenant = (tenant_id or "default").strip() or "default"
    max_items = max(1, min(int(limit or 100), 500))
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        query = (
            "SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at "
            "FROM operation_checklists WHERE tenant_id=$1"
        )
        args: list[Any] = [tenant]
        if campaign_id is not None:
            query += " AND campaign_id=$2"
            args.append(int(campaign_id))
        query += f" ORDER BY created_at DESC LIMIT ${len(args) + 1}"
        args.append(max_items)
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
    else:
        assert db._sqlite_conn is not None

        def _run() -> list[Any]:
            assert db._sqlite_conn is not None
            if campaign_id is not None:
                cur = db._sqlite_conn.execute(
                    """
                    SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at
                    FROM operation_checklists
                    WHERE tenant_id=? AND campaign_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (tenant, int(campaign_id), max_items),
                )
            else:
                cur = db._sqlite_conn.execute(
                    """
                    SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id, created_at, updated_at
                    FROM operation_checklists
                    WHERE tenant_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (tenant, max_items),
                )
            return cur.fetchall()

        rows = await db._run_sqlite_op(_run, write=False)
    return [
        OperationChecklistRecord(
            id=int(row["id"]),
            campaign_id=None if row["campaign_id"] is None else int(row["campaign_id"]),
            tenant_id=str(row["tenant_id"]),
            title=str(row["title"]),
            items_json=str(row["items_json"]),
            status=str(row["status"]),
            owner_user_id=str(row["owner_user_id"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    ]
