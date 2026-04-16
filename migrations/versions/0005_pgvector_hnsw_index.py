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
    # pgvector eklentisi kuruluysa/kurulabiliyorsa HNSW indeksi etkinleştirilir.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        DO $$
        BEGIN
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
    op.execute("DROP INDEX IF EXISTS idx_rag_embeddings_embedding_hnsw")
