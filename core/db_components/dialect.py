"""Database dialect normalization helpers."""

from __future__ import annotations

import re
from typing import Any

ASYNCPG_COMMAND_TAG_COUNT_RE = re.compile(
    r"^(?:INSERT\s+\d+|UPDATE|DELETE|SELECT|MOVE|FETCH|COPY)\s+(\d+)\s*$", re.IGNORECASE
)


def quote_sql_identifier(identifier: str) -> str:
    """Validate and quote an SQL identifier without accepting SQL fragments."""
    value = (identifier or "").strip()
    if not value:
        raise ValueError("SQL identifier cannot be empty")
    if not value.replace("_", "").isalnum() or not (value[0].isalpha() or value[0] == "_"):
        raise ValueError(f"Invalid SQL identifier: {identifier!r}")
    return f'"{value}"'


def parse_asyncpg_affected_rows(
    command_tag: Any, *, pattern: Any = ASYNCPG_COMMAND_TAG_COUNT_RE
) -> int:
    """Safely parse the affected-row count from an asyncpg command tag."""
    text = str(command_tag or "").strip()
    match = pattern.search(text)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return 0


__all__ = ["ASYNCPG_COMMAND_TAG_COUNT_RE", "parse_asyncpg_affected_rows", "quote_sql_identifier"]
