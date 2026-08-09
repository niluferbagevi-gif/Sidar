"""Pure document listing and session-consolidation helpers for RAG stores."""

from __future__ import annotations

from typing import Any

DocumentItem = tuple[str, dict[str, Any]]


def normalize_session_id(session_id: str | None) -> str:
    """Normalize an optional session id to the legacy global session name."""
    return str(session_id or "").strip() or "global"


def documents_for_session(
    index: dict[str, dict[str, Any]], session_id: str | None
) -> list[DocumentItem]:
    """Return copied document metadata entries for a session."""
    normalized_session = normalize_session_id(session_id)
    return [
        (doc_id, dict(meta))
        for doc_id, meta in index.items()
        if meta.get("session_id", "global") == normalized_session
    ]


def sort_documents_for_retention(docs: list[DocumentItem]) -> list[DocumentItem]:
    """Sort documents by recent access and access count for retention decisions."""
    return sorted(
        docs,
        key=lambda item: (
            float(item[1].get("last_accessed_at", item[1].get("created_at", 0.0)) or 0.0),
            int(item[1].get("access_count", 0) or 0),
        ),
        reverse=True,
    )


def select_removable_session_documents(
    docs: list[DocumentItem], *, keep_recent_docs: int = 2
) -> list[DocumentItem]:
    """Select low-value, unpinned session documents eligible for consolidation."""
    keep_count = max(1, int(keep_recent_docs or 1))
    removable: list[DocumentItem] = []
    for doc_id, meta in sort_documents_for_retention(docs)[keep_count:]:
        tags = {str(tag).strip().lower() for tag in list(meta.get("tags", []) or [])}
        if "pinned" in tags or "memory-summary" in tags:
            continue
        if int(meta.get("access_count", 0) or 0) > 1:
            continue
        removable.append((doc_id, meta))
    return removable


def nightly_digest_document_ids(docs: list[DocumentItem]) -> list[str]:
    """Return existing nightly digest document ids that should be replaced."""
    return [
        doc_id
        for doc_id, meta in docs
        if str(meta.get("source", "") or "").startswith("memory://nightly-digest")
    ]


def build_session_summary_lines(
    session_id: str, removable: list[DocumentItem], *, preview_limit: int = 160
) -> list[str]:
    """Build deterministic digest lines for consolidated session documents."""
    lines = [
        f"Oturum: {session_id}",
        f"Konsolide edilen belge sayısı: {len(removable)}",
        "Öne çıkan eski belge özetleri:",
    ]
    for doc_id, meta in removable[:8]:
        lines.append(
            f"- [{doc_id}] {meta.get('title', doc_id)} :: "
            f"{str(meta.get('preview', '') or '')[:preview_limit]}"
        )
    return lines


def format_document_listing(
    docs: dict[str, dict[str, Any]],
    *,
    vector_backend: str = "bm25",
    pgvector_available: bool = True,
) -> str:
    """Format RAG document metadata using the legacy user-facing text shape."""
    if not docs:
        return "Belge deposu boş veya bu oturum için belge bulunamadı."

    backend_note = ""
    if vector_backend == "pgvector" and not pgvector_available:
        backend_note = " (pgvector pasif)"
    lines = [f"[Belge Deposu — {len(docs)} belge]{backend_note}", ""]
    for doc_id, meta in docs.items():
        tags = ", ".join(meta.get("tags", [])) or "-"
        size_kb = meta.get("size", 0) / 1024
        lines.append(f"  [{doc_id}] {meta['title']}")
        lines.append(
            f"    Kaynak: {meta.get('source', '-')} | Boyut: {size_kb:.1f} KB | Etiketler: {tags}"
        )
    return "\n".join(lines)
