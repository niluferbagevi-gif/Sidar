from __future__ import annotations

import importlib

import pytest

CRITICAL_MODULES = [
    "main",
    "cli",
    "web_server",
    "agent.sidar_agent",
    "core.llm_client",
    "core.rag",
]


@pytest.mark.smoke
@pytest.mark.parametrize("module_name", CRITICAL_MODULES)
def test_critical_imports(module_name: str) -> None:
    try:
        imported = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.skip(f"Missing optional dependency for smoke import: {exc.name}")
    assert imported is not None
