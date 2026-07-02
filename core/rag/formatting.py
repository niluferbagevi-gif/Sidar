"""Pure RAG search result formatting helpers."""

from __future__ import annotations

from typing import Any


def format_results_from_struct(
    results: list[dict[str, Any]], query: str, source_name: str
) -> tuple[bool, str]:
    """Format structured RAG backend results into the legacy markdown response."""
    if not results:
        return False, f"'{query}' için belge deposunda ilgili sonuç bulunamadı."

    lines = [f"[RAG Arama: {query}] (Motor: {source_name})", ""]
    for result in results:
        lines.append(f"**[{result['id']}] {result['title']}**")
        if result["source"]:
            lines.append(f"  Kaynak: {result['source']}")

        snippet = result["snippet"].replace("\n", " ").strip()
        if len(snippet) > 400:
            snippet = snippet[:400] + "..."

        lines.append(f"  {snippet}")
        lines.append("")

    return True, "\n".join(lines)


def extract_snippet(content: str, query: str, window: int = 400) -> str:
    """Extract a query-centered snippet for BM25 and keyword backend results."""
    keywords = query.lower().split()
    content_lower = content.lower()

    for keyword in keywords:
        idx = content_lower.find(keyword)
        if idx != -1:
            start = max(0, idx - 100)
            end = min(len(content), idx + window)
            snippet = content[start:end].strip()
            return f"...{snippet}..." if start > 0 else snippet

    return content[:window] + ("..." if len(content) > window else "")
