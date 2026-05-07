"""add hnsw index for pgvector rag embeddings

Revision ID: 0005_pgvector_hnsw_index
Revises: 0004_faz_e_tables
Create Date: 2026-04-16 00:00:00
"""

from __future__ import annotations

from alembic import op

revision = "0005_pgvector_hnsw_index"
down_revision = "0004_faz_e_tables"
branch_labels = None
depends_on = None


RAG_EMBEDDING_DIMENSION = 384


def upgrade() -> None:
    # pgvector yalnızca PostgreSQL'de desteklenir; SQLite degraded mode bu migrasyonu atlar.
    bind = op.get_bind()
    if bind.engine.name != "postgresql":
        return

    op.execute(
        f"""
        DO $$
        DECLARE
            vector_available BOOLEAN;
        BEGIN
            SELECT EXISTS (
                SELECT 1
                FROM pg_available_extensions
                WHERE name = 'vector'
            )
            INTO vector_available;

            IF NOT vector_available THEN
                RETURN;
            END IF;

            BEGIN
                EXECUTE 'CREATE EXTENSION IF NOT EXISTS vector';
            EXCEPTION
                WHEN insufficient_privilege THEN
                    RETURN;
            END;

            EXECUTE '
                CREATE TABLE IF NOT EXISTS rag_embeddings (
                    doc_id TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT,
                    source TEXT,
                    chunk_content TEXT,
                    embedding vector({RAG_EMBEDDING_DIMENSION}),
                    PRIMARY KEY (doc_id, chunk_index)
                )
            ';

            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_embeddings_session '
                 || 'ON rag_embeddings(session_id)';
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_embeddings_parent '
                 || 'ON rag_embeddings(parent_id)';
            EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_embeddings_embedding_hnsw '
                 || 'ON rag_embeddings USING hnsw (embedding vector_cosine_ops)';
        END $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.engine.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS idx_rag_embeddings_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_rag_embeddings_parent")
    op.execute("DROP INDEX IF EXISTS idx_rag_embeddings_session")
    op.execute("DROP TABLE IF EXISTS rag_embeddings")
