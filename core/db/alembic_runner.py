"""Alembic runner compatibility exports for the DB package."""

from __future__ import annotations

from core.db_components.migrations import run_alembic_upgrade_head

__all__ = ["run_alembic_upgrade_head"]
