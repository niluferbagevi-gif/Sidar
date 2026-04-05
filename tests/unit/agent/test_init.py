import importlib
import sys
from types import ModuleType

import pytest


@pytest.fixture
def fresh_agent_module():
    sys.modules.pop("agent", None)
    module = importlib.import_module("agent")
    yield module
    sys.modules.pop("agent", None)


def test_getattr_loads_lazy_class_exports_with_stubbed_modules(fresh_agent_module):
    agent_mod = fresh_agent_module

    fake_sidar = ModuleType("agent.sidar_agent")
    fake_auto = ModuleType("agent.auto_handle")

    class SidarAgent:
        pass

    class AutoHandle:
        pass

    fake_sidar.SidarAgent = SidarAgent
    fake_auto.AutoHandle = AutoHandle

    sys.modules["agent.sidar_agent"] = fake_sidar
    sys.modules["agent.auto_handle"] = fake_auto

    sidar_cls = agent_mod.__getattr__("SidarAgent")
    auto_handle_cls = agent_mod.__getattr__("AutoHandle")
    auto_handler_cls = agent_mod.__getattr__("AutoHandler")

    assert sidar_cls is SidarAgent
    assert auto_handle_cls is AutoHandle
    assert auto_handler_cls is AutoHandle


def test_getattr_loads_lazy_module_exports_via_import_module(monkeypatch, fresh_agent_module):
    agent_mod = fresh_agent_module

    fake_roles = ModuleType("agent.roles")
    fake_registry = ModuleType("agent.registry")

    def fake_import_module(name, package):
        if (name, package) == (".roles", "agent"):
            return fake_roles
        if (name, package) == (".registry", "agent"):
            return fake_registry
        raise AssertionError(f"unexpected import call: {(name, package)}")

    monkeypatch.setattr(agent_mod, "import_module", fake_import_module)

    assert agent_mod.__getattr__("roles") is fake_roles
    assert agent_mod.__getattr__("registry") is fake_registry


def test_getattr_loads_definition_constants(fresh_agent_module):
    agent_mod = fresh_agent_module

    system_prompt = agent_mod.__getattr__("SIDAR_SYSTEM_PROMPT")
    keys = agent_mod.__getattr__("SIDAR_KEYS")
    wake_words = agent_mod.__getattr__("SIDAR_WAKE_WORDS")

    assert isinstance(system_prompt, str)
    assert isinstance(keys, list)
    assert isinstance(wake_words, list)
    assert keys
    assert wake_words


def test_getattr_unknown_name_raises_attribute_error(fresh_agent_module):
    agent_mod = fresh_agent_module

    with pytest.raises(AttributeError, match="UNKNOWN_EXPORT"):
        agent_mod.__getattr__("UNKNOWN_EXPORT")


def test_all_contains_public_lazy_exports(fresh_agent_module):
    agent_mod = fresh_agent_module

    assert agent_mod.__all__ == [
        "SidarAgent",
        "AutoHandle",
        "AutoHandler",
        "SIDAR_SYSTEM_PROMPT",
        "SIDAR_KEYS",
        "SIDAR_WAKE_WORDS",
    ]
