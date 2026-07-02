"""Pure database helper functions extracted from the monolith facade."""

from __future__ import annotations

import importlib
import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(UTC).isoformat()


def utc_now_pair() -> tuple[datetime, str]:
    """Return the current UTC datetime and its ISO-8601 representation."""
    now_dt = datetime.now(UTC)
    return now_dt, now_dt.isoformat()


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def json_dumps(payload: Any) -> str:
    """Serialize JSON with stable ordering and UTF-8 text preservation."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def new_entity_id() -> str:
    """Generate a time-sortable UUID when available, otherwise UUIDv4."""
    uuid7_builtin = getattr(uuid, "uuid7", None)
    if callable(uuid7_builtin):
        return str(uuid7_builtin())

    try:
        uuid6_module = importlib.import_module("uuid6")
        uuid7_external = getattr(uuid6_module, "uuid7", None)
        if callable(uuid7_external):
            return str(uuid7_external())
    except Exception as exc:  # pragma: no cover - optional dependency fallback
        logger.debug("uuid6 modülü kullanılamadı, uuid4 fallback kullanılacak: %s", exc)

    return str(uuid.uuid4())


def sqlite_fetchone(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    """Fetch one SQLite row while preserving the legacy typed helper contract."""
    return cursor.fetchone()
