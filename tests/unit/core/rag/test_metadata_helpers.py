from __future__ import annotations

import uuid

from core.rag import metadata
from core.rag.metadata import build_chunk_ids, build_chunk_metadatas, build_index_metadata


def test_build_document_identity_preserves_legacy_shapes(monkeypatch) -> None:
    monkeypatch.setattr(
        metadata.uuid,
        "uuid4",
        lambda: uuid.UUID("12345678-1234-5678-1234-567812345678"),
    )

    doc_id, parent_id = metadata.build_document_identity("Title", "source://x")

    assert doc_id == "123456781234"
    assert len(parent_id) == 12


def test_build_chunk_metadata_preserves_chroma_schema() -> None:
    assert build_chunk_ids("doc", 2) == ["doc_0", "doc_1"]

    metadatas = build_chunk_metadatas(
        chunk_count=1,
        source="memory://source",
        title="Title",
        tags=["a", "b"],
        parent_id="parent",
        session_id="session",
        timestamp=12.5,
    )

    assert metadatas == [
        {
            "source": "memory://source",
            "title": "Title",
            "tags": "a,b",
            "parent_id": "parent",
            "chunk_index": 0,
            "session_id": "session",
            "created_at": 12.5,
            "last_accessed_at": 12.5,
            "access_count": 0,
        }
    ]


def test_build_index_metadata_preserves_preview_and_counters() -> None:
    meta = build_index_metadata(
        title="Title",
        source="source",
        tags=["tag"],
        content="abcdef",
        parent_id="parent",
        session_id="session",
        timestamp=42.0,
    )

    assert meta["preview"] == "abcdef"
    assert meta["size"] == 6
    assert meta["access_count"] == 0
    assert meta["tags"] == ["tag"]
