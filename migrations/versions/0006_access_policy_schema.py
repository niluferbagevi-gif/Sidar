"""move access policy schema into alembic

Revision ID: 0006_access_policy_schema
Revises: 0005_pgvector_hnsw_index
Create Date: 2026-05-07 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_access_policy_schema"
down_revision = "0005_pgvector_hnsw_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "tenant_id" not in user_columns:
        op.add_column(
            "users",
            sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        )

    if "access_policies" not in inspector.get_table_names():
        op.create_table(
            "access_policies",
            sa.Column(
                "id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                primary_key=True,
                autoincrement=True,
            ),
            sa.Column(
                "user_id",
                sa.String(length=36),
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
                name="uq_access_policies_scope",
            ),
        )
    index_names = {index["name"] for index in inspector.get_indexes("access_policies")}
    if "idx_access_policies_user_tenant" not in index_names:
        op.create_index(
            "idx_access_policies_user_tenant",
            "access_policies",
            ["user_id", "tenant_id", "resource_type", "action"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "access_policies" in inspector.get_table_names():
        index_names = {index["name"] for index in inspector.get_indexes("access_policies")}
        if "idx_access_policies_user_tenant" in index_names:
            op.drop_index("idx_access_policies_user_tenant", table_name="access_policies")
        op.drop_table("access_policies")

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "tenant_id" in user_columns:
        op.drop_column("users", "tenant_id")
