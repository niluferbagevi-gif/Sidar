"""Domain record model aliases for the phased ``core.db`` package split.

Phase 1 keeps the canonical dataclass definitions in ``core.db`` for import
compatibility while exposing stable domain module boundaries for follow-up PRs.
"""

from __future__ import annotations

from core.db import (
    AccessPolicyRecord,
    AuditLogRecord,
    AuthTokenRecord,
    ContentAssetRecord,
    CoverageFindingRecord,
    CoverageTaskRecord,
    MarketingCampaignRecord,
    MessageRecord,
    OperationChecklistRecord,
    PromptRecord,
    SessionRecord,
    UserRecord,
)

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
