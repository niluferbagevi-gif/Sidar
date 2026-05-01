import pytest

from agent.registry import AgentCatalog


@pytest.mark.integration
def test_builtin_roles_are_discoverable_by_capability() -> None:
    coder_roles = {spec.role_name for spec in AgentCatalog.find_by_capability("code_generation")}
    reviewer_roles = {spec.role_name for spec in AgentCatalog.find_by_capability("code_review")}
    coverage_roles = {spec.role_name for spec in AgentCatalog.find_by_capability("coverage_analysis")}
    marketing_roles = {spec.role_name for spec in AgentCatalog.find_by_capability("marketing_strategy")}

    assert "coder" in coder_roles
    assert "reviewer" in reviewer_roles
    assert "coverage" in coverage_roles
    assert "poyraz" in marketing_roles


@pytest.mark.integration
def test_builtin_role_set_contains_multi_agent_backbone() -> None:
    roles = {spec.role_name for spec in AgentCatalog.list_all()}
    assert {"coder", "reviewer", "coverage", "poyraz", "qa", "researcher"}.issubset(roles)
