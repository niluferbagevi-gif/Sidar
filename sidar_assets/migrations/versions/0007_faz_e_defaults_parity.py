"""align faz e table server_defaults with the SQLite bootstrap schema

Revision ID: 0007_faz_e_defaults_parity
Revises: 0006_access_control_schema
Create Date: 2026-08-06 00:00:00

`core/db/monolith.py:_init_schema_sqlite()` (the hand-written SQLite bootstrap
schema used for local/degraded-mode installs) and this Alembic chain (the
single source of truth for PostgreSQL) had no automated parity check between
them, so `0004_faz_e_tables`'s PostgreSQL `server_default`s silently drifted
from the SQLite DDL and from the actual Python-level defaults every
`core/db/marketing.py`/`core/db/coverage.py` insert path already uses
(`channel=""`, `objective=""`, `owner_user_id=""`, `status="pending"`,
`status="pending_review"`, `requester_role="coverage"`,
`severity="medium"`). Application code always supplies these values
explicitly today, so this had no observed runtime impact, but any future
raw INSERT relying on the column default (a backfill, a manual fix, a new
code path) would silently diverge in behavior between SQLite and
PostgreSQL. This migration brings the seven affected columns back in line
with the values every other call site already treats as canonical.
"""

from __future__ import annotations

from alembic import op

revision = "0007_faz_e_defaults_parity"
down_revision = "0006_access_control_schema"
branch_labels = None
depends_on = None

# (table, column, new_server_default, previous_server_default)
# previous_server_default=None means the column had no default at all.
_DEFAULT_CHANGES = (
    ("marketing_campaigns", "channel", "", None),
    ("marketing_campaigns", "objective", "", None),
    ("marketing_campaigns", "owner_user_id", "", "system"),
    ("content_assets", "channel", "", "generic"),
    ("operation_checklists", "owner_user_id", "", "system"),
    ("operation_checklists", "status", "pending", "open"),
    ("coverage_tasks", "requester_role", "coverage", None),
    ("coverage_tasks", "status", "pending_review", "queued"),
    ("coverage_findings", "severity", "medium", "info"),
)


def upgrade() -> None:
    for table, column, new_default, _previous_default in _DEFAULT_CHANGES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(column, server_default=new_default)


def downgrade() -> None:
    for table, column, _new_default, previous_default in reversed(_DEFAULT_CHANGES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(column, server_default=previous_default)
