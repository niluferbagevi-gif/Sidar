"""Pure entity normalization helpers for GraphRAG document metadata."""

from __future__ import annotations

import hashlib
import re
from typing import Any


def entity_slug(value: str) -> str:
    """Normalize an entity value into a stable, URL-safe graph id segment."""
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    normalized = normalized.strip("-")
    if normalized:
        return normalized[:80]
    return hashlib.md5(str(value).encode(), usedforsecurity=False).hexdigest()[:12]


def entity_id(label: str, name: str) -> str:
    """Build the legacy GraphRAG entity id for a label/name pair."""
    return f"{label.lower()}:{entity_slug(name)}"


def clean_entity_value(value: Any) -> str:
    """Normalize an extracted entity value for graph storage."""
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n-–—:|,.;")
    return cleaned[:180]
