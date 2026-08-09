"""Backward-compatible wrapper for :mod:`core.db.audit`.

New audit persistence code should import ``core.db.audit`` directly. This module
remains for legacy callers during the phased monolith split.
"""

from __future__ import annotations

from core.db.audit import list_audit_logs, record_audit_log

__all__ = ["list_audit_logs", "record_audit_log"]
