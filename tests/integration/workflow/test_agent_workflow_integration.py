import pytest

from agent.registry import AgentCatalog


@pytest.mark.integration
def test_agent_catalog_programmatic_registration_lifecycle() -> None:
    role_name = "integration_temp_programmatic"

    class IntegrationTempProgrammaticAgent:
        def __init__(self, *, name: str):
            self.name = name

    AgentCatalog.unregister(role_name)
    AgentCatalog.register_type(
        role_name=role_name,
        agent_class=IntegrationTempProgrammaticAgent,
        capabilities=["integration_capability"],
        description="integration test role",
        version="0.0.1",
        is_builtin=False,
    )

    spec = AgentCatalog.get(role_name)
    assert spec is not None
    assert spec.role_name == role_name
    assert "integration_capability" in spec.capabilities

    created = AgentCatalog.create(role_name, name="sidar")
    assert isinstance(created, IntegrationTempProgrammaticAgent)
    assert created.name == "sidar"

    matches = AgentCatalog.find_by_capability("integration_capability")
    assert any(item.role_name == role_name for item in matches)

    assert AgentCatalog.unregister(role_name) is True
    assert AgentCatalog.get(role_name) is None


@pytest.mark.integration
def test_agent_catalog_decorator_registration_exposes_metadata() -> None:
    role_name = "integration_temp_decorator"
    AgentCatalog.unregister(role_name)

    @AgentCatalog.register(
        capabilities=["decorator_capability"],
        description="decorator integration role",
        version="0.0.2",
        is_builtin=False,
    )
    class IntegrationTempDecoratorAgent:
        ROLE_NAME = role_name

        def __init__(self, *, value: int):
            self.value = value

    listed_roles = {spec.role_name for spec in AgentCatalog.list_all()}
    assert role_name in listed_roles

    created = AgentCatalog.create(role_name, value=7)
    assert isinstance(created, IntegrationTempDecoratorAgent)
    assert created.value == 7

    assert AgentCatalog.unregister(role_name) is True
