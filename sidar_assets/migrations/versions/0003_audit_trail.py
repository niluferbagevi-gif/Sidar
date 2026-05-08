"""add audit trail table

Revision ID: 0003_audit_trail
Revises: 0002_prompt_registry
Create Date: 2026-03-19 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_audit_trail"
down_revision = "0002_prompt_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.Text(), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_audit_logs_user_timestamp", "audit_logs", ["user_id", "timestamp"])
    op.create_index("idx_audit_logs_timestamp", "audit_logs", ["timestamp"])


def downgrade() -> None:
    op.drop_index("idx_audit_logs_timestamp", table_name="audit_logs")
    op.drop_index("idx_audit_logs_user_timestamp", table_name="audit_logs")
    op.drop_table("audit_logs")