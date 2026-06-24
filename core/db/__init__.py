"""Backward-compatible facade for Sidar's database package.

The large legacy implementation lives in :mod:`core.db.monolith` while new code can
move toward narrower modules such as ``engine``, ``multitenant`` and
``alembic_runner``. The runtime module is still aliased to the legacy implementation
so existing imports and monkeypatch paths keep behaving during the transition, but
this facade also declares the supported public export surface for static analysis.
"""

from __future__ import annotations

import importlib as _importlib
import sys as _sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.db.monolith import (
        AccessPolicyRecord,
        AuditLogRecord,
        ContentAssetRecord,
        Database,
        MarketingCampaignRecord,
        OperationChecklistRecord,
        PromptRecord,
        postgres_failure_diagnosis,
    )
    from core.db.session import MessageRecord, SessionRecord

__all__ = [
    "AccessPolicyRecord",
    "AuditLogRecord",
    "ContentAssetRecord",
    "Database",
    "MarketingCampaignRecord",
    "MessageRecord",
    "OperationChecklistRecord",
    "PromptRecord",
    "SessionRecord",
    "postgres_failure_diagnosis",
]

from core.db import monolith as _monolith

_monolith.__package__ = __name__
_monolith.__path__ = __path__
_sys.modules[__name__] = _monolith

for _submodule in (
    "audit_log",
    "auth",
    "coverage",
    "metrics",
    "models",
    "prompt_registry",
    "session",
    "sessions",
):
    try:
        setattr(_monolith, _submodule, _importlib.import_module(f"{__name__}.{_submodule}"))
    except Exception:  # nosec B110 - optional submodule imports must not block core.db itself
        # Optional/legacy submodule imports should not block core.db itself; direct
        # imports will surface the concrete error when callers need that module.
        pass

_session = _importlib.import_module(f"{__name__}.session")
_monolith_exports = vars(_monolith)
_monolith_exports["MessageRecord"] = _session.MessageRecord
_monolith_exports["SessionRecord"] = _session.SessionRecord
_monolith_exports["__all__"] = list(__all__)
