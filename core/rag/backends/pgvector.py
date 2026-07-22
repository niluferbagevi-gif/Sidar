"""PostgreSQL pgvector backend helpers for the RAG document store."""

from __future__ import annotations

import builtins
import logging
import re
from typing import Any, cast

from core.db import postgres_failure_diagnosis
from core.embeddings import get_sentence_transformer_model

logger = logging.getLogger(__name__)
_PGVECTOR_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_valid_pgvector_identifier(identifier: str) -> bool:
    """Return True for unquoted PostgreSQL identifiers safe to embed in DDL."""
    return bool(_PGVECTOR_IDENTIFIER_RE.fullmatch(identifier))


def pgvector_failure_action_message(exc: BaseException) -> str:
    """Return a single-line pgvector fallback message using DB diagnostics."""
    diagnosis = postgres_failure_diagnosis("pgvector backend başlatılamadı", exc)
    if "yetki/parola" in diagnosis:
        return (
            "pgvector pasif, BM25 fallback aktif edildi. DATABASE_URL, "
            "SIDAR_CONTAINER_DATABASE_URL ve POSTGRES_PASSWORD değerleriyle parola/yetki "
            f"ayarlarını kontrol edin. Teşhis: {diagnosis}."
        )
    return f"pgvector pasif, BM25 fallback aktif. Teşhis: {diagnosis}."


def normalize_pg_url(url: str) -> str:
    return url.replace("+asyncpg", "")


def format_vector_for_sql(values: builtins.list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def pgvector_table_name(store: Any) -> str:
    """Return the pgvector table invariant with a safe legacy-stub fallback."""
    return str(getattr(store, "_pg_table", "rag_embeddings") or "rag_embeddings")


def _reject_if_invalid_pg_table(store: Any, pg_table: str) -> bool:
    """Return True if ``pg_table`` is safe to interpolate into DDL/DML.

    ``init_pgvector`` validates the table name once at startup, but nothing
    prevents a later mutation of ``store._pg_table`` (e.g. a future config
    hot-reload path) from bypassing that one-time check. Every call site
    that builds SQL from the table name re-validates here instead of
    trusting init-time state, and fails closed (disables pgvector, does not
    silently redirect to a different table) exactly like init_pgvector does.
    """
    if is_valid_pgvector_identifier(pg_table):
        return True
    store._pgvector_available = False
    logger.warning(
        pgvector_failure_action_message(
            ValueError("invalid PGVECTOR_TABLE; expected pattern " r"^[A-Za-z_][A-Za-z0-9_]*$")
        )
    )
    return False


def init_pgvector(store: Any) -> None:
    """Initialize PostgreSQL + pgvector table."""
    db_url = str(getattr(store.cfg, "DATABASE_URL", "") or "")
    if not db_url.startswith("postgresql"):
        logger.warning(
            pgvector_failure_action_message(RuntimeError("DATABASE_URL is not PostgreSQL"))
        )
        return

    pg_table = pgvector_table_name(store)
    if not _reject_if_invalid_pg_table(store, pg_table):
        return

    if not store._check_import("sqlalchemy") or not store._check_import("pgvector"):
        logger.warning(
            pgvector_failure_action_message(RuntimeError("pgvector dependencies missing"))
        )
        return

    try:
        from sqlalchemy import create_engine, text

        store.pg_engine = create_engine(normalize_pg_url(db_url), pool_pre_ping=True)
        engine = store._require_pg_engine()
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {pg_table} (
                    doc_id TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT,
                    source TEXT,
                    chunk_content TEXT,
                    embedding vector({store._pg_embedding_dim}),
                    PRIMARY KEY (doc_id, chunk_index)
                )
            """
            conn.execute(text(create_table_sql))  # nosec B608
            conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS idx_{pg_table}_session ON {pg_table}(session_id)")
            )
            conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS idx_{pg_table}_parent ON {pg_table}(parent_id)")
            )
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS idx_{pg_table}_embedding_hnsw ON {pg_table} USING "
                    f"hnsw (embedding vector_cosine_ops)"
                )
            )

        store._pg_embedding_model = get_sentence_transformer_model(
            store._pg_embedding_model_name, store.cfg
        )
        store._pg_embedding_device = "cuda" if bool(getattr(store, "_use_gpu", False)) else "cpu"
        store._pgvector_available = True
        store._log_backend_init_status_once(
            "pgvector_init_success",
            "pgvector backend başlatıldı: table=%s model=%s",
            pg_table,
            store._pg_embedding_model_name,
        )
    except Exception as exc:
        logger.warning(pgvector_failure_action_message(exc))
        logger.debug("pgvector backend devre dışı bırakıldı: error_type=%s", type(exc).__name__)
        store._pgvector_available = False


def pgvector_embed_texts(
    store: Any, texts: builtins.list[str]
) -> builtins.list[builtins.list[float]]:
    if not store._pg_embedding_model or not texts:
        return []
    try:
        try:
            vectors = store._pg_embedding_model.encode(
                texts, normalize_embeddings=True, show_progress_bar=False
            )
        except TypeError:
            vectors = store._pg_embedding_model.encode(texts, normalize_embeddings=True)
        if hasattr(vectors, "tolist"):
            raw_vectors = vectors.tolist()
            return [list(map(float, row)) for row in raw_vectors]
        return [list(map(float, v)) for v in vectors]
    except Exception as exc:
        logger.warning("pgvector embedding üretilemedi: %s", exc)
        return []


def upsert_pgvector_chunks(
    store: Any,
    doc_id: str,
    parent_id: str,
    session_id: str,
    title: str,
    source: str,
    chunks: builtins.list[str],
) -> None:
    if (
        not getattr(store, "_pgvector_available", False)
        or not getattr(store, "pg_engine", None)
        or not chunks
    ):
        return
    try:
        from sqlalchemy import text

        pg_table = pgvector_table_name(store)
        if not _reject_if_invalid_pg_table(store, pg_table):
            return
        vectors = store._pgvector_embed_texts(chunks)
        if not vectors:
            return

        engine = store._require_pg_engine()
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {pg_table} WHERE parent_id = :parent_id"  # nosec B608  # pg_table içi kontrollü tablo adı üreticisinden gelir, kullanıcı girdisi değildir.
                    " AND session_id = :session_id"
                ),
                {"parent_id": parent_id, "session_id": session_id},
            )
            rows = [
                {
                    "doc_id": doc_id,
                    "parent_id": parent_id,
                    "session_id": session_id,
                    "chunk_index": idx,
                    "title": title,
                    "source": source,
                    "chunk_content": chunk,
                    "embedding": format_vector_for_sql(vec),
                }
                for idx, (chunk, vec) in enumerate(zip(chunks, vectors, strict=False))
            ]
            upsert_sql = """
                    INSERT INTO __TABLE__
                    (doc_id, parent_id, session_id, chunk_index, title, source, chunk_content,
                    embedding)
                    VALUES
                    (:doc_id, :parent_id, :session_id, :chunk_index, :title, :source,
                    :chunk_content, CAST(:embedding AS vector))
                    ON CONFLICT (doc_id, chunk_index)
                    DO UPDATE SET
                        parent_id = EXCLUDED.parent_id,
                        session_id = EXCLUDED.session_id,
                        title = EXCLUDED.title,
                        source = EXCLUDED.source,
                        chunk_content = EXCLUDED.chunk_content,
                        embedding = EXCLUDED.embedding
                """.replace("__TABLE__", pg_table)  # nosec B608
            conn.execute(text(upsert_sql), rows)
    except Exception as exc:
        logger.error("pgvector belge ekleme hatası: %s", exc)


def delete_pgvector_parent(store: Any, parent_id: str, session_id: str) -> None:
    if not getattr(store, "_pgvector_available", False) or not getattr(store, "pg_engine", None):
        return
    try:
        from sqlalchemy import text

        pg_table = pgvector_table_name(store)
        if not _reject_if_invalid_pg_table(store, pg_table):
            return
        engine = store._require_pg_engine()
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {pg_table} WHERE parent_id = :parent_id"  # nosec B608  # pg_table içi kontrollü tablo adı üreticisinden gelir, kullanıcı girdisi değildir.
                    " AND session_id = :session_id"
                ),
                {"parent_id": parent_id, "session_id": session_id},
            )
    except Exception as exc:
        logger.error("pgvector silme hatası: %s", exc)


def fetch_pgvector(store: Any, query: str, top_k: int, session_id: str) -> list[dict[str, Any]]:
    if not getattr(store, "_pgvector_available", False) or not getattr(store, "pg_engine", None):
        return []
    try:
        vectors = store._pgvector_embed_texts([query])
        if not vectors:
            return []

        from sqlalchemy import text

        pg_table = pgvector_table_name(store)
        if not _reject_if_invalid_pg_table(store, pg_table):
            return []
        qvec = format_vector_for_sql(vectors[0])
        engine = store._require_pg_engine()
        with engine.begin() as conn:
            select_sql = """
                    SELECT doc_id, parent_id, title, source, chunk_content,
                           (embedding <=> CAST(:qvec AS vector)) AS distance
                    FROM __TABLE__
                    WHERE session_id = :session_id
                    ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                    LIMIT :lim
                """.replace("__TABLE__", pg_table)  # nosec B608
            rows = conn.execute(
                text(select_sql),
                {
                    "qvec": qvec,
                    "session_id": session_id,
                    "lim": max(
                        top_k * (2 if getattr(store, "_is_local_llm_provider", False) else 3),
                        top_k,
                    ),
                },
            ).fetchall()

        found_docs, seen_parents = [], set()
        for row in rows:
            parent_id = row.parent_id
            if parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            found_docs.append(
                {
                    "id": parent_id,
                    "title": row.title or "?",
                    "source": row.source or "",
                    "snippet": row.chunk_content or "",
                    "score": max(0.0, 1.0 - float(row.distance)),
                }
            )
            if len(found_docs) >= top_k:
                break
        return found_docs
    except Exception as exc:
        logger.warning("pgvector arama hatası: %s", exc)
        return []


def pgvector_search(store: Any, query: str, top_k: int, session_id: str) -> tuple[bool, str]:
    results = fetch_pgvector(store, query, top_k, session_id)
    return cast(
        tuple[bool, str],
        store._format_results_from_struct(results, query, source_name="Vektör Arama (pgvector)"),
    )


# Backwards-compatible exported name.
_pgvector_failure_action_message = pgvector_failure_action_message

__all__ = [
    "_pgvector_failure_action_message",
    "delete_pgvector_parent",
    "fetch_pgvector",
    "format_vector_for_sql",
    "init_pgvector",
    "is_valid_pgvector_identifier",
    "normalize_pg_url",
    "pgvector_embed_texts",
    "pgvector_failure_action_message",
    "pgvector_search",
    "pgvector_table_name",
    "upsert_pgvector_chunks",
]
