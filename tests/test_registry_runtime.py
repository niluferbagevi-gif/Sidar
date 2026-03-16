import pytest

from agent.registry import AgentRegistry


class _AgentA:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _AgentB:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_create_unknown_role_raises_key_error():
    with pytest.raises(KeyError, match="ajan tipi kayıt defterinde bulunamadı"):
        AgentRegistry.create("definitely_missing_role")


def test_register_type_duplicate_role_replaces_existing_registration():
    role = "tmp_test_registry_role"
    AgentRegistry.unregister(role)

    AgentRegistry.register_type(role_name=role, agent_class=_AgentA, capabilities=["x"], is_builtin=False)
    AgentRegistry.register_type(role_name=role, agent_class=_AgentB, capabilities=["y"], is_builtin=False)

    spec = AgentRegistry.get(role)
    instance = AgentRegistry.create(role, cfg={"ok": True})

    assert spec is not None
    assert spec.agent_class is _AgentB
    assert spec.capabilities == ["y"]
    assert isinstance(instance, _AgentB)

    AgentRegistry.unregister(role)
