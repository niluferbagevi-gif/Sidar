"""Tests for migrations/versions/0006_access_control_schema.py"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import sqlalchemy as sa


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

    def get_table_names(self):
        return list(self._tables)

    def get_columns(self, table_name: str):
        if table_name != "users":
            return []
        return [{"name": name} for name in self._user_columns]

    def get_indexes(self, table_name: str):
        if table_name != "access_policies":
            return []
        return [{"name": name} for name in self._indexes]


def _load_migration(monkeypatch, inspector: _Inspector | None = None):
    op_mock = MagicMock()
    op_mock.get_bind.return_value = SimpleNamespace()
    monkeypatch.setattr(sa, "inspect", lambda _bind: inspector or _Inspector())

    alembic_mod = types.ModuleType("alembic")
    alembic_mod.op = op_mock
    monkeypatch.setitem(sys.modules, "alembic", alembic_mod)
    monkeypatch.setitem(sys.modules, "alembic.op", op_mock)

    spec = importlib.util.spec_from_file_location(
        "migrations.versions.0006_access_control_schema",
        Path("migrations/versions/0006_access_control_schema.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, op_mock


def test_module_metadata(monkeypatch):
    module, _ = _load_migration(monkeypatch)

    assert module.revision == "0006_access_control_schema"
    assert module.down_revision == "0005_pgvector_hnsw_index"
    assert module.branch_labels is None
    assert module.depends_on is None


def test_upgrade_adds_tenant_and_access_policies(monkeypatch):
    module, op_mock = _load_migration(monkeypatch)

    module.upgrade()

    op_mock.add_column.assert_called_once()
    assert op_mock.add_column.call_args.args[0] == "users"
    created_tables = [call.args[0] for call in op_mock.create_table.call_args_list]
    assert "access_policies" in created_tables
    created_indexes = [call.args[0] for call in op_mock.create_index.call_args_list]
    assert "idx_access_policies_user_tenant" in created_indexes


def test_upgrade_uses_backend_aware_uuid_fk(monkeypatch):
    module, op_mock = _load_migration(monkeypatch)

    module.upgrade()

    access_call = next(
        call for call in op_mock.create_table.call_args_list if call.args[0] == "access_policies"
    )
    user_id_column = next(column for column in access_call.args[1:] if column.name == "user_id")
    assert isinstance(user_id_column.type, module.SidarUUID)


def test_upgrade_skips_legacy_objects_when_present(monkeypatch):
    module, op_mock = _load_migration(
        monkeypatch,
        inspector=_Inspector(
            tables={"users", "access_policies"},
            user_columns={"id", "username", "tenant_id"},
            indexes={"idx_access_policies_user_tenant"},
        ),
    )

    module.upgrade()

    op_mock.add_column.assert_not_called()
    op_mock.create_table.assert_not_called()
    op_mock.create_index.assert_not_called()


def test_downgrade_removes_access_policies_and_tenant(monkeypatch):
    module, op_mock = _load_migration(monkeypatch)

    module.downgrade()

    op_mock.drop_index.assert_called_once_with(
        "idx_access_policies_user_tenant", table_name="access_policies"
    )
    op_mock.drop_table.assert_called_once_with("access_policies")
    op_mock.drop_column.assert_called_once_with("users", "tenant_id")
