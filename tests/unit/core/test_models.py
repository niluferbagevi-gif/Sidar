"""Tests for SQLAlchemy schema metadata models."""

from __future__ import annotations

import uuid

from sqlalchemy.dialects import postgresql, sqlite

from core.models import Base, PGVector384, SidarUUID


def test_metadata_exposes_expected_tables_for_alembic_autogenerate() -> None:
    expected = {
        "users",
        "sessions",
        "messages",
        "prompt_registry",
        "audit_logs",
        "marketing_campaigns",
        "coverage_tasks",
        "rag_embeddings",
        "access_policies",
    }

    assert expected.issubset(set(Base.metadata.tables))


def test_sidar_uuid_uses_native_postgresql_and_sqlite_fallback() -> None:
    uuid_type = SidarUUID()

    pg_impl = uuid_type.load_dialect_impl(postgresql.dialect())
    sqlite_impl = uuid_type.load_dialect_impl(sqlite.dialect())

    assert pg_impl.python_type is uuid.UUID
    assert sqlite_impl.length == 36


def test_sidar_uuid_bind_and_result_values_are_portable() -> None:
    value = "12345678-1234-5678-1234-567812345678"
    uuid_type = SidarUUID()

    assert uuid_type.process_bind_param(value, postgresql.dialect()) == uuid.UUID(value)
    assert uuid_type.process_bind_param(value, sqlite.dialect()) == value
    assert uuid_type.process_result_value(uuid.UUID(value), postgresql.dialect()) == value


def test_pgvector_metadata_type_has_expected_column_spec() -> None:
    assert PGVector384().get_col_spec() == "vector(384)"
