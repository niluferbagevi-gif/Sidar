import asyncio
from pathlib import Path
from types import SimpleNamespace

from core.db import Database


def _cfg(tmp_path: Path):
    return SimpleNamespace(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'coverage.db'}",
        DB_POOL_SIZE=1,
        DB_SCHEMA_VERSION_TABLE="schema_versions",
        DB_SCHEMA_TARGET_VERSION=1,
        BASE_DIR=tmp_path,
    )


def test_coverage_tables_store_tasks_and_findings(tmp_path):
    async def _run():
        db = Database(cfg=_cfg(tmp_path))
        await db.connect()
        await db.init_schema()
        try:
            task = await db.create_coverage_task(
                tenant_id="tenant-a",
                requester_role="coverage",
                command="pytest -q",
                pytest_output="1 failed",
                status="pending_review",
                target_path="core/sample.py",
                suggested_test_path="tests/test_sample_coverage.py",
                review_payload_json='{"decision":"pending"}',
            )
            finding = await db.add_coverage_finding(
                task_id=task.id,
                finding_type="missing_coverage",
                target_path="core/sample.py",
                summary="Eksik satırlar: 10-12",
                details={"missing_lines": "10-12"},
            )
            tasks = await db.list_coverage_tasks(tenant_id="tenant-a", status="pending_review")

            assert task.target_path == "core/sample.py"
            assert finding.task_id == task.id
            assert tasks[0].suggested_test_path == "tests/test_sample_coverage.py"
        finally:
            await db.close()

    asyncio.run(_run())
