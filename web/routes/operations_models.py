"""Pydantic request models for operations, Poyraz, and Coverage QA routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class OperationChecklistCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    items: list[str] = Field(default_factory=list)
    status: str = Field(default="pending", min_length=1, max_length=32)


class ContentAssetCreateRequest(BaseModel):
    asset_type: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=160)
    content: str = Field(..., min_length=1)
    channel: str = Field(default="", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CampaignCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    channel: str = Field(default="", max_length=64)
    objective: str = Field(default="", max_length=400)
    status: str = Field(default="draft", min_length=1, max_length=32)
    budget: float = Field(default=0.0, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    initial_assets: list[ContentAssetCreateRequest] = Field(default_factory=list)
    initial_checklists: list[OperationChecklistCreateRequest] = Field(default_factory=list)


class PoyrazToolRunRequest(BaseModel):
    tool_name: str = Field(..., min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)
    room_id: str = Field(default="ops:control", max_length=120)


class LandingPageDraftRequest(BaseModel):
    brand_name: str = Field(..., min_length=1, max_length=160)
    offer: str = Field(..., min_length=1, max_length=600)
    audience: str = Field(..., min_length=1, max_length=400)
    call_to_action: str = Field(..., min_length=1, max_length=160)
    tone: str = Field(default="professional", max_length=64)
    sections: list[str] = Field(default_factory=list)
    campaign_id: int | None = Field(default=None)
    store_asset: bool = Field(default=False)
    asset_title: str = Field(default="Landing Page Taslağı", max_length=160)
    channel: str = Field(default="web", max_length=64)
    room_id: str = Field(default="ops:control", max_length=120)


class CampaignCopyGenerateRequest(BaseModel):
    campaign_name: str = Field(..., min_length=1, max_length=160)
    objective: str = Field(..., min_length=1, max_length=400)
    audience: str = Field(..., min_length=1, max_length=400)
    channels: list[str] = Field(default_factory=list)
    offer: str = Field(default="", max_length=600)
    tone: str = Field(default="professional", max_length=64)
    call_to_action: str = Field(default="", max_length=160)
    campaign_id: int | None = Field(default=None)
    store_asset: bool = Field(default=False)
    asset_title: str = Field(default="Kampanya Kopyası", max_length=160)
    room_id: str = Field(default="ops:control", max_length=120)


class ServiceOperationsPlanRequest(BaseModel):
    campaign_id: int | None = Field(default=None)
    campaign_name: str = Field(default="", max_length=160)
    service_name: str = Field(default="", max_length=160)
    audience: str = Field(default="", max_length=400)
    menu_plan: dict[str, list[str]] = Field(default_factory=dict)
    vendor_assignments: dict[str, str] = Field(default_factory=dict)
    timeline: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)
    persist_checklist: bool = Field(default=True)
    checklist_title: str = Field(default="Operasyon Planı", max_length=160)
    room_id: str = Field(default="ops:control", max_length=120)


class CoverageAnalyzeRequest(BaseModel):
    coverage_xml: str = Field(default="coverage.xml", max_length=512)
    coveragerc: str = Field(default=".coveragerc", max_length=512)
    coverage_output: str = Field(default="")
    limit: int = Field(default=25, ge=1, le=200)
    room_id: str = Field(default="qa:coverage", max_length=120)


class CoverageGenerateRequest(BaseModel):
    coverage_finding: dict[str, Any] = Field(default_factory=dict)
    coveragerc: dict[str, Any] = Field(default_factory=dict)
    target_path: str = Field(default="", max_length=512)
    pytest_output: str = Field(default="")
    analysis: dict[str, Any] = Field(default_factory=dict)
    room_id: str = Field(default="qa:coverage", max_length=120)


class CoverageBatchRequest(BaseModel):
    coverage_xml: str = Field(default="coverage.xml", max_length=512)
    coveragerc: str = Field(default=".coveragerc", max_length=512)
    limit: int = Field(default=10, ge=1, le=100)
    batch_size: int = Field(default=1, ge=1, le=10)
    append: bool = Field(default=True)
    room_id: str = Field(default="qa:coverage", max_length=120)


__all__ = [
    "OperationChecklistCreateRequest",
    "ContentAssetCreateRequest",
    "CampaignCreateRequest",
    "PoyrazToolRunRequest",
    "LandingPageDraftRequest",
    "CampaignCopyGenerateRequest",
    "ServiceOperationsPlanRequest",
    "CoverageAnalyzeRequest",
    "CoverageGenerateRequest",
    "CoverageBatchRequest",
]
