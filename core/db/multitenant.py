"""Multi-tenant record compatibility exports for the DB package."""

from __future__ import annotations

from core.db.monolith import AccessPolicyRecord, AuditLogRecord

__all__ = ["AccessPolicyRecord", "AuditLogRecord"]
