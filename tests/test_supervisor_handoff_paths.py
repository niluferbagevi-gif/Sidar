from __future__ import annotations

import asyncio
import importlib
import sys
import types
from types import MethodType, SimpleNamespace


def _install_supervisor_import_stubs() -> None:
    config_mod = types.ModuleType("config")

    class Config:
        MAX_QA_RETRIES = 3
        REACT_TIMEOUT = 60

    config_mod.Config = Config
    sys.modules["config"] = config_mod

    base_agent_mod = types.ModuleType("agent.base_agent")

    class BaseAgent:
        def __init__(self, cfg=None, role_name="base") -> None:
            self.cfg = cfg
            self.role_name = role_name

    base_agent_mod.BaseAgent = BaseAgent
    sys.modules["agent.base_agent"] = base_agent_mod

    contracts_mod = types.ModuleType("agent.core.contracts")

    class TaskResult:
        def __init__(self, task_id, status, summary) -> None:
            self.task_id = task_id
            self.status = status
            self.summary = summary

    contracts_mod.TaskResult = TaskResult
    contracts_mod.TaskEnvelope = lambda **kwargs: SimpleNamespace(**kwargs)
    contracts_mod.DelegationRequest = object
    contracts_mod.is_delegation_request = lambda _x: False
    sys.modules["agent.core.contracts"] = contracts_mod

    registry_mod = types.ModuleType("agent.core.registry")

    class ActiveAgentRegistry:
        def get(self, _name):
            return SimpleNamespace(run_task=lambda _goal: "ok")

        def has(self, _name):
            return False

        def register(self, *_args, **_kwargs):
            return None

    registry_mod.ActiveAgentRegistry = ActiveAgentRegistry
    sys.modules["agent.core.registry"] = registry_mod

    event_stream_mod = types.ModuleType("agent.core.event_stream")

    class _Bus:
        async def publish(self, *_args, **_kwargs):
            return None

    event_stream_mod.get_agent_event_bus = lambda: _Bus()
    sys.modules["agent.core.event_stream"] = event_stream_mod

    memory_hub_mod = types.ModuleType("agent.core.memory_hub")
    memory_hub_mod.MemoryHub = lambda: SimpleNamespace(add_role_note=lambda *_a, **_k: None, add_global=lambda *_a, **_k: None)
    sys.modules["agent.core.memory_hub"] = memory_hub_mod

    for mod_name, cls_name in [
        ("agent.roles.coder_agent", "CoderAgent"),
        ("agent.roles.researcher_agent", "ResearcherAgent"),
        ("agent.roles.reviewer_agent", "ReviewerAgent"),
        ("agent.roles.poyraz_agent", "PoyrazAgent"),
        ("agent.roles.qa_agent", "QAAgent"),
        ("agent.roles.coverage_agent", "CoverageAgent"),
    ]:
        role_mod = types.ModuleType(mod_name)
        role_mod.__dict__[cls_name] = type(cls_name, (), {"__init__": lambda self, _cfg: None})
        sys.modules[mod_name] = role_mod


_install_supervisor_import_stubs()
supervisor_module = importlib.import_module("agent.core.supervisor")
SupervisorAgent = supervisor_module.SupervisorAgent
TaskResult = importlib.import_module("agent.core.contracts").TaskResult


def test_route_p2p_stops_when_reject_feedback_exceeds_retry_limit() -> None:
    supervisor = SupervisorAgent.__new__(SupervisorAgent)
    supervisor.cfg = SimpleNamespace(MAX_QA_RETRIES=0, REACT_TIMEOUT=5)
    supervisor.events = SimpleNamespace(publish=lambda *_args, **_kwargs: asyncio.sleep(0))

    async def _delegate(*_args, **_kwargs):
        return TaskResult(task_id="t1", status="done", summary="ok")

    supervisor._delegate = MethodType(lambda _self, *a, **k: _delegate(*a, **k), supervisor)

    request = SimpleNamespace(
        target_agent="coder",
        payload="qa_feedback|decision=reject",
        intent="review",
        parent_task_id="parent",
        task_id="task",
        reply_to="reviewer",
        protocol="p2p.v1",
        meta={},
        handoff_depth=0,
    )

    result = asyncio.run(supervisor._route_p2p(request, max_hops=4))
    assert result.status == "failed"
    assert "Maksimum QA retry limiti" in result.summary


def test_run_task_returns_fail_closed_summary_when_review_keeps_rejecting() -> None:
    supervisor = SupervisorAgent.__new__(SupervisorAgent)
    supervisor.cfg = SimpleNamespace(MAX_QA_RETRIES=1)
    supervisor.events = SimpleNamespace(publish=lambda *_args, **_kwargs: asyncio.sleep(0))
    supervisor.memory_hub = SimpleNamespace(add_global=lambda *_args, **_kwargs: None)
    supervisor.registry = SimpleNamespace(has=lambda _name: False)

    supervisor._intent = MethodType(lambda _self, _prompt: "code", supervisor)

    calls = {"count": 0}

    async def _delegate(receiver: str, *_args, **_kwargs):
        if receiver == "coder":
            calls["count"] += 1
            return TaskResult(task_id=f"c{calls['count']}", status="done", summary=f"code pass {calls['count']}")
        return TaskResult(task_id="r1", status="done", summary="Decision=reject")

    supervisor._delegate = MethodType(lambda _self, *a, **k: _delegate(*a, **k), supervisor)

    result = asyncio.run(supervisor.run_task("kodu yaz"))

    assert "[P2P:STOP]" in result
    assert "Reviewer QA Özeti" in result
