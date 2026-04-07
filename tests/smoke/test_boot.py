"""Smoke tests for application boot sanity."""

from agent.registry import AgentCatalog


def test_boot_agent_catalog_api_available() -> None:
    """Boot sonrası AgentCatalog API'sinin çalıştığını doğrular."""
    specs = AgentCatalog.list_all()
    assert isinstance(specs, list)


def test_boot_agent_catalog_unknown_role_returns_none() -> None:
    """Kayıtlı olmayan rol sorgusunda None dönüldüğünü doğrular."""
    assert AgentCatalog.get("__missing_role__") is None
