"""Database and pgvector Doctor checks."""

from __future__ import annotations

import core.doctor as _doctor
from core.doctor import DoctorCheck


def check_database_env() -> DoctorCheck:
    return _doctor.check_database_env()


def check_database_connectivity() -> DoctorCheck:
    return _doctor.check_database_connectivity()


def check_pgvector_ready(
    database_connectivity: DoctorCheck | None = None,
) -> DoctorCheck:
    """Check pgvector while optionally reusing the connectivity probe result."""
    return _doctor.check_pgvector_ready(database_connectivity=database_connectivity)


__all__ = ["check_database_connectivity", "check_database_env", "check_pgvector_ready"]
