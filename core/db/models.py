"""Domain record model aliases for the phased ``core.db`` package split."""

from __future__ import annotations

from core.db import (
    AccessPolicyRecord,
    AuditLogRecord,
    ContentAssetRecord,
    MarketingCampaignRecord,
    OperationChecklistRecord,
    PromptRecord,
)
from core.db.auth import AuthTokenRecord, UserRecord
from core.db.coverage import CoverageFindingRecord, CoverageTaskRecord
from core.db.session import MessageRecord, SessionRecord

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
