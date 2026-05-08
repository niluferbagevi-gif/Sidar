"""SQLAlchemy schema models for Sidar database migrations.

These models are the metadata source for Alembic autogenerate. Runtime record
DTOs remain in ``core.db`` until query-by-query migration to SQLAlchemy async
Core/ORM is completed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import CHAR, TypeDecorator, UserDefinedType


class SidarUUID(TypeDecorator[str]):
    """Backend-aware UUID type.

    PostgreSQL uses native ``UUID`` for compact indexes and storage. SQLite and
    other fallback dialects store canonical UUID text in ``CHAR(36)`` so degraded
    mode remains portable.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: object, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return parsed
        return str(parsed)

    def process_result_value(self, value: object, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return str(value)


class PGVector384(UserDefinedType[Any]):
    """Minimal pgvector column type for Alembic metadata without runtime pgvector import."""

    cache_ok = True

    def get_col_spec(self, **_kwargs: object) -> str:
        return "vector(384)"


class Base(DeclarativeBase):
    """Declarative base exposed to Alembic ``target_metadata``."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(SidarUUID(), primary_key=True)
    username: Mapped[str] = mapped_column(sa.Text(), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    role: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="user")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    tenant_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="default")


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    token: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        SidarUUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class UserQuota(Base):
    __tablename__ = "user_quotas"

    user_id: Mapped[str] = mapped_column(
        SidarUUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    daily_token_limit: Mapped[int] = mapped_column(sa.Integer(), nullable=False, server_default="0")
    daily_request_limit: Mapped[int] = mapped_column(
        sa.Integer(), nullable=False, server_default="0"
    )


class ProviderUsageDaily(Base):
    __tablename__ = "provider_usage_daily"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "provider", "usage_date", name="uq_provider_usage_daily"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        SidarUUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    usage_date: Mapped[datetime] = mapped_column(sa.Date(), nullable=False)
    requests_used: Mapped[int] = mapped_column(sa.Integer(), nullable=False, server_default="0")
    tokens_used: Mapped[int] = mapped_column(sa.Integer(), nullable=False, server_default="0")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(SidarUUID(), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        SidarUUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        SidarUUID(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    tokens_used: Mapped[int] = mapped_column(sa.Integer(), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    version: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text(), nullable=False)


class PromptRegistry(Base):
    __tablename__ = "prompt_registry"
    __table_args__ = (
        sa.UniqueConstraint("role_name", "version", name="uq_prompt_registry_role_version"),
        sa.Index("idx_prompt_registry_role_active", "role_name", "is_active"),
    )

    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    prompt_text: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer(), nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.text("false")
    )
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        sa.Index("idx_audit_logs_user_timestamp", "user_id", "timestamp"),
        sa.Index("idx_audit_logs_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="")
    tenant_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="default")
    action: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    resource: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    ip_address: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    allowed: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.text("false")
    )
    timestamp: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class MarketingCampaign(Base):
    __tablename__ = "marketing_campaigns"
    __table_args__ = (
        sa.Index("idx_marketing_campaigns_tenant_status", "tenant_id", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="default")
    name: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    channel: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    objective: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="draft")
    owner_user_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="system")
    budget: Mapped[float] = mapped_column(sa.Numeric(14, 2), nullable=False, server_default="0")
    metadata_json: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class ContentAsset(Base):
    __tablename__ = "content_assets"
    __table_args__ = (
        sa.Index("idx_content_assets_campaign_tenant", "campaign_id", "tenant_id", "asset_type"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        sa.BigInteger(), sa.ForeignKey("marketing_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="default")
    asset_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    channel: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="generic")
    metadata_json: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class OperationChecklist(Base):
    __tablename__ = "operation_checklists"
    __table_args__ = (
        sa.Index("idx_operation_checklists_campaign_tenant", "campaign_id", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    campaign_id: Mapped[int | None] = mapped_column(
        sa.BigInteger(), sa.ForeignKey("marketing_campaigns.id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="default")
    title: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    items_json: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="open")
    owner_user_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="system")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class CoverageTask(Base):
    __tablename__ = "coverage_tasks"
    __table_args__ = (
        sa.Index("idx_coverage_tasks_tenant_status", "tenant_id", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="default")
    requester_role: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    command: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    pytest_output: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="")
    status: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="queued")
    target_path: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="")
    suggested_test_path: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="")
    review_payload_json: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class CoverageFinding(Base):
    __tablename__ = "coverage_findings"
    __table_args__ = (
        sa.Index("idx_coverage_findings_task", "task_id", "finding_type", "severity"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        sa.BigInteger(), sa.ForeignKey("coverage_tasks.id", ondelete="CASCADE"), nullable=False
    )
    finding_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    target_path: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="")
    summary: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    severity: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="info")
    details_json: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class RagEmbedding(Base):
    __tablename__ = "rag_embeddings"
    __table_args__ = (
        sa.Index("idx_rag_embeddings_session", "session_id"),
        sa.Index("idx_rag_embeddings_parent", "parent_id"),
    )

    doc_id: Mapped[str] = mapped_column(sa.Text(), primary_key=True)
    parent_id: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    session_id: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    chunk_index: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    title: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    source: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    chunk_content: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(PGVector384(), nullable=True)


class AccessPolicy(Base):
    __tablename__ = "access_policies"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "tenant_id",
            "resource_type",
            "resource_id",
            "action",
            name="uq_access_policies_user_tenant_resource_action",
        ),
        sa.Index("idx_access_policies_user_tenant", "user_id", "tenant_id", "resource_type", "action"),
    )

    id: Mapped[int] = mapped_column(sa.BigInteger(), primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        SidarUUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="default")
    resource_type: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    resource_id: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="*")
    action: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    effect: Mapped[str] = mapped_column(sa.Text(), nullable=False, server_default="allow")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
