"""Engine and connection-pool compatibility exports for the DB package."""

from __future__ import annotations

from core.db.monolith import (
    Database,
    postgres_failure_diagnosis,
)

__all__ = ["Database", "postgres_failure_diagnosis"]
