from __future__ import annotations

from core.rag.chunking import recursive_chunk_text
from core.rag.entity_helpers import clean_entity_value, entity_id, entity_slug


def test_recursive_chunk_text_preserves_legacy_overlap_boundaries() -> None:
    chunks = recursive_chunk_text("abcdefghij", size=4, overlap=1)

    assert chunks == ["abcd", "defg", "ghij"]


def test_recursive_chunk_text_normalizes_invalid_overlap() -> None:
    chunks = recursive_chunk_text("abcdef", size=3, overlap=99)

    assert chunks == ["abc", "bcd", "cde", "def"]


def test_entity_helpers_normalize_ids_and_values() -> None:
    assert entity_slug(" Sidar Campaign! ") == "sidar-campaign"
    assert entity_id("Campaign", " Sidar Campaign! ") == "campaign:sidar-campaign"
    assert clean_entity_value("  -- Sidar\n\tGrowth:  ") == "Sidar Growth"
    assert len(entity_slug("!!!")) == 12
