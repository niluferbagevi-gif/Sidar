"""Dataclass records shared by database repository modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AccessPolicyRecord:
    """Row of ``access_policies``: one allow/deny rule for a user and resource."""

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
    """Row of ``prompt_registry``: one versioned system prompt for an agent role."""

    id: int
    role_name: str
    prompt_text: str
    version: int
    is_active: bool
    created_at: str
    updated_at: str


@dataclass
class AuditLogRecord:
    """Row of ``audit_logs``: one recorded access decision."""

    id: int
    user_id: str
    tenant_id: str
    action: str
    resource: str
    ip_address: str
    allowed: bool
    timestamp: str


@dataclass
class MarketingCampaignRecord:
    """Row of ``marketing_campaigns`` owned by a tenant."""

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
    """Row of ``content_assets``: generated content attached to a campaign."""

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
    """Row of ``operation_checklists``: a JSON item list, optionally tied to a campaign."""

    id: int
    campaign_id: int | None
    tenant_id: str
    title: str
    items_json: str
    status: str
    owner_user_id: str
    created_at: str
    updated_at: str
