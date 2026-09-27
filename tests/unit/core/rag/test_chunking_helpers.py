"""``core.rag.chunking`` ve ``core.rag.entity_helpers`` için unit testler."""

from __future__ import annotations

from core.rag.chunking import recursive_chunk_text
from core.rag.entity_helpers import clean_entity_value, entity_id, entity_slug


def test_recursive_chunk_text_preserves_legacy_overlap_boundaries() -> None:
    """Recursive chunk text preserves legacy overlap boundaries."""
    chunks = recursive_chunk_text("abcdefghij", size=4, overlap=1)

    assert chunks == ["abcd", "defg", "ghij"]


def test_recursive_chunk_text_normalizes_invalid_overlap() -> None:
    """Recursive chunk text normalizes invalid overlap."""
    chunks = recursive_chunk_text("abcdef", size=3, overlap=99)

    assert chunks == ["abc", "bcd", "cde", "def"]


def test_entity_helpers_normalize_ids_and_values() -> None:
    """Entity helpers normalize ids and values."""
    assert entity_slug(" Sidar Campaign! ") == "sidar-campaign"
    assert entity_id("Campaign", " Sidar Campaign! ") == "campaign:sidar-campaign"
    assert clean_entity_value("  -- Sidar\n\tGrowth:  ") == "Sidar Growth"
    assert len(entity_slug("!!!")) == 12
