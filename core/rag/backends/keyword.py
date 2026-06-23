"""Keyword fallback backend helpers for the RAG document store."""

from __future__ import annotations

from typing import Any, cast


def keyword_search(store: Any, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
    keywords = query.lower().split()
    scored = []

    for doc_id, meta in list(store._index.items()):
        if meta.get("session_id", "global") != session_id:
            continue

        doc_file = store.store_dir / f"{doc_id}.txt"
        try:
            text = doc_file.read_text(encoding="utf-8").lower()
        except FileNotFoundError:
            text = ""

        title_lower = meta["title"].lower()
        tags_lower = " ".join(meta.get("tags", [])).lower()
        score = sum(
            text.count(kw) + title_lower.count(kw) * 5 + tags_lower.count(kw) * 3 for kw in keywords
        )
        if score > 0:
            scored.append((doc_id, score))

    ranked = sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]
    results = []
    for doc_id, score in ranked:
        doc_file = store.store_dir / f"{doc_id}.txt"
        try:
            content = doc_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""
        meta = store._index.get(doc_id, {})
        snippet = store._extract_snippet(content, query)
        results.append(
            {
                "id": doc_id,
                "title": meta.get("title", "?"),
                "source": meta.get("source", ""),
                "snippet": snippet,
                "score": score,
            }
        )

    return cast(
        tuple[bool, str],
        store._format_results_from_struct(results, query, source_name="Kelime Eşleşmesi"),
    )


class KeywordBackendMixin:
    """Compatibility mixin marker for keyword backend capabilities."""


__all__ = ["KeywordBackendMixin", "keyword_search"]
