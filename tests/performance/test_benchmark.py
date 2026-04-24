"""Performance-oriented sanity checks for deterministic utility paths."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.db import Database
from scripts.coverage_hotspots import FileCoverage, format_table

pytestmark = pytest.mark.benchmark
pytest.importorskip("pytest_benchmark")


@pytest.fixture(scope="module")
def large_dataset_rows() -> list[FileCoverage]:
    return [
        FileCoverage(
            path=f"module_{index // 100}/file_{index:05d}.py",
            covered=(index % 120) + 1,
            missed=index % 7,
        )
        for index in range(10_000)
    ]


def test_format_table_handles_large_dataset_quickly(benchmark, large_dataset_rows) -> None:
    output = benchmark(format_table, large_dataset_rows)

    assert "| File | Coverage | Missed | Covered |" in output
    assert "module_0/file_00000.py" in output
    assert "module_99/file_09999.py" in output


def _make_cfg(base_dir: Path, db_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{base_dir / db_name}",
        BASE_DIR=str(base_dir),
        DB_POOL_SIZE=8,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=2,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_TTL_DAYS=3,
    )


def test_multi_user_session_message_workload_scales_with_concurrency(benchmark, tmp_path) -> None:
    """Çoklu kullanıcı + oturum + mesaj yazım iş yükünü benchmark eder ve bütünlüğü doğrular."""
    users = 20
    messages_per_session = 8

    async def _workload(run_id: str) -> int:
        cfg = _make_cfg(tmp_path, f"benchmark_{run_id}.db")
        db = Database(cfg)
        await db.connect()
        await db.init_schema()
        try:
            created_users = await asyncio.gather(
                *[db.create_user(f"user_{run_id}_{idx}", tenant_id=f"tenant-{idx % 4}", password="pw") for idx in range(users)]
            )
            sessions = await asyncio.gather(
                *[db.create_session(user.id, f"session-{i}") for i, user in enumerate(created_users)]
            )

            inserted = await db.add_messages_bulk(
                [
                    {
                        "session_id": session.id,
                        "role": "user",
                        "content": f"hello-{j}",
                        "tokens_used": j,
                    }
                    for session in sessions
                    for j in range(messages_per_session)
                ]
            )
            assert inserted == users * messages_per_session

            grouped_messages = await db.get_messages_for_sessions([session.id for session in sessions])
            per_session_messages = [grouped_messages.get(session.id, []) for session in sessions]
            assert all(len(items) == messages_per_session for items in per_session_messages)
            assert all([m.tokens_used for m in items] == list(range(messages_per_session)) for items in per_session_messages)
            return sum(len(items) for items in per_session_messages)
        finally:
            await db.close()

    total_messages = benchmark(lambda: asyncio.run(_workload(uuid4().hex)))
    assert total_messages == users * messages_per_session
