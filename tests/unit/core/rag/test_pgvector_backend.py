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
        "detail": "invalid PGVECTOR_TABLE; expected pattern ^[A-Za-z_][A-Za-z0-9_]*$",
        "failure_count": 1,
    }


def test_mark_pgvector_degraded_redacts_credentials_from_runtime_status_detail():
    """The detail surfaced via pgvector_runtime_status must never leak secrets."""
    pgvector = importlib.reload(pgvector_module)
    store = SimpleNamespace(_pgvector_available=True)

    pgvector._mark_pgvector_degraded(
        store,
        "initialization",
        RuntimeError(
            "connection to postgresql://sidar:super-secret-pw@localhost:5432/sidar failed"
        ),
    )

    status = pgvector.pgvector_runtime_status(store)
    assert status["operation"] == "initialization"
    assert status["reason"] == "RuntimeError"
    assert "super-secret-pw" not in status["detail"]
    assert "postgresql://sidar:***@localhost:5432/sidar" in status["detail"]


def test_init_pgvector_success_clears_previous_degraded_detail(monkeypatch):
    """A later successful init must not leave a stale failure detail behind."""
    pgvector = importlib.reload(pgvector_module)
    store = SimpleNamespace(
        cfg=SimpleNamespace(DATABASE_URL="postgresql://sidar:pw@localhost/sidar"),
        _pg_table="rag_embeddings",
        _pg_embedding_dim=384,
        _pg_embedding_model_name="model",
        _pgvector_degraded_detail="stale detail from a previous failure",
        _check_import=lambda _name: True,
        _log_backend_init_status_once=lambda *_a, **_kw: None,
    )

    class _FakeConn:
        def execute(self, *_a, **_kw):
            return None

    class _FakeEngineCtx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, *_exc):
            return False

    class _FakeEngine:
        def begin(self):
            return _FakeEngineCtx()

    store._require_pg_engine = lambda: _FakeEngine()
    monkeypatch.setattr(pgvector, "get_sentence_transformer_model", lambda *_a, **_kw: object())

    class _FakeSqlAlchemyModule:
        @staticmethod
        def create_engine(*_a, **_kw):
            return _FakeEngine()

        @staticmethod
        def text(sql):
            return sql

    monkeypatch.setitem(__import__("sys").modules, "sqlalchemy", _FakeSqlAlchemyModule())

    pgvector.init_pgvector(store)

    assert store._pgvector_available is True
    assert store._pgvector_degraded_detail == ""


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


def test_describe_unclassified_pgvector_failure_uses_redacted_exception_summary():
    pgvector = importlib.reload(pgvector_module)
    unclassified = pgvector.UNCLASSIFIED_POSTGRES_DIAGNOSIS

    assert pgvector.describe_unclassified_pgvector_failure("known", OSError("x")) == "known"
    assert pgvector.describe_unclassified_pgvector_failure(unclassified, OSError()) == "OSError"
    summary = pgvector.describe_unclassified_pgvector_failure(
        unclassified, OSError("postgresql://sidar:secret@db/x unreachable\nsecond line")
    )
    assert summary.startswith("OSError: ")
    assert "secret" not in summary
    assert "second line" not in summary
