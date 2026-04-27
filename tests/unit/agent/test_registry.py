"""Unit tests for AgentCatalog registry behaviors."""

from __future__ import annotations

import pytest

from agent.registry import AgentCatalog, AgentSpec, _import_builtin_roles


class _DummyAgent:
    ROLE_NAME = "tmp_dummy"

    def __init__(self, value: int = 0) -> None:
        self.value = value


def test_agent_catalog_programmatic_registration_lifecycle() -> None:
    role_name = "unit_temp_programmatic"

    class UnitTempProgrammaticAgent:
        def __init__(self, *, name: str):
            self.name = name

    AgentCatalog.unregister(role_name)
    AgentCatalog.register_type(
        role_name=role_name,
        agent_class=UnitTempProgrammaticAgent,
        capabilities=["unit_capability"],
        description="unit test role",
        version="0.0.1",
        is_builtin=False,
    )

    spec = AgentCatalog.get(role_name)
    assert spec is not None
    assert spec.role_name == role_name
    assert "unit_capability" in spec.capabilities

    created = AgentCatalog.create(role_name, name="sidar")
    assert isinstance(created, UnitTempProgrammaticAgent)
    assert created.name == "sidar"

    matches = AgentCatalog.find_by_capability("unit_capability")
    assert any(item.role_name == role_name for item in matches)

    assert AgentCatalog.unregister(role_name) is True
    assert AgentCatalog.get(role_name) is None


def test_agent_catalog_decorator_registration_exposes_metadata() -> None:
    role_name = "unit_temp_decorator"
    AgentCatalog.unregister(role_name)

    @AgentCatalog.register(
        capabilities=["decorator_capability"],
        description="decorator unit role",
        version="0.0.2",
        is_builtin=False,
    )
    class UnitTempDecoratorAgent:
        ROLE_NAME = role_name

        def __init__(self, *, value: int):
            self.value = value

    listed_roles = {spec.role_name for spec in AgentCatalog.list_all()}
    assert role_name in listed_roles

    created = AgentCatalog.create(role_name, value=7)
    assert isinstance(created, UnitTempDecoratorAgent)
    assert created.value == 7

    assert AgentCatalog.unregister(role_name) is True


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


def test_create_uses_factory_when_agent_class_is_missing() -> None:
    def _factory(*, value: int) -> dict[str, int]:
        return {"value": value}

    AgentCatalog._registry["tmp_factory"] = AgentSpec(  # type: ignore[attr-defined]
        role_name="tmp_factory",
        agent_class=None,
        capabilities=["unit_test"],
        description="factory-backed spec",
        version="1.0.0",
        is_builtin=False,
    )
    AgentCatalog._registry["tmp_factory"]._agent_factory = _factory  # type: ignore[attr-defined]

    instance = AgentCatalog.create("tmp_factory", value=7)
    assert instance == {"value": 7}

    assert AgentCatalog.unregister("tmp_factory") is True


def test_create_raises_typeerror_when_no_class_or_factory() -> None:
    AgentCatalog._registry["tmp_broken"] = AgentSpec(  # type: ignore[attr-defined]
        role_name="tmp_broken",
        agent_class=None,
        capabilities=[],
        description="missing instantiation hooks",
        version="1.0.0",
        is_builtin=False,
    )

    with pytest.raises(TypeError):
        AgentCatalog.create("tmp_broken")

    assert AgentCatalog.unregister("tmp_broken") is True


def test_unregister_returns_false_for_unknown_role() -> None:
    assert AgentCatalog.unregister("definitely_unknown_role") is False


def test_import_builtin_roles_skips_failed_module_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    imported_modules: list[str] = []

    def _fake_import_module(module_name: str):
        imported_modules.append(module_name)
        if module_name.endswith("qa_agent"):
            raise RuntimeError("simulated import failure")
        return object()

    monkeypatch.setattr("importlib.import_module", _fake_import_module)

    _import_builtin_roles()

    assert imported_modules == [
        "agent.roles.coder_agent",
        "agent.roles.researcher_agent",
        "agent.roles.reviewer_agent",
        "agent.roles.poyraz_agent",
        "agent.roles.coverage_agent",
        "agent.roles.qa_agent",
    ]
