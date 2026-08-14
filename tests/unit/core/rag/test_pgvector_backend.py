import importlib
from types import SimpleNamespace

import pytest

from core.rag.backends import pgvector as pgvector_module


def test_pgvector_failure_action_message_includes_auth_configuration_guidance(monkeypatch):
    pgvector = importlib.reload(pgvector_module)
    monkeypatch.setattr(
        pgvector,
        "postgres_failure_diagnosis",
        lambda _context, _exc: "yetki/parola doğrulaması başarısız",
    )

    message = pgvector.pgvector_failure_action_message(RuntimeError("auth failed"))

    assert "DATABASE_URL" in message
    assert "SIDAR_CONTAINER_DATABASE_URL" in message
    assert "POSTGRES_PASSWORD" in message
    assert "parola/yetki ayarlarını" in message
    assert "yetki/parola doğrulaması başarısız" in message


def test_pgvector_failure_action_message_non_auth_path(monkeypatch):
    pgvector = importlib.reload(pgvector_module)
    monkeypatch.setattr(
        pgvector,
        "postgres_failure_diagnosis",
        lambda _context, _exc: "pgvector extension missing",
    )

    message = pgvector.pgvector_failure_action_message(RuntimeError("extension missing"))

    assert message == "pgvector pasif, BM25 fallback aktif. Teşhis: pgvector extension missing."


def test_reject_if_invalid_pg_table_blocks_sql_injection_identifier(monkeypatch):
    """Keep attacker-controlled table syntax out of every pgvector SQL builder."""
    pgvector = importlib.reload(pgvector_module)
    store = SimpleNamespace(_pgvector_available=True)
    diagnostics = []
    monkeypatch.setattr(pgvector.logger, "warning", lambda message: diagnostics.append(message))

    accepted = pgvector._reject_if_invalid_pg_table(
        store,
        "x; DROP TABLE users--",
    )

    assert accepted is False
    assert store._pgvector_available is False
    assert len(diagnostics) == 1
    assert "pgvector pasif, BM25 fallback aktif" in diagnostics[0]
    assert pgvector.pgvector_runtime_status(store) == {
        "backend": "pgvector",
        "available": False,
        "degraded": True,
        "operation": "identifier_validation",
        "reason": "ValueError",
        "failure_count": 1,
    }


def test_pgvector_sql_builder_centralizes_validated_identifier_interpolation():
    pgvector = importlib.reload(pgvector_module)

    queries = pgvector._pgvector_sql("rag_embeddings")

    assert set(queries) == {"delete", "upsert", "select"}
    assert all("rag_embeddings" in query for query in queries.values())


def test_pgvector_sql_builder_rejects_malicious_identifier() -> None:
    pgvector = importlib.reload(pgvector_module)

    with pytest.raises(ValueError, match="invalid PGVECTOR_TABLE identifier"):
        pgvector._pgvector_sql("rag_embeddings; DROP TABLE users")


def test_pgvector_ddl_builder_validates_table_indexes_and_dimension() -> None:
    pgvector = importlib.reload(pgvector_module)
    statements = pgvector._pgvector_ddl("rag_embeddings", 384)

    assert "CREATE TABLE IF NOT EXISTS rag_embeddings" in statements[0]
    assert "embedding vector(384)" in statements[0]
    assert "idx_rag_embeddings_session ON rag_embeddings" in statements[1]
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        pgvector._pgvector_ddl("rag; DROP TABLE users", 384)
    with pytest.raises(ValueError, match="Invalid SQL integer literal"):
        pgvector._pgvector_ddl("rag_embeddings", -1)
