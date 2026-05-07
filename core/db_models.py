"""SQLAlchemy schema metadata for Sidar's Alembic-managed database.

The runtime data layer may still use lightweight asyncpg/sqlite operations for
hot paths, but table definitions live here so Alembic autogenerate has a single
Python source of truth.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


BIGINT_SQLITE_INTEGER = BigInteger().with_variant(Integer, "sqlite")


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="user")
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthTokenModel(Base):
    __tablename__ = "auth_tokens"
    __table_args__ = (Index("idx_auth_tokens_user_id", "user_id"),)

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class UserQuotaModel(Base):
    __tablename__ = "user_quotas"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    daily_token_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    daily_request_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class ProviderUsageDailyModel(Base):
    __tablename__ = "provider_usage_daily"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "usage_date", name="uq_provider_usage_daily"),
        Index("idx_provider_usage_daily_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT_SQLITE_INTEGER, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    usage_date: Mapped[object] = mapped_column(Date, nullable=False)
    requests_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class SessionModel(Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("idx_sessions_user_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageModel(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_session_id", "session_id"),)

    id: Mapped[int] = mapped_column(BIGINT_SQLITE_INTEGER, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class SchemaVersionModel(Base):
    __tablename__ = "schema_versions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class PromptRegistryModel(Base):
    __tablename__ = "prompt_registry"
    __table_args__ = (
        UniqueConstraint("role_name", "version", name="uq_prompt_registry_role_version"),
        Index("idx_prompt_registry_role_active", "role_name", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_user_timestamp", "user_id", "timestamp"),
        Index("idx_audit_logs_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(BIGINT_SQLITE_INTEGER, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str] = mapped_column(Text, nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    timestamp: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AccessPolicyModel(Base):
    __tablename__ = "access_policies"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tenant_id",
            "resource_type",
            "resource_id",
            "action",
            name="uq_access_policies_scope",
        ),
        Index("idx_access_policies_user_tenant", "user_id", "tenant_id", "resource_type", "action"),
    )

    id: Mapped[int] = mapped_column(BIGINT_SQLITE_INTEGER, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="*")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    effect: Mapped[str] = mapped_column(Text, nullable=False, server_default="allow")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketingCampaignModel(Base):
    __tablename__ = "marketing_campaigns"
    __table_args__ = (
        Index("idx_marketing_campaigns_tenant_status", "tenant_id", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT_SQLITE_INTEGER, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    objective: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    owner_user_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="system")
    budget: Mapped[object] = mapped_column(Numeric(14, 2), nullable=False, server_default="0")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentAssetModel(Base):
    __tablename__ = "content_assets"
    __table_args__ = (
        Index("idx_content_assets_campaign_tenant", "campaign_id", "tenant_id", "asset_type"),
    )

    id: Mapped[int] = mapped_column(BIGINT_SQLITE_INTEGER, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        BIGINT_SQLITE_INTEGER,
        ForeignKey("marketing_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False, server_default="generic")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationChecklistModel(Base):
    __tablename__ = "operation_checklists"
    __table_args__ = (
        Index("idx_operation_checklists_campaign_tenant", "campaign_id", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BIGINT_SQLITE_INTEGER, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int | None] = mapped_column(
        BIGINT_SQLITE_INTEGER,
        ForeignKey("marketing_campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    items_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    owner_user_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="system")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class CoverageTaskModel(Base):
    __tablename__ = "coverage_tasks"
    __table_args__ = (
        Index("idx_coverage_tasks_tenant_status", "tenant_id", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT_SQLITE_INTEGER, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    requester_role: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    pytest_output: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    target_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    suggested_test_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    review_payload_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class CoverageFindingModel(Base):
    __tablename__ = "coverage_findings"
    __table_args__ = (Index("idx_coverage_findings_task", "task_id", "finding_type", "severity"),)

    id: Mapped[int] = mapped_column(BIGINT_SQLITE_INTEGER, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BIGINT_SQLITE_INTEGER, ForeignKey("coverage_tasks.id", ondelete="CASCADE"), nullable=False
    )
    finding_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default="info")
    details_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
