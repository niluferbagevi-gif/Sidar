"""SQLite FTS5 BM25 backend helpers for the RAG document store."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


def init_fts(store: Any) -> None:
    """Initialize the disk-backed SQLite FTS5 BM25 index."""
    try:
        db_path = store.store_dir / "bm25_fts.db"
        store.fts_conn = sqlite3.connect(db_path, check_same_thread=False)
        store.fts_conn.row_factory = sqlite3.Row
        with store._write_lock:
            store.fts_conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS bm25_index USING fts5(
                    doc_id UNINDEXED,
                    session_id UNINDEXED,
                    content,
                    tokenize='unicode61 remove_diacritics 1'
                );
            """)
            cursor = store.fts_conn.execute("SELECT count(*) as c FROM bm25_index")
            if cursor.fetchone()["c"] == 0 and store._index:
                logger.info("Mevcut belgeler SQLite FTS5 disk motoruna aktarılıyor...")
                for doc_id, meta in store._index.items():
                    doc_file = store.store_dir / f"{doc_id}.txt"
                    try:
                        content = doc_file.read_text(encoding="utf-8")
                        session_id = meta.get("session_id", "global")
                        store.fts_conn.execute(
                            "INSERT INTO bm25_index (doc_id, session_id, content) VALUES (?, ?, ?)",
                            (doc_id, session_id, content),
                        )
                    except Exception as exc:
                        logger.debug("Doküman FTS'e migrate edilemedi (%s): %s", doc_id, exc)
            store.fts_conn.commit()
        store._log_backend_init_status_once(
            "bm25_fts_init_success",
            "SQLite FTS5 (BM25) veritabanı disk üzerinde başarıyla başlatıldı.",
        )
    except Exception as exc:
        logger.error("FTS5 başlatma hatası: %s", exc)
        store._bm25_available = False


def update_bm25_cache_on_add(store: Any, doc_id: str, content: str) -> None:
    """Persist a document in the FTS5 table.

    This is called from paths that already hold the store write lock.
    """
    if not store._bm25_available:
        return
    session_id = store._index.get(doc_id, {}).get("session_id", "global")
    store.fts_conn.execute("DELETE FROM bm25_index WHERE doc_id = ?", (doc_id,))
    store.fts_conn.execute(
        "INSERT INTO bm25_index (doc_id, session_id, content) VALUES (?, ?, ?)",
        (doc_id, session_id, content),
    )
    store.fts_conn.commit()


def update_bm25_cache_on_delete(store: Any, doc_id: str) -> None:
    """Remove a deleted document from the FTS5 table.

    This is called from paths that already hold the store write lock.
    """
    if not store._bm25_available:
        return
    store.fts_conn.execute("DELETE FROM bm25_index WHERE doc_id = ?", (doc_id,))
    store.fts_conn.commit()


def fetch_bm25(store: Any, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]:
    """Fetch BM25-ranked results from the disk-backed FTS5 index."""
    if not store._bm25_available:
        return []

    words = [w for w in query.replace('"', "").replace("'", "").split() if w.isalnum()]
    if not words:
        return []

    match_query = " OR ".join(words)
    sql = """
        SELECT doc_id, bm25(bm25_index) as score
        FROM bm25_index
        WHERE bm25_index MATCH ? AND session_id = ?
        ORDER BY score
        LIMIT ?
    """

    try:
        with store._write_lock:
            cursor = store.fts_conn.execute(sql, (match_query, session_id, top_k))
            rows = cursor.fetchall()
    except Exception as exc:
        logger.warning("FTS5 Arama Hatası: %s", exc)
        return []

    results = []
    for row in rows:
        doc_id = row["doc_id"]
        score = abs(row["score"])
        meta = store._index.get(doc_id, {})
        doc_file = store.store_dir / f"{doc_id}.txt"
        try:
            content = doc_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = ""
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
    return results


def bm25_search(store: Any, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
    results = fetch_bm25(store, query, top_k, session_id)
    return store._format_results_from_struct(results, query, source_name="BM25")


class BM25BackendMixin:
    """Compatibility mixin marker for BM25 backend capabilities."""


__all__ = [
    "BM25BackendMixin",
    "bm25_search",
    "fetch_bm25",
    "init_fts",
    "update_bm25_cache_on_add",
    "update_bm25_cache_on_delete",
]
