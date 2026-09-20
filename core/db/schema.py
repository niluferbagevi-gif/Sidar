"""SQLite/PostgreSQL schema bootstrap boundary for the phased ``core.db`` split.

The hand-written SQLite bootstrap DDL here (``init_schema_sqlite`` and the
related ``ensure_*_schema_sqlite`` helpers) and the Alembic migration chain
(the single source of truth for PostgreSQL, driven through
``init_schema_postgresql``/``run_alembic_upgrade_head``) are two independent,
hand-maintained schema sources. Keep them in sync when adding a column or
table -- ``tests/integration/db/test_db_migrations_integration.py::
test_sqlite_bootstrap_schema_matches_alembic_head_schema`` compares both
schemas' table/column sets plus ``nullable``/``default`` values and fails CI
on drift.

Every cross-step call here goes through the ``db`` instance (``db.X(...)``)
rather than calling a sibling function in this module directly, so that
``Database``'s thin wrapper methods -- and any test that monkeypatches one of
them as an instance attribute -- keep observing the same call graph as before
this extraction.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from core.db.dialect import render_sql_identifier_template
from core.db.helpers import sqlite_fetchone, utc_now_iso
from core.db_components.migrations import run_alembic_upgrade_head as _run_alembic_upgrade_head_impl
from sidar_assets.paths import alembic_ini_path, migrations_path

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_access_control_schema_postgresql",
    "ensure_access_control_schema_sqlite",
    "ensure_audit_log_schema_postgresql",
    "ensure_audit_log_schema_sqlite",
    "ensure_schema_version_postgresql",
    "ensure_schema_version_sqlite",
    "init_schema",
    "init_schema_postgresql",
    "init_schema_sqlite",
    "run_alembic_upgrade_head",
]


async def init_schema(db: Any) -> None:
    if db._backend == "postgresql":
        # PostgreSQL schema is managed by Alembic as the single source of truth.
        # Keep SQLite bootstrap below because degraded/local fallback does not run
        # Alembic and must remain dependency-light.
        await db._init_schema_postgresql()
        await db.ensure_default_prompt_registry()
        return
    await db._init_schema_sqlite()
    await db._ensure_access_control_schema_sqlite()
    await db._ensure_audit_log_schema_sqlite()
    await db._ensure_schema_version_sqlite()
    await db.ensure_default_prompt_registry()


async def ensure_access_control_schema_sqlite(db: Any) -> None:
    assert db._sqlite_conn is not None

    def _run() -> None:
        assert db._sqlite_conn is not None
        cols = db._sqlite_conn.execute("PRAGMA table_info(users)").fetchall()
        col_names = {str(c[1]) for c in cols}
        if "tenant_id" not in col_names:
            db._sqlite_conn.execute(
                "ALTER TABLE users ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
            )
        db._sqlite_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS access_policies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL DEFAULT '*',
                action TEXT NOT NULL,
                effect TEXT NOT NULL DEFAULT 'allow',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, tenant_id, resource_type, resource_id, action),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        db._sqlite_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_access_policies_user_tenant ON "
            "access_policies(user_id, tenant_id, resource_type, action)"
        )
        db._sqlite_conn.commit()

    await db._run_sqlite_op(_run)


async def ensure_access_control_schema_postgresql(db: Any) -> None:
    assert db._pg_pool is not None
    async with db._pg_pool.acquire() as conn:
        await conn.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'"
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS access_policies (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL DEFAULT '*',
                action TEXT NOT NULL,
                effect TEXT NOT NULL DEFAULT 'allow',
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                UNIQUE(user_id, tenant_id, resource_type, resource_id, action)
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_access_policies_user_tenant ON "
            "access_policies(user_id, tenant_id, resource_type, action)"
        )


async def ensure_audit_log_schema_sqlite(db: Any) -> None:
    assert db._sqlite_conn is not None

    def _run() -> None:
        assert db._sqlite_conn is not None
        db._sqlite_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT 'default',
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                allowed INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL
            )
            """
        )
        db._sqlite_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_user_timestamp ON audit_logs(user_id, "
            "timestamp)"
        )
        db._sqlite_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp)"
        )
        db._sqlite_conn.commit()

    await db._run_sqlite_op(_run)


async def ensure_audit_log_schema_postgresql(db: Any) -> None:
    assert db._pg_pool is not None
    async with db._pg_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '',
                tenant_id TEXT NOT NULL DEFAULT 'default',
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                allowed BOOLEAN NOT NULL DEFAULT FALSE,
                timestamp TIMESTAMPTZ NOT NULL
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_user_timestamp ON audit_logs(user_id, "
            "timestamp)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp)"
        )


async def init_schema_sqlite(db: Any) -> None:
    assert db._sqlite_conn is not None

    # NOT NULL, added explicitly on every PRIMARY KEY column below (both TEXT
    # and INTEGER AUTOINCREMENT ones): SQLite's PRIMARY KEY alone does not
    # imply NOT NULL the way SQL:1999/Alembic's Column(primary_key=True)
    # does — a bare `id TEXT PRIMARY KEY` still accepts NULL, and since
    # SQLite's UNIQUE/PRIMARY KEY index never treats two NULLs as
    # conflicting, that silently allowed multiple NULL-id rows. This also
    # keeps this hand-written bootstrap DDL structurally comparable to the
    # Alembic-managed PostgreSQL schema (see
    # test_sqlite_bootstrap_schema_matches_alembic_head_schema in
    # tests/integration/db/test_db_migrations_integration.py, which
    # reflects both schemas and previously had to special-case this
    # divergence).
    schema_sql = """
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY NOT NULL,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT,
        role TEXT NOT NULL DEFAULT 'user',
        tenant_id TEXT NOT NULL DEFAULT 'default',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS auth_tokens (
        token TEXT PRIMARY KEY NOT NULL,
        user_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS user_quotas (
        user_id TEXT PRIMARY KEY NOT NULL,
        daily_token_limit INTEGER NOT NULL DEFAULT 0,
        daily_request_limit INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS provider_usage_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        user_id TEXT NOT NULL,
        provider TEXT NOT NULL,
        usage_date TEXT NOT NULL,
        requests_used INTEGER NOT NULL DEFAULT 0,
        tokens_used INTEGER NOT NULL DEFAULT 0,
        UNIQUE(user_id, provider, usage_date),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        tokens_used INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
    CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens(user_id);
    CREATE INDEX IF NOT EXISTS idx_provider_usage_daily_user_id ON
    provider_usage_daily(user_id);
    CREATE TABLE IF NOT EXISTS access_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        user_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        resource_type TEXT NOT NULL,
        resource_id TEXT NOT NULL DEFAULT '*',
        action TEXT NOT NULL,
        effect TEXT NOT NULL DEFAULT 'allow',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(user_id, tenant_id, resource_type, resource_id, action),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_access_policies_user_tenant
        ON access_policies(user_id, tenant_id, resource_type, action);

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        user_id TEXT NOT NULL DEFAULT '',
        tenant_id TEXT NOT NULL DEFAULT 'default',
        action TEXT NOT NULL,
        resource TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        allowed INTEGER NOT NULL DEFAULT 0,
        timestamp TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_audit_logs_user_timestamp ON audit_logs(user_id, timestamp);
    CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);

    CREATE TABLE IF NOT EXISTS prompt_registry (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        role_name TEXT NOT NULL,
        prompt_text TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_registry_role_version ON
    prompt_registry(role_name, version);
    CREATE INDEX IF NOT EXISTS idx_prompt_registry_role_active ON prompt_registry(role_name,
    is_active);

    CREATE TABLE IF NOT EXISTS marketing_campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        name TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT '',
        objective TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft',
        owner_user_id TEXT NOT NULL DEFAULT '',
        budget REAL NOT NULL DEFAULT 0,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_marketing_campaigns_tenant_status
        ON marketing_campaigns(tenant_id, status, updated_at);

    CREATE TABLE IF NOT EXISTS content_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        campaign_id INTEGER NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        asset_type TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        channel TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES marketing_campaigns(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_content_assets_campaign_tenant
        ON content_assets(campaign_id, tenant_id, asset_type);

    CREATE TABLE IF NOT EXISTS operation_checklists (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        campaign_id INTEGER,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        title TEXT NOT NULL,
        items_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'pending',
        owner_user_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(campaign_id) REFERENCES marketing_campaigns(id) ON DELETE SET NULL
    );
    CREATE INDEX IF NOT EXISTS idx_operation_checklists_campaign_tenant
        ON operation_checklists(campaign_id, tenant_id, status);

    CREATE TABLE IF NOT EXISTS coverage_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        requester_role TEXT NOT NULL DEFAULT 'coverage',
        command TEXT NOT NULL,
        pytest_output TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending_review',
        target_path TEXT NOT NULL DEFAULT '',
        suggested_test_path TEXT NOT NULL DEFAULT '',
        review_payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_coverage_tasks_tenant_status
        ON coverage_tasks(tenant_id, status, updated_at);

    CREATE TABLE IF NOT EXISTS coverage_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        task_id INTEGER NOT NULL,
        finding_type TEXT NOT NULL,
        target_path TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'medium',
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(task_id) REFERENCES coverage_tasks(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_coverage_findings_task
        ON coverage_findings(task_id, finding_type, severity);
    """

    def _run() -> None:
        assert db._sqlite_conn is not None
        db._sqlite_conn.executescript(schema_sql)
        db._sqlite_conn.commit()

    await db._run_sqlite_op(_run)


def run_alembic_upgrade_head(db: Any) -> None:
    """Run the extracted Alembic migration helper for this database facade."""
    _run_alembic_upgrade_head_impl(
        database_url=db.database_url,
        alembic_ini=alembic_ini_path(),
        migrations_dir=migrations_path(),
    )


async def init_schema_postgresql(db: Any) -> None:
    """Initialize PostgreSQL schema through Alembic when auto-migrate is enabled.

    In production, auto-migrate may be disabled by policy. We still run a one-time
    bootstrap migration when this looks like a fresh database (no alembic_version table).
    """
    assert db._pg_pool is not None
    should_run_migration = db.auto_migrate
    if not should_run_migration:
        if hasattr(db._pg_pool, "fetchval"):
            has_alembic_version = await db._pg_pool.fetchval(
                "SELECT to_regclass('public.alembic_version')"
            )
        elif hasattr(db._pg_pool, "fetch_value"):
            has_alembic_version = await db._pg_pool.fetch_value(
                "SELECT to_regclass('public.alembic_version')"
            )
        else:
            async with db._pg_pool.acquire() as conn:
                has_alembic_version = await conn.fetchval(
                    "SELECT to_regclass('public.alembic_version')"
                )
        if has_alembic_version:
            logger.info("SIDAR_AUTO_MIGRATE devre dışı; runtime Alembic upgrade atlandı.")
            return
        logger.warning(
            "SIDAR_AUTO_MIGRATE devre dışı ancak fresh DB tespit edildi (alembic_version yok). "
            "İlk açılış bootstrap migrasyonu çalıştırılıyor."
        )
        should_run_migration = True

    # Reaching this point always means migration is required: auto-migrate was
    # enabled initially or the disabled-policy fresh DB bootstrap promoted it.
    await asyncio.to_thread(db._run_alembic_upgrade_head)


async def ensure_schema_version_sqlite(db: Any) -> None:
    assert db._sqlite_conn is not None

    def _run() -> None:
        assert db._sqlite_conn is not None
        tbl = db._schema_version_table_quoted
        db._sqlite_conn.execute(
            render_sql_identifier_template(
                "CREATE TABLE IF NOT EXISTS {table} "
                "(version INTEGER PRIMARY KEY NOT NULL, "
                "applied_at TEXT NOT NULL, description TEXT NOT NULL)",
                table=tbl,
            )
        )
        cur = db._sqlite_conn.execute(
            render_sql_identifier_template("SELECT MAX(version) AS v FROM {table}", table=tbl)
        )
        row = sqlite_fetchone(cur)
        current = int((row["v"] if row else 0) or 0)
        if current >= db.target_schema_version:
            return
        for v in range(current + 1, db.target_schema_version + 1):
            db._sqlite_conn.execute(
                render_sql_identifier_template(
                    "INSERT INTO {table} (version, applied_at, description) VALUES (?, ?, ?)",
                    table=tbl,
                ),
                (v, utc_now_iso(), f"baseline migration v{v}"),
            )
        db._sqlite_conn.commit()

    await db._run_sqlite_op(_run)


async def ensure_schema_version_postgresql(db: Any) -> None:
    assert db._pg_pool is not None
    tbl = db._schema_version_table_quoted
    async with db._pg_pool.acquire() as conn:
        await conn.execute(
            render_sql_identifier_template(
                "CREATE TABLE IF NOT EXISTS {table} "
                "(version INTEGER PRIMARY KEY NOT NULL, "
                "applied_at TIMESTAMPTZ NOT NULL, description TEXT NOT NULL)",
                table=tbl,
            )
        )
        current = await conn.fetchval(
            render_sql_identifier_template(
                "SELECT COALESCE(MAX(version), 0) FROM {table}", table=tbl
            )
        )
        current = int(current or 0)
        if current >= db.target_schema_version:
            return
        for v in range(current + 1, db.target_schema_version + 1):
            await conn.execute(
                render_sql_identifier_template(
                    "INSERT INTO {table} (version, applied_at, description) VALUES ($1, $2, $3)",
                    table=tbl,
                ),
                v,
                datetime.now(UTC),
                f"baseline migration v{v}",
            )
