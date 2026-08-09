"""Coverage persistence boundary for the phased ``core.db`` split."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, cast

from core.db.helpers import json_dumps, sqlite_fetchone, utc_now_pair


@dataclass
class CoverageTaskRecord:
    id: int
    tenant_id: str
    requester_role: str
    command: str
    pytest_output: str
    status: str
    target_path: str
    suggested_test_path: str
    review_payload_json: str
    created_at: str
    updated_at: str


@dataclass
class CoverageFindingRecord:
    id: int
    task_id: int
    finding_type: str
    target_path: str
    summary: str
    severity: str
    details_json: str
    created_at: str


__all__ = [
    "CoverageFindingRecord",
    "CoverageTaskRecord",
    "add_coverage_finding",
    "create_coverage_task",
    "list_coverage_tasks",
]


async def create_coverage_task(
    db: Any,
    *,
    tenant_id: str = "default",
    requester_role: str = "coverage",
    command: str,
    pytest_output: str,
    status: str = "pending_review",
    target_path: str = "",
    suggested_test_path: str = "",
    review_payload_json: str = "{}",
) -> CoverageTaskRecord:
    tenant = (tenant_id or "default").strip() or "default"
    now_dt, now = utc_now_pair()
    if not str(command or "").strip():
        raise ValueError("command is required")
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO coverage_tasks (
                    tenant_id, requester_role, command, pytest_output, status,
                    target_path, suggested_test_path, review_payload_json, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $9)
                RETURNING id, tenant_id, requester_role, command, pytest_output, status,
                          target_path, suggested_test_path, review_payload_json, created_at,
                          updated_at
                """,
                tenant,
                str(requester_role or "coverage"),
                str(command),
                str(pytest_output or ""),
                str(status or "pending_review"),
                str(target_path or ""),
                str(suggested_test_path or ""),
                str(review_payload_json or "{}"),
                now_dt,
            )
        return CoverageTaskRecord(
            id=int(row["id"]),
            tenant_id=str(row["tenant_id"]),
            requester_role=str(row["requester_role"]),
            command=str(row["command"]),
            pytest_output=str(row["pytest_output"]),
            status=str(row["status"]),
            target_path=str(row["target_path"]),
            suggested_test_path=str(row["suggested_test_path"]),
            review_payload_json=str(row["review_payload_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    assert db._sqlite_conn is not None

    def _run() -> sqlite3.Row:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            """
            INSERT INTO coverage_tasks (
                tenant_id, requester_role, command, pytest_output, status,
                target_path, suggested_test_path, review_payload_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant,
                str(requester_role or "coverage"),
                str(command),
                str(pytest_output or ""),
                str(status or "pending_review"),
                str(target_path or ""),
                str(suggested_test_path or ""),
                str(review_payload_json or "{}"),
                now,
                now,
            ),
        )
        row = sqlite_fetchone(
            db._sqlite_conn.execute(
                """
                SELECT id, tenant_id, requester_role, command, pytest_output, status,
                       target_path, suggested_test_path, review_payload_json, created_at, updated_at
                FROM coverage_tasks WHERE id=?
                """,
                (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
            )
        )
        db._sqlite_conn.commit()
        assert row is not None
        return row

    row = await db._run_sqlite_op(_run)
    return CoverageTaskRecord(
        id=int(row["id"]),
        tenant_id=str(row["tenant_id"]),
        requester_role=str(row["requester_role"]),
        command=str(row["command"]),
        pytest_output=str(row["pytest_output"]),
        status=str(row["status"]),
        target_path=str(row["target_path"]),
        suggested_test_path=str(row["suggested_test_path"]),
        review_payload_json=str(row["review_payload_json"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


async def add_coverage_finding(
    db: Any,
    *,
    task_id: int,
    finding_type: str,
    target_path: str,
    summary: str,
    severity: str = "medium",
    details: dict[str, Any] | None = None,
) -> CoverageFindingRecord:
    now_dt, now = utc_now_pair()
    if not str(finding_type or "").strip() or not str(summary or "").strip():
        raise ValueError("finding_type and summary are required")
    details_json = json_dumps(details or {})
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        async with db._pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO coverage_findings (task_id, finding_type, target_path, summary,
                severity, details_json, created_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                RETURNING id, task_id, finding_type, target_path, summary, severity, details_json,
                created_at
                """,
                int(task_id),
                str(finding_type),
                str(target_path or ""),
                str(summary),
                str(severity or "medium"),
                details_json,
                now_dt,
            )
        return CoverageFindingRecord(
            id=int(row["id"]),
            task_id=int(row["task_id"]),
            finding_type=str(row["finding_type"]),
            target_path=str(row["target_path"]),
            summary=str(row["summary"]),
            severity=str(row["severity"]),
            details_json=str(row["details_json"]),
            created_at=str(row["created_at"]),
        )

    assert db._sqlite_conn is not None

    def _run() -> sqlite3.Row:
        assert db._sqlite_conn is not None
        cur = db._sqlite_conn.execute(
            """
            INSERT INTO coverage_findings (task_id, finding_type, target_path, summary, severity,
            details_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(task_id),
                str(finding_type),
                str(target_path or ""),
                str(summary),
                str(severity or "medium"),
                details_json,
                now,
            ),
        )
        row = sqlite_fetchone(
            db._sqlite_conn.execute(
                """
                SELECT id, task_id, finding_type, target_path, summary, severity, details_json,
                created_at
                FROM coverage_findings WHERE id=?
                """,
                (int(cur.lastrowid) if cur.lastrowid is not None else 0,),
            )
        )
        db._sqlite_conn.commit()
        assert row is not None
        return row

    row = await db._run_sqlite_op(_run)
    return CoverageFindingRecord(
        id=int(row["id"]),
        task_id=int(row["task_id"]),
        finding_type=str(row["finding_type"]),
        target_path=str(row["target_path"]),
        summary=str(row["summary"]),
        severity=str(row["severity"]),
        details_json=str(row["details_json"]),
        created_at=str(row["created_at"]),
    )


async def list_coverage_tasks(
    db: Any,
    *,
    tenant_id: str = "default",
    status: str | None = None,
    limit: int = 100,
) -> list[CoverageTaskRecord]:
    tenant = (tenant_id or "default").strip() or "default"
    normalized_status = (status or "").strip() or None
    max_items = max(1, min(int(limit or 100), 500))
    if db._backend == "postgresql":
        assert db._pg_pool is not None
        query = (
            "SELECT id, tenant_id, requester_role, command, pytest_output, status, "
            "target_path, suggested_test_path, review_payload_json, created_at, updated_at "
            "FROM coverage_tasks WHERE tenant_id=$1"
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
                    SELECT id, tenant_id, requester_role, command, pytest_output, status,
                           target_path, suggested_test_path, review_payload_json, created_at,
                           updated_at
                    FROM coverage_tasks
                    WHERE tenant_id=? AND status=?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (tenant, normalized_status, max_items),
                )
            else:
                cur = db._sqlite_conn.execute(
                    """
                    SELECT id, tenant_id, requester_role, command, pytest_output, status,
                           target_path, suggested_test_path, review_payload_json, created_at,
                           updated_at
                    FROM coverage_tasks
                    WHERE tenant_id=?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (tenant, max_items),
                )
            return cast(list[Any], cur.fetchall())

        rows = await db._run_sqlite_op(_run, write=False)
    return [
        CoverageTaskRecord(
            id=int(row["id"]),
            tenant_id=str(row["tenant_id"]),
            requester_role=str(row["requester_role"]),
            command=str(row["command"]),
            pytest_output=str(row["pytest_output"]),
            status=str(row["status"]),
            target_path=str(row["target_path"]),
            suggested_test_path=str(row["suggested_test_path"]),
            review_payload_json=str(row["review_payload_json"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    ]
