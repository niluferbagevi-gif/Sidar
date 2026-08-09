"""User account persistence and authentication helpers."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from core.db.auth import UserRecord
from core.db.helpers import new_entity_id as _new_entity_id
from core.db.helpers import sqlite_fetchone as _sqlite_fetchone
from core.db.helpers import utc_now_pair as _utc_now_pair


async def ensure_user(db: Any, username: str, role: str = "user") -> UserRecord:
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, username, role, created_at, tenant_id FROM users WHERE username=$1",
                username,
            )
            if row:
                return UserRecord(
                    id=str(row["id"]),
                    username=str(row["username"]),
                    role=str(row["role"]),
                    created_at=str(row["created_at"]),
                    tenant_id=str(
                        row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]
                    ),
                )
        return cast(UserRecord, await db.create_user(username=username, role=role))

    assert db._sqlite_conn is not None

    def _fetch() -> sqlite3.Row | None:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            "SELECT id, username, role, created_at, tenant_id FROM users WHERE username=?",
            (username,),
        )
        return _sqlite_fetchone(cur)

    row = await db._run_sqlite_op(_fetch)
    if row:
        return UserRecord(
            id=str(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            created_at=str(row["created_at"]),
        )
    return cast(UserRecord, await db.create_user(username=username, role=role))


async def create_user(
    db: Any,
    username: str,
    role: str,
    password: str | None,
    tenant_id: str,
    hash_password: Callable[[str], str],
) -> UserRecord:
    user_id = _new_entity_id()
    created_at_dt, created_at = _utc_now_pair()
    password_hash = await asyncio.to_thread(hash_password, password) if password else None

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, username, password_hash, role, tenant_id, created_at)"
                " VALUES ($1, $2, $3, $4, $5, $6)",
                user_id,
                username,
                password_hash,
                role,
                tenant_id,
                created_at_dt,
            )
        return UserRecord(
            id=user_id, username=username, role=role, created_at=created_at, tenant_id=tenant_id
        )

    assert db._sqlite_conn is not None

    def _run() -> None:
        assert db._sqlite_conn is not None
        db._sqlite_conn.execute(
            "INSERT INTO users (id, username, password_hash, role, tenant_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, password_hash, role, tenant_id, created_at),
        )
        db._sqlite_conn.commit()

    await db._run_sqlite_op(_run)
    return UserRecord(
        id=user_id, username=username, role=role, created_at=created_at, tenant_id=tenant_id
    )


async def register_user(
    db: Any,
    username: str,
    password: str,
    role: str = "user",
    tenant_id: str = "default",
) -> UserRecord:
    return cast(
        UserRecord,
        await db.create_user(username=username, role=role, password=password, tenant_id=tenant_id),
    )


async def authenticate_user(
    db: Any,
    username: str,
    password: str,
    verify_password: Callable[[str, str], bool],
) -> UserRecord | None:
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, username, password_hash, role, created_at, tenant_id FROM users WHERE "
                "username=$1",
                username,
            )
        if not row or not row["password_hash"]:
            return None
        if not await asyncio.to_thread(verify_password, password, str(row["password_hash"])):
            return None
        return UserRecord(
            id=str(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            created_at=str(row["created_at"]),
            tenant_id=str(
                row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]
            ),
        )

    assert db._sqlite_conn is not None

    def _run() -> sqlite3.Row | None:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            "SELECT id, username, password_hash, role, created_at, tenant_id FROM users WHERE "
            "username=?",
            (username,),
        )
        return _sqlite_fetchone(cur)

    row = await db._run_sqlite_op(_run)
    if not row or not row["password_hash"]:
        return None
    if not await asyncio.to_thread(verify_password, password, str(row["password_hash"])):
        return None
    return UserRecord(
        id=str(row["id"]),
        username=str(row["username"]),
        role=str(row["role"]),
        created_at=str(row["created_at"]),
        tenant_id=str(row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]),
    )


async def get_user_by_id(db: Any, user_id: str) -> UserRecord | None:
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, username, role, created_at, tenant_id FROM users WHERE id=$1",
                user_id,
            )
        if not row:
            return None
        return UserRecord(
            id=str(row["id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            created_at=str(row["created_at"]),
            tenant_id=str(
                row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]
            ),
        )

    assert db._sqlite_conn is not None

    def _run() -> sqlite3.Row | None:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            "SELECT id, username, role, created_at, tenant_id FROM users WHERE id=?",
            (user_id,),
        )
        return _sqlite_fetchone(cur)

    row = await db._run_sqlite_op(_run)
    if not row:
        return None
    return UserRecord(
        id=str(row["id"]),
        username=str(row["username"]),
        role=str(row["role"]),
        created_at=str(row["created_at"]),
        tenant_id=str(row.get("tenant_id", "default") if hasattr(row, "get") else row["tenant_id"]),
    )


async def ensure_user_id(
    db: Any,
    user_id: str,
    username: str | None = None,
    role: str = "user",
    tenant_id: str = "default",
) -> UserRecord:
    """Belirli `user_id` için kullanıcı kaydının varlığını garanti eder."""
    existing: UserRecord | None = await db._get_user_by_id(user_id)
    if existing:
        return existing

    created_at_dt = datetime.now(UTC)
    created_at = created_at_dt.isoformat()
    normalized_username = str(username or user_id).strip() or str(user_id)
    normalized_role = str(role or "user").strip() or "user"
    normalized_tenant_id = str(tenant_id or "default").strip() or "default"

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users (id, username, password_hash, role, tenant_id, created_at)"
                " VALUES ($1, $2, $3, $4, $5, $6)",
                user_id,
                normalized_username,
                None,
                normalized_role,
                normalized_tenant_id,
                created_at_dt,
            )
        return UserRecord(
            id=user_id,
            username=normalized_username,
            role=normalized_role,
            created_at=created_at,
            tenant_id=normalized_tenant_id,
        )

    assert db._sqlite_conn is not None

    def _run() -> None:
        assert db._sqlite_conn is not None
        db._sqlite_conn.execute(
            "INSERT INTO users (id, username, password_hash, role, tenant_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id,
                normalized_username,
                None,
                normalized_role,
                normalized_tenant_id,
                created_at,
            ),
        )
        db._sqlite_conn.commit()

    await db._run_sqlite_op(_run)
    return UserRecord(
        id=user_id,
        username=normalized_username,
        role=normalized_role,
        created_at=created_at,
        tenant_id=normalized_tenant_id,
    )
