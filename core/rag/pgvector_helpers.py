"""Small pgvector helper facade functions used by RAG orchestration."""

from __future__ import annotations

from collections.abc import Callable

from core.db import postgres_failure_diagnosis
from core.rag.backends import pgvector as pgvector_backend


def is_valid_pgvector_identifier(identifier: str) -> bool:
    """Return True for unquoted PostgreSQL identifiers safe to embed in DDL."""
    return pgvector_backend.is_valid_pgvector_identifier(identifier)


def pgvector_failure_action_message(
    exc: BaseException,
    diagnosis_func: Callable[[str, BaseException | None], str] = postgres_failure_diagnosis,
) -> str:
    """Return a single-line pgvector fallback message using shared DB diagnostics."""
    diagnosis = diagnosis_func("pgvector backend başlatılamadı", exc)
    if "yetki/parola" in diagnosis:
        return (
            "pgvector pasif, BM25 fallback aktif edildi. DATABASE_URL, "
            "SIDAR_CONTAINER_DATABASE_URL ve POSTGRES_PASSWORD değerleriyle parola/yetki "
            f"ayarlarını kontrol edin. Teşhis: {diagnosis}."
        )
    return f"pgvector pasif, BM25 fallback aktif. Teşhis: {diagnosis}."
