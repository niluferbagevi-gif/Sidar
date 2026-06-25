from __future__ import annotations

import types

from tests import conftest


def test_critical_sys_module_pollution_guard_detects_fake_core_db(monkeypatch) -> None:
    original = conftest.sys.modules.get("core.db", conftest._MISSING_SYS_MODULE)
    fake_core_db = types.ModuleType("core.db")
    fake_core_db.Database = object
    monkeypatch.setitem(conftest.sys.modules, "core.db", fake_core_db)

    errors = conftest._critical_sys_module_pollution_errors({"core.db": original})

    assert errors
    assert "core.db polluted" in errors[0]
    assert "UserRecord" in errors[0]


def test_critical_sys_module_pollution_guard_allows_pending_monkeypatch(monkeypatch) -> None:
    original = conftest.sys.modules.get("core.llm_client", conftest._MISSING_SYS_MODULE)
    fake_llm_client = types.ModuleType("core.llm_client")
    fake_llm_client.LLMClient = object
    monkeypatch.setitem(conftest.sys.modules, "core.llm_client", fake_llm_client)

    errors = conftest._critical_sys_module_pollution_errors(
        {"core.llm_client": original}, allow_pending_monkeypatch=True
    )

    assert errors == []


def test_sensitive_sys_modules_excludes_torch_c_extension_state() -> None:
    assert "torch" not in conftest._SENSITIVE_SYS_MODULES
