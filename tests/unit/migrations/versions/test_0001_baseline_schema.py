"""Tests for migrations/versions/0001_baseline_schema.py"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, call, patch


def _load_migration(monkeypatch):
    """Load the migration module with mocked alembic and sqlalchemy."""
    op_mock = MagicMock()
    sa_mock = MagicMock()

    alembic_mod = types.ModuleType("alembic")
    alembic_mod.op = op_mock
    monkeypatch.setitem(sys.modules, "alembic", alembic_mod)
    monkeypatch.setitem(sys.modules, "alembic.op", op_mock)

    monkeypatch.setitem(sys.modules, "sqlalchemy", sa_mock)

    spec = importlib.util.spec_from_file_location(
        "migrations.versions.0001_baseline_schema",
        Path("migrations/versions/0001_baseline_schema.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, op_mock, sa_mock


def test_module_metadata(monkeypatch):
    module, _, _ = _load_migration(monkeypatch)
    assert module.revision == "0001_baseline_schema"
    assert module.down_revision is None
    assert module.branch_labels is None
    assert module.depends_on is None


def test_upgrade_creates_all_tables(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    created_tables = [c.args[0] for c in op_mock.create_table.call_args_list]
    assert "users" in created_tables
    assert "auth_tokens" in created_tables
    assert "user_quotas" in created_tables
    assert "provider_usage_daily" in created_tables
    assert "sessions" in created_tables
    assert "messages" in created_tables
    assert "schema_versions" in created_tables
    assert len(created_tables) == 7


def test_upgrade_creates_all_indexes(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    created_indexes = [c.args[0] for c in op_mock.create_index.call_args_list]
    assert "idx_sessions_user_id" in created_indexes
    assert "idx_messages_session_id" in created_indexes
    assert "idx_auth_tokens_user_id" in created_indexes
    assert "idx_provider_usage_daily_user_id" in created_indexes
    assert len(created_indexes) == 4


def test_downgrade_drops_all_indexes_and_tables(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.downgrade()

    dropped_indexes = [c.args[0] for c in op_mock.drop_index.call_args_list]
    assert "idx_provider_usage_daily_user_id" in dropped_indexes
    assert "idx_auth_tokens_user_id" in dropped_indexes
    assert "idx_messages_session_id" in dropped_indexes
    assert "idx_sessions_user_id" in dropped_indexes

    dropped_tables = [c.args[0] for c in op_mock.drop_table.call_args_list]
    assert "users" in dropped_tables
    assert "auth_tokens" in dropped_tables
    assert "sessions" in dropped_tables
    assert "messages" in dropped_tables
    assert "schema_versions" in dropped_tables


def test_downgrade_drops_tables_in_dependency_order(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.downgrade()

    dropped_tables = [c.args[0] for c in op_mock.drop_table.call_args_list]
    # Child tables must be dropped before parent 'users'
    assert dropped_tables.index("schema_versions") < dropped_tables.index("users")
    assert dropped_tables.index("messages") < dropped_tables.index("users")
    assert dropped_tables.index("sessions") < dropped_tables.index("users")
