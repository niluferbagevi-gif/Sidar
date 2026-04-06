"""Tests for migrations/versions/0003_audit_trail.py"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _load_migration(monkeypatch):
    op_mock = MagicMock()
    sa_mock = MagicMock()

    alembic_mod = types.ModuleType("alembic")
    alembic_mod.op = op_mock
    monkeypatch.setitem(sys.modules, "alembic", alembic_mod)
    monkeypatch.setitem(sys.modules, "alembic.op", op_mock)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sa_mock)

    spec = importlib.util.spec_from_file_location(
        "migrations.versions.0003_audit_trail",
        Path("migrations/versions/0003_audit_trail.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, op_mock, sa_mock


def test_module_metadata(monkeypatch):
    module, _, _ = _load_migration(monkeypatch)
    assert module.revision == "0003_audit_trail"
    assert module.down_revision == "0002_prompt_registry"
    assert module.branch_labels is None
    assert module.depends_on is None


def test_upgrade_creates_audit_logs_table(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    created_tables = [c.args[0] for c in op_mock.create_table.call_args_list]
    assert "audit_logs" in created_tables
    assert len(created_tables) == 1


def test_upgrade_creates_two_indexes(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    created_indexes = [c.args[0] for c in op_mock.create_index.call_args_list]
    assert "idx_audit_logs_user_timestamp" in created_indexes
    assert "idx_audit_logs_timestamp" in created_indexes
    assert len(created_indexes) == 2


def test_downgrade_drops_indexes_then_table(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    call_order = []
    op_mock.drop_index.side_effect = lambda *a, **kw: call_order.append(("drop_index", a[0]))
    op_mock.drop_table.side_effect = lambda *a, **kw: call_order.append(("drop_table", a[0]))

    module.downgrade()

    names = [c[1] for c in call_order]
    assert "idx_audit_logs_timestamp" in names
    assert "idx_audit_logs_user_timestamp" in names
    assert "audit_logs" in names
    # indexes before table
    assert call_order[-1] == ("drop_table", "audit_logs")


def test_downgrade_drops_both_indexes(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.downgrade()

    dropped_indexes = [c.args[0] for c in op_mock.drop_index.call_args_list]
    assert "idx_audit_logs_timestamp" in dropped_indexes
    assert "idx_audit_logs_user_timestamp" in dropped_indexes
