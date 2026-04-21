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


def upgrade() -> None:
    # Veritabanı motorunu kontrol et. PostgreSQL değilse (örn: testlerdeki SQLite) sessizce atla.
    bind = op.get_bind()
    if bind.engine.name != "postgresql":
        return

    # pgvector mevcut değilse migrasyonu sessizce atla (ChromaDB fallback çalışmaya devam eder).
    op.execute(
        """
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

            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'rag_embeddings'
                  AND column_name = 'embedding'
            ) THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS idx_rag_embeddings_embedding_hnsw '
                     || 'ON rag_embeddings USING hnsw (embedding vector_cosine_ops)';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Downgrade işleminde de veritabanı motorunu kontrol et.
    bind = op.get_bind()
    if bind.engine.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS idx_rag_embeddings_embedding_hnsw")
