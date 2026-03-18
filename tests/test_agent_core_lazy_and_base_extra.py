import asyncio
import importlib
import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _load_real_agent_modules():
    saved = {
        name: sys.modules.get(name)
        for name in (
            "agent",
            "agent.core",
            "agent.core.contracts",
            "agent.core.memory_hub",
            "agent.core.registry",
            "agent.core.event_stream",
            "agent.core.supervisor",
            "agent.base_agent",
            "agent.roles",
            "agent.roles.coder_agent",
            "agent.roles.researcher_agent",
            "agent.roles.reviewer_agent",
            "config",
            "core",
            "core.llm_client",
        )
    }

    agent_pkg = types.ModuleType("agent")
    agent_pkg.__path__ = [str(ROOT / "agent")]
    core_pkg = types.ModuleType("agent.core")
    core_pkg.__path__ = [str(ROOT / "agent" / "core")]
    roles_pkg = types.ModuleType("agent.roles")
    roles_pkg.__path__ = [str(ROOT / "agent" / "roles")]
    root_core_pkg = types.ModuleType("core")
    llm_client_mod = types.ModuleType("core.llm_client")
    config_mod = types.ModuleType("config")

    class _Config:
        AI_PROVIDER = "test"

    class _LLMClient:
        def __init__(self, *_args, **_kwargs):
            pass

    class _EventBus:
        async def publish(self, *_args, **_kwargs):
            return None

    config_mod.Config = _Config
    llm_client_mod.LLMClient = _LLMClient
    root_core_pkg.llm_client = llm_client_mod

    sys.modules["agent"] = agent_pkg
    sys.modules["agent.core"] = core_pkg
    sys.modules["agent.roles"] = roles_pkg
    sys.modules["config"] = config_mod
    sys.modules["core"] = root_core_pkg
    sys.modules["core.llm_client"] = llm_client_mod

    event_stream_mod = types.ModuleType("agent.core.event_stream")
    event_stream_mod.get_agent_event_bus = lambda: _EventBus()
    sys.modules["agent.core.event_stream"] = event_stream_mod

    for module_name, class_name in (
        ("agent.roles.coder_agent", "CoderAgent"),
        ("agent.roles.researcher_agent", "ResearcherAgent"),
        ("agent.roles.reviewer_agent", "ReviewerAgent"),
    ):
        role_mod = types.ModuleType(module_name)
        role_mod.__dict__[class_name] = type(class_name, (), {})
        sys.modules[module_name] = role_mod

    try:
        for name, rel_path in (
            ("agent.core.contracts", "agent/core/contracts.py"),
            ("agent.core.memory_hub", "agent/core/memory_hub.py"),
            ("agent.base_agent", "agent/base_agent.py"),
            ("agent.core.registry", "agent/core/registry.py"),
            ("agent.core", "agent/core/__init__.py"),
        ):
            spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            sys.modules[name] = mod
            spec.loader.exec_module(mod)

        yield (
            sys.modules["agent.base_agent"].BaseAgent,
            sys.modules["agent.core"],
            sys.modules["agent.core.memory_hub"].MemoryHub,
        )
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_base_agent_tool_dispatch_and_delegation_helpers():
    with _load_real_agent_modules() as (BaseAgent, _, _):

        class _MiniAgent(BaseAgent):
            def __init__(self, cfg=None, role_name="mini"):
                self.cfg = cfg
                self.role_name = role_name
                self.system_prompt = ""
                self.tools = {}

            async def run_task(self, task_prompt: str) -> str:
                return task_prompt

        agent = _MiniAgent(role_name="mini")

        async def _echo(arg: str) -> str:
            return f"ok:{arg}"

        agent.register_tool("echo", _echo)
        assert asyncio.run(agent.call_tool("echo", "x")) == "ok:x"
        assert "tanımlı değil" in asyncio.run(agent.call_tool("missing", "x"))

        req = agent.delegate_to("reviewer", "payload")
        assert req.task_id == "p2p-mini"
        assert _MiniAgent.is_delegation_message(req) is True
        assert _MiniAgent.is_delegation_message("not-delegation") is False


def test_agent_core_lazy_getattr_exports_and_error_paths():
    with _load_real_agent_modules() as (_, agent_core, MemoryHub):
        core = importlib.reload(agent_core)

        assert core.MemoryHub is MemoryHub
        assert core.AgentRegistry.__name__ == "AgentRegistry"
        assert core.SupervisorAgent.__name__ == "SupervisorAgent"

        with pytest.raises(AttributeError):
            getattr(core, "NotExisting")


def test_memory_hub_empty_branches_and_async_helpers():
    with _load_real_agent_modules() as (_, _, MemoryHub):
        hub = MemoryHub()

        hub.add_global("")
        assert hub.global_context() == []

        hub.add_role_note("coder", "")
        assert hub.role_context("coder") == []

        hub.aadd_global("g1")
        hub.aadd_role_note("coder", "n1")
        assert hub.aglobal_context(limit=1) == ["g1"]
        assert hub.arole_context("coder", limit=1) == ["n1"]
        assert hub.role_context("unknown") == []
