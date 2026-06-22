"""Coverage persistence records for ``core.db``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CoverageTaskRecord:
    id: int
    tenant_id: str
    requester_role: str
    command: str
    pytest_output: str
    status: str
    target_path: str
    suggested_test_path: str
    review_payload_json: str
    created_at: str
    updated_at: str


@dataclass
class CoverageFindingRecord:
    id: int
    task_id: int
    finding_type: str
    target_path: str
    summary: str
    severity: str
    details_json: str
    created_at: str


__all__ = ["CoverageFindingRecord", "CoverageTaskRecord"]
