from __future__ import annotations

from core.rag.formatting import extract_snippet, format_results_from_struct


def test_format_results_from_struct_matches_legacy_markdown_shape() -> None:
    ok, rendered = format_results_from_struct(
        [
            {
                "id": "doc1",
                "title": "Sidar Notes",
                "source": "memory://sidar",
                "snippet": "first line\nsecond line",
            }
        ],
        "sidar",
        "BM25",
    )

    assert ok is True
    assert "[RAG Arama: sidar] (Motor: BM25)" in rendered
    assert "**[doc1] Sidar Notes**" in rendered
    assert "Kaynak: memory://sidar" in rendered
    assert "first line second line" in rendered


def test_format_results_from_struct_handles_empty_results() -> None:
    ok, rendered = format_results_from_struct([], "missing", "Keyword")

    assert ok is False
    assert rendered == "'missing' için belge deposunda ilgili sonuç bulunamadı."


def test_extract_snippet_prefers_query_window_and_falls_back_to_prefix() -> None:
    content = "a" * 120 + "needle and surrounding context"

    assert extract_snippet(content, "needle", window=20).startswith("...")
    assert extract_snippet("short text", "absent", window=5) == "short..."
