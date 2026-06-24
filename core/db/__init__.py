"""Backward-compatible facade for Sidar's database package.

The large legacy implementation lives in :mod:`core.db.monolith` while new code can
move toward narrower modules such as ``engine``, ``multitenant`` and
``alembic_runner``. This module aliases ``core.db`` to the legacy implementation
so existing imports and monkeypatch paths (including private helpers used by older
tests) keep behaving exactly as before during the transition.
"""

from __future__ import annotations

import importlib as _importlib
import sys as _sys

from core.db import monolith as _monolith

_monolith.__package__ = __name__
_monolith.__path__ = __path__  # type: ignore[attr-defined]
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
