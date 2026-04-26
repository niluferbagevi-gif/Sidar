"""Factory helpers for test object creation."""

from __future__ import annotations

import time
from typing import Any


def build_hitl_request(**overrides: Any):
    """Ortak HITLRequest üreticisi."""
    from core.hitl import HITLDecision, HITLRequest

    payload = {
        "request_id": "req-factory",
        "action": "file_delete",
        "description": "delete a file",
        "payload": {"path": "/tmp/x"},
        "requested_by": "tester",
        "created_at": time.time(),
        "expires_at": time.time() + 60,
        "decision": HITLDecision.PENDING,
    }
    payload.update(overrides)
    return HITLRequest(**payload)
