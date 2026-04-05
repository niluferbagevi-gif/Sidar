"""Unit tests for AgentCatalog registry behaviors."""

from __future__ import annotations

import pytest

from agent.registry import AgentCatalog


class _DummyAgent:
    ROLE_NAME = "tmp_dummy"

    def __init__(self, value: int = 0) -> None:
        self.value = value


def test_register_decorator_populates_catalog_and_capability_index() -> None:
    @AgentCatalog.register(
        capabilities=["unit_test_capability"],
        description="decorator registration test",
        version="1.0.0",
        is_builtin=False,
    )
    class _DecoratedAgent:  # noqa: N801 - local test class name
        ROLE_NAME = "tmp_decorated"

    spec = AgentCatalog.get("tmp_decorated")
    assert spec is not None
    assert spec.description == "decorator registration test"

    matches = AgentCatalog.find_by_capability("unit_test_capability")
    assert any(item.role_name == "tmp_decorated" for item in matches)

    assert AgentCatalog.unregister("tmp_decorated") is True


def test_register_type_create_and_unregister_roundtrip() -> None:
    AgentCatalog.register_type(
        role_name="tmp_dummy",
        agent_class=_DummyAgent,
        capabilities=["unit_test"],
        description="temporary role for test",
        version="1.0.0",
        is_builtin=False,
    )

    instance = AgentCatalog.create("tmp_dummy", value=42)
    assert isinstance(instance, _DummyAgent)
    assert instance.value == 42

    assert AgentCatalog.unregister("tmp_dummy") is True
    assert AgentCatalog.get("tmp_dummy") is None


def test_create_unknown_role_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        AgentCatalog.create("definitely_missing_role")
