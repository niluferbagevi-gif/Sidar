"""Tests for migrations/versions/0002_prompt_registry.py"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


def _load_migration(monkeypatch, system_prompt: str = "TEST_SYSTEM_PROMPT"):
    op_mock = MagicMock()
    sa_mock = MagicMock()
    sa_mock.text = lambda s: MagicMock(bindparams=MagicMock(return_value=MagicMock()))

    alembic_mod = types.ModuleType("alembic")
    alembic_mod.op = op_mock
    monkeypatch.setitem(sys.modules, "alembic", alembic_mod)
    monkeypatch.setitem(sys.modules, "alembic.op", op_mock)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sa_mock)

    # Mock agent.definitions so we can inject SIDAR_SYSTEM_PROMPT
    definitions_mod = types.ModuleType("agent.definitions")
    definitions_mod.SIDAR_SYSTEM_PROMPT = system_prompt
    agent_mod = types.ModuleType("agent")
    agent_mod.definitions = definitions_mod
    monkeypatch.setitem(sys.modules, "agent", agent_mod)
    monkeypatch.setitem(sys.modules, "agent.definitions", definitions_mod)

    spec = importlib.util.spec_from_file_location(
        "migrations.versions.0002_prompt_registry",
        Path("migrations/versions/0002_prompt_registry.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, op_mock, sa_mock


def test_module_metadata(monkeypatch):
    module, _, _ = _load_migration(monkeypatch)
    assert module.revision == "0002_prompt_registry"
    assert module.down_revision == "0001_baseline_schema"
    assert module.branch_labels is None
    assert module.depends_on is None


def test_upgrade_creates_prompt_registry_table(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    created_tables = [c.args[0] for c in op_mock.create_table.call_args_list]
    assert "prompt_registry" in created_tables


def test_upgrade_creates_index(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    created_indexes = [c.args[0] for c in op_mock.create_index.call_args_list]
    assert "idx_prompt_registry_role_active" in created_indexes


def test_upgrade_executes_seed_insert(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    assert op_mock.execute.called, "upgrade() must execute the seed INSERT"


def test_downgrade_drops_index_and_table(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.downgrade()

    dropped_indexes = [c.args[0] for c in op_mock.drop_index.call_args_list]
    assert "idx_prompt_registry_role_active" in dropped_indexes

    dropped_tables = [c.args[0] for c in op_mock.drop_table.call_args_list]
    assert "prompt_registry" in dropped_tables


def test_downgrade_drops_index_before_table(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    call_order = []
    op_mock.drop_index.side_effect = lambda *a, **kw: call_order.append(("drop_index", a[0]))
    op_mock.drop_table.side_effect = lambda *a, **kw: call_order.append(("drop_table", a[0]))

    module.downgrade()

    types_order = [c[0] for c in call_order]
    assert types_order[0] == "drop_index"
    assert types_order[-1] == "drop_table"
