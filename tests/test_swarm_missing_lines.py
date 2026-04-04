from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import agent.swarm as swarm
from agent.core.contracts import DelegationRequest, TaskResult
from agent.swarm import SwarmOrchestrator, SwarmTask, SwarmResult, TaskRouter


def test_task_router_route_and_route_by_role(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Spec:
        def __init__(self, role_name: str) -> None:
            self.role_name = role_name

    monkeypatch.setattr("agent.registry.AgentCatalog.find_by_capability", lambda _cap: [_Spec("coder")])
    monkeypatch.setattr("agent.registry.AgentCatalog.get", lambda role: _Spec(role))

    router = TaskRouter()
    assert router.route("code_review").role_name == "coder"
    assert router.route_by_role("qa").role_name == "qa"


def test_dispatch_distributed_raises_without_backend_and_spec() -> None:
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    with pytest.raises(RuntimeError, match="yapılandırılmadı"):
        asyncio.run(orch.dispatch_distributed(SwarmTask(goal="x")))

    orch.configure_delegation_backend(swarm.InMemoryDelegationBackend())
    orch.router.route = lambda _intent: None
    with pytest.raises(RuntimeError, match="uygun ajan bulunamadı"):
        asyncio.run(orch.dispatch_distributed(SwarmTask(goal="x", intent="unknown")))


def test_loop_repeat_limit_and_browser_snapshot() -> None:
    orch_openai = SwarmOrchestrator(cfg=SimpleNamespace(AI_PROVIDER="openai"))
    orch_ollama = SwarmOrchestrator(cfg=SimpleNamespace(AI_PROVIDER="ollama"))
    orch_override = SwarmOrchestrator(cfg=SimpleNamespace(AI_PROVIDER="openai", SWARM_LOOP_GUARD_MAX_REPEAT=0))

    assert orch_openai._loop_repeat_limit() == 3
    assert orch_ollama._loop_repeat_limit() == 2
    assert orch_override._loop_repeat_limit() == 3

    snap = orch_openai._browser_context_snapshot({"browser_signal_summary": "  hi  "})
    assert snap["browser_session_id"] == ""
    assert snap["browser_signal_summary"] == "hi"


@pytest.mark.parametrize("reply", ["done", "  done  "])
def test_run_supervisor_fallback_success(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    class _Supervisor:
        def __init__(self, _cfg) -> None:
            pass

        async def run_task(self, _prompt: str) -> str:
            return reply

    fake_supervisor_mod = types.ModuleType("agent.core.supervisor")
    fake_supervisor_mod.SupervisorAgent = _Supervisor
    monkeypatch.setitem(sys.modules, "agent.core.supervisor", fake_supervisor_mod)

    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    res = asyncio.run(
        orch._run_supervisor_fallback(
            SwarmTask(task_id="t1", goal="g", intent="review"),
            session_id="s1",
            started_at=0.0,
            route_trace=["a", "b"],
            handoff_chain=[{"sender": "x"}],
            failed_role="coder",
            reason="fallback:ValueError",
        )
    )

    assert res.status == "success"
    assert res.agent_role == "supervisor"
    assert res.handoffs[-1]["receiver"] == "supervisor"


def test_run_supervisor_fallback_invalid_output_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Supervisor:
        def __init__(self, _cfg) -> None:
            pass

        async def run_task(self, _prompt: str) -> str:
            return "   "

    fake_supervisor_mod = types.ModuleType("agent.core.supervisor")
    fake_supervisor_mod.SupervisorAgent = _Supervisor
    monkeypatch.setitem(sys.modules, "agent.core.supervisor", fake_supervisor_mod)
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    with pytest.raises(RuntimeError, match="geçerli bir çıktı"):
        asyncio.run(
            orch._run_supervisor_fallback(
                SwarmTask(task_id="t2", goal="g"),
                session_id="s",
                started_at=0.0,
                route_trace=[],
                handoff_chain=[],
                failed_role="coder",
                reason="x",
            )
        )


def test_run_autonomous_feedback_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    flagged: list[dict[str, str]] = []

    async def _flag(**kwargs):
        flagged.append(kwargs)

    monkeypatch.setattr("core.active_learning.flag_weak_response", _flag)

    async def _run() -> None:
        await orch._run_autonomous_feedback(prompt="", response="r", context={}, session_id="s", agent_role="a", task_id="t")

        judge_disabled = SimpleNamespace(enabled=False)
        monkeypatch.setattr("core.judge.get_llm_judge", lambda: judge_disabled)
        await orch._run_autonomous_feedback(prompt="p", response="r", context={}, session_id="s", agent_role="a", task_id="t")

        judge_none = SimpleNamespace(enabled=True, evaluate_response=AsyncMock(return_value=None))
        monkeypatch.setattr("core.judge.get_llm_judge", lambda: judge_none)
        await orch._run_autonomous_feedback(prompt="p", response="r", context={}, session_id="s", agent_role="a", task_id="t")

        high = SimpleNamespace(score=9, reasoning="ok", provider="p", model="m")
        judge_high = SimpleNamespace(enabled=True, evaluate_response=AsyncMock(return_value=high))
        monkeypatch.setattr("core.judge.get_llm_judge", lambda: judge_high)
        await orch._run_autonomous_feedback(prompt="p", response="r", context={}, session_id="s", agent_role="a", task_id="t")

        low = SimpleNamespace(score=4, reasoning="bad", provider="p", model="m")
        judge_low = SimpleNamespace(enabled=True, evaluate_response=AsyncMock(return_value=low))
        monkeypatch.setattr("core.judge.get_llm_judge", lambda: judge_low)
        await orch._run_autonomous_feedback(prompt="p", response="r", context={}, session_id="s", agent_role="a", task_id="t")

        async def _boom(*_args, **_kwargs):
            raise RuntimeError("nope")

        judge_err = SimpleNamespace(enabled=True, evaluate_response=_boom)
        monkeypatch.setattr("core.judge.get_llm_judge", lambda: judge_err)
        await orch._run_autonomous_feedback(prompt="p", response="r", context={}, session_id="s", agent_role="a", task_id="t")

    asyncio.run(_run())
    assert flagged and flagged[0]["score"] == 4


def test_schedule_autonomous_feedback_runtimeerror_and_task_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    orch._schedule_autonomous_feedback(prompt="", response="r", context={}, session_id="s", agent_role="a", task_id="t")
    orch._schedule_autonomous_feedback(prompt="p", response="", context={}, session_id="s", agent_role="a", task_id="t")

    seen = {"ran": False}

    async def _fake_run(**_kwargs):
        seen["ran"] = True

    monkeypatch.setattr(orch, "_run_autonomous_feedback", _fake_run)

    async def _run() -> None:
        orch._schedule_autonomous_feedback(prompt="p", response="r", context={}, session_id="s", agent_role="a", task_id="t")
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert seen["ran"] is True


def test_p2p_context_and_direct_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    req = DelegationRequest(
        task_id="t",
        reply_to="src",
        target_agent="dst",
        payload="payload",
        intent="review",
        handoff_depth=2,
        meta={"reason": "need review"},
    )
    ctx = orch._p2p_context({"x": "1"}, req, session_id="s1", hop=3, route_trace=["a", "b"])
    assert ctx["p2p_receiver"] == "dst"
    assert ctx["swarm_hop"] == "3"

    with pytest.raises(RuntimeError, match="target_agent boş"):
        bad = DelegationRequest(task_id="t", reply_to="a", target_agent="", payload="x")
        asyncio.run(orch._direct_handoff(SwarmTask(goal="g"), bad, session_id="s", hop=1, route_trace=[], handoff_chain=[]))

    async def _fake_execute(task: SwarmTask, **kwargs):
        assert task.preferred_agent == "dst"
        assert kwargs["_parent_task_id"] == "t"
        return SwarmResult(task_id=task.task_id, agent_role="dst", status="success", summary="ok", elapsed_ms=1)

    monkeypatch.setattr(orch, "_execute_task", _fake_execute)
    out = asyncio.run(orch._direct_handoff(SwarmTask(task_id="t", goal="orig", intent="mixed"), req, session_id="s", hop=1, route_trace=["a"], handoff_chain=[]))
    assert out.agent_role == "dst"


def test_run_parallel_pipeline_and_run_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = SwarmOrchestrator(cfg=SimpleNamespace())

    async def _fake_execute(task: SwarmTask, **_kwargs):
        status = "success" if "ok" in task.goal else "failed"
        return SwarmResult(task_id=task.task_id, agent_role="r", status=status, summary=task.goal, elapsed_ms=1)

    monkeypatch.setattr(orch, "_execute_task", _fake_execute)

    single = asyncio.run(orch.run("ok-goal", intent="review", session_id="s"))
    assert single.summary == "ok-goal"

    parallel = asyncio.run(orch.run_parallel([SwarmTask(goal="ok-1"), SwarmTask(goal="ok-2")], session_id="s", max_concurrency=1))
    assert len(parallel) == 2

    t1 = SwarmTask(goal="ok-first", intent="review", context={})
    t2 = SwarmTask(goal="bad-second", intent="review", context={})
    pipe = asyncio.run(orch.run_pipeline([t1, t2], session_id="s"))
    assert len(pipe) == 2
    assert "prev_r" in t2.context


def test_execute_task_guard_and_factory_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = SwarmOrchestrator(cfg=SimpleNamespace())

    over_hop = asyncio.run(orch._execute_task(SwarmTask(task_id="t-hop", goal="g", preferred_agent="coder"), _hop=9))
    assert over_hop.status == "failed"

    orch.router.route = lambda _intent: SimpleNamespace(role_name="coder")
    loop_task = SwarmTask(task_id="t-loop", goal="repeat", intent="review")
    rt = ["coder|review|repeat", "coder|review|repeat", "coder|review|repeat"]
    looped = asyncio.run(orch._execute_task(loop_task, _route_trace=rt))
    assert looped.status == "failed"

    monkeypatch.setattr(swarm, "AgentCatalog", SimpleNamespace(create=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("create-fail"))))
    failed = asyncio.run(orch._execute_task(SwarmTask(task_id="t-create", goal="g", intent="review")))
    assert "Ajan oluşturulamadı" in failed.summary


def test_execute_task_retry_attribute_error_and_feedback_coroutine(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = SwarmOrchestrator(cfg=SimpleNamespace(SWARM_TASK_MAX_RETRIES=1, SWARM_TASK_RETRY_DELAY_MS=1))
    orch.router.route = lambda _intent: SimpleNamespace(role_name="role")

    class _AgentNoMethods:
        pass

    monkeypatch.setattr(swarm, "AgentCatalog", SimpleNamespace(create=lambda *_a, **_k: _AgentNoMethods()))
    out = asyncio.run(orch._execute_task(SwarmTask(task_id="t-attr", goal="g", intent="review")))
    assert out.status == "failed"

    calls = {"n": 0}

    class _RetryAgent:
        async def handle(self, _env):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("retry")
            return TaskResult(task_id="t", status="success", summary="ok", evidence=["e1"])

    monkeypatch.setattr(swarm, "AgentCatalog", SimpleNamespace(create=lambda *_a, **_k: _RetryAgent()))

    async def _fake_feedback(**_kwargs):
        return None

    monkeypatch.setattr(orch, "_schedule_autonomous_feedback", _fake_feedback)
    success = asyncio.run(orch._execute_task(SwarmTask(task_id="t-retry", goal="g", intent="review"), session_id="s"))
    assert success.status == "success"
    assert calls["n"] == 2


def test_execute_task_delegation_and_exception_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    orch.router.route = lambda _intent: SimpleNamespace(role_name="role")

    class _DelegatingAgent:
        async def handle(self, _env):
            req = DelegationRequest(task_id="t", reply_to="", target_agent="qa", payload="child", intent="review")
            return TaskResult(task_id="t", status="success", summary=req, evidence=[])

    monkeypatch.setattr(swarm, "AgentCatalog", SimpleNamespace(create=lambda *_a, **_k: _DelegatingAgent()))

    async def _fake_handoff(task, delegation, **_kwargs):
        assert delegation.reply_to == "role"
        return SwarmResult(task_id=task.task_id, agent_role="qa", status="success", summary="delegated", elapsed_ms=1)

    monkeypatch.setattr(orch, "_direct_handoff", _fake_handoff)
    delegated = asyncio.run(orch._execute_task(SwarmTask(task_id="t-del", goal="g", intent="review"), session_id="s"))
    assert delegated.agent_role == "qa"

    class _BoomAgent:
        async def handle(self, _env):
            raise ValueError("json malformed")

    monkeypatch.setattr(swarm, "AgentCatalog", SimpleNamespace(create=lambda *_a, **_k: _BoomAgent()))

    async def _fallback_ok(*_args, **_kwargs):
        return SwarmResult(task_id="t", agent_role="supervisor", status="success", summary="ok", elapsed_ms=1)

    monkeypatch.setattr(orch, "_run_supervisor_fallback", _fallback_ok)
    ok = asyncio.run(orch._execute_task(SwarmTask(task_id="t-fb", goal="g", intent="review")))
    assert ok.agent_role == "supervisor"

    async def _fallback_fail(*_args, **_kwargs):
        raise RuntimeError("fb-fail")

    monkeypatch.setattr(orch, "_run_supervisor_fallback", _fallback_fail)
    failed_fb = asyncio.run(orch._execute_task(SwarmTask(task_id="t-fb2", goal="g", intent="review")))
    assert failed_fb.status == "failed" and failed_fb.agent_role == "supervisor"

    class _NonFallbackAgent:
        async def handle(self, _env):
            raise RuntimeError("network hiccup")

    monkeypatch.setattr(swarm, "AgentCatalog", SimpleNamespace(create=lambda *_a, **_k: _NonFallbackAgent()))
    plain = asyncio.run(orch._execute_task(SwarmTask(task_id="t-plain", goal="g", intent="review")))
    assert plain.agent_role == "role"


def test_available_agents_and_active_task_count(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    orch._active_agents = {"t": object()}

    class _Spec:
        def __init__(self, role_name: str) -> None:
            self.role_name = role_name

    monkeypatch.setattr(swarm, "AgentCatalog", SimpleNamespace(list_all=lambda: [_Spec("a"), _Spec("b")]))

    assert orch.active_task_count == 1
    assert orch.available_agents() == ["a", "b"]
