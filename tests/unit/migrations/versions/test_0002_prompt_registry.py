"""Tests for migrations/versions/0002_prompt_registry.py"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


class _TextClause:
    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.bound_params: dict[str, object] = {}

    def bindparams(self, **kwargs: object) -> _TextClause:
        self.bound_params.update(kwargs)
        return self


def _load_migration(monkeypatch):
    op_mock = MagicMock()
    sa_mock = MagicMock()
    sa_mock.text = lambda s: _TextClause(s)

    alembic_mod = types.ModuleType("alembic")
    alembic_mod.op = op_mock
    monkeypatch.setitem(sys.modules, "alembic", alembic_mod)
    monkeypatch.setitem(sys.modules, "alembic.op", op_mock)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sa_mock)
    monkeypatch.delitem(sys.modules, "agent.definitions", raising=False)
    monkeypatch.delitem(sys.modules, "agent", raising=False)

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


def test_module_uses_static_seed_prompt_without_agent_import(monkeypatch):
    module, _, _ = _load_migration(monkeypatch)
    source = Path("migrations/versions/0002_prompt_registry.py").read_text(encoding="utf-8")

    assert "from agent.definitions import" not in source
    assert module.MIGRATION_SEED_SYSTEM_PROMPT.startswith("Sen SİDAR'sın")
    assert "qwen2.5-coder:7b" in module.MIGRATION_SEED_SYSTEM_PROMPT


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


def test_upgrade_executes_static_seed_insert(monkeypatch):
    module, op_mock, _ = _load_migration(monkeypatch)
    module.upgrade()

    executed = op_mock.execute.call_args.args[0]
    assert "INSERT INTO prompt_registry" in executed.sql
    assert executed.bound_params["role_name"] == "system"
    assert executed.bound_params["prompt_text"] == module.MIGRATION_SEED_SYSTEM_PROMPT
    assert executed.bound_params["version"] == 1
    assert executed.bound_params["is_active"] is True


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
