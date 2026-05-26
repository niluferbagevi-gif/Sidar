"""add tenant access control schema

Revision ID: 0006_access_control_schema
Revises: 0005_pgvector_hnsw_index
Create Date: 2026-05-07 00:00:00
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeEngine

revision = "0006_access_control_schema"
down_revision = "0005_pgvector_hnsw_index"
branch_labels = None
depends_on = None


class SidarUUID(sa.TypeDecorator[str]):
    """Use PostgreSQL native UUID while preserving SQLite string fallback."""

    impl = sa.String
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID

            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(sa.String(length=36))

    def process_bind_param(self, value: object, dialect: Dialect) -> uuid.UUID | str | None:
        if value is None:
            return None
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return parsed
        return str(parsed)

    def process_result_value(self, value: object, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return str(value)


UUID_TYPE = SidarUUID()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    user_columns = {
        str(column.get("name"))
        for column in inspector.get_columns("users")
        if isinstance(column, dict)
    }

    if "tenant_id" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "tenant_id",
                sa.Text(),
                nullable=False,
                server_default="default",
            ),
        )

    if "access_policies" not in table_names:
        op.create_table(
            "access_policies",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                UUID_TYPE,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
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
                name="uq_access_policies_user_tenant_resource_action",
            ),
        )
        existing_indexes: set[str] = set()
    else:
        existing_indexes = {
            str(index.get("name"))
            for index in inspector.get_indexes("access_policies")
            if isinstance(index, dict)
        }

    global_index_conflict = False
    if bind.engine.name == "postgresql":
        conflict_table = bind.execute(
            sa.text(
                """
                SELECT tablename
                FROM pg_indexes
                WHERE schemaname = ANY (current_schemas(false))
                  AND indexname = :index_name
                LIMIT 1
                """
            ),
            {"index_name": "idx_access_policies_user_tenant"},
        ).scalar()
        if conflict_table and str(conflict_table) != "access_policies":
            global_index_conflict = True
            raise RuntimeError(
                "Index name conflict detected: idx_access_policies_user_tenant already exists "
                f"on table '{conflict_table}'. Resolve the naming conflict before applying 0006_access_control_schema."
            )

    if not global_index_conflict and "idx_access_policies_user_tenant" not in existing_indexes:
        op.create_index(
            "idx_access_policies_user_tenant",
            "access_policies",
            ["user_id", "tenant_id", "resource_type", "action"],
        )


def downgrade() -> None:
    op.drop_index("idx_access_policies_user_tenant", table_name="access_policies")
    op.drop_table("access_policies")
    op.drop_column("users", "tenant_id")
