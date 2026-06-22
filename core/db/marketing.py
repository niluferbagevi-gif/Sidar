"""Marketing persistence boundary for the ``core.db`` package."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketingCampaignRecord:
    id: int
    tenant_id: str
    name: str
    channel: str
    objective: str
    status: str
    owner_user_id: str
    budget: float
    metadata_json: str
    created_at: str
    updated_at: str


@dataclass
class ContentAssetRecord:
    id: int
    campaign_id: int
    tenant_id: str
    asset_type: str
    title: str
    content: str
    channel: str
    metadata_json: str
    created_at: str
    updated_at: str


@dataclass
class OperationChecklistRecord:
    id: int
    campaign_id: int | None
    tenant_id: str
    title: str
    items_json: str
    status: str
    owner_user_id: str
    created_at: str
    updated_at: str


__all__ = ["ContentAssetRecord", "MarketingCampaignRecord", "OperationChecklistRecord"]
