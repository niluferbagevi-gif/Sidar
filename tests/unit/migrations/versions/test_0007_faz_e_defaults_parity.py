"""Tests for migrations/versions/0007_faz_e_defaults_parity.py"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _load_migration(monkeypatch):
    op_mock = MagicMock()
    batch_op_mock = MagicMock()
    op_mock.batch_alter_table.return_value.__enter__.return_value = batch_op_mock
    op_mock.batch_alter_table.return_value.__exit__.return_value = False

    alembic_mod = types.ModuleType("alembic")
    alembic_mod.op = op_mock
    monkeypatch.setitem(sys.modules, "alembic", alembic_mod)
    monkeypatch.setitem(sys.modules, "alembic.op", op_mock)

    spec = importlib.util.spec_from_file_location(
        "migrations.versions.0007_faz_e_defaults_parity",
        Path("migrations/versions/0007_faz_e_defaults_parity.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, op_mock, batch_op_mock


def test_module_metadata(monkeypatch):
    module, _, _ = _load_migration(monkeypatch)
    assert module.revision == "0007_faz_e_defaults_parity"
    assert module.down_revision == "0006_access_control_schema"
    assert module.branch_labels is None
    assert module.depends_on is None


def test_upgrade_realigns_all_nine_defaults(monkeypatch):
    module, op_mock, batch_op_mock = _load_migration(monkeypatch)

    module.upgrade()

    batched_tables = [call.args[0] for call in op_mock.batch_alter_table.call_args_list]
    assert batched_tables == [
        "marketing_campaigns",
        "marketing_campaigns",
        "marketing_campaigns",
        "content_assets",
        "operation_checklists",
        "operation_checklists",
        "coverage_tasks",
        "coverage_tasks",
        "coverage_findings",
    ]

    altered = [
        (call.args[0], call.kwargs["server_default"])
        for call in batch_op_mock.alter_column.call_args_list
    ]
    assert altered == [
        ("channel", ""),
        ("objective", ""),
        ("owner_user_id", ""),
        ("channel", ""),
        ("owner_user_id", ""),
        ("status", "pending"),
        ("requester_role", "coverage"),
        ("status", "pending_review"),
        ("severity", "medium"),
    ]


def test_downgrade_restores_previous_defaults_in_reverse_order(monkeypatch):
    module, op_mock, batch_op_mock = _load_migration(monkeypatch)

    module.downgrade()

    batched_tables = [call.args[0] for call in op_mock.batch_alter_table.call_args_list]
    assert batched_tables == [
        "coverage_findings",
        "coverage_tasks",
        "coverage_tasks",
        "operation_checklists",
        "operation_checklists",
        "content_assets",
        "marketing_campaigns",
        "marketing_campaigns",
        "marketing_campaigns",
    ]

    restored = [
        (call.args[0], call.kwargs["server_default"])
        for call in batch_op_mock.alter_column.call_args_list
    ]
    assert restored == [
        ("severity", "info"),
        ("status", "queued"),
        ("requester_role", None),
        ("status", "open"),
        ("owner_user_id", "system"),
        ("channel", "generic"),
        ("owner_user_id", "system"),
        ("objective", None),
        ("channel", None),
    ]


def test_default_changes_table_is_internally_consistent(monkeypatch):
    module, _, _ = _load_migration(monkeypatch)

    for table, column, new_default, previous_default in module._DEFAULT_CHANGES:
        assert isinstance(table, str) and table
        assert isinstance(column, str) and column
        assert new_default != previous_default
