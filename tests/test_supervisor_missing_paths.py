from __future__ import annotations

import asyncio
import importlib
import sys
import types
from types import SimpleNamespace


class _DummyTaskResult:
    def __init__(self, task_id: str, status: str, summary):
        self.task_id = task_id
        self.status = status
        self.summary = summary


class _DummyTaskEnvelope:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Delegation:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def bumped(self):
        self.handoff_depth = getattr(self, "handoff_depth", 0) + 1
        return self


def _install_stubs(*, base_agent_raises_type_error: bool = False, role_ctor_raises_type_error: bool = False, coverage_ctor_raises: bool = False):
    config_mod = types.ModuleType("config")

    class Config:
        MAX_QA_RETRIES = 2
        REACT_TIMEOUT = 5

    config_mod.Config = Config
    sys.modules["config"] = config_mod

    base_agent_mod = types.ModuleType("agent.base_agent")

    if base_agent_raises_type_error:
        class BaseAgent:  # noqa: D401
            __init__ = object.__init__
    else:
        class BaseAgent:
            def __init__(self, cfg=None, role_name="base"):
                self.cfg = cfg
                self.role_name = role_name

    base_agent_mod.BaseAgent = BaseAgent
    sys.modules["agent.base_agent"] = base_agent_mod

    contracts_mod = types.ModuleType("agent.core.contracts")
    contracts_mod.DelegationRequest = _Delegation
    contracts_mod.TaskEnvelope = _DummyTaskEnvelope
    contracts_mod.TaskResult = _DummyTaskResult
    contracts_mod.is_delegation_request = lambda x: isinstance(x, _Delegation)
    sys.modules["agent.core.contracts"] = contracts_mod

    class Registry:
        def __init__(self):
            self._agents = {}

        def register(self, name, agent):
            self._agents[name] = agent

        def get(self, name):
            return self._agents[name]

        def has(self, name):
            return name in self._agents

    registry_mod = types.ModuleType("agent.core.registry")
    registry_mod.ActiveAgentRegistry = Registry
    sys.modules["agent.core.registry"] = registry_mod

    class Bus:
        def __init__(self):
            self.messages = []

        async def publish(self, sender, msg):
            self.messages.append((sender, msg))

    bus = Bus()
    event_mod = types.ModuleType("agent.core.event_stream")
    event_mod.get_agent_event_bus = lambda: bus
    sys.modules["agent.core.event_stream"] = event_mod

    class Hub:
        def __init__(self):
            self.globals = []
            self.role_notes = []

        def add_global(self, text):
            self.globals.append(text)

        def add_role_note(self, role, note):
            self.role_notes.append((role, note))

    mem_mod = types.ModuleType("agent.core.memory_hub")
    mem_mod.MemoryHub = Hub
    sys.modules["agent.core.memory_hub"] = mem_mod

    def _mk_role(label: str, raises: bool = False):
        class _Role:
            def __init__(self, _cfg):
                if raises:
                    raise TypeError("bad ctor")
                self.label = label

            async def run_task(self, prompt):
                return f"{label}:{prompt}"

        return _Role

    roles = {
        "agent.roles.researcher_agent": ("ResearcherAgent", _mk_role("researcher", role_ctor_raises_type_error)),
        "agent.roles.coder_agent": ("CoderAgent", _mk_role("coder", role_ctor_raises_type_error)),
        "agent.roles.reviewer_agent": ("ReviewerAgent", _mk_role("reviewer", role_ctor_raises_type_error)),
        "agent.roles.poyraz_agent": ("PoyrazAgent", _mk_role("poyraz", role_ctor_raises_type_error)),
        "agent.roles.qa_agent": ("QAAgent", _mk_role("qa", role_ctor_raises_type_error)),
        "agent.roles.coverage_agent": ("CoverageAgent", _mk_role("coverage", coverage_ctor_raises)),
    }
    for mod_name, (cls_name, cls_obj) in roles.items():
        m = types.ModuleType(mod_name)
        setattr(m, cls_name, cls_obj)
        sys.modules[mod_name] = m

    return bus


def _reload_supervisor_module():
    sys.modules.pop("agent.core.supervisor", None)
    return importlib.import_module("agent.core.supervisor")


def test_init_fallbacks_and_nullspan_methods():
    _install_stubs(base_agent_raises_type_error=True, role_ctor_raises_type_error=True)
    sup_mod = _reload_supervisor_module()
    n = sup_mod._NullSpan()
    assert n.__enter__() is n
    assert n.__exit__(None, None, None) is False
    n.set_attribute("k", "v")

    s = sup_mod.SupervisorAgent()
    assert s.role_name == "supervisor"
    assert s.researcher is None and s.coverage is None


def test_init_uses_qa_when_coverage_agent_init_fails():
    _install_stubs(coverage_ctor_raises=True)
    sup_mod = _reload_supervisor_module()
    s = sup_mod.SupervisorAgent()
    assert s.qa is not None
    assert s.coverage is s.qa


def test_delegate_records_memory_and_metrics_and_handles_metric_exceptions(monkeypatch):
    _install_stubs()
    sup_mod = _reload_supervisor_module()
    s = sup_mod.SupervisorAgent()

    class Span:
        def __init__(self):
            self.attrs = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def set_attribute(self, k, v):
            self.attrs[k] = v

    class Tracer:
        def start_as_current_span(self, *_a, **_k):
            return Span()

    class Metrics:
        def record(self, *_args):
            raise RuntimeError("ignored")

    monkeypatch.setattr(sup_mod, "_tracer", Tracer())
    monkeypatch.setattr(sup_mod, "_get_agent_metrics", lambda: Metrics())

    result = asyncio.run(s._delegate("coder", "do x", "code"))
    assert result.status == "done"
    assert s.memory_hub.role_notes[-1][0] == "coder"


def test_delegate_sets_error_status_before_reraise(monkeypatch):
    _install_stubs()
    sup_mod = _reload_supervisor_module()
    s = sup_mod.SupervisorAgent()

    class BoomAgent:
        async def run_task(self, _goal):
            raise ValueError("boom")

    s.registry._agents["coder"] = BoomAgent()

    calls = []

    class Metrics:
        def record(self, receiver, intent, status, _duration):
            calls.append((receiver, intent, status))

    monkeypatch.setattr(sup_mod, "_tracer", None)
    monkeypatch.setattr(sup_mod, "_get_agent_metrics", lambda: Metrics())

    try:
        asyncio.run(s._delegate("coder", "do y", "code"))
        assert False, "exception expected"
    except ValueError:
        pass

    assert calls[-1] == ("coder", "code", "error")


def test_route_p2p_continues_on_delegation_and_stops_on_hop_limit():
    _install_stubs()
    sup_mod = _reload_supervisor_module()
    s = sup_mod.SupervisorAgent()

    async def _delegate(_receiver, _goal, *_a, **_k):
        req = _Delegation(
            target_agent="reviewer",
            payload="next",
            intent="p2p",
            parent_task_id="pp",
            task_id="tid",
            reply_to="coder",
            protocol="p2p.v1",
            meta={},
            handoff_depth=0,
        )
        return _DummyTaskResult("x", "done", req)

    s._delegate = _delegate
    req0 = _Delegation(
        target_agent="qa",
        payload="start",
        intent="p2p",
        parent_task_id="pp",
        task_id="tid",
        reply_to="supervisor",
        protocol="p2p.v1",
        meta={"reason": "r"},
        handoff_depth=0,
    )

    result = asyncio.run(s._route_p2p(req0, max_hops=1))
    assert result.status == "failed"
    assert "Maksimum delegasyon hop" in result.summary


def test_run_task_covers_all_intent_branches_and_routing_paths(monkeypatch):
    _install_stubs()
    sup_mod = _reload_supervisor_module()
    s = sup_mod.SupervisorAgent()

    route_calls = []

    async def _route(req, **kwargs):
        route_calls.append((req.target_agent, kwargs.get("parent_task_id")))
        if req.target_agent == "coder":
            routed_summary = "Decision=reject"
        elif req.target_agent == "qa":
            routed_summary = "iter2"
        else:
            routed_summary = "code-v1"
        return _DummyTaskResult("routed", "done", routed_summary)

    s._route_p2p = _route

    async def _delegate(receiver, goal, intent, **_kwargs):
        if intent in {"research", "marketing", "coverage"} or (intent == "review" and not str(goal).startswith("review_code|")):
            req = _Delegation(
                target_agent="coder",
                payload=f"p:{receiver}",
                intent="p2p",
                parent_task_id="p1",
                task_id="t1",
                reply_to=receiver,
                protocol="p2p.v1",
                meta={},
                handoff_depth=0,
            )
            return _DummyTaskResult("t1", "done", req)
        if receiver == "coder" and "düzeltme" not in goal:
            req = _Delegation(
                target_agent="reviewer",
                payload="qa_feedback|decision=accept",
                intent="p2p",
                parent_task_id="pc",
                task_id="tc",
                reply_to="coder",
                protocol="p2p.v1",
                meta={},
                handoff_depth=0,
            )
            return _DummyTaskResult("tc", "done", req)
        if receiver == "reviewer" and goal.startswith("review_code|"):
            if "iter2" in goal:
                return _DummyTaskResult("rv2", "done", "all good")
            req = _Delegation(
                target_agent="coder",
                payload="needs change",
                intent="p2p",
                parent_task_id="pr",
                task_id="tr",
                reply_to="reviewer",
                protocol="p2p.v1",
                meta={},
                handoff_depth=0,
            )
            return _DummyTaskResult("tr", "done", req)
        if receiver == "coder" and "düzeltme" in goal:
            req = _Delegation(
                target_agent="qa",
                payload="iter2",
                intent="p2p",
                parent_task_id="pn",
                task_id="tn",
                reply_to="coder",
                protocol="p2p.v1",
                meta={},
                handoff_depth=0,
            )
            return _DummyTaskResult("tn", "done", req)
        return _DummyTaskResult("ok", "done", f"{receiver}:{goal}")

    s._delegate = _delegate

    for intent_prompt in [
        "web doküman araştır",
        "pull request incele",
        "growth funnel kampanya",
        "pytest coverage arttır",
    ]:
        out = asyncio.run(s.run_task(intent_prompt))
        assert out

    s.registry = SimpleNamespace(has=lambda name: name == "coverage")

    def _is_delegate(x):
        return isinstance(x, _Delegation)

    monkeypatch.setattr(sup_mod, "is_delegation_request", _is_delegate)

    result = asyncio.run(s.run_task("normal kod görevi"))
    assert "Reviewer QA Özeti (2. tur):" in result
    assert route_calls


def test_is_reject_feedback_payload_empty_body():
    _install_stubs()
    sup_mod = _reload_supervisor_module()
    assert sup_mod.SupervisorAgent._is_reject_feedback_payload("qa_feedback|   ") is False
