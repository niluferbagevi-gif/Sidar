"""
Database check helpers for Sidar doctor.

These functions delegate to the original implementations in core.doctor
so that orchestration lives in core.doctor but the check logic can be
cohesively organized in this module.
"""

from __future__ import annotations

from core.doctor import DoctorCheck
# Import original check implementations to re-export them under this module.
from core.doctor import (
    check_database_env as _orig_check_database_env,
    check_database_connectivity as _orig_check_database_connectivity,
    check_pgvector_ready as _orig_check_pgvector_ready,
)


def check_database_env() -> DoctorCheck:
    """
    Verify that the PostgreSQL environment variables and DSNs are consistent.

    Delegates to core.doctor.check_database_env() to perform the actual checks.
    """
    return _orig_check_database_env()


def check_database_connectivity() -> DoctorCheck:
    """
    Perform a lightweight connectivity smoke test against the configured database.

    Delegates to core.doctor.check_database_connectivity() to perform the actual checks.
    """
    return _orig_check_database_connectivity()


def check_pgvector_ready() -> DoctorCheck:
    """
    Check that the pgvector backend is ready when configured.

    Delegates to core.doctor.check_pgvector_ready() to perform the actual checks.
    """
    return _orig_check_pgvector_ready()
