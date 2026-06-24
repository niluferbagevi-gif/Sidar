"""Provider usage, quota and admin metric persistence helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast


async def record_provider_usage_daily(
    db: Any, user_id: str, provider: str, tokens_used: int, requests_inc: int = 1
) -> None:
    provider_name = (provider or "unknown").lower().strip() or "unknown"
    today = datetime.now(UTC).date().isoformat()
    req = max(0, int(requests_inc or 0))
    toks = max(0, int(tokens_used or 0))

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO provider_usage_daily (user_id, provider, usage_date, requests_used, tokens_used)
                VALUES ($1, $2, $3::date, $4, $5)
                ON CONFLICT (user_id, provider, usage_date)
                DO UPDATE SET requests_used=provider_usage_daily.requests_used + EXCLUDED.requests_used,
                              tokens_used=provider_usage_daily.tokens_used + EXCLUDED.tokens_used
                """,
                user_id,
                provider_name,
                today,
                req,
                toks,
            )
        return

    assert db._sqlite_conn is not None

    def _run() -> None:
        assert db._sqlite_conn is not None
        db._sqlite_conn.execute(
            """
            INSERT INTO provider_usage_daily (user_id, provider, usage_date, requests_used, tokens_used)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, provider, usage_date)
            DO UPDATE SET requests_used=requests_used + excluded.requests_used,
                          tokens_used=tokens_used + excluded.tokens_used
            """,
            (user_id, provider_name, today, req, toks),
        )
        db._sqlite_conn.commit()

    await db._run_sqlite_op(_run)


async def get_user_quota_status(
    db: Any, user_id: str, provider: str, sqlite_fetchone: Any
) -> dict[str, int | bool]:
    provider_name = (provider or "unknown").lower().strip() or "unknown"
    today = datetime.now(UTC).date().isoformat()

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            quota = await conn.fetchrow(
                "SELECT daily_token_limit, daily_request_limit FROM user_quotas WHERE user_id=$1",
                user_id,
            )
            usage = await conn.fetchrow(
                """
                SELECT requests_used, tokens_used
                FROM provider_usage_daily
                WHERE user_id=$1 AND provider=$2 AND usage_date=$3::date
                """,
                user_id,
                provider_name,
                today,
            )
        q_tokens = int((quota["daily_token_limit"] if quota else 0) or 0)
        q_reqs = int((quota["daily_request_limit"] if quota else 0) or 0)
        u_tokens = int((usage["tokens_used"] if usage else 0) or 0)
        u_reqs = int((usage["requests_used"] if usage else 0) or 0)
    else:
        assert db._sqlite_conn is not None

        def _run() -> tuple[Any | None, Any | None]:
            assert db._sqlite_conn is not None
            q = sqlite_fetchone(
                db._sqlite_conn.execute(
                    "SELECT daily_token_limit, daily_request_limit FROM user_quotas WHERE user_id=?",
                    (user_id,),
                )
            )
            u = sqlite_fetchone(
                db._sqlite_conn.execute(
                    "SELECT requests_used, tokens_used FROM provider_usage_daily WHERE user_id=? AND provider=? AND usage_date=?",
                    (user_id, provider_name, today),
                )
            )
            return q, u

        quota, usage = await db._run_sqlite_op(_run)
        q_tokens = int((quota["daily_token_limit"] if quota else 0) or 0)
        q_reqs = int((quota["daily_request_limit"] if quota else 0) or 0)
        u_tokens = int((usage["tokens_used"] if usage else 0) or 0)
        u_reqs = int((usage["requests_used"] if usage else 0) or 0)

    return {
        "daily_token_limit": q_tokens,
        "daily_request_limit": q_reqs,
        "tokens_used": u_tokens,
        "requests_used": u_reqs,
        "token_limit_exceeded": q_tokens > 0 and u_tokens >= q_tokens,
        "request_limit_exceeded": q_reqs > 0 and u_reqs >= q_reqs,
    }


async def list_users_with_quotas(db: Any) -> list[dict[str, Any]]:
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.id, u.username, u.role, u.created_at,
                       COALESCE(q.daily_token_limit, 0) AS daily_token_limit,
                       COALESCE(q.daily_request_limit, 0) AS daily_request_limit
                FROM users u
                LEFT JOIN user_quotas q ON q.user_id = u.id
                ORDER BY u.created_at ASC
                """
            )
            return [_user_quota_row(row) for row in rows]

    assert db._sqlite_conn is not None

    def _run() -> list[dict[str, Any]]:
        assert db._sqlite_conn is not None
        rows = db._sqlite_conn.execute(
            """
            SELECT u.id, u.username, u.role, u.created_at,
                   COALESCE(q.daily_token_limit, 0) AS daily_token_limit,
                   COALESCE(q.daily_request_limit, 0) AS daily_request_limit
            FROM users u
            LEFT JOIN user_quotas q ON q.user_id = u.id
            ORDER BY u.created_at ASC
            """
        ).fetchall()
        return [_user_quota_row(row) for row in rows]

    return cast(list[dict[str, Any]], await db._run_sqlite_op(_run))


def _user_quota_row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "username": str(row["username"]),
        "role": str(row["role"]),
        "created_at": str(row["created_at"]),
        "daily_token_limit": int(row["daily_token_limit"] or 0),
        "daily_request_limit": int(row["daily_request_limit"] or 0),
    }


async def get_admin_stats(db: Any, sqlite_fetchone: Any) -> dict[str, Any]:
    users = await list_users_with_quotas(db)

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            totals = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(tokens_used), 0) AS total_tokens_used,
                    COALESCE(SUM(requests_used), 0) AS total_api_requests
                FROM provider_usage_daily
                """
            )
    else:
        assert db._sqlite_conn is not None

        def _run_totals() -> Any:
            assert db._sqlite_conn is not None
            row = sqlite_fetchone(
                db._sqlite_conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(tokens_used), 0) AS total_tokens_used,
                        COALESCE(SUM(requests_used), 0) AS total_api_requests
                    FROM provider_usage_daily
                    """
                )
            )
            assert row is not None
            return row

        totals = await db._run_sqlite_op(_run_totals)

    return {
        "total_users": len(users),
        "total_tokens_used": int(totals["total_tokens_used"] or 0),
        "total_api_requests": int(totals["total_api_requests"] or 0),
        "users": users,
    }
