"""Domain record models for the ``core.db`` package.

Holds the canonical access-policy / prompt / audit dataclasses and
re-exports the auth / session / marketing / coverage records from their
domain modules so callers can rely on a single import location.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.db.auth import AuthTokenRecord, UserRecord
from core.db.coverage import CoverageFindingRecord, CoverageTaskRecord
from core.db.marketing import (
    ContentAssetRecord,
    MarketingCampaignRecord,
    OperationChecklistRecord,
)
from core.db.session import MessageRecord, SessionRecord


@dataclass
class AccessPolicyRecord:
    id: int
    user_id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    action: str
    effect: str
    created_at: str
    updated_at: str


@dataclass
class PromptRecord:
    id: int
    role_name: str
    prompt_text: str
    version: int
    is_active: bool
    created_at: str
    updated_at: str


@dataclass
class AuditLogRecord:
    id: int
    user_id: str
    tenant_id: str
    action: str
    resource: str
    ip_address: str
    allowed: bool
    timestamp: str


__all__ = [
    "AccessPolicyRecord",
    "AuditLogRecord",
    "AuthTokenRecord",
    "ContentAssetRecord",
    "CoverageFindingRecord",
    "CoverageTaskRecord",
    "MarketingCampaignRecord",
    "MessageRecord",
    "OperationChecklistRecord",
    "PromptRecord",
    "SessionRecord",
    "UserRecord",
]
