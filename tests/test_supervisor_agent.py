import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_supervisor_module():
    saved = {
        name: sys.modules.get(name)
        for name in (
            "agent",
            "agent.core",
            "agent.core.contracts",
            "agent.core.memory_hub",
            "agent.core.registry",
            "agent.core.event_stream",
            "agent.base_agent",
            "agent.roles",
            "agent.roles.coder_agent",
            "agent.roles.researcher_agent",
            "agent.roles.reviewer_agent",
            "agent.roles.poyraz_agent",
            "agent.roles.qa_agent",
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
        REACT_TIMEOUT = 0.1

    class _LLMClient:
        def __init__(self, *_args, **_kwargs):
            pass

    class _EventBus:
        def __init__(self):
            self.messages = []

        async def publish(self, source, message):
            self.messages.append((source, message))

    class _RoleAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        async def run_task(self, task_prompt: str):
            return task_prompt

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
        ("agent.roles.poyraz_agent", "PoyrazAgent"),
        ("agent.roles.qa_agent", "QAAgent"),
    ):
        role_mod = types.ModuleType(module_name)
        role_mod.__dict__[class_name] = type(class_name, (_RoleAgent,), {})
        sys.modules[module_name] = role_mod

    try:
        for name, rel_path in (
            ("agent.core.contracts", "agent/core/contracts.py"),
            ("agent.core.memory_hub", "agent/core/memory_hub.py"),
            ("agent.base_agent", "agent/base_agent.py"),
            ("agent.core.registry", "agent/core/registry.py"),
            ("agent.core.supervisor", "agent/core/supervisor.py"),
        ):
            spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            sys.modules[name] = mod
            spec.loader.exec_module(mod)

        return (
            sys.modules["agent.core.contracts"],
            sys.modules["agent.core.supervisor"].SupervisorAgent,
        )
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


contracts_mod, SupervisorAgent = _load_supervisor_module()
DelegationRequest = contracts_mod.DelegationRequest
TaskEnvelope = contracts_mod.TaskEnvelope
TaskResult = contracts_mod.TaskResult


def test_contract_models_basic_shape():
    env = TaskEnvelope(task_id="t1", sender="supervisor", receiver="researcher", goal="g")
    res = TaskResult(task_id="t1", status="done", summary="ok")

    assert env.task_id == "t1"
    assert env.intent == "mixed"
    assert res.status == "done"


def test_supervisor_init_falls_back_when_base_and_role_agents_are_object_stubs(monkeypatch):
    supervisor_mod = sys.modules["agent.core.supervisor"]

    monkeypatch.setattr(supervisor_mod.BaseAgent, "__init__", object.__init__)
    monkeypatch.setattr(supervisor_mod, "ResearcherAgent", object)
    monkeypatch.setattr(supervisor_mod, "CoderAgent", object)
    monkeypatch.setattr(supervisor_mod, "ReviewerAgent", object)
    monkeypatch.setattr(supervisor_mod, "PoyrazAgent", object)
    monkeypatch.setattr(supervisor_mod, "QAAgent", object)

    cfg = object()
    s = SupervisorAgent(cfg=cfg)

    assert s.cfg is cfg
    assert s.role_name == "supervisor"
    assert s.llm is None
    assert s.tools == {}
    assert s.researcher is None
    assert s.coder is None
    assert s.reviewer is None
    assert s.poyraz is None
    assert s.qa is None


def test_supervisor_routes_research_to_researcher(monkeypatch):
    s = SupervisorAgent()

    async def fake_run_task(prompt: str) -> str:
        return f"RESEARCH:{prompt}"

    monkeypatch.setattr(s.researcher, "run_task", fake_run_task)

    out = asyncio.run(s.run_task("Python 3.12 yenilikleri neler? web kaynaklarıyla özetle"))
    assert out.startswith("RESEARCH:")


def test_supervisor_routes_review_intent_to_reviewer(monkeypatch):
    s = SupervisorAgent()

    async def fake_review_run_task(prompt: str) -> str:
        return f"REVIEW:{prompt}"

    monkeypatch.setattr(s.reviewer, "run_task", fake_review_run_task)

    out = asyncio.run(s.run_task("GitHub issue ve pull request incele"))
    assert out.startswith("REVIEW:")


def test_supervisor_intent_classifies_marketing_keywords():
    assert SupervisorAgent._intent("SEO ve kampanya metni hazırla") == "marketing"


def test_supervisor_intent_classifies_coverage_keywords():
    assert SupervisorAgent._intent("Coverage açığını kapatmak için eksik test yaz") == "coverage"


def test_supervisor_routes_coverage_intent_to_coverage_agent(monkeypatch):
    s = SupervisorAgent()

    async def fake_coverage_run_task(prompt: str) -> str:
        return f"COVERAGE:{prompt}"

    monkeypatch.setattr(s.coverage, "run_task", fake_coverage_run_task)

    out = asyncio.run(s.run_task("Coverage açığını kapatmak için test yaz"))
    assert out.startswith("COVERAGE:")


def test_supervisor_routes_marketing_intent_to_poyraz(monkeypatch):
    s = SupervisorAgent()

    async def fake_marketing_run_task(prompt: str) -> str:
        return f"MARKETING:{prompt}"

    monkeypatch.setattr(s.poyraz, "run_task", fake_marketing_run_task)

    out = asyncio.run(s.run_task("SEO ve kampanya planı hazırla"))
    assert out.startswith("MARKETING:")


def test_supervisor_routes_coverage_delegation_requests_through_p2p(monkeypatch):
    s = SupervisorAgent()

    req = DelegationRequest(
        task_id="p2p-coverage",
        reply_to="coverage",
        target_agent="qa",
        payload="coverage boşluklarını tekrar doğrula",
    )

    async def fake_delegate(receiver: str, goal: str, intent: str, parent_task_id=None, sender="supervisor", context=None):
        assert receiver == "coverage"
        assert intent == "coverage"
        assert parent_task_id is None
        return TaskResult(task_id="coverage-1", status="done", summary=req)

    routed = []

    async def fake_route(request, *, parent_task_id=None, max_hops=4):
        routed.append((request, parent_task_id, max_hops))
        return TaskResult(task_id="route-4", status="done", summary="COVERAGE:P2P")

    monkeypatch.setattr(s, "_delegate", fake_delegate)
    monkeypatch.setattr(s, "_route_p2p", fake_route)
    monkeypatch.setattr(s.registry, "has", lambda name: name == "coverage")

    out = asyncio.run(s.run_task("coverage açığını kapat ve gerekiyorsa devret"))

    assert out == "COVERAGE:P2P"
    assert routed == [(req, "coverage-1", 4)]


def test_supervisor_routes_research_delegation_requests_through_p2p(monkeypatch):
    s = SupervisorAgent()

    req = DelegationRequest(
        task_id="p2p-research",
        reply_to="researcher",
        target_agent="coder",
        payload="araştırma bulgusunu koda dönüştür",
    )

    async def fake_delegate(receiver: str, goal: str, intent: str, parent_task_id=None, sender="supervisor", context=None):
        assert receiver == "researcher"
        assert intent == "research"
        assert parent_task_id is None
        return TaskResult(task_id="research-1", status="done", summary=req)

    routed = []

    async def fake_route(request, *, parent_task_id=None, max_hops=4):
        routed.append((request, parent_task_id, max_hops))
        return TaskResult(task_id="route-1", status="done", summary="RESEARCH:P2P")

    monkeypatch.setattr(s, "_delegate", fake_delegate)
    monkeypatch.setattr(s, "_route_p2p", fake_route)

    out = asyncio.run(s.run_task("web araştır ve gerekiyorsa devret"))

    assert out == "RESEARCH:P2P"
    assert routed == [(req, "research-1", 4)]


def test_supervisor_routes_review_delegation_requests_through_p2p(monkeypatch):
    s = SupervisorAgent()

    req = DelegationRequest(
        task_id="p2p-review",
        reply_to="reviewer",
        target_agent="coder",
        payload="review geri bildirimlerini uygula",
    )

    async def fake_delegate(receiver: str, goal: str, intent: str, parent_task_id=None, sender="supervisor", context=None):
        assert receiver == "reviewer"
        assert intent == "review"
        assert parent_task_id is None
        return TaskResult(task_id="review-1", status="done", summary=req)

    routed = []

    async def fake_route(request, *, parent_task_id=None, max_hops=4):
        routed.append((request, parent_task_id, max_hops))
        return TaskResult(task_id="route-2", status="done", summary="REVIEW:P2P")

    monkeypatch.setattr(s, "_delegate", fake_delegate)
    monkeypatch.setattr(s, "_route_p2p", fake_route)

    out = asyncio.run(s.run_task("pull request review et ve gerekiyorsa devret"))

    assert out == "REVIEW:P2P"
    assert routed == [(req, "review-1", 4)]


def test_supervisor_routes_marketing_delegation_requests_through_p2p(monkeypatch):
    s = SupervisorAgent()

    req = DelegationRequest(
        task_id="p2p-marketing",
        reply_to="poyraz",
        target_agent="reviewer",
        payload="kampanya metnini kalite açısından incele",
    )

    async def fake_delegate(receiver: str, goal: str, intent: str, parent_task_id=None, sender="supervisor", context=None):
        assert receiver == "poyraz"
        assert intent == "marketing"
        assert parent_task_id is None
        return TaskResult(task_id="marketing-1", status="done", summary=req)

    routed = []

    async def fake_route(request, *, parent_task_id=None, max_hops=4):
        routed.append((request, parent_task_id, max_hops))
        return TaskResult(task_id="route-3", status="done", summary="MARKETING:P2P")

    monkeypatch.setattr(s, "_delegate", fake_delegate)
    monkeypatch.setattr(s, "_route_p2p", fake_route)

    out = asyncio.run(s.run_task("SEO kampanyasını hazırla ve gerekiyorsa devret"))

    assert out == "MARKETING:P2P"
    assert routed == [(req, "marketing-1", 4)]


def test_supervisor_routes_code_intent_to_coder(monkeypatch):
    s = SupervisorAgent()

    async def fake_coder_run_task(prompt: str) -> str:
        return f"CODER:{prompt}"

    async def fake_reviewer_run_task(prompt: str) -> str:
        return "[REVIEW:PASS] Kod uygun."

    monkeypatch.setattr(s.coder, "run_task", fake_coder_run_task)
    monkeypatch.setattr(s.reviewer, "run_task", fake_reviewer_run_task)

    out = asyncio.run(s.run_task("test.py isimli bir dosyaya 'print(hello)' yaz"))
    assert out.startswith("CODER:")


def test_supervisor_retries_coder_when_review_fails(monkeypatch):
    s = SupervisorAgent()
    calls = {"coder": 0}

    async def fake_coder_run_task(prompt: str) -> str:
        calls["coder"] += 1
        return f"CODER_RUN_{calls['coder']}:{prompt}"

    async def fake_review_run_task(prompt: str) -> str:
        if "CODER_RUN_1" in prompt:
            return "[REVIEW:FAIL] regresyon bulundu"
        return "[REVIEW:PASS] kalite uygun"

    monkeypatch.setattr(s.coder, "run_task", fake_coder_run_task)
    monkeypatch.setattr(s.reviewer, "run_task", fake_review_run_task)

    out = asyncio.run(s.run_task("özellik ekle"))

    assert calls["coder"] == 2
    assert "2. tur" in out


def test_supervisor_routes_p2p_delegation_from_reviewer_to_coder(monkeypatch):
    s = SupervisorAgent()

    async def fake_coder_run_task(prompt: str):
        if prompt.startswith("qa_feedback|"):
            return "[CODER:APPROVED] ack"
        return "CODER:initial"

    async def fake_reviewer_run_task(_prompt: str):
        return DelegationRequest(
            task_id="p2p-1",
            reply_to="reviewer",
            target_agent="coder",
            payload="qa_feedback|decision=APPROVE;risk=düşük",
        )

    monkeypatch.setattr(s.coder, "run_task", fake_coder_run_task)
    monkeypatch.setattr(s.reviewer, "run_task", fake_reviewer_run_task)

    out = asyncio.run(s.run_task("bir kod görevi"))
    assert "CODER:" in out or "ack" in out


def test_supervisor_route_p2p_timeout_bubbles_for_unresponsive_subagent():
    s = object.__new__(SupervisorAgent)
    s.cfg = type("Cfg", (), {"REACT_TIMEOUT": 0.01})()

    published = []

    class _Events:
        async def publish(self, source, message):
            published.append((source, message))

    async def _delegate(*_args, **_kwargs):
        await asyncio.sleep(1)
        return TaskResult(task_id="late", status="done", summary="never")

    s.events = _Events()
    s._delegate = _delegate

    req = DelegationRequest(
        task_id="p2p-timeout",
        reply_to="reviewer",
        target_agent="coder",
        payload="fix",
    )

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(s._route_p2p(req, max_hops=2))

    assert published == [("supervisor", "P2P yönlendirme: reviewer → coder")]


def test_supervisor_route_p2p_preserves_direct_handoff_context():
    s = object.__new__(SupervisorAgent)
    s.cfg = type("Cfg", (), {"REACT_TIMEOUT": 1})()

    class _Events:
        async def publish(self, *_args):
            return None

    captured = {}

    async def _delegate(receiver, goal, intent, parent_task_id=None, sender="supervisor", context=None):
        captured["receiver"] = receiver
        captured["goal"] = goal
        captured["intent"] = intent
        captured["parent_task_id"] = parent_task_id
        captured["sender"] = sender
        captured["context"] = dict(context or {})
        return TaskResult(task_id="ok", status="done", summary="P2P:DONE")

    s.events = _Events()
    s._delegate = _delegate

    req = DelegationRequest(
        task_id="p2p-ctx",
        reply_to="coder",
        target_agent="reviewer",
        payload="review_code|diff",
        intent="review",
        parent_task_id="root-1",
        handoff_depth=2,
        meta={"reason": "coder_request_review"},
    )

    result = asyncio.run(s._route_p2p(req, max_hops=2))

    assert result.summary == "P2P:DONE"
    assert captured["receiver"] == "reviewer"
    assert captured["sender"] == "coder"
    assert captured["intent"] == "review"
    assert captured["parent_task_id"] == "root-1"
    assert captured["context"]["p2p_reason"] == "coder_request_review"
    assert captured["context"]["p2p_sender"] == "coder"
    assert captured["context"]["p2p_receiver"] == "reviewer"


def test_supervisor_init_falls_back_when_base_init_raises_type_error(monkeypatch):
    supervisor_mod = sys.modules["agent.core.supervisor"]

    def _boom(*_args, **_kwargs):
        raise TypeError("stubbed base init")

    monkeypatch.setattr(supervisor_mod.BaseAgent, "__init__", _boom)
    monkeypatch.setattr(supervisor_mod, "ResearcherAgent", object)
    monkeypatch.setattr(supervisor_mod, "CoderAgent", object)
    monkeypatch.setattr(supervisor_mod, "ReviewerAgent", object)
    monkeypatch.setattr(supervisor_mod, "PoyrazAgent", object)
    monkeypatch.setattr(supervisor_mod, "QAAgent", object)

    cfg = object()
    s = SupervisorAgent(cfg=cfg)

    assert s.cfg is cfg
    assert s.role_name == "supervisor"
    assert s.llm is None
    assert s.tools == {}
    assert s.researcher is None
    assert s.coder is None
    assert s.reviewer is None
    assert s.poyraz is None
    assert s.qa is None


def test_supervisor_null_span_methods_are_safe():
    supervisor_mod = sys.modules["agent.core.supervisor"]
    span = supervisor_mod._NullSpan()

    assert span.__enter__() is span
    assert span.__exit__(None, None, None) is False
    assert span.set_attribute("sidar.result_len", 12) is None


def test_supervisor_delegate_raises_key_error_for_unknown_role(monkeypatch):
    supervisor_mod = sys.modules["agent.core.supervisor"]
    sup = object.__new__(SupervisorAgent)

    class _Registry:
        def get(self, receiver):
            raise KeyError(f"missing role: {receiver}")

    class _MemoryHub:
        def add_role_note(self, *_args, **_kwargs):
            raise AssertionError("memory should not be written when delegation fails early")

    sup.registry = _Registry()
    sup.memory_hub = _MemoryHub()

    monkeypatch.setattr(supervisor_mod, "_tracer", None)
    monkeypatch.setattr(supervisor_mod, "_get_agent_metrics", None)

    with pytest.raises(KeyError, match="missing role: ghost"):
        asyncio.run(sup._delegate("ghost", "görev", "code"))


def test_supervisor_delegate_reraises_agent_errors_even_if_metrics_fail(monkeypatch):
    supervisor_mod = sys.modules["agent.core.supervisor"]
    sup = object.__new__(SupervisorAgent)

    class _BrokenAgent:
        async def run_task(self, _prompt: str):
            raise RuntimeError("agent boom")

    class _Registry:
        def get(self, _receiver):
            return _BrokenAgent()

    class _MemoryHub:
        def add_role_note(self, *_args, **_kwargs):
            raise AssertionError("memory should not be written on failure")

    class _Collector:
        def record(self, *_args, **_kwargs):
            raise RuntimeError("metrics boom")

    sup.registry = _Registry()
    sup.memory_hub = _MemoryHub()

    monkeypatch.setattr(supervisor_mod, "_tracer", None)
    monkeypatch.setattr(supervisor_mod, "_get_agent_metrics", lambda: _Collector())

    with pytest.raises(RuntimeError, match="agent boom"):
        asyncio.run(sup._delegate("coder", "görev", "code"))


def test_supervisor_routes_coverage_intent_to_qa_when_coverage_agent_is_unavailable(monkeypatch):
    s = object.__new__(SupervisorAgent)
    s.events = type("_Events", (), {"publish": lambda self, *_a, **_k: asyncio.sleep(0)})()
    s.memory_hub = type("_MemoryHub", (), {"add_global": lambda self, *_a, **_k: None})()
    s.registry = type("_Registry", (), {"has": lambda self, name: False})()

    captured = {}

    async def fake_delegate(receiver: str, goal: str, intent: str, parent_task_id=None, sender="supervisor", context=None):
        captured["receiver"] = receiver
        captured["goal"] = goal
        captured["intent"] = intent
        return TaskResult(task_id="coverage-qa", status="done", summary="QA:COVERAGE")

    s._delegate = fake_delegate
    s._route_p2p = None

    out = asyncio.run(s.run_task("coverage açığını kapatmak için test yaz"))

    assert out == "QA:COVERAGE"
    assert captured == {
        "receiver": "qa",
        "goal": "coverage açığını kapatmak için test yaz",
        "intent": "coverage",
    }


def test_supervisor_route_p2p_returns_fail_closed_when_hop_limit_is_exceeded():
    s = object.__new__(SupervisorAgent)
    s.cfg = type("Cfg", (), {"REACT_TIMEOUT": 0.1, "MAX_QA_RETRIES": 3})()
    s.events = type("_Events", (), {"publish": lambda self, *_a, **_k: asyncio.sleep(0)})()

    async def _delegate(*_args, **_kwargs):
        return TaskResult(
            task_id="loop",
            status="done",
            summary=DelegationRequest(
                task_id="loop",
                reply_to="coder",
                target_agent="reviewer",
                payload="review_code|diff",
            ),
        )

    s._delegate = _delegate

    result = asyncio.run(
        s._route_p2p(
            DelegationRequest(
                task_id="root-loop",
                reply_to="reviewer",
                target_agent="coder",
                payload="qa_feedback|decision=approve",
            ),
            max_hops=2,
        )
    )

    assert result.status == "failed"
    assert "Maksimum delegasyon hop sayısı aşıldı" in result.summary


def test_supervisor_delegate_records_metrics_memory_and_span_attributes(monkeypatch):
    supervisor_mod = sys.modules["agent.core.supervisor"]
    sup = object.__new__(SupervisorAgent)

    class _Agent:
        async def run_task(self, prompt: str):
            assert prompt == "görev"
            return "tamamlandı"

    class _Registry:
        def get(self, receiver):
            assert receiver == "coder"
            return _Agent()

    notes = []

    class _MemoryHub:
        def add_role_note(self, role, summary):
            notes.append((role, summary))

    span_attrs = {}

    class _Span:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def set_attribute(self, key, value):
            span_attrs[key] = value

    class _Tracer:
        def start_as_current_span(self, name, attributes=None):
            span_attrs["span_name"] = name
            span_attrs["attributes"] = dict(attributes or {})
            return _Span()

    calls = []

    class _Collector:
        def record(self, receiver, intent, status, duration_s):
            calls.append((receiver, intent, status, duration_s > 0))

    sup.registry = _Registry()
    sup.memory_hub = _MemoryHub()

    monkeypatch.setattr(supervisor_mod, "_tracer", _Tracer())
    monkeypatch.setattr(supervisor_mod, "_get_agent_metrics", lambda: _Collector())

    result = asyncio.run(sup._delegate("coder", "görev", "code", parent_task_id="parent-1"))

    assert result.status == "done"
    assert result.summary == "tamamlandı"
    assert notes == [("coder", "tamamlandı")]
    assert calls == [("coder", "code", "done", True)]
    assert span_attrs["span_name"] == "supervisor.delegate.coder"
    assert span_attrs["attributes"]["sidar.parent_task_id"] == "parent-1"
    assert span_attrs["sidar.result_len"] == len("tamamlandı")