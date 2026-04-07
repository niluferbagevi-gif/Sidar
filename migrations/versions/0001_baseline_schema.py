"""baseline schema for sidar v3.0

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-03-11 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "auth_tokens",
        sa.Column("token", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "user_quotas",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("daily_token_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_request_limit", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "provider_usage_daily",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("requests_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "provider", "usage_date", name="uq_provider_usage_daily"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "schema_versions",
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
    )

    op.create_index("idx_sessions_user_id", "sessions", ["user_id"])
    op.create_index("idx_messages_session_id", "messages", ["session_id"])
    op.create_index("idx_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("idx_provider_usage_daily_user_id", "provider_usage_daily", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_provider_usage_daily_user_id", table_name="provider_usage_daily")
    op.drop_index("idx_auth_tokens_user_id", table_name="auth_tokens")
    op.drop_index("idx_messages_session_id", table_name="messages")
    op.drop_index("idx_sessions_user_id", table_name="sessions")

    op.drop_table("schema_versions")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("provider_usage_daily")
    op.drop_table("user_quotas")
    op.drop_table("auth_tokens")
    op.drop_table("users")
