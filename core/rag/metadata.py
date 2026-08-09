"""Pure-ish metadata builders for RAG document ingestion."""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any


def build_document_identity(title: str, source: str) -> tuple[str, str]:
    """Build legacy document and parent ids for a title/source pair."""
    doc_id = uuid.uuid4().hex[:12]
    parent_id = hashlib.md5(f"{title}{source}".encode(), usedforsecurity=False).hexdigest()[:12]
    return doc_id, parent_id


def now_timestamp() -> float:
    """Return the timestamp used by RAG document metadata."""
    return time.time()


def build_chunk_ids(doc_id: str, chunk_count: int) -> list[str]:
    """Build Chroma-compatible chunk ids for a document."""
    return [f"{doc_id}_{index}" for index in range(chunk_count)]


def build_chunk_metadatas(
    *,
    chunk_count: int,
    source: str,
    title: str,
    tags: list[str],
    parent_id: str,
    session_id: str,
    timestamp: float,
) -> list[dict[str, Any]]:
    """Build per-chunk metadata records with the legacy Chroma schema."""
    return [
        {
            "source": source,
            "title": title,
            "tags": ",".join(tags),
            "parent_id": parent_id,
            "chunk_index": index,
            "session_id": session_id,
            "created_at": timestamp,
            "last_accessed_at": timestamp,
            "access_count": 0,
        }
        for index in range(chunk_count)
    ]


def build_index_metadata(
    *,
    title: str,
    source: str,
    tags: list[str],
    content: str,
    parent_id: str,
    session_id: str,
    timestamp: float,
) -> dict[str, Any]:
    """Build the persisted document index metadata record."""
    return {
        "title": title,
        "source": source,
        "tags": tags,
        "size": len(content),
        "preview": content[:300],
        "parent_id": parent_id,
        "session_id": session_id,
        "created_at": timestamp,
        "last_accessed_at": timestamp,
        "access_count": 0,
    }
