"""Tests for migrations/versions/0004_faz_e_tables.py"""

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
        "migrations.versions.0004_faz_e_tables",
        Path("migrations/versions/0004_faz_e_tables.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, op_mock, sa_mock


def test_module_metadata(monkeypatch):
    module, _, _ = _load_migration(monkeypatch)
    assert module.revision == "0004_faz_e_tables"
    assert module.down_revision == "0003_audit_trail"
    assert module.branch_labels is None
    assert module.depends_on is None


def test_upgrade_creates_all_five_tables(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    created_tables = [c.args[0] for c in op_mock.create_table.call_args_list]
    assert "marketing_campaigns" in created_tables
    assert "content_assets" in created_tables
    assert "operation_checklists" in created_tables
    assert "coverage_tasks" in created_tables
    assert "coverage_findings" in created_tables
    assert len(created_tables) == 5


def test_upgrade_creates_all_five_indexes(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    created_indexes = [c.args[0] for c in op_mock.create_index.call_args_list]
    assert "idx_marketing_campaigns_tenant_status" in created_indexes
    assert "idx_content_assets_campaign_tenant" in created_indexes
    assert "idx_operation_checklists_campaign_tenant" in created_indexes
    assert "idx_coverage_tasks_tenant_status" in created_indexes
    assert "idx_coverage_findings_task" in created_indexes
    assert len(created_indexes) == 5


def test_downgrade_drops_child_tables_first(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.downgrade()

    dropped_tables = [c.args[0] for c in op_mock.drop_table.call_args_list]
    # coverage_findings depends on coverage_tasks
    assert dropped_tables.index("coverage_findings") < dropped_tables.index("coverage_tasks")
    # content_assets and operation_checklists depend on marketing_campaigns
    assert dropped_tables.index("content_assets") < dropped_tables.index("marketing_campaigns")
    assert dropped_tables.index("operation_checklists") < dropped_tables.index("marketing_campaigns")


def test_downgrade_drops_all_indexes_and_tables(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.downgrade()

    dropped_indexes = [c.args[0] for c in op_mock.drop_index.call_args_list]
    assert "idx_coverage_findings_task" in dropped_indexes
    assert "idx_coverage_tasks_tenant_status" in dropped_indexes
    assert "idx_operation_checklists_campaign_tenant" in dropped_indexes
    assert "idx_content_assets_campaign_tenant" in dropped_indexes
    assert "idx_marketing_campaigns_tenant_status" in dropped_indexes

    dropped_tables = [c.args[0] for c in op_mock.drop_table.call_args_list]
    assert len(dropped_tables) == 5
