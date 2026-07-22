"""Prompt registry persistence helpers for ``core.db``."""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sqlite3
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

PROMPT_REGISTRY_COLUMNS = "id, role_name, prompt_text, version, is_active, created_at, updated_at"


def _prompt_record(prompt_record_cls: type[Any], row: Any, *, sqlite_bool: bool = False) -> Any:
    is_active = bool(int(row["is_active"])) if sqlite_bool else bool(row["is_active"])
    return prompt_record_cls(
        id=int(row["id"]),
        role_name=str(row["role_name"]),
        prompt_text=str(row["prompt_text"]),
        version=int(row["version"]),
        is_active=is_active,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


async def ensure_default_prompt_registry(db: Any, *, prompt_record_cls: type[Any]) -> None:
    definitions_path = Path(__file__).resolve().parents[2] / "agent" / "definitions.py"
    spec = importlib.util.spec_from_file_location("sidar_agent_definitions", definitions_path)
    default_prompt = ""
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        default_prompt = str(getattr(module, "SIDAR_SYSTEM_PROMPT", "") or "")

    existing = await get_active_prompt(db, "system", prompt_record_cls=prompt_record_cls)
    if existing or not default_prompt:
        return
    try:
        await upsert_prompt(
            db,
            "system",
            default_prompt,
            activate=True,
            prompt_record_cls=prompt_record_cls,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Varsayılan prompt kaydı oluşturulamadı: %s", exc)


async def list_prompts(
    db: Any, role_name: str | None = None, *, prompt_record_cls: type[Any]
) -> list[Any]:
    role = (role_name or "").strip() or None
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        query = f"SELECT {PROMPT_REGISTRY_COLUMNS} FROM prompt_registry"  # nosec B608  # PROMPT_REGISTRY_COLUMNS sabit modül seviyesi değerdir, kullanıcı girdisi değildir.
        args: tuple[Any, ...] = ()
        if role:
            query += " WHERE role_name=$1"
            args = (role,)
        query += " ORDER BY role_name ASC, version DESC"
        async with db._pg_pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return [_prompt_record(prompt_record_cls, row) for row in rows]

    assert db._sqlite_conn is not None

    def _run() -> list[sqlite3.Row]:
        assert db._sqlite_conn is not None
        if role:
            cur = db._sqlite_conn.execute(
                f"""
                SELECT {PROMPT_REGISTRY_COLUMNS}
                FROM prompt_registry
                WHERE role_name=?
                ORDER BY role_name ASC, version DESC
                """,  # nosec B608  # PROMPT_REGISTRY_COLUMNS sabit modül seviyesi değerdir, kullanıcı girdisi değildir.
                (role,),
            )
            return cast(list[sqlite3.Row], cur.fetchall())
        cur = db._sqlite_conn.execute(
            f"""
            SELECT {PROMPT_REGISTRY_COLUMNS}
            FROM prompt_registry
            ORDER BY role_name ASC, version DESC
            """  # nosec B608  # PROMPT_REGISTRY_COLUMNS sabit modül seviyesi değerdir, kullanıcı girdisi değildir.
        )
        return cast(list[sqlite3.Row], cur.fetchall())

    rows = await db._run_sqlite_op(_run, write=False)
    return [_prompt_record(prompt_record_cls, row, sqlite_bool=True) for row in rows]


async def get_active_prompt(db: Any, role_name: str, *, prompt_record_cls: type[Any]) -> Any | None:
    role = (role_name or "").strip().lower()
    if not role:
        return None
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {PROMPT_REGISTRY_COLUMNS}
                FROM prompt_registry
                WHERE role_name=$1 AND is_active=TRUE
                ORDER BY version DESC
                LIMIT 1
                """,  # nosec B608  # PROMPT_REGISTRY_COLUMNS sabit modül seviyesi değerdir, kullanıcı girdisi değildir.
                role,
            )
        if not row:
            return None
        return _prompt_record(prompt_record_cls, row)

    assert db._sqlite_conn is not None

    def _run() -> sqlite3.Row | None:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            f"""
            SELECT {PROMPT_REGISTRY_COLUMNS}
            FROM prompt_registry
            WHERE role_name=? AND is_active=1
            ORDER BY version DESC
            LIMIT 1
            """,  # nosec B608  # PROMPT_REGISTRY_COLUMNS sabit modül seviyesi değerdir, kullanıcı girdisi değildir.
            (role,),
        )
        return cast(sqlite3.Row | None, db._sqlite_fetchone(cur))

    row = await db._run_sqlite_op(_run)
    if not row:
        return None
    return _prompt_record(prompt_record_cls, row, sqlite_bool=True)


async def upsert_prompt(
    db: Any,
    role_name: str,
    prompt_text: str,
    *,
    activate: bool = True,
    prompt_record_cls: type[Any],
) -> Any:
    role = (role_name or "").strip().lower()
    text = (prompt_text or "").strip()
    if not role or not text:
        raise ValueError("role_name ve prompt_text boş olamaz")

    now_dt, now = db._utc_now_pair()
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            tx_ctx = conn.transaction()
            if inspect.isawaitable(tx_ctx):
                tx_ctx = await tx_ctx
            async with tx_ctx:
                current_version = await conn.fetchval(
                    "SELECT COALESCE(MAX(version), 0) FROM prompt_registry WHERE role_name=$1",
                    role,
                )
                new_version = int(current_version or 0) + 1
                if activate:
                    await conn.execute(
                        "UPDATE prompt_registry SET is_active=FALSE, updated_at=$2 WHERE "
                        "role_name=$1",
                        role,
                        now_dt,
                    )
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO prompt_registry (role_name, prompt_text, version, is_active, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING {PROMPT_REGISTRY_COLUMNS}
                    """,  # nosec B608  # PROMPT_REGISTRY_COLUMNS sabit modül seviyesi değerdir, kullanıcı girdisi değildir.
                    role,
                    text,
                    new_version,
                    activate,
                    now_dt,
                    now_dt,
                )
        return _prompt_record(prompt_record_cls, row)

    assert db._sqlite_conn is not None

    def _run() -> sqlite3.Row:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM prompt_registry WHERE role_name=?",
            (role,),
        )
        row = db._sqlite_fetchone(cur)
        new_version = int((row["v"] if row else 0) or 0) + 1
        if activate:
            db._sqlite_conn.execute(
                "UPDATE prompt_registry SET is_active=0, updated_at=? WHERE role_name=?",
                (now, role),
            )
        db._sqlite_conn.execute(
            """
            INSERT INTO prompt_registry (role_name, prompt_text, version, is_active, created_at,
            updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (role, text, new_version, 1 if activate else 0, now, now),
        )
        db._sqlite_conn.commit()
        out = db._sqlite_conn.execute(
            f"""
            SELECT {PROMPT_REGISTRY_COLUMNS}
            FROM prompt_registry WHERE role_name=? AND version=?
            """,  # nosec B608  # PROMPT_REGISTRY_COLUMNS sabit modül seviyesi değerdir, kullanıcı girdisi değildir.
            (role, new_version),
        )
        fetched = db._sqlite_fetchone(out)
        assert fetched is not None
        return cast(sqlite3.Row, fetched)

    inserted = await db._run_sqlite_op(_run)
    return _prompt_record(prompt_record_cls, inserted, sqlite_bool=True)


async def activate_prompt(db: Any, prompt_id: int, *, prompt_record_cls: type[Any]) -> Any | None:
    target_id = int(prompt_id)
    if target_id <= 0:
        return None

    now_dt, now = db._utc_now_pair()
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            tx_ctx = conn.transaction()
            if inspect.isawaitable(tx_ctx):
                tx_ctx = await tx_ctx
            async with tx_ctx:
                row = await conn.fetchrow(
                    "SELECT id, role_name FROM prompt_registry WHERE id=$1",
                    target_id,
                )
                if not row:
                    return None
                role = str(row["role_name"])
                await conn.execute(
                    "UPDATE prompt_registry SET is_active=FALSE, updated_at=$2 WHERE role_name=$1",
                    role,
                    now_dt,
                )
                await conn.execute(
                    "UPDATE prompt_registry SET is_active=TRUE, updated_at=$2 WHERE id=$1",
                    target_id,
                    now_dt,
                )
        return await db.get_active_prompt(role)

    assert db._sqlite_conn is not None

    def _run() -> str | None:
        assert db._sqlite_conn is not None
        row = db._sqlite_fetchone(
            db._sqlite_conn.execute(
                "SELECT role_name FROM prompt_registry WHERE id=?",
                (target_id,),
            )
        )
        if not row:
            return None
        role = str(row["role_name"])
        db._sqlite_conn.execute(
            "UPDATE prompt_registry SET is_active=0, updated_at=? WHERE role_name=?",
            (now, role),
        )
        db._sqlite_conn.execute(
            "UPDATE prompt_registry SET is_active=1, updated_at=? WHERE id=?",
            (now, target_id),
        )
        db._sqlite_conn.commit()
        return role

    role_name = await db._run_sqlite_op(_run)
    if not role_name:
        return None
    return await db.get_active_prompt(role_name)


__all__ = [
    "activate_prompt",
    "ensure_default_prompt_registry",
    "get_active_prompt",
    "list_prompts",
    "upsert_prompt",
]
