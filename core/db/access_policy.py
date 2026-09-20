"""Access-policy persistence boundary for the phased ``core.db`` split."""

from __future__ import annotations

import sqlite3
from typing import Any, cast

from core.db.helpers import utc_now_pair
from core.db.records import AccessPolicyRecord

__all__ = [
    "AccessPolicyRecord",
    "check_access_policy",
    "list_access_policies",
    "upsert_access_policy",
]


async def list_access_policies(
    db: Any, user_id: str, tenant_id: str | None = None
) -> list[AccessPolicyRecord]:
    effective_tenant = (tenant_id or "").strip()
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        query = (
            "SELECT id, user_id, tenant_id, resource_type, resource_id, action, effect, "
            "created_at, updated_at "
            "FROM access_policies WHERE user_id=$1"
        )
        args: list[Any] = [user_id]
        if effective_tenant:
            query += " AND tenant_id=$2"
            args.append(effective_tenant)
        query += " ORDER BY resource_type, action, resource_id"
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return [
            AccessPolicyRecord(
                id=int(r["id"]),
                user_id=str(r["user_id"]),
                tenant_id=str(r["tenant_id"]),
                resource_type=str(r["resource_type"]),
                resource_id=str(r["resource_id"]),
                action=str(r["action"]),
                effect=str(r["effect"]),
                created_at=str(r["created_at"]),
                updated_at=str(r["updated_at"]),
            )
            for r in rows
        ]

    assert db._sqlite_conn is not None

    def _run() -> list[sqlite3.Row]:
        assert db._sqlite_conn is not None
        if effective_tenant:
            cur = db._sqlite_conn.execute(
                """
                SELECT id, user_id, tenant_id, resource_type, resource_id, action, effect,
                created_at, updated_at
                FROM access_policies
                WHERE user_id=? AND tenant_id=?
                ORDER BY resource_type, action, resource_id
                """,
                (user_id, effective_tenant),
            )
        else:
            cur = db._sqlite_conn.execute(
                """
                SELECT id, user_id, tenant_id, resource_type, resource_id, action, effect,
                created_at, updated_at
                FROM access_policies
                WHERE user_id=?
                ORDER BY resource_type, action, resource_id
                """,
                (user_id,),
            )
        return cast(list[sqlite3.Row], cur.fetchall())

    rows = await db._run_sqlite_op(_run, write=False)
    return [
        AccessPolicyRecord(
            id=int(r["id"]),
            user_id=str(r["user_id"]),
            tenant_id=str(r["tenant_id"]),
            resource_type=str(r["resource_type"]),
            resource_id=str(r["resource_id"]),
            action=str(r["action"]),
            effect=str(r["effect"]),
            created_at=str(r["created_at"]),
            updated_at=str(r["updated_at"]),
        )
        for r in rows
    ]


async def upsert_access_policy(
    db: Any,
    *,
    user_id: str,
    tenant_id: str = "default",
    resource_type: str,
    resource_id: str = "*",
    action: str,
    effect: str = "allow",
) -> None:
    now_dt, now = utc_now_pair()
    tenant = (tenant_id or "default").strip() or "default"
    r_type = (resource_type or "").strip().lower()
    r_id = (resource_id or "*").strip() or "*"
    act = (action or "").strip().lower()
    eff = (effect or "allow").strip().lower()
    if eff not in {"allow", "deny"}:
        raise ValueError("effect must be allow or deny")
    if not r_type or not act:
        raise ValueError("resource_type and action are required")

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO access_policies (user_id, tenant_id, resource_type, resource_id,
                action, effect, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                ON CONFLICT (user_id, tenant_id, resource_type, resource_id, action)
                DO UPDATE SET effect=EXCLUDED.effect, updated_at=EXCLUDED.updated_at
                """,
                user_id,
                tenant,
                r_type,
                r_id,
                act,
                eff,
                now_dt,
            )
        return

    assert db._sqlite_conn is not None

    def _run() -> None:
        assert db._sqlite_conn is not None
        db._sqlite_conn.execute(
            """
            INSERT INTO access_policies (user_id, tenant_id, resource_type, resource_id, action,
            effect, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, tenant_id, resource_type, resource_id, action)
            DO UPDATE SET effect=excluded.effect, updated_at=excluded.updated_at
            """,
            (user_id, tenant, r_type, r_id, act, eff, now, now),
        )
        db._sqlite_conn.commit()

    await db._run_sqlite_op(_run)


async def check_access_policy(
    db: Any,
    *,
    user_id: str,
    tenant_id: str = "default",
    resource_type: str,
    action: str,
    resource_id: str = "*",
) -> bool:
    tenant = (tenant_id or "default").strip() or "default"
    r_type = (resource_type or "").strip().lower()
    act = (action or "").strip().lower()
    r_id = (resource_id or "*").strip() or "*"
    if not user_id or not r_type or not act:
        return False

    policies = await db.list_access_policies(user_id=user_id, tenant_id=tenant)
    if not policies and tenant != "default":
        policies = await db.list_access_policies(user_id=user_id, tenant_id="default")

    def _match(spec: AccessPolicyRecord) -> bool:
        return (
            spec.resource_type == r_type
            and spec.action == act
            and (spec.resource_id == "*" or spec.resource_id == r_id)
        )

    matched = [p for p in policies if _match(p)]
    matched.sort(key=lambda p: 0 if p.resource_id == r_id else 1)
    if not matched:
        return False
    if any(p.effect == "deny" for p in matched):
        return False
    return any(p.effect == "allow" for p in matched)
