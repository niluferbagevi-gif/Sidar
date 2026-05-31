"""Incremental extraction helpers for the legacy :mod:`core.db` facade."""

from .dialect import parse_asyncpg_affected_rows, quote_sql_identifier
from .migrations import run_alembic_upgrade_head

__all__ = ["parse_asyncpg_affected_rows", "quote_sql_identifier", "run_alembic_upgrade_head"]
