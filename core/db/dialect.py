"""Database dialect helper facade for PostgreSQL/asyncpg compatibility."""

from __future__ import annotations

from typing import Any

from core.db_components.dialect import (
    ASYNCPG_COMMAND_TAG_COUNT_RE as ASYNCPG_COMMAND_TAG_COUNT_RE,
)
from core.db_components.dialect import (
    assert_safe_sql_identifier as assert_safe_sql_identifier,
)
from core.db_components.dialect import (
    is_safe_sql_identifier as is_safe_sql_identifier,
)
from core.db_components.dialect import (
    parse_asyncpg_affected_rows as _parse_asyncpg_affected_rows,
)
from core.db_components.dialect import quote_sql_identifier as quote_sql_identifier


def parse_asyncpg_affected_rows(
    command_tag: Any, *, pattern: Any = ASYNCPG_COMMAND_TAG_COUNT_RE
) -> int:
    """Parse affected row count from an asyncpg command tag."""
    return _parse_asyncpg_affected_rows(command_tag, pattern=pattern)
