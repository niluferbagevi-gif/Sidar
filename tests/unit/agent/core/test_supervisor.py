from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest


# supervisor modülünü güvenli import edebilmek için ağır bağımlılıkları stub'la
class _StubBaseAgent:
    def __init__(self, cfg=None, role_name="stub") -> None:
        self.cfg = cfg
        self.role_name = role_name


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
_register_stub_module("agent.roles.coverage_agent", "CoverageAgent")

event_stream_mod = types.ModuleType("agent.core.event_stream")


class _StubEventBus:
    async def publish(self, source: str, message: str) -> None:
        return None


def get_agent_event_bus():
    return _StubEventBus()


event_stream_mod.get_agent_event_bus = get_agent_event_bus
sys.modules["agent.core.event_stream"] = event_stream_mod

from agent.core.contracts import DelegationRequest, TaskResult
from agent.core.supervisor import SupervisorAgent

class _DummyEvents:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def publish(self, source: str, message: str) -> None:
        self.messages.append((source, message))


class _DummyMemoryHub:
    def __init__(self) -> None:
        self.global_notes: list[str] = []

    def add_global(self, note: str) -> None:
        self.global_notes.append(note)


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
