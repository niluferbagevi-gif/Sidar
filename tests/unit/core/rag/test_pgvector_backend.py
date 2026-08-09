import importlib
from types import SimpleNamespace

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
