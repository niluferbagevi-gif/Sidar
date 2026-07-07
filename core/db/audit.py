"""Audit log persistence helpers for the phased ``core.db`` split."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, cast

logger = logging.getLogger(__name__)


async def record_audit_log(
    db: Any,
    *,
    record_cls: type[Any],  # kept for symmetric call sites and future typed factories
    parse_iso_datetime: Any,
    utc_now_iso: Any,
    user_id: str = "",
    tenant_id: str = "default",
    action: str,
    resource: str,
    ip_address: str,
    allowed: bool,
    timestamp: str | None = None,
) -> None:
    del record_cls
    event_time = (timestamp or utc_now_iso()).strip() or utc_now_iso()
    event_time_dt = parse_iso_datetime(event_time)
    tenant = (tenant_id or "default").strip() or "default"
    user = (user_id or "").strip()
    act = (action or "").strip().lower()
    res = (resource or "").strip()
    ip = (ip_address or "unknown").strip() or "unknown"
    if not act or not res:
        raise ValueError("action and resource are required")

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_logs (user_id, tenant_id, action, resource, ip_address, allowed, timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                user,
                tenant,
                act,
                res,
                ip,
                bool(allowed),
                event_time_dt,
            )
        return

    assert db._sqlite_conn is not None

    def _run() -> None:
        assert db._sqlite_conn is not None
        db._sqlite_conn.execute(
            """
            INSERT INTO audit_logs (user_id, tenant_id, action, resource, ip_address, allowed, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user, tenant, act, res, ip, int(bool(allowed)), event_time),
        )
        db._sqlite_conn.commit()

    try:
        await db._run_sqlite_op(_run)
    except sqlite3.Error:
        logger.exception("SQLite audit log insert failed.")
        raise RuntimeError("SQLite audit log insert failed.") from None


async def list_audit_logs(
    db: Any,
    *,
    record_cls: type[Any],
    user_id: str | None = None,
    tenant_id: str | None = None,
    limit: int = 100,
) -> list[Any]:
    max_items = max(1, min(int(limit or 100), 1000))
    normalized_user = (user_id or "").strip() or None
    normalized_tenant = (tenant_id or "").strip() or None
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        query = (
            "SELECT id, user_id, tenant_id, action, resource, ip_address, allowed, timestamp "
            "FROM audit_logs"
        )
        conditions: list[str] = []
        args_list: list[Any] = []
        if normalized_user is not None:
            args_list.append(normalized_user)
            conditions.append(f"user_id=${len(args_list)}")
        if normalized_tenant is not None:
            args_list.append(normalized_tenant)
            conditions.append(f"tenant_id=${len(args_list)}")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        args_list.append(max_items)
        query += f" ORDER BY timestamp DESC LIMIT ${len(args_list)}"
        args = tuple(args_list)
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
    else:
        assert db._sqlite_conn is not None

        def _run() -> list[Any]:
            assert db._sqlite_conn is not None
            conditions: list[str] = []
            params: list[Any] = []
            if normalized_user is not None:
                conditions.append("user_id=?")
                params.append(normalized_user)
            if normalized_tenant is not None:
                conditions.append("tenant_id=?")
                params.append(normalized_tenant)
            query = (
                "SELECT id, user_id, tenant_id, action, resource, ip_address, allowed, timestamp "
                "FROM audit_logs"
            )
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(max_items)
            cur = db._sqlite_conn.execute(query, tuple(params))
            return cast(list[Any], cur.fetchall())

        try:
            rows = await db._run_sqlite_op(_run, write=False)
        except sqlite3.Error:
            logger.exception("SQLite audit log query failed.")
            raise RuntimeError("SQLite audit log query failed.") from None

    return [
        record_cls(
            id=int(r["id"]),
            user_id=str(r["user_id"]),
            tenant_id=str(r["tenant_id"]),
            action=str(r["action"]),
            resource=str(r["resource"]),
            ip_address=str(r["ip_address"]),
            allowed=bool(r["allowed"]),
            timestamp=str(r["timestamp"]),
        )
        for r in rows
    ]
