"""add prompt registry table

Revision ID: 0002_prompt_registry
Revises: 0001_baseline_schema
Create Date: 2026-03-16 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from agent.definitions import SIDAR_SYSTEM_PROMPT

revision = "0002_prompt_registry"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_registry",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("role_name", sa.Text(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("role_name", "version", name="uq_prompt_registry_role_version"),
    )
    op.create_index("idx_prompt_registry_role_active", "prompt_registry", ["role_name", "is_active"])

    op.execute(
        sa.text(
            """
            INSERT INTO prompt_registry (role_name, prompt_text, version, is_active, created_at, updated_at)
            VALUES (:role_name, :prompt_text, :version, :is_active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ).bindparams(
            role_name="system",
            prompt_text=SIDAR_SYSTEM_PROMPT,
            version=1,
            is_active=True,
        )
    )



def downgrade() -> None:
    op.drop_index("idx_prompt_registry_role_active", table_name="prompt_registry")
    op.drop_table("prompt_registry")
