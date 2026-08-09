"""Conversation session and message persistence helpers."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

T = TypeVar("T")


def _parse_asyncpg_affected_rows(command_tag: str) -> int:
    try:
        return int(str(command_tag).split()[-1])
    except (IndexError, TypeError, ValueError):
        return 0


def _session_record(record_cls: Callable[..., T], row: Any) -> T:
    return record_cls(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        title=str(row["title"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


async def list_sessions(db: Any, record_cls: Callable[..., T], user_id: str) -> list[T]:
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM sessions
                WHERE user_id=$1
                ORDER BY updated_at DESC
                """,
                user_id,
            )
    else:
        assert db._sqlite_conn is not None

        def _run() -> list[Any]:
            assert db._sqlite_conn is not None
            cur = db._sqlite_conn.execute(
                "SELECT id, user_id, title, created_at, updated_at FROM sessions WHERE user_id=? "
                "ORDER BY updated_at DESC",
                (user_id,),
            )
            return cast(list[Any], cur.fetchall())

        rows = await db._run_sqlite_op(_run, write=False)
    return [_session_record(record_cls, r) for r in rows]


async def count_sessions_total(db: Any) -> int:
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            value = await conn.fetchval("SELECT COUNT(*) FROM sessions")
        return int(value or 0)

    assert db._sqlite_conn is not None

    def _run() -> int:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute("SELECT COUNT(*) FROM sessions")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    return cast(int, await db._run_sqlite_op(_run, write=False))


async def load_session(
    db: Any,
    record_cls: Callable[..., T],
    sqlite_fetchone: Any,
    session_id: str,
    user_id: str | None = None,
) -> T | None:
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            if user_id:
                row = await conn.fetchrow(
                    "SELECT id, user_id, title, created_at, updated_at FROM sessions"
                    " WHERE id=$1 AND user_id=$2",
                    session_id,
                    user_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT id, user_id, title, created_at, updated_at FROM sessions WHERE id=$1",
                    session_id,
                )
    else:
        assert db._sqlite_conn is not None

        def _run() -> Any | None:
            assert db._sqlite_conn is not None
            if user_id:
                cur = db._sqlite_conn.execute(
                    "SELECT id, user_id, title, created_at, updated_at FROM sessions"
                    " WHERE id=? AND user_id=?",
                    (session_id, user_id),
                )
            else:
                cur = db._sqlite_conn.execute(
                    "SELECT id, user_id, title, created_at, updated_at FROM sessions WHERE id=?",
                    (session_id,),
                )
            return sqlite_fetchone(cur)

        row = await db._run_sqlite_op(_run)
    return _session_record(record_cls, row) if row else None


async def update_session_title(db: Any, session_id: str, title: str) -> bool:
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE sessions SET title=$1, updated_at=$2 WHERE id=$3",
                title,
                now_dt,
                session_id,
            )
        return _parse_asyncpg_affected_rows(result) > 0

    assert db._sqlite_conn is not None

    def _run() -> bool:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
            (title, now, session_id),
        )
        db._sqlite_conn.commit()
        return cast(bool, cur.rowcount > 0)

    return cast(bool, await db._run_sqlite_op(_run))


async def delete_session(db: Any, session_id: str, user_id: str | None = None) -> bool:
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            if user_id:
                result = await conn.execute(
                    "DELETE FROM sessions WHERE id=$1 AND user_id=$2", session_id, user_id
                )
            else:
                result = await conn.execute("DELETE FROM sessions WHERE id=$1", session_id)
        return _parse_asyncpg_affected_rows(result) > 0

    assert db._sqlite_conn is not None

    def _run() -> bool:
        assert db._sqlite_conn is not None
        if user_id:
            cur = db._sqlite_conn.execute(
                "DELETE FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)
            )
        else:
            cur = db._sqlite_conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        db._sqlite_conn.commit()
        return cast(bool, cur.rowcount > 0)

    return cast(bool, await db._run_sqlite_op(_run))


async def create_session(
    db: Any,
    record_cls: Callable[..., T],
    new_entity_id: Any,
    user_id: str,
    title: str,
) -> T:
    session_id = new_entity_id()
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sessions (id, user_id, title, created_at, updated_at) VALUES ($1, $2, "
                "$3, $4, $5)",
                session_id,
                user_id,
                title,
                now_dt,
                now_dt,
            )
    else:
        assert db._sqlite_conn is not None

        def _run() -> None:
            assert db._sqlite_conn is not None
            db._sqlite_conn.execute(
                "INSERT INTO sessions (id, user_id, title, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, user_id, title, now, now),
            )
            db._sqlite_conn.commit()

        await db._run_sqlite_op(_run)
    return record_cls(
        id=session_id,
        user_id=user_id,
        title=title,
        created_at=now,
        updated_at=now,
    )


async def add_message(
    db: Any,
    record_cls: Callable[..., T],
    session_id: str,
    role: str,
    content: str,
    tokens_used: int = 0,
) -> T:
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
    tokens = max(0, int(tokens_used or 0))

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO messages (session_id, role, content, tokens_used, created_at)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                session_id,
                role,
                content,
                tokens,
                now_dt,
            )
            msg_id = int(row["id"])
    else:
        assert db._sqlite_conn is not None

        def _run() -> int:
            assert db._sqlite_conn is not None
            cur = db._sqlite_conn.execute(
                "INSERT INTO messages (session_id, role, content, tokens_used, created_at) VALUES "
                "(?, ?, ?, ?, ?)",
                (session_id, role, content, tokens, now),
            )
            db._sqlite_conn.commit()
            return int(cur.lastrowid) if cur.lastrowid is not None else 0

        msg_id = await db._run_sqlite_op(_run)
    return record_cls(
        id=msg_id,
        session_id=session_id,
        role=role,
        content=content,
        tokens_used=tokens,
        created_at=now,
    )


async def add_messages_bulk(db: Any, items: list[dict[str, object]]) -> int:
    prepared: list[tuple[str, str, str, int, datetime, str]] = []
    for item in items:
        session_id = str(item.get("session_id", "") or "").strip()
        role = str(item.get("role", "") or "").strip() or "user"
        content = str(item.get("content", "") or "")
        raw_tokens = item.get("tokens_used", 0)
        if isinstance(raw_tokens, bool):
            tokens = int(raw_tokens)
        elif isinstance(raw_tokens, int | float):
            tokens = int(raw_tokens)
        elif isinstance(raw_tokens, str):
            try:
                tokens = int(raw_tokens.strip() or "0")
            except ValueError:
                tokens = 0
        else:
            tokens = 0
        tokens = max(0, tokens)
        if not session_id:
            continue
        now_dt = datetime.now(UTC)
        prepared.append((session_id, role, content, tokens, now_dt, now_dt.isoformat()))

    if not prepared:
        return 0

    if db._backend == "postgresql":
        async with db.transaction() as conn:
            await conn.executemany(
                """
                INSERT INTO messages (session_id, role, content, tokens_used, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                [(s, r, c, t, dt) for s, r, c, t, dt, _iso in prepared],
            )
            return len(prepared)

    def _run() -> int:
        assert db._sqlite_conn is not None
        db._sqlite_conn.executemany(
            "INSERT INTO messages (session_id, role, content, tokens_used, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [(s, r, c, t, iso) for s, r, c, t, _dt, iso in prepared],
        )
        db._sqlite_conn.commit()
        return len(prepared)

    return cast(int, await db._run_sqlite_op(_run))


async def get_session_messages(db: Any, session_id: str) -> list[Any]:
    return [
        db._to_message_record(r) for r in await db._fetch_message_rows_by_session_ids([session_id])
    ]


async def get_messages_for_sessions(db: Any, session_ids: list[str]) -> dict[str, list[Any]]:
    normalized_ids = [
        str(session_id).strip() for session_id in session_ids if str(session_id).strip()
    ]
    if not normalized_ids:
        return {}
    rows = await db._fetch_message_rows_by_session_ids(normalized_ids)

    grouped: dict[str, list[Any]] = {session_id: [] for session_id in normalized_ids}
    for r in rows:
        record = db._to_message_record(r)
        grouped.setdefault(record.session_id, []).append(record)
    return grouped


async def replace_session_messages(
    db: Any, session_id: str, messages: list[dict[str, object]]
) -> int:
    normalized_messages = [
        {
            "role": str(item.get("role", "") or "").strip() or "assistant",
            "content": str(item.get("content", "") or "").strip(),
        }
        for item in list(messages or [])
        if str(item.get("content", "") or "").strip()
    ]
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()

    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            tx_ctx = conn.transaction()
            if inspect.isawaitable(tx_ctx):
                tx_ctx = await tx_ctx
            async with tx_ctx:
                await conn.execute("DELETE FROM messages WHERE session_id=$1", session_id)
                for item in normalized_messages:
                    await conn.execute(
                        """
                        INSERT INTO messages (session_id, role, content, tokens_used, created_at)
                        VALUES ($1, $2, $3, $4, $5)
                        """,
                        session_id,
                        item["role"],
                        item["content"],
                        0,
                        now_dt,
                    )
                await conn.execute(
                    "UPDATE sessions SET updated_at=$2 WHERE id=$1",
                    session_id,
                    now_dt,
                )
        return len(normalized_messages)

    assert db._sqlite_conn is not None

    def _run() -> int:
        assert db._sqlite_conn is not None
        db._sqlite_conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        for item in normalized_messages:
            db._sqlite_conn.execute(
                "INSERT INTO messages (session_id, role, content, tokens_used, created_at) VALUES "
                "(?, ?, ?, ?, ?)",
                (session_id, item["role"], item["content"], 0, now),
            )
        db._sqlite_conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?",
            (now, session_id),
        )
        db._sqlite_conn.commit()
        return len(normalized_messages)

    return cast(int, await db._run_sqlite_op(_run))
