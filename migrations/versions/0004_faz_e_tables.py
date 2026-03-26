"""add faz e marketing and coverage tables

Revision ID: 0004_faz_e_tables
Revises: 0003_audit_trail
Create Date: 2026-03-26 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_faz_e_tables"
down_revision = "0003_audit_trail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_campaigns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("owner_user_id", sa.Text(), nullable=False, server_default="system"),
        sa.Column("budget", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_marketing_campaigns_tenant_status",
        "marketing_campaigns",
        ["tenant_id", "status", "updated_at"],
    )

    op.create_table(
        "content_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "campaign_id",
            sa.BigInteger(),
            sa.ForeignKey("marketing_campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("asset_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False, server_default="generic"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_content_assets_campaign_tenant",
        "content_assets",
        ["campaign_id", "tenant_id", "asset_type"],
    )

    op.create_table(
        "operation_checklists",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "campaign_id",
            sa.BigInteger(),
            sa.ForeignKey("marketing_campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("items_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("owner_user_id", sa.Text(), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_operation_checklists_campaign_tenant",
        "operation_checklists",
        ["campaign_id", "tenant_id", "status"],
    )

    op.create_table(
        "coverage_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("requester_role", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("pytest_output", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("target_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("suggested_test_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("review_payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_coverage_tasks_tenant_status",
        "coverage_tasks",
        ["tenant_id", "status", "updated_at"],
    )

    op.create_table(
        "coverage_findings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("coverage_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("finding_type", sa.Text(), nullable=False),
        sa.Column("target_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default="info"),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_coverage_findings_task",
        "coverage_findings",
        ["task_id", "finding_type", "severity"],
    )


def downgrade() -> None:
    op.drop_index("idx_coverage_findings_task", table_name="coverage_findings")
    op.drop_table("coverage_findings")

    op.drop_index("idx_coverage_tasks_tenant_status", table_name="coverage_tasks")
    op.drop_table("coverage_tasks")

    op.drop_index("idx_operation_checklists_campaign_tenant", table_name="operation_checklists")
    op.drop_table("operation_checklists")

    op.drop_index("idx_content_assets_campaign_tenant", table_name="content_assets")
    op.drop_table("content_assets")

    op.drop_index("idx_marketing_campaigns_tenant_status", table_name="marketing_campaigns")
    op.drop_table("marketing_campaigns")
