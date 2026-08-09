"""Marketing persistence boundary for the phased ``core.db`` split."""

from __future__ import annotations

import sqlite3
from typing import Any, cast

from core.db.helpers import json_dumps, sqlite_fetchone, utc_now_pair
from core.db.records import ContentAssetRecord, MarketingCampaignRecord, OperationChecklistRecord

__all__ = [
    "ContentAssetRecord",
    "MarketingCampaignRecord",
    "OperationChecklistRecord",
    "add_content_asset",
    "add_operation_checklist",
    "list_content_assets",
    "list_marketing_campaigns",
    "list_operation_checklists",
    "upsert_marketing_campaign",
]


async def upsert_marketing_campaign(
    db: Any,
    *,
    tenant_id: str = "default",
    name: str,
    channel: str = "",
    objective: str = "",
    status: str = "draft",
    owner_user_id: str = "",
    budget: float = 0.0,
    metadata: dict[str, Any] | None = None,
    campaign_id: int | None = None,
) -> MarketingCampaignRecord:
    tenant = (tenant_id or "default").strip() or "default"
    campaign_name = (name or "").strip()
    if not campaign_name:
        raise ValueError("campaign name is required")
    now_dt, now = utc_now_pair()
    normalized_status = (status or "draft").strip().lower() or "draft"
    metadata_json = json_dumps(metadata or {})
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            if campaign_id:
                row = await conn.fetchrow(
                    """
                    UPDATE marketing_campaigns
                    SET tenant_id=$2, name=$3, channel=$4, objective=$5, status=$6,
                        owner_user_id=$7, budget=$8, metadata_json=$9::jsonb, updated_at=$10
                    WHERE id=$1
                    RETURNING id, tenant_id, name, channel, objective, status, owner_user_id,
                    budget, metadata_json, created_at, updated_at
                    """,
                    int(campaign_id),
                    tenant,
                    campaign_name,
                    (channel or "").strip(),
                    (objective or "").strip(),
                    normalized_status,
                    (owner_user_id or "").strip(),
                    float(budget or 0.0),
                    metadata_json,
                    now_dt,
                )
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO marketing_campaigns (tenant_id, name, channel, objective, status,
                    owner_user_id, budget, metadata_json, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $9)
                    RETURNING id, tenant_id, name, channel, objective, status, owner_user_id,
                    budget, metadata_json, created_at, updated_at
                    """,
                    tenant,
                    campaign_name,
                    (channel or "").strip(),
                    (objective or "").strip(),
                    normalized_status,
                    (owner_user_id or "").strip(),
                    float(budget or 0.0),
                    metadata_json,
                    now_dt,
                )
        if row is None:
            raise ValueError("campaign not found")
        return MarketingCampaignRecord(
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

    assert db._sqlite_conn is not None

    def _run() -> sqlite3.Row:
        assert db._sqlite_conn is not None
        if campaign_id:
            db._sqlite_conn.execute(
                """
                UPDATE marketing_campaigns
                SET tenant_id=?, name=?, channel=?, objective=?, status=?, owner_user_id=?,
                budget=?, metadata_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    tenant,
                    campaign_name,
                    (channel or "").strip(),
                    (objective or "").strip(),
                    normalized_status,
                    (owner_user_id or "").strip(),
                    float(budget or 0.0),
                    metadata_json,
                    now,
                    int(campaign_id),
                ),
            )
            cur = db._sqlite_conn.execute(
                """
                SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget,
                metadata_json, created_at, updated_at
                FROM marketing_campaigns WHERE id=?
                """,
                (int(campaign_id),),
            )
        else:
            cur = db._sqlite_conn.execute(
                """
                INSERT INTO marketing_campaigns (tenant_id, name, channel, objective, status,
                owner_user_id, budget, metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    campaign_name,
                    (channel or "").strip(),
                    (objective or "").strip(),
                    normalized_status,
                    (owner_user_id or "").strip(),
                    float(budget or 0.0),
                    metadata_json,
                    now,
                    now,
                ),
            )
            cur = db._sqlite_conn.execute(
                """
                SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget,
                metadata_json, created_at, updated_at
                FROM marketing_campaigns WHERE id=?
                """,
                (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
            )
        row = sqlite_fetchone(cur)
        db._sqlite_conn.commit()
        if row is None:
            raise ValueError("campaign not found")
        return row

    row = await db._run_sqlite_op(_run)
    return MarketingCampaignRecord(
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


async def add_content_asset(
    db: Any,
    *,
    campaign_id: int,
    tenant_id: str = "default",
    asset_type: str,
    title: str,
    content: str,
    channel: str = "",
    metadata: dict[str, Any] | None = None,
) -> ContentAssetRecord:
    now_dt, now = utc_now_pair()
    tenant = (tenant_id or "default").strip() or "default"
    asset_kind = (asset_type or "").strip().lower()
    asset_title = (title or "").strip()
    asset_content = str(content or "").strip()
    if not asset_kind or not asset_title or not asset_content:
        raise ValueError("asset_type, title and content are required")
    metadata_json = json_dumps(metadata or {})
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO content_assets (campaign_id, tenant_id, asset_type, title, content,
                channel, metadata_json, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $8)
                RETURNING id, campaign_id, tenant_id, asset_type, title, content, channel,
                metadata_json, created_at, updated_at
                """,
                int(campaign_id),
                tenant,
                asset_kind,
                asset_title,
                asset_content,
                (channel or "").strip(),
                metadata_json,
                now_dt,
            )
        return ContentAssetRecord(
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

    assert db._sqlite_conn is not None

    def _run() -> sqlite3.Row:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            """
            INSERT INTO content_assets (campaign_id, tenant_id, asset_type, title, content, channel,
            metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(campaign_id),
                tenant,
                asset_kind,
                asset_title,
                asset_content,
                (channel or "").strip(),
                metadata_json,
                now,
                now,
            ),
        )
        row = sqlite_fetchone(
            db._sqlite_conn.execute(
                """
                SELECT id, campaign_id, tenant_id, asset_type, title, content, channel,
                metadata_json, created_at, updated_at
                FROM content_assets WHERE id=?
                """,
                (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
            )
        )
        db._sqlite_conn.commit()
        assert row is not None
        return row

    row = await db._run_sqlite_op(_run)
    return ContentAssetRecord(
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


async def add_operation_checklist(
    db: Any,
    *,
    tenant_id: str = "default",
    title: str,
    items: list[Any],
    status: str = "pending",
    owner_user_id: str = "",
    campaign_id: int | None = None,
) -> OperationChecklistRecord:
    tenant = (tenant_id or "default").strip() or "default"
    checklist_title = (title or "").strip()
    if not checklist_title:
        raise ValueError("title is required")
    normalized_items: list[Any] = []
    for item in list(items or []):
        if isinstance(item, dict):
            normalized_dict = {
                str(key).strip(): value for key, value in item.items() if str(key).strip()
            }
            if normalized_dict:
                normalized_items.append(normalized_dict)
            continue
        text = str(item).strip()
        if text:
            normalized_items.append(text)
    now_dt, now = utc_now_pair()
    items_json = json_dumps(normalized_items)
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO operation_checklists (campaign_id, tenant_id, title, items_json, status,
                owner_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $7)
                RETURNING id, campaign_id, tenant_id, title, items_json, status, owner_user_id,
                created_at, updated_at
                """,
                int(campaign_id) if campaign_id is not None else None,
                tenant,
                checklist_title,
                items_json,
                (status or "pending").strip().lower() or "pending",
                (owner_user_id or "").strip(),
                now_dt,
            )
        return OperationChecklistRecord(
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

    assert db._sqlite_conn is not None

    def _run() -> sqlite3.Row:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            """
            INSERT INTO operation_checklists (campaign_id, tenant_id, title, items_json, status,
            owner_user_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(campaign_id) if campaign_id is not None else None,
                tenant,
                checklist_title,
                items_json,
                (status or "pending").strip().lower() or "pending",
                (owner_user_id or "").strip(),
                now,
                now,
            ),
        )
        row = sqlite_fetchone(
            db._sqlite_conn.execute(
                """
                SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id,
                created_at, updated_at
                FROM operation_checklists WHERE id=?
                """,
                (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
            )
        )
        db._sqlite_conn.commit()
        assert row is not None
        return row

    row = await db._run_sqlite_op(_run)
    return OperationChecklistRecord(
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
            "SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget, "
            "metadata_json, created_at, updated_at "
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
                    SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget,
                    metadata_json, created_at, updated_at
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
                    SELECT id, tenant_id, name, channel, objective, status, owner_user_id, budget,
                    metadata_json, created_at, updated_at
                    FROM marketing_campaigns
                    WHERE tenant_id=?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (tenant, max_items),
                )
            return cast(list[Any], cur.fetchall())

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
            "SELECT id, campaign_id, tenant_id, asset_type, title, content, channel, "
            "metadata_json, created_at, updated_at "
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
                    SELECT id, campaign_id, tenant_id, asset_type, title, content, channel,
                    metadata_json, created_at, updated_at
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
                    SELECT id, campaign_id, tenant_id, asset_type, title, content, channel,
                    metadata_json, created_at, updated_at
                    FROM content_assets
                    WHERE tenant_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (tenant, max_items),
                )
            return cast(list[Any], cur.fetchall())

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
            "SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id, "
            "created_at, updated_at "
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
                    SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id,
                    created_at, updated_at
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
                    SELECT id, campaign_id, tenant_id, title, items_json, status, owner_user_id,
                    created_at, updated_at
                    FROM operation_checklists
                    WHERE tenant_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (tenant, max_items),
                )
            return cast(list[Any], cur.fetchall())

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
