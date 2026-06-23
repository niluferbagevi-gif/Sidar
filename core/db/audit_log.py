"""Audit log persistence helpers for the phased ``core.db`` split."""

from __future__ import annotations

from typing import Any


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

    await db._run_sqlite_op(_run)


async def list_audit_logs(
    db: Any,
    *,
    record_cls: type[Any],
    user_id: str | None = None,
    limit: int = 100,
) -> list[Any]:
    max_items = max(1, min(int(limit or 100), 1000))
    normalized_user = (user_id or "").strip() or None
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        query = (
            "SELECT id, user_id, tenant_id, action, resource, ip_address, allowed, timestamp "
            "FROM audit_logs"
        )
        args: tuple[Any, ...]
        if normalized_user is not None:
            query += " WHERE user_id=$1 ORDER BY timestamp DESC LIMIT $2"
            args = (normalized_user, max_items)
        else:
            query += " ORDER BY timestamp DESC LIMIT $1"
            args = (max_items,)
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
    else:
        assert db._sqlite_conn is not None

        def _run() -> list[Any]:
            assert db._sqlite_conn is not None
            if normalized_user is not None:
                cur = db._sqlite_conn.execute(
                    """
                    SELECT id, user_id, tenant_id, action, resource, ip_address, allowed, timestamp
                    FROM audit_logs
                    WHERE user_id=?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (normalized_user, max_items),
                )
            else:
                cur = db._sqlite_conn.execute(
                    """
                    SELECT id, user_id, tenant_id, action, resource, ip_address, allowed, timestamp
                    FROM audit_logs
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (max_items,),
                )
            return cur.fetchall()

        rows = await db._run_sqlite_op(_run, write=False)

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
