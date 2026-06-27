"""add hnsw index for pgvector rag embeddings

Revision ID: 0005_pgvector_hnsw_index
Revises: 0004_faz_e_tables
Create Date: 2026-04-16 00:00:00
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "0005_pgvector_hnsw_index"
down_revision = "0004_faz_e_tables"
branch_labels = None
depends_on = None

HNSW_M_ENV = "PGVECTOR_HNSW_M"
HNSW_EF_CONSTRUCTION_ENV = "PGVECTOR_HNSW_EF_CONSTRUCTION"
DEFAULT_HNSW_M = 16
DEFAULT_HNSW_EF_CONSTRUCTION = 64


def _resolve_engine_name(bind: object) -> str:
    engine = getattr(bind, "engine", None)
    if engine is not None and getattr(engine, "name", None):
        return str(engine.name).strip().lower()
    dialect = getattr(bind, "dialect", None)
    if dialect is not None and getattr(dialect, "name", None):
        return str(dialect.name).strip().lower()
    return ""


def _bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _hnsw_index_options() -> str:
    """Resolve bounded HNSW index options for different memory/VRAM profiles."""
    m = _bounded_int_env(HNSW_M_ENV, DEFAULT_HNSW_M, minimum=4, maximum=64)
    ef_construction = _bounded_int_env(
        HNSW_EF_CONSTRUCTION_ENV,
        DEFAULT_HNSW_EF_CONSTRUCTION,
        minimum=16,
        maximum=512,
    )
    return f"WITH (m = {m}, ef_construction = {ef_construction})"


def upgrade() -> None:
    # Veritabanı motorunu kontrol et. PostgreSQL değilse (örn: testlerdeki SQLite) sessizce atla.
    bind = op.get_bind()
    if _resolve_engine_name(bind) != "postgresql":
        return

    vector_backend = os.getenv("RAG_VECTOR_BACKEND", "chroma").strip().lower()
    require_pgvector = vector_backend == "pgvector"

    # NOT: op.execute() bir Result döndürmez (None). SELECT için bağlı connection'ı kullan.
    if hasattr(bind, "execute"):
        vector_available = bind.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_available_extensions
                    WHERE name = 'vector'
                )
                """
            )
        ).scalar()
    else:  # test doubles may not expose execute on bind
        vector_available = True

    if not vector_available:
        if require_pgvector:
            raise RuntimeError(
                "RAG_VECTOR_BACKEND=pgvector but pgvector extension is not available in this PostgreSQL image."
            )
        return

    if require_pgvector:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    else:
        try:
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:
            return

    hnsw_options = _hnsw_index_options()
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE '
                CREATE TABLE IF NOT EXISTS rag_embeddings (
                    doc_id TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT,
                    source TEXT,
                    chunk_content TEXT,
                    embedding vector(384),
                    PRIMARY KEY (doc_id, chunk_index)
                )
            ';

            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_embeddings_session '
                 || 'ON rag_embeddings(session_id)';
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_embeddings_parent '
                 || 'ON rag_embeddings(parent_id)';
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_embeddings_embedding_hnsw '
                 || 'ON rag_embeddings USING hnsw (embedding vector_cosine_ops) {hnsw_options}';
        END $$;
        """
    )


def downgrade() -> None:
    # Downgrade işleminde de veritabanı motorunu kontrol et.
    bind = op.get_bind()
    if _resolve_engine_name(bind) != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS idx_rag_embeddings_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_rag_embeddings_parent")
    op.execute("DROP INDEX IF EXISTS idx_rag_embeddings_session")
    op.execute("DROP TABLE IF EXISTS rag_embeddings")
