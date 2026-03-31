from __future__ import annotations

import importlib
import pathlib
import sys
import types


def test_agent_core_lazy_getattr_and_all(monkeypatch):
    project_root = pathlib.Path(__file__).resolve().parents[1]
    fake_agent_pkg = types.ModuleType("agent")
    fake_agent_pkg.__path__ = [str(project_root / "agent")]
    fake_agent_pkg.__package__ = "agent"
    monkeypatch.setitem(sys.modules, "agent", fake_agent_pkg)
    sys.modules.pop("agent.core", None)

    import agent.core as core_pkg

    fake_memory_hub = types.ModuleType("agent.core.memory_hub")
    class MemoryHub:  # noqa: D401
        pass
    fake_memory_hub.MemoryHub = MemoryHub

    fake_registry = types.ModuleType("agent.core.registry")
    class AgentRegistry:  # noqa: D401
        pass
    fake_registry.AgentRegistry = AgentRegistry

    fake_supervisor = types.ModuleType("agent.core.supervisor")
    class SupervisorAgent:  # noqa: D401
        pass
    fake_supervisor.SupervisorAgent = SupervisorAgent

    monkeypatch.setitem(sys.modules, "agent.core.memory_hub", fake_memory_hub)
    monkeypatch.setitem(sys.modules, "agent.core.registry", fake_registry)
    monkeypatch.setitem(sys.modules, "agent.core.supervisor", fake_supervisor)

    assert "MemoryHub" in core_pkg.__all__
    assert core_pkg.MemoryHub is MemoryHub
    assert core_pkg.AgentRegistry is AgentRegistry
    assert core_pkg.SupervisorAgent is SupervisorAgent
    try:
        _ = core_pkg.UnknownSymbol
        raised = False
    except AttributeError as exc:
        raised = True
        assert str(exc) == "UnknownSymbol"
    assert raised is True



def test_agent_roles_exports_expected_classes(monkeypatch):
    project_root = pathlib.Path(__file__).resolve().parents[1]
    fake_agent_pkg = types.ModuleType("agent")
    fake_agent_pkg.__path__ = [str(project_root / "agent")]
    fake_agent_pkg.__package__ = "agent"
    monkeypatch.setitem(sys.modules, "agent", fake_agent_pkg)

    role_map = {
        "agent.roles.coder_agent": "CoderAgent",
        "agent.roles.researcher_agent": "ResearcherAgent",
        "agent.roles.reviewer_agent": "ReviewerAgent",
        "agent.roles.poyraz_agent": "PoyrazAgent",
        "agent.roles.qa_agent": "QAAgent",
        "agent.roles.coverage_agent": "CoverageAgent",
    }

    for module_name, class_name in role_map.items():
        fake_module = types.ModuleType(module_name)
        fake_class = type(class_name, (), {})
        setattr(fake_module, class_name, fake_class)
        monkeypatch.setitem(sys.modules, module_name, fake_module)

    sys.modules.pop("agent.roles", None)
    roles_pkg = importlib.import_module("agent.roles")

    for class_name in role_map.values():
        assert class_name in roles_pkg.__all__
        assert getattr(roles_pkg, class_name).__name__ == class_name
