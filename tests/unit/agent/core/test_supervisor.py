from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace

import pytest

_ORIGINAL_MODULES = {
    name: sys.modules.get(name)
    for name in (
        "agent.base_agent",
        "agent.roles.coder_agent",
        "agent.roles.researcher_agent",
        "agent.roles.reviewer_agent",
        "agent.roles.poyraz_agent",
        "agent.roles.qa_agent",
        "agent.core.event_stream",
        "agent.roles._missing_stub_for_coverage",
    )
}


# supervisor modülünü güvenli import edebilmek için ağır bağımlılıkları stub'la
class _StubBaseAgent:
    def __init__(self, cfg=None, role_name="stub") -> None:
        self.cfg = cfg
        self.role_name = role_name


def test_stub_base_agent_initializes_cfg_and_role_name() -> None:
    agent = _StubBaseAgent(cfg={"x": 1}, role_name="tester")

    assert agent.cfg == {"x": 1}
    assert agent.role_name == "tester"


def _register_stub_module(module_name: str, class_name: str) -> None:
    mod = types.ModuleType(module_name)

    class _StubRole:
        def __init__(self, cfg=None) -> None:
            self.cfg = cfg

        async def run_task(self, goal: str) -> str:
            return f"stub:{class_name}:{goal}"

    setattr(mod, class_name, _StubRole)
    sys.modules[module_name] = mod


base_agent_mod = types.ModuleType("agent.base_agent")
base_agent_mod.BaseAgent = _StubBaseAgent
sys.modules["agent.base_agent"] = base_agent_mod

_register_stub_module("agent.roles.coder_agent", "CoderAgent")
_register_stub_module("agent.roles.researcher_agent", "ResearcherAgent")
_register_stub_module("agent.roles.reviewer_agent", "ReviewerAgent")
_register_stub_module("agent.roles.poyraz_agent", "PoyrazAgent")
_register_stub_module("agent.roles.qa_agent", "QAAgent")

event_stream_mod = types.ModuleType("agent.core.event_stream")


class _StubEventBus:
    async def publish(self, source: str, message: str) -> None:
        return None


def get_agent_event_bus():
    return _StubEventBus()


event_stream_mod.get_agent_event_bus = get_agent_event_bus
sys.modules["agent.core.event_stream"] = event_stream_mod

import agent.core.supervisor as supervisor_mod
from agent.core.contracts import DelegationRequest, TaskResult
from agent.core.supervisor import SupervisorAgent

# Stub'lar sadece supervisor import'u için gerekli.
# Import tamamlandıktan sonra global sys.modules kirlenmesini hemen geri al.
for name, original in _ORIGINAL_MODULES.items():
    if original is None:
        sys.modules.pop(name, None)
    else:
        sys.modules[name] = original


def teardown_module(_module) -> None:
    for name, original in _ORIGINAL_MODULES.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


def test_register_stub_module_creates_runnable_role() -> None:
    module_name = "agent.roles._temporary_stub_role"
    _register_stub_module(module_name, "TempAgent")
    stub_module = sys.modules[module_name]
    role_cls = stub_module.TempAgent
    role = role_cls(cfg={"mode": "test"})

    assert role.cfg == {"mode": "test"}
    assert asyncio.run(role.run_task("hedef")) == "stub:TempAgent:hedef"

    sys.modules.pop(module_name, None)


def test_stub_event_bus_factory_returns_publishable_bus() -> None:
    bus = get_agent_event_bus()
    assert isinstance(bus, _StubEventBus)
    assert asyncio.run(bus.publish("supervisor", "hello")) is None


class _DummyEvents:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, source: str, message: str) -> None:
        self.messages.append((source, message))


class _DummyMemoryHub:
    def __init__(self) -> None:
        self.global_notes: list[str] = []
        self.role_notes: list[tuple[str, str]] = []

    def add_global(self, note: str) -> None:
        self.global_notes.append(note)

    def add_role_note(self, role: str, note: str) -> None:
        self.role_notes.append((role, note))


class _DummyRegistry:
    def __init__(self, has_coverage: bool = True) -> None:
        self._has_coverage = has_coverage

    def has(self, role: str) -> bool:
        return role == "coverage" and self._has_coverage


def _build_supervisor(*, max_qa_retries: int = 2, has_coverage: bool = True) -> SupervisorAgent:
    sup = SupervisorAgent.__new__(SupervisorAgent)
    sup.cfg = SimpleNamespace(MAX_QA_RETRIES=max_qa_retries, REACT_TIMEOUT=1)
    sup.events = _DummyEvents()
    sup.memory_hub = _DummyMemoryHub()
    sup.registry = _DummyRegistry(has_coverage=has_coverage)
    return sup


@pytest.mark.parametrize(
    ("prompt", "expected_intent"),
    [
        ("web kaynak araştır", "research"),
        ("github issue review et", "review"),
        ("seo kampanya planı", "marketing"),
        ("eksik test yaz ve coverage artır", "coverage"),
        ("yeni bir python fonksiyonu yaz", "code"),
    ],
)
def test_intent_classification(prompt: str, expected_intent: str) -> None:
    assert SupervisorAgent._intent(prompt) == expected_intent


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("decision=reject", True),
        ("risk: yüksek", True),
        ("Tüm testler geçti", False),
    ],
)
def test_review_requires_revision(summary: str, expected: bool) -> None:
    assert SupervisorAgent._review_requires_revision(summary) is expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ('qa_feedback|{"decision":"reject"}', True),
        ("qa_feedback|decision=reject", True),
        ("qa_feedback|{bad json", False),
        ('qa_feedback|{"decision":"approve"}', False),
        ("plain-text", False),
    ],
)
def test_is_reject_feedback_payload(payload: str, expected: bool) -> None:
    assert SupervisorAgent._is_reject_feedback_payload(payload) is expected


@pytest.mark.parametrize(
    ("delegation_request", "expected_missing"),
    [
        (
            DelegationRequest(task_id="t", reply_to="", target_agent="coder", payload="x"),
            "reply_to",
        ),
        (
            DelegationRequest(task_id="t", reply_to="qa", target_agent="", payload="x"),
            "target_agent",
        ),
        (
            DelegationRequest(task_id="t", reply_to="qa", target_agent="coder", payload=""),
            "payload",
        ),
    ],
)
def test_validate_p2p_request_reports_missing_fields(
    delegation_request: DelegationRequest, expected_missing: str
) -> None:
    missing = SupervisorAgent._validate_p2p_request(delegation_request)
    assert missing is not None
    assert expected_missing in missing


def test_route_p2p_stops_when_reject_feedback_exceeds_retry_limit() -> None:
    sup = _build_supervisor(max_qa_retries=0)

    async def _delegate(*_args, **_kwargs):
        raise AssertionError("_delegate should not be called when retry limit is exceeded")

    sup._delegate = _delegate

    req = DelegationRequest(
        task_id="t1",
        reply_to="reviewer",
        target_agent="coder",
        payload="qa_feedback|decision=reject",
        intent="p2p",
    )

    import asyncio

    result = asyncio.run(sup._route_p2p(req, max_hops=3))

    assert result.status == "failed"
    assert "Maksimum QA retry limiti" in str(result.summary)


def test_route_p2p_fails_when_max_hops_exceeded() -> None:
    sup = _build_supervisor(max_qa_retries=3)

    async def _delegate(*_args, **_kwargs):
        next_req = DelegationRequest(
            task_id="next",
            reply_to="reviewer",
            target_agent="coder",
            payload="yeni görev",
            intent="p2p",
        )
        return TaskResult(task_id="next", status="done", summary=next_req)

    sup._delegate = _delegate

    req = DelegationRequest(
        task_id="start",
        reply_to="reviewer",
        target_agent="coder",
        payload="ilk görev",
        intent="p2p",
    )

    import asyncio

    result = asyncio.run(sup._route_p2p(req, max_hops=2))

    assert result.status == "failed"
    assert "Maksimum delegasyon hop" in str(result.summary)


@pytest.mark.parametrize(
    ("prompt", "expected_receiver"),
    [
        ("web kaynak araştır", "researcher"),
        ("github issue review et", "reviewer"),
        ("seo kampanya üret", "poyraz"),
        ("eksik test yaz", "coverage"),
    ],
)
def test_run_task_routes_non_code_intents(prompt: str, expected_receiver: str) -> None:
    sup = _build_supervisor(has_coverage=True)
    calls: list[tuple[str, str]] = []

    async def _delegate(receiver: str, goal: str, intent: str, **_kwargs):
        calls.append((receiver, intent))
        return TaskResult(task_id="t", status="done", summary=f"{receiver}:{goal}")

    async def _route_p2p(*_args, **_kwargs):
        raise AssertionError("_route_p2p should not be called in this scenario")

    sup._delegate = _delegate
    sup._route_p2p = _route_p2p

    import asyncio

    result = asyncio.run(sup.run_task(prompt))

    assert calls[0][0] == expected_receiver
    assert expected_receiver in result
    assert prompt in sup.memory_hub.global_notes


def test_run_task_coverage_falls_back_to_qa_when_coverage_agent_missing() -> None:
    sup = _build_supervisor(has_coverage=False)

    async def _delegate(receiver: str, goal: str, intent: str, **_kwargs):
        return TaskResult(task_id="t", status="done", summary=f"{receiver}:{intent}:{goal}")

    sup._delegate = _delegate
    sup._route_p2p = lambda *_args, **_kwargs: None

    import asyncio

    result = asyncio.run(sup.run_task("eksik test yaz"))

    assert result.startswith("qa:coverage:")


def test_run_task_code_flow_retries_and_returns_final_review_summary() -> None:
    sup = _build_supervisor(max_qa_retries=2)

    responses = iter(
        [
            TaskResult(task_id="c1", status="done", summary="ilk kod taslağı"),
            TaskResult(task_id="r1", status="done", summary="decision=reject: düzelt"),
            TaskResult(task_id="c2", status="done", summary="düzeltilmiş kod"),
            TaskResult(task_id="r2", status="done", summary="Tüm testler geçti"),
        ]
    )

    async def _delegate(*_args, **_kwargs):
        return next(responses)

    async def _route_p2p(*_args, **_kwargs):
        raise AssertionError("_route_p2p should not be called in this scenario")

    sup._delegate = _delegate
    sup._route_p2p = _route_p2p

    import asyncio

    result = asyncio.run(sup.run_task("bir modül geliştir"))

    assert "düzeltilmiş kod" in result
    assert "Reviewer QA Özeti (2. tur)" in result
    assert "Tüm testler geçti" in result


def test_run_task_code_flow_stops_after_retry_limit() -> None:
    sup = _build_supervisor(max_qa_retries=1)

    responses = iter(
        [
            TaskResult(task_id="c1", status="done", summary="ilk kod"),
            TaskResult(task_id="r1", status="done", summary="decision=reject"),
            TaskResult(task_id="c2", status="done", summary="ikinci kod"),
            TaskResult(task_id="r2", status="done", summary="decision=reject"),
        ]
    )

    async def _delegate(*_args, **_kwargs):
        return next(responses)

    async def _route_p2p(*_args, **_kwargs):
        raise AssertionError("_route_p2p should not be called in this scenario")

    sup._delegate = _delegate
    sup._route_p2p = _route_p2p

    import asyncio

    result = asyncio.run(sup.run_task("bir modül geliştir"))

    assert "[P2P:STOP] Maksimum QA retry limiti aşıldı (1)." in result
    assert "ikinci kod" in result


def test_run_task_code_flow_skips_reviewer_in_cli_fast_mode() -> None:
    sup = _build_supervisor(max_qa_retries=2)
    sup.cfg.CLI_FAST_MODE = True
    calls: list[tuple[str, str]] = []

    async def _delegate(receiver: str, goal: str, intent: str, **_kwargs):
        calls.append((receiver, intent))
        if receiver == "reviewer":
            raise AssertionError("reviewer should be skipped in CLI fast mode")
        return TaskResult(task_id="c1", status="done", summary="hızlı kod çıktısı")

    async def _route_p2p(*_args, **_kwargs):
        raise AssertionError("_route_p2p should not be called in this scenario")

    sup._delegate = _delegate
    sup._route_p2p = _route_p2p

    result = asyncio.run(sup.run_task("hızlı bir komut çalıştır"))

    assert result == "hızlı kod çıktısı"
    assert calls == [("coder", "code")]


def test_ensure_delegation_request_shape_uses_existing_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts_mod = types.SimpleNamespace(DelegationRequest=DelegationRequest)
    monkeypatch.setattr(supervisor_mod.importlib, "import_module", lambda _name: contracts_mod)

    assert supervisor_mod._ensure_delegation_request_shape() is DelegationRequest


def test_ensure_delegation_request_shape_builds_compat_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts_mod = types.SimpleNamespace(DelegationRequest=object)
    monkeypatch.setattr(supervisor_mod.importlib, "import_module", lambda _name: contracts_mod)

    compat_cls = supervisor_mod._ensure_delegation_request_shape()
    req = compat_cls(
        task_id="t", reply_to="a", target_agent="b", payload="p", handoff_depth=2, meta={"k": "v"}
    )
    bumped = req.bumped()

    assert req.handoff_depth == 2
    assert bumped.handoff_depth == 3
    assert bumped.meta == {"k": "v"}
    assert contracts_mod.DelegationRequest is compat_cls


def test_null_span_noop_methods() -> None:
    span = supervisor_mod._NullSpan()
    with span as ctx:
        assert ctx is span
        ctx.set_attribute("k", "v")


def test_supervisor_init_falls_back_when_base_agent_init_raises_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken_base_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise TypeError("stub object init")

    monkeypatch.setattr(supervisor_mod.BaseAgent, "__init__", _broken_base_init)
    sup = SupervisorAgent()

    assert sup.role_name == "supervisor"
    assert sup.llm is None
    assert sup.tools == {}


def test_supervisor_init_falls_back_when_base_agent_init_raises_attribute_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken_base_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AttributeError("missing AI_PROVIDER")

    monkeypatch.setattr(supervisor_mod.BaseAgent, "__init__", _broken_base_init)
    sup = SupervisorAgent()

    assert sup.role_name == "supervisor"
    assert sup.llm is None
    assert sup.tools == {}


@pytest.mark.parametrize("exc", [TypeError("stub"), AttributeError("missing AI_PROVIDER")])
def test_supervisor_init_keeps_minimal_state_when_base_init_fails(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
) -> None:
    calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def _broken_base_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((self, args, kwargs))
        raise exc

    monkeypatch.setattr(supervisor_mod.BaseAgent, "__init__", _broken_base_init)

    sup = SupervisorAgent()

    assert len(calls) >= 1
    called_self, called_args, called_kwargs = calls[0]
    assert called_self is sup
    assert called_args == ()
    assert called_kwargs == {"cfg": sup.cfg, "role_name": "supervisor"}
    assert sup.role_name == "supervisor"
    assert sup.llm is None
    assert sup.tools == {}


def test_supervisor_init_sets_agents_none_when_role_instantiation_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenRole:
        def __init__(self, _cfg=None) -> None:
            raise TypeError("role build failed")

    monkeypatch.setattr(supervisor_mod, "ResearcherAgent", _BrokenRole)

    sup = SupervisorAgent()

    assert sup.researcher is None
    assert sup.coder is None
    assert sup.reviewer is None
    assert sup.poyraz is None
    assert sup.qa is None
    assert sup.coverage is None


def test_supervisor_init_coverage_registration_failure_falls_back_to_qa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenCoverage:
        def __init__(self, _cfg=None) -> None:
            raise RuntimeError("coverage unavailable")

    monkeypatch.setattr(supervisor_mod, "CoverageAgent", _BrokenCoverage)

    sup = SupervisorAgent()

    assert sup.coverage is sup.qa


def test_is_reject_feedback_payload_false_when_empty_body() -> None:
    assert SupervisorAgent._is_reject_feedback_payload("qa_feedback|   ") is False


def test_delegate_records_metrics_and_ignores_metrics_record_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sup = _build_supervisor()

    class _Agent:
        async def run_task(self, goal: str) -> str:
            return f"ok:{goal}"

    class _Registry:
        def get(self, _receiver: str) -> _Agent:
            return _Agent()

    class _Metrics:
        def record(self, *_args, **_kwargs) -> None:
            raise RuntimeError("metrics down")

    class _Span:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def set_attribute(self, *_args) -> None:
            return None

    class _Tracer:
        def start_as_current_span(self, *_args, **_kwargs) -> _Span:
            return _Span()

    monkeypatch.setattr(supervisor_mod, "_tracer", _Tracer())
    monkeypatch.setattr(supervisor_mod, "_get_agent_metrics", lambda: _Metrics())
    sup.registry = _Registry()

    result = asyncio.run(sup._delegate("coder", "hedef", "code"))
    assert result.status == "done"
    assert sup.memory_hub.role_notes[-1] == ("coder", "ok:hedef")


def test_delegate_with_span_without_set_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    sup = _build_supervisor()

    class _Agent:
        async def run_task(self, _goal: str) -> str:
            return "minimal"

    class _Registry:
        def get(self, _receiver: str) -> _Agent:
            return _Agent()

    class _SpanNoAttrs:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return False

    class _Tracer:
        def start_as_current_span(self, *_args, **_kwargs) -> _SpanNoAttrs:
            return _SpanNoAttrs()

    monkeypatch.setattr(supervisor_mod, "_tracer", _Tracer())
    monkeypatch.setattr(supervisor_mod, "_get_agent_metrics", None)
    sup.registry = _Registry()

    result = asyncio.run(sup._delegate("reviewer", "kontrol", "review"))
    assert result.summary == "minimal"


@pytest.mark.parametrize(
    "prompt",
    [
        "github issue review et",
        "seo kampanya üret",
        "eksik test yaz",
    ],
)
def test_run_task_non_code_routes_delegation_requests(prompt: str) -> None:
    sup = _build_supervisor(has_coverage=True)

    delegation = DelegationRequest(
        task_id="deleg",
        reply_to="reviewer",
        target_agent="coder",
        payload="fix this",
        intent="p2p",
    )

    async def _delegate(*_args, **_kwargs):
        return TaskResult(task_id="t0", status="done", summary=delegation)

    async def _route_p2p(request: DelegationRequest, **_kwargs):
        assert request is delegation
        return TaskResult(task_id="t1", status="done", summary="p2p-done")

    sup._delegate = _delegate
    sup._route_p2p = _route_p2p

    result = asyncio.run(sup.run_task(prompt))
    assert result == "p2p-done"


def test_run_task_code_flow_routes_delegation_requests_at_each_stage() -> None:
    sup = _build_supervisor(max_qa_retries=2)

    code_req = DelegationRequest(
        task_id="d1",
        reply_to="reviewer",
        target_agent="coder",
        payload="qa_feedback|decision=reject",
        intent="p2p",
    )
    review_req = DelegationRequest(
        task_id="d2",
        reply_to="coder",
        target_agent="reviewer",
        payload="review this",
        intent="p2p",
    )
    revise_req = DelegationRequest(
        task_id="d3",
        reply_to="reviewer",
        target_agent="coder",
        payload="revise this",
        intent="p2p",
    )
    final_review_req = DelegationRequest(
        task_id="d4",
        reply_to="coder",
        target_agent="reviewer",
        payload="final review",
        intent="p2p",
    )
    responses = iter(
        [
            TaskResult(task_id="c1", status="done", summary=code_req),
            TaskResult(task_id="r1", status="done", summary=review_req),
            TaskResult(task_id="c2", status="done", summary=revise_req),
            TaskResult(task_id="r2", status="done", summary=final_review_req),
        ]
    )
    p2p_outputs = iter(["ilk kod", "decision=reject", "ikinci kod", "Tüm testler geçti"])

    async def _delegate(*_args, **_kwargs):
        return next(responses)

    async def _route_p2p(_req: DelegationRequest, **_kwargs):
        return TaskResult(task_id="x", status="done", summary=next(p2p_outputs))

    sup._delegate = _delegate
    sup._route_p2p = _route_p2p

    result = asyncio.run(sup.run_task("bir modül geliştir"))
    assert "Reviewer QA Özeti (2. tur)" in result
    assert "ikinci kod" in result
    assert "Tüm testler geçti" in result


def test_init_registers_specialist_agents() -> None:
    sup = SupervisorAgent()
    assert sup.registry.has("researcher")
    assert sup.registry.has("coder")
    assert sup.registry.has("reviewer")
    assert sup.registry.has("poyraz")
    assert sup.registry.has("qa")
    assert sup.coverage is not None


def test_init_falls_back_to_qa_when_coverage_registration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenCoverage:
        def __init__(self, _cfg=None) -> None:
            raise RuntimeError("broken")

    monkeypatch.setattr(supervisor_mod, "CoverageAgent", _BrokenCoverage)
    sup = SupervisorAgent()
    assert sup.coverage is sup.qa


def test_delegate_success_records_metrics_and_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    sup = SupervisorAgent.__new__(SupervisorAgent)
    sup.cfg = SimpleNamespace(REACT_TIMEOUT=1)
    sup.memory_hub = _DummyMemoryHub()
    sup.events = _DummyEvents()

    class _Worker:
        async def run_task(self, goal: str) -> str:
            return f"ok:{goal}"

    class _Registry:
        def get(self, _role: str):
            return _Worker()

    records: list[tuple[str, str, str]] = []

    class _Collector:
        def record(self, receiver: str, intent: str, status: str, _duration: float) -> None:
            records.append((receiver, intent, status))

    monkeypatch.setattr(supervisor_mod, "_tracer", None)
    monkeypatch.setattr(supervisor_mod, "_get_agent_metrics", lambda: _Collector())
    sup.registry = _Registry()

    result = asyncio.run(sup._delegate("coder", "görev", "code", parent_task_id="p1"))

    assert result.status == "done"
    assert result.summary == "ok:görev"
    assert sup.memory_hub.global_notes == []
    assert sup.memory_hub.role_notes == [("coder", "ok:görev")]
    assert records == [("coder", "code", "done")]


def test_delegate_error_records_status_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    sup = SupervisorAgent.__new__(SupervisorAgent)
    sup.cfg = SimpleNamespace(REACT_TIMEOUT=1)
    sup.memory_hub = _DummyMemoryHub()
    sup.events = _DummyEvents()

    class _Worker:
        async def run_task(self, _goal: str) -> str:
            raise RuntimeError("boom")

    class _Registry:
        def get(self, _role: str):
            return _Worker()

    statuses: list[str] = []

    class _Collector:
        def record(self, _receiver: str, _intent: str, status: str, _duration: float) -> None:
            statuses.append(status)

    monkeypatch.setattr(supervisor_mod, "_tracer", None)
    monkeypatch.setattr(supervisor_mod, "_get_agent_metrics", lambda: _Collector())
    sup.registry = _Registry()

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(sup._delegate("coder", "görev", "code"))

    assert statuses == ["error"]


def test_route_p2p_delegates_and_returns_terminal_result() -> None:
    sup = _build_supervisor(max_qa_retries=3)
    calls: list[dict[str, object]] = []

    async def _delegate(receiver: str, goal: str, intent: str, **kwargs):
        calls.append({"receiver": receiver, "goal": goal, "intent": intent, **kwargs})
        return TaskResult(task_id="done", status="done", summary="tamam")

    sup._delegate = _delegate
    req = DelegationRequest(
        task_id="start",
        reply_to="reviewer",
        target_agent="coder",
        payload="kod üret",
        intent="p2p",
        meta={"reason": "qa"},
        handoff_depth=2,
        protocol="p2p.v1",
    )

    result = asyncio.run(sup._route_p2p(req, parent_task_id="parent", max_hops=2))

    assert result.summary == "tamam"
    assert calls[0]["receiver"] == "coder"
    assert calls[0]["sender"] == "reviewer"
    assert calls[0]["parent_task_id"] == "parent"
    assert calls[0]["context"]["p2p_handoff_depth"] == "2"


def test_route_p2p_reject_feedback_continues_until_retry_limit_exceeded() -> None:
    sup = _build_supervisor(max_qa_retries=1)
    delegate_calls: list[str] = []

    async def _delegate(receiver: str, _goal: str, intent: str, **_kwargs):
        assert intent == "p2p"
        delegate_calls.append(receiver)
        return TaskResult(
            task_id=str(len(delegate_calls)),
            status="done",
            summary=DelegationRequest(
                task_id=f"loop-{len(delegate_calls)}",
                reply_to="reviewer",
                target_agent="coder",
                payload="qa_feedback|decision=reject",
                intent="p2p",
                protocol="p2p.v1",
            ),
        )

    sup._delegate = _delegate
    req = DelegationRequest(
        task_id="start",
        reply_to="reviewer",
        target_agent="coder",
        payload="qa_feedback|decision=reject",
        intent="p2p",
        protocol="p2p.v1",
    )

    result = asyncio.run(sup._route_p2p(req, max_hops=5))

    assert len(delegate_calls) == 1
    assert result.status == "failed"
    assert "Maksimum QA retry limiti aşıldı (1)" in str(result.summary)


def test_route_p2p_returns_fail_closed_for_malformed_request() -> None:
    sup = _build_supervisor(max_qa_retries=2)

    async def _delegate(*_args, **_kwargs):
        raise AssertionError("_delegate should not run for malformed requests")

    sup._delegate = _delegate
    req = DelegationRequest(
        task_id="start",
        reply_to="reviewer",
        target_agent="",
        payload="",
        intent="p2p",
    )
    result = asyncio.run(sup._route_p2p(req, max_hops=2))
    assert result.status == "failed"
    assert "Geçersiz delegasyon isteği" in str(result.summary)
    assert "target_agent" in str(result.summary)
    assert "payload" in str(result.summary)


def test_route_p2p_handles_none_meta_without_crashing() -> None:
    sup = _build_supervisor(max_qa_retries=2)
    calls: list[dict[str, object]] = []

    async def _delegate(receiver: str, goal: str, intent: str, **kwargs):
        calls.append({"receiver": receiver, "goal": goal, "intent": intent, **kwargs})
        return TaskResult(task_id="done", status="done", summary="ok")

    sup._delegate = _delegate
    req = DelegationRequest(
        task_id="start",
        reply_to="reviewer",
        target_agent="coder",
        payload="kod üret",
        intent="p2p",
    )
    req.meta = None  # type: ignore[assignment]

    result = asyncio.run(sup._route_p2p(req, max_hops=1))

    assert result.status == "done"
    assert calls[0]["context"]["p2p_reason"] == ""


def test_run_task_research_routes_p2p_when_delegation_request_returns() -> None:
    sup = _build_supervisor()

    async def _delegate(receiver: str, goal: str, intent: str, **_kwargs):
        assert receiver == "researcher"
        return TaskResult(
            task_id="r1",
            status="done",
            summary=DelegationRequest(
                task_id="d1",
                reply_to="researcher",
                target_agent="coder",
                payload="aktar",
                intent="p2p",
            ),
        )

    async def _route_p2p(request: DelegationRequest, **kwargs):
        assert request.target_agent == "coder"
        assert kwargs["parent_task_id"] == "r1"
        return TaskResult(task_id="x", status="done", summary="p2p-sonuc")

    sup._delegate = _delegate
    sup._route_p2p = _route_p2p

    result = asyncio.run(sup.run_task("web araştırması yap"))
    assert result == "p2p-sonuc"


@pytest.mark.parametrize(
    ("prompt", "_intent_name"),
    [
        ("web kaynak araştır", "research"),
        ("github issue review et", "review"),
        ("seo kampanya planı", "marketing"),
        ("eksik test yaz ve coverage artır", "coverage"),
        ("yeni bir python fonksiyonu yaz", "code"),
    ],
)
def test_run_task_circuit_breaker_first_turn(prompt: str, _intent_name: str) -> None:
    """İlk turn tüketiminde circuit breaker dallarını kapsar."""
    sup = _build_supervisor()
    sup._max_turns = lambda: 0

    result = asyncio.run(sup.run_task(prompt))
    assert "[P2P:STOP] Circuit breaker tetiklendi" in result


def test_run_task_circuit_breaker_before_initial_reviewer() -> None:
    """İlk reviewer çağrısı öncesi circuit breaker dalını kapsar."""
    sup = _build_supervisor()
    sup._max_turns = lambda: 1

    async def _delegate(*_args, **_kwargs):
        return TaskResult(task_id="t1", status="done", summary="kod üretildi")

    sup._delegate = _delegate
    result = asyncio.run(sup.run_task("yeni kod yaz"))

    assert "[P2P:STOP] Circuit breaker tetiklendi" in result


def test_run_task_circuit_breaker_while_loop_start() -> None:
    """while başlangıcındaki turn_count >= max_turns dalını kapsar."""
    sup = _build_supervisor(max_qa_retries=2)
    sup._max_turns = lambda: 2

    responses = iter(
        [
            TaskResult(task_id="t1", status="done", summary="hatalı kod"),
            TaskResult(task_id="t2", status="done", summary="risk: yüksek, düzelt"),
        ]
    )

    async def _delegate(*_args, **_kwargs):
        return next(responses)

    sup._delegate = _delegate
    result = asyncio.run(sup.run_task("kod yaz"))

    assert "Reviewer QA Özeti (circuit breaker):" in result
    assert "[P2P:STOP] Circuit breaker tetiklendi" in result


class MockMaxTurnsForDeadCode:
    """Defansif dal için karşılaştırma davranışını manipüle eden max_turns mock'u."""

    def __le__(self, _other):
        return False

    def __ge__(self, other):
        return other < 3

    def __str__(self):
        return "3"


def test_run_task_circuit_breaker_before_revise_coder() -> None:
    """while içindeki revise-coder öncesi _consume_turn dalını kapsar."""
    sup = _build_supervisor(max_qa_retries=2)
    sup._max_turns = lambda: MockMaxTurnsForDeadCode()

    responses = iter(
        [
            TaskResult(task_id="t1", status="done", summary="hatalı kod"),
            TaskResult(task_id="t2", status="done", summary="risk: yüksek, düzelt"),
        ]
    )

    async def _delegate(*_args, **_kwargs):
        return next(responses)

    sup._delegate = _delegate
    result = asyncio.run(sup.run_task("kod yaz"))

    assert "[P2P:STOP] Circuit breaker tetiklendi" in result


def test_run_task_circuit_breaker_before_second_reviewer() -> None:
    """while içindeki ikinci reviewer öncesi _consume_turn dalını kapsar."""
    sup = _build_supervisor(max_qa_retries=2)
    sup._max_turns = lambda: 3

    responses = iter(
        [
            TaskResult(task_id="c1", status="done", summary="ilk kod"),
            TaskResult(task_id="r1", status="done", summary="risk: yüksek"),
            TaskResult(task_id="c2", status="done", summary="düzeltilmiş kod"),
        ]
    )

    async def _delegate(*_args, **_kwargs):
        return next(responses)

    sup._delegate = _delegate
    result = asyncio.run(sup.run_task("kod yaz"))

    assert "[P2P:STOP] Circuit breaker tetiklendi" in result


def test_supervisor_init_registers_and_gets_coverage_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Coverage:
        def __init__(self, _cfg=None) -> None:
            self.ready = True

    monkeypatch.setattr(supervisor_mod, "CoverageAgent", _Coverage)

    sup = SupervisorAgent()

    assert sup.coverage is not None
    assert getattr(sup.coverage, "ready", False) is True


def test_coerce_delegation_request_uses_bumped_payload_object() -> None:
    class _CompatRequest:
        def __init__(self) -> None:
            self.task_id = "t-1"
            self.reply_to = "reviewer"
            self.target_agent = "coder"
            self.payload = "fix"
            self.intent = "p2p"
            self.parent_task_id = "parent"
            self.handoff_depth = 2
            self.protocol = "p2p.v1"
            self.meta = {"source": "qa"}

        def bumped(self) -> object:
            return types.SimpleNamespace(
                task_id="t-2",
                reply_to="reviewer",
                target_agent="coder",
                payload="revise",
                intent="p2p",
                parent_task_id="parent",
                handoff_depth=3,
                protocol="p2p.v2",
                meta={"source": "review"},
            )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(supervisor_mod, "is_delegation_request", lambda _value: True)
    req = SupervisorAgent._coerce_delegation_request(_CompatRequest())
    monkeypatch.undo()

    assert isinstance(req, DelegationRequest)
    assert req.task_id == "t-2"
    assert req.handoff_depth == 3
    assert req.protocol == "p2p.v2"
    assert req.meta == {"source": "review"}


def test_coerce_delegation_request_returns_bumped_request_instance() -> None:
    bumped = DelegationRequest(
        task_id="t-9",
        reply_to="qa",
        target_agent="coder",
        payload="ship",
        intent="p2p",
        parent_task_id="p-1",
        handoff_depth=5,
        protocol="p2p.v3",
        meta={"source": "coverage"},
    )

    class _CompatRequest:
        def bumped(self) -> DelegationRequest:
            return bumped

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(supervisor_mod, "is_delegation_request", lambda _value: True)
    req = SupervisorAgent._coerce_delegation_request(_CompatRequest())
    monkeypatch.undo()

    assert req is bumped


def test_coerce_delegation_request_keeps_flow_when_bumped_returns_non_request_scalar() -> None:
    class _CompatRequest:
        def __init__(self) -> None:
            self.task_id = "t-raw"
            self.reply_to = "qa"
            self.target_agent = "reviewer"
            self.payload = "payload"
            self.intent = "mixed"
            self.parent_task_id = None
            self.handoff_depth = 0
            self.protocol = "p2p.v1"
            self.meta = {"m": 1}

        def bumped(self) -> object:
            return "not-a-request"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(supervisor_mod, "is_delegation_request", lambda _value: True)
    req = SupervisorAgent._coerce_delegation_request(_CompatRequest())
    monkeypatch.undo()

    assert isinstance(req, DelegationRequest)
    assert req.task_id == ""
    assert req.reply_to == ""
    assert req.target_agent == ""
