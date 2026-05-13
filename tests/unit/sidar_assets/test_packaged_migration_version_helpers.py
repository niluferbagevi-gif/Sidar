"""Focused tests for packaged sidar_assets Alembic migration helper branches."""

from __future__ import annotations

import importlib.util
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGED_VERSIONS = PROJECT_ROOT / "sidar_assets" / "migrations" / "versions"


class _Inspector:
    def __init__(
        self,
        *,
        tables: set[str] | None = None,
        user_columns: set[str] | None = None,
        indexes: set[str] | None = None,
    ) -> None:
        self._tables = tables or {"users"}
        self._user_columns = user_columns or {"id", "username"}
        self._indexes = indexes or set()

    def get_table_names(self) -> list[str]:
        return list(self._tables)

    def get_columns(self, table_name: str) -> list[dict[str, str]]:
        if table_name != "users":
            return []
        return [{"name": name} for name in self._user_columns]

    def get_indexes(self, table_name: str) -> list[dict[str, str]]:
        if table_name != "access_policies":
            return []
        return [{"name": name} for name in self._indexes]


def _load_packaged_migration(monkeypatch, filename: str, *, op_mock: MagicMock | None = None):
    op_mock = op_mock or MagicMock()
    alembic_mod = types.ModuleType("alembic")
    alembic_mod.op = op_mock
    monkeypatch.setitem(sys.modules, "alembic", alembic_mod)
    monkeypatch.setitem(sys.modules, "alembic.op", op_mock)

    module_name = f"packaged_migrations.{filename.removesuffix('.py')}"
    spec = importlib.util.spec_from_file_location(module_name, PACKAGED_VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, op_mock


def _assert_sidar_uuid_handles_sqlite_and_postgresql(module) -> None:
    sqlite_dialect = sqlite.dialect()
    postgresql_dialect = postgresql.dialect()
    value = uuid.UUID("11111111-1111-1111-1111-111111111111")

    assert module.UUID_TYPE.process_bind_param(None, sqlite_dialect) is None
    assert module.UUID_TYPE.process_bind_param(value, sqlite_dialect) == str(value)
    assert module.UUID_TYPE.process_bind_param(str(value), postgresql_dialect) == value
    assert module.UUID_TYPE.process_result_value(None, sqlite_dialect) is None
    assert module.UUID_TYPE.process_result_value(value, sqlite_dialect) == str(value)

    sqlite_impl = module.UUID_TYPE.load_dialect_impl(sqlite_dialect)
    postgresql_impl = module.UUID_TYPE.load_dialect_impl(postgresql_dialect)

    assert isinstance(sqlite_impl, sa.String)
    assert sqlite_impl.length == 36
    assert "UUID" in postgresql_impl.__class__.__name__.upper()


def test_packaged_baseline_uuid_type_handles_backend_specific_values(monkeypatch) -> None:
    module, _ = _load_packaged_migration(monkeypatch, "0001_baseline_schema.py")

    _assert_sidar_uuid_handles_sqlite_and_postgresql(module)


def test_packaged_access_control_uuid_type_handles_backend_specific_values(monkeypatch) -> None:
    module, _ = _load_packaged_migration(monkeypatch, "0006_access_control_schema.py")

    _assert_sidar_uuid_handles_sqlite_and_postgresql(module)


def test_packaged_pgvector_upgrade_skips_non_postgresql(monkeypatch) -> None:
    op_mock = MagicMock()
    op_mock.get_bind.return_value = SimpleNamespace(engine=SimpleNamespace(name="sqlite"))
    module, op_mock = _load_packaged_migration(
        monkeypatch, "0005_pgvector_hnsw_index.py", op_mock=op_mock
    )

    module.upgrade()

    op_mock.execute.assert_not_called()


def test_packaged_pgvector_upgrade_emits_postgresql_vector_schema(monkeypatch) -> None:
    op_mock = MagicMock()
    op_mock.get_bind.return_value = SimpleNamespace(engine=SimpleNamespace(name="postgresql"))
    module, op_mock = _load_packaged_migration(
        monkeypatch, "0005_pgvector_hnsw_index.py", op_mock=op_mock
    )

    module.upgrade()

    sql = op_mock.execute.call_args.args[0]
    assert "CREATE TABLE IF NOT EXISTS rag_embeddings" in sql
    assert "embedding vector(384)" in sql
    assert "idx_rag_embeddings_embedding_hnsw" in sql


def test_packaged_pgvector_downgrade_skips_non_postgresql(monkeypatch) -> None:
    op_mock = MagicMock()
    op_mock.get_bind.return_value = SimpleNamespace(engine=SimpleNamespace(name="sqlite"))
    module, op_mock = _load_packaged_migration(
        monkeypatch, "0005_pgvector_hnsw_index.py", op_mock=op_mock
    )

    module.downgrade()

    op_mock.execute.assert_not_called()


def test_packaged_pgvector_downgrade_drops_postgresql_vector_objects(monkeypatch) -> None:
    op_mock = MagicMock()
    op_mock.get_bind.return_value = SimpleNamespace(engine=SimpleNamespace(name="postgresql"))
    module, op_mock = _load_packaged_migration(
        monkeypatch, "0005_pgvector_hnsw_index.py", op_mock=op_mock
    )

    module.downgrade()

    statements = [call.args[0] for call in op_mock.execute.call_args_list]
    assert statements == [
        "DROP INDEX IF EXISTS idx_rag_embeddings_embedding_hnsw",
        "DROP INDEX IF EXISTS idx_rag_embeddings_parent",
        "DROP INDEX IF EXISTS idx_rag_embeddings_session",
        "DROP TABLE IF EXISTS rag_embeddings",
    ]


def test_packaged_access_control_upgrade_reuses_existing_table_and_adds_missing_index(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sa,
        "inspect",
        lambda _bind: _Inspector(tables={"users", "access_policies"}, indexes=set()),
    )
    module, op_mock = _load_packaged_migration(monkeypatch, "0006_access_control_schema.py")

    module.upgrade()

    op_mock.add_column.assert_called_once()
    op_mock.create_table.assert_not_called()
    op_mock.create_index.assert_called_once_with(
        "idx_access_policies_user_tenant",
        "access_policies",
        ["user_id", "tenant_id", "resource_type", "action"],
    )


def test_packaged_access_control_upgrade_skips_existing_column_table_and_index(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sa,
        "inspect",
        lambda _bind: _Inspector(
            tables={"users", "access_policies"},
            user_columns={"id", "username", "tenant_id"},
            indexes={"idx_access_policies_user_tenant"},
        ),
    )
    module, op_mock = _load_packaged_migration(monkeypatch, "0006_access_control_schema.py")

    module.upgrade()

    op_mock.add_column.assert_not_called()
    op_mock.create_table.assert_not_called()
    op_mock.create_index.assert_not_called()
