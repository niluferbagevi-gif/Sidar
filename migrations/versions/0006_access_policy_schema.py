"""add tenant column and access policy table

Revision ID: 0006_access_policy_schema
Revises: 0005_pgvector_hnsw_index
Create Date: 2026-05-07 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_access_policy_schema"
down_revision = "0005_pgvector_hnsw_index"
branch_labels = None
depends_on = None


BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


class MigrationGUID(sa.types.TypeDecorator[str]):
    """PostgreSQL'de native UUID, SQLite'ta String(36) kullanan migrasyon tipi."""

    impl = sa.String
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=False))
        return dialect.type_descriptor(sa.String(length=36))


GUID = MigrationGUID()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    if bind.engine.name == "postgresql":
        result = bind.execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = :table_name
                      AND column_name = :column_name
                )
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        )
        return bool(result.scalar())

    rows = bind.execute(sa.text(f"PRAGMA table_info({table_name})")).fetchall()  # nosec B608
    return any(str(row[1]) == column_name for row in rows)


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    if bind.engine.name == "postgresql":
        result = bind.execute(
            sa.text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_name = :table_name
                )
                """
            ),
            {"table_name": table_name},
        )
        return bool(result.scalar())

    rows = bind.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
        {"table_name": table_name},
    ).fetchall()
    return bool(rows)


def upgrade() -> None:
    if not _has_column("users", "tenant_id"):
        op.add_column(
            "users",
            sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        )

    if not _has_table("access_policies"):
        op.create_table(
            "access_policies",
            sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
            sa.Column("user_id", GUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
            sa.Column("resource_type", sa.Text(), nullable=False),
            sa.Column("resource_id", sa.Text(), nullable=False, server_default="*"),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("effect", sa.Text(), nullable=False, server_default="allow"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "user_id",
                "tenant_id",
                "resource_type",
                "resource_id",
                "action",
                name="uq_access_policies_scope",
            ),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_access_policies_user_tenant "
        "ON access_policies(user_id, tenant_id, resource_type, action)"
    )


def downgrade() -> None:
    op.drop_index("idx_access_policies_user_tenant", table_name="access_policies")
    op.drop_table("access_policies")
    if _has_column("users", "tenant_id"):
        op.drop_column("users", "tenant_id")
