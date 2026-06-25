import importlib

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
