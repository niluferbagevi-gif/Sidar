import importlib.util
import sys
import types
from pathlib import Path


def _load_registry_module(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path("agent/registry.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_agent_registry_register_create_find_and_unregister(monkeypatch):
    class _BaseAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _Coder(_BaseAgent):
        pass

    class _Researcher(_BaseAgent):
        pass

    class _Reviewer(_BaseAgent):
        pass

    monkeypatch.setitem(sys.modules, "agent.roles.coder_agent", types.SimpleNamespace(CoderAgent=_Coder))
    monkeypatch.setitem(sys.modules, "agent.roles.researcher_agent", types.SimpleNamespace(ResearcherAgent=_Researcher))
    monkeypatch.setitem(sys.modules, "agent.roles.reviewer_agent", types.SimpleNamespace(ReviewerAgent=_Reviewer))

    mod = _load_registry_module("agent_registry_under_test_full")

    @mod.AgentRegistry.register(capabilities=["math"], description="sum")
    class MathAgent(_BaseAgent):
        ROLE_NAME = "math"

    created = mod.AgentRegistry.create("math", cfg="x")
    assert isinstance(created, MathAgent)
    assert created.kwargs["cfg"] == "x"

    by_cap = mod.AgentRegistry.find_by_capability("math")
    assert any(spec.role_name == "math" for spec in by_cap)

    listed = [spec.role_name for spec in mod.AgentRegistry.list_all()]
    assert "math" in listed
    assert "coder" in listed

    assert mod.AgentRegistry.unregister("math") is True
    assert mod.AgentRegistry.unregister("math") is False


def test_agent_registry_create_missing_role_raises_key_error(monkeypatch):
    for name in ("agent.roles.coder_agent", "agent.roles.researcher_agent", "agent.roles.reviewer_agent"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    mod = _load_registry_module("agent_registry_under_test_empty")

    try:
        mod.AgentRegistry.create("does_not_exist")
        assert False, "KeyError bekleniyordu"
    except KeyError as exc:
        assert "does_not_exist" in str(exc)