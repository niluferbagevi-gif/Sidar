"""Marketing persistence boundary for the phased ``core.db`` split."""

from __future__ import annotations

from core.db.monolith import ContentAssetRecord, MarketingCampaignRecord, OperationChecklistRecord

__all__ = ["ContentAssetRecord", "MarketingCampaignRecord", "OperationChecklistRecord"]
