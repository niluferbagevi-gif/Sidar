"""Database dialect normalization helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

ASYNCPG_COMMAND_TAG_COUNT_RE = re.compile(
    r"^(?:INSERT\s+\d+|UPDATE|DELETE|SELECT|MOVE|FETCH|COPY)\s+(\d+)\s*$", re.IGNORECASE
)

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class _ValidatedSQLFragment(str):
    """Marker for non-value SQL fragments produced only by audited builders."""


def is_safe_sql_identifier(identifier: str, *, allowed: Iterable[str] | None = None) -> bool:
    """Return True if ``identifier`` is safe to interpolate unquoted into SQL.

    This is the single source of truth for "is this table/column name safe"
    checks that build SQL with an f-string instead of a bind parameter
    (table/column names cannot be bound like values). It requires an
    unquoted-identifier shape — letters, digits, underscore, not starting
    with a digit — and, when ``allowed`` is given, membership in that
    allowlist too. New call sites needing this check should use this
    function (or ``assert_safe_sql_identifier``) instead of adding another
    identifier regex.
    """
    if not _SQL_IDENTIFIER_RE.fullmatch(identifier or ""):
        return False
    if allowed is not None and identifier not in allowed:
        return False
    return True


def assert_safe_sql_identifier(identifier: str, *, allowed: Iterable[str] | None = None) -> str:
    """Return ``identifier`` unchanged, raising ValueError if it is unsafe.

    See ``is_safe_sql_identifier`` for the safety rule being enforced.
    """
    if not is_safe_sql_identifier(identifier, allowed=allowed):
        raise ValueError(f"Invalid SQL identifier: {identifier!r}")
    return identifier


def quote_sql_identifier(identifier: str) -> str:
    """Validate and quote an SQL identifier without accepting SQL fragments."""
    value = (identifier or "").strip()
    if not value:
        raise ValueError("SQL identifier cannot be empty")
    return f'"{assert_safe_sql_identifier(value)}"'


def join_sql_identifiers(
    identifiers: Iterable[str], *, allowed: Iterable[str] | None = None
) -> str:
    """Validate and join identifiers for SQL column or table lists.

    Bind parameters cannot represent identifiers.  Callers that need a dynamic
    comma-separated identifier list should use this helper rather than validating
    and joining in separate steps, which could accidentally interpolate a different
    collection than the one that was checked.
    """
    values = tuple(identifiers)
    if not values:
        raise ValueError("SQL identifier list cannot be empty")
    return ", ".join(assert_safe_sql_identifier(value, allowed=allowed) for value in values)


def postgres_bind_placeholders(count: int) -> str:
    """Return a validated PostgreSQL positional-bind placeholder list."""
    if isinstance(count, bool) or count < 1:
        raise ValueError(f"PostgreSQL bind placeholder count must be positive: {count!r}")
    return _ValidatedSQLFragment(", ".join(f"${index}" for index in range(1, count + 1)))


def render_sql_identifier_template(template: str, /, **tokens: str | Iterable[str] | int) -> str:
    """Render an internal SQL template using only validated non-value tokens.

    SQL bind parameters cannot represent table names, column lists, or DDL integer
    literals. This audited sink accepts only identifiers, identifier iterables, and
    non-negative integers; query values must still use driver bind parameters.
    """
    rendered: dict[str, str] = {}
    for name, token in tokens.items():
        if isinstance(token, _ValidatedSQLFragment):
            rendered[name] = token
        elif isinstance(token, bool):
            raise ValueError(f"Invalid SQL integer literal for {name!r}: {token!r}")
        elif isinstance(token, int):
            if token < 0:
                raise ValueError(f"Invalid SQL integer literal for {name!r}: {token!r}")
            rendered[name] = str(token)
        elif isinstance(token, str):
            rendered[name] = assert_safe_sql_identifier(token)
        else:
            rendered[name] = join_sql_identifiers(token)
    return template.format_map(rendered)


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


__all__ = [
    "ASYNCPG_COMMAND_TAG_COUNT_RE",
    "assert_safe_sql_identifier",
    "is_safe_sql_identifier",
    "join_sql_identifiers",
    "parse_asyncpg_affected_rows",
    "postgres_bind_placeholders",
    "quote_sql_identifier",
    "render_sql_identifier_template",
]
