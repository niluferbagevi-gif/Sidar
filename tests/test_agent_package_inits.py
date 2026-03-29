"""agent paket __init__ dosyaları için kapsam artırıcı testler."""

from __future__ import annotations

import importlib
import pathlib as _pl
import sys
import types

import pytest

_proj = _pl.Path(__file__).parent.parent


def _ensure_agent_pkg_stub() -> None:
    pkg = types.ModuleType("agent")
    pkg.__path__ = [str(_proj / "agent")]
    pkg.__package__ = "agent"
    sys.modules["agent"] = pkg


def _stub_core_lazy_modules() -> None:
    """agent.core.__getattr__ içinde lazy import edilen modülleri hafif stub'lar."""
    mh = types.ModuleType("agent.core.memory_hub")
    mh.MemoryHub = type("MemoryHub", (), {})
    sys.modules["agent.core.memory_hub"] = mh

    reg = types.ModuleType("agent.core.registry")
    reg.AgentRegistry = type("AgentRegistry", (), {})
    sys.modules["agent.core.registry"] = reg

    sup = types.ModuleType("agent.core.supervisor")
    sup.SupervisorAgent = type("SupervisorAgent", (), {})
    sys.modules["agent.core.supervisor"] = sup


def _stub_role_modules() -> None:
    for mod_name, cls_name in [
        ("agent.roles.coder_agent", "CoderAgent"),
        ("agent.roles.researcher_agent", "ResearcherAgent"),
        ("agent.roles.reviewer_agent", "ReviewerAgent"),
        ("agent.roles.poyraz_agent", "PoyrazAgent"),
        ("agent.roles.qa_agent", "QAAgent"),
        ("agent.roles.coverage_agent", "CoverageAgent"),
    ]:
        mod = types.ModuleType(mod_name)
        mod.__dict__[cls_name] = type(cls_name, (), {})
        sys.modules[mod_name] = mod


def _import_agent_core():
    _ensure_agent_pkg_stub()
    _stub_core_lazy_modules()
    sys.modules.pop("agent.core", None)
    return importlib.import_module("agent.core")


def _import_agent_roles():
    _ensure_agent_pkg_stub()
    _stub_role_modules()
    sys.modules.pop("agent.roles", None)
    return importlib.import_module("agent.roles")


def test_agent_core_exports_and_lazy_getattr():
    core = _import_agent_core()

    assert "TaskEnvelope" in core.__all__
    assert "TaskResult" in core.__all__
    assert "MemoryHub" in core.__all__
    assert "AgentRegistry" in core.__all__
    assert "SupervisorAgent" in core.__all__

    assert core.MemoryHub.__name__ == "MemoryHub"
    assert core.AgentRegistry.__name__ == "AgentRegistry"
    assert core.SupervisorAgent.__name__ == "SupervisorAgent"


def test_agent_core_getattr_unknown_raises_attribute_error():
    core = _import_agent_core()

    with pytest.raises(AttributeError, match="DefinitelyMissing"):
        _ = core.DefinitelyMissing  # type: ignore[attr-defined]


def test_agent_core_reimport_keeps_contract_exports():
    core = _import_agent_core()

    assert hasattr(core, "TaskEnvelope")
    assert hasattr(core, "TaskResult")


def test_agent_roles_exports():
    roles = _import_agent_roles()

    assert "ResearcherAgent" in roles.__all__
    assert "CoderAgent" in roles.__all__
    assert "ReviewerAgent" in roles.__all__
    assert "PoyrazAgent" in roles.__all__
    assert "QAAgent" in roles.__all__
    assert "CoverageAgent" in roles.__all__

    assert roles.ResearcherAgent.__name__ == "ResearcherAgent"
    assert roles.CoderAgent.__name__ == "CoderAgent"
    assert roles.ReviewerAgent.__name__ == "ReviewerAgent"
    assert roles.PoyrazAgent.__name__ == "PoyrazAgent"
    assert roles.QAAgent.__name__ == "QAAgent"
    assert roles.CoverageAgent.__name__ == "CoverageAgent"
