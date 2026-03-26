import importlib.util
import sys
import types
from pathlib import Path


def test_agent_core_registry_get_missing_role_raises_keyerror():
    fake_agent_pkg = types.ModuleType("agent")
    fake_agent_pkg.__path__ = []
    fake_base_agent_mod = types.ModuleType("agent.base_agent")

    class _BaseAgent:
        pass

    fake_base_agent_mod.BaseAgent = _BaseAgent

    prev_agent = sys.modules.get("agent")
    prev_base = sys.modules.get("agent.base_agent")
    sys.modules["agent"] = fake_agent_pkg
    sys.modules["agent.base_agent"] = fake_base_agent_mod
    try:
        spec = importlib.util.spec_from_file_location(
            "agent_core_registry_under_test",
            Path("agent/core/registry.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        reg = mod.AgentRegistry()
        try:
            reg.get("missing")
            assert False
        except KeyError as exc:
            assert "rolü kayıtlı değil" in str(exc)
    finally:
        if prev_agent is None:
            sys.modules.pop("agent", None)
        else:
            sys.modules["agent"] = prev_agent

        if prev_base is None:
            sys.modules.pop("agent.base_agent", None)
        else:
            sys.modules["agent.base_agent"] = prev_base