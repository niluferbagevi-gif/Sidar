"""Database and pgvector Doctor checks."""

from __future__ import annotations

import core.doctor as _doctor
from core.doctor import DoctorCheck


def check_database_env() -> DoctorCheck:
    return _doctor.check_database_env()


def check_database_connectivity() -> DoctorCheck:
    return _doctor.check_database_connectivity()


def check_pgvector_ready() -> DoctorCheck:
    return _doctor.check_pgvector_ready()


__all__ = ["check_database_connectivity", "check_database_env", "check_pgvector_ready"]
