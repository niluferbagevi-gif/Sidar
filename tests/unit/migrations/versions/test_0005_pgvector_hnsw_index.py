"""Tests for migrations/versions/0005_pgvector_hnsw_index.py"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


def _load_migration(monkeypatch, engine_name: str = "postgresql"):
    op_mock = MagicMock()
    op_mock.get_bind.return_value = SimpleNamespace(engine=SimpleNamespace(name=engine_name))

    alembic_mod = types.ModuleType("alembic")
    alembic_mod.op = op_mock
    monkeypatch.setitem(sys.modules, "alembic", alembic_mod)
    monkeypatch.setitem(sys.modules, "alembic.op", op_mock)

    spec = importlib.util.spec_from_file_location(
        "migrations.versions.0005_pgvector_hnsw_index",
        Path("migrations/versions/0005_pgvector_hnsw_index.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, op_mock


def test_upgrade_skips_non_postgresql(monkeypatch):
    module, op_mock = _load_migration(monkeypatch, engine_name="sqlite")

    module.upgrade()

    op_mock.execute.assert_not_called()


def test_upgrade_defines_rag_embeddings_schema_and_indexes(monkeypatch):
    module, op_mock = _load_migration(monkeypatch)

    module.upgrade()

    statements = [call.args[0] for call in op_mock.execute.call_args_list]
    combined_sql = "\n".join(statements)
    assert "CREATE TABLE IF NOT EXISTS rag_embeddings" in combined_sql
    assert "embedding vector(384)" in combined_sql
    assert any(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rag_embeddings_session" in stmt
        for stmt in statements
    )
    assert any(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rag_embeddings_parent" in stmt
        for stmt in statements
    )
    assert any(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rag_embeddings_embedding_hnsw" in stmt
        for stmt in statements
    )
    assert "WITH (m = 16, ef_construction = 64)" in combined_sql


def test_upgrade_builds_indexes_concurrently_in_autocommit_blocks(monkeypatch):
    module, op_mock = _load_migration(monkeypatch)

    module.upgrade()

    # CONCURRENTLY cannot run inside a transaction block; each index build must
    # happen as the sole statement in its own autocommit block.
    assert op_mock.get_context.return_value.autocommit_block.call_count == 3
    index_statements = [
        call.args[0] for call in op_mock.execute.call_args_list if "CREATE INDEX" in call.args[0]
    ]
    assert len(index_statements) == 3
    assert all("CONCURRENTLY" in stmt for stmt in index_statements)


def test_upgrade_uses_bounded_env_hnsw_options(monkeypatch):
    monkeypatch.setenv("PGVECTOR_HNSW_M", "32")
    monkeypatch.setenv("PGVECTOR_HNSW_EF_CONSTRUCTION", "128")
    module, op_mock = _load_migration(monkeypatch)

    module.upgrade()

    assert "WITH (m = 32, ef_construction = 128)" in op_mock.execute.call_args.args[0]

    monkeypatch.setenv("PGVECTOR_HNSW_M", "999")
    monkeypatch.setenv("PGVECTOR_HNSW_EF_CONSTRUCTION", "1")
    assert module._hnsw_index_options() == "WITH (m = 64, ef_construction = 16)"


def test_downgrade_drops_rag_embeddings_objects(monkeypatch):
    module, op_mock = _load_migration(monkeypatch)

    module.downgrade()

    statements = [call.args[0] for call in op_mock.execute.call_args_list]
    assert "DROP INDEX IF EXISTS idx_rag_embeddings_embedding_hnsw" in statements
    assert "DROP INDEX IF EXISTS idx_rag_embeddings_parent" in statements
    assert "DROP INDEX IF EXISTS idx_rag_embeddings_session" in statements
    assert "DROP TABLE IF EXISTS rag_embeddings" in statements
