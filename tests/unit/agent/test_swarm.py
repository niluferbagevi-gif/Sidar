import json
import sys
import types
from types import SimpleNamespace

import pytest

import agent.swarm as swarm
from agent.core.contracts import DelegationRequest, TaskResult
from agent.registry import AgentSpec
from agent.swarm import InMemoryDelegationBackend, SwarmOrchestrator, SwarmTask, TaskRouter


class _FakeCatalog:
    def __init__(self, specs):
        self._specs = list(specs)

    def find_by_capability(self, capability):
        return [spec for spec in self._specs if capability in (spec.capabilities or [])]

    def list_all(self):
        return list(self._specs)

    def get(self, role_name):
        for spec in self._specs:
            if spec.role_name == role_name:
                return spec
        return None


class _LegacyOnlyCatalog:
    def __init__(self, specs):
        self._specs = list(specs)

    def list_all(self):
        return list(self._specs)


class _HandleAgent:
    def __init__(self, result):
        self._result = result

    async def handle(self, envelope):
        value = self._result(envelope) if callable(self._result) else self._result
        if hasattr(value, "__await__"):
            return await value
        return value


class _RunTaskAgent:
    def __init__(self, text):
        self._text = text

    async def run_task(self, _goal):
        return self._text


class _NoHandlerAgent:
    pass


def test_fake_catalog_get_returns_match_and_none():
    coder = AgentSpec(role_name="coder", capabilities=["code_generation"])
    reviewer = AgentSpec(role_name="reviewer", capabilities=["code_review"])
    catalog = _FakeCatalog([coder, reviewer])

    assert catalog.get("coder") == coder
    assert catalog.get("missing") is None


def test_task_router_routes_by_intent_capability(monkeypatch):
    coder = AgentSpec(role_name="coder", capabilities=["code_generation"])
    reviewer = AgentSpec(role_name="reviewer", capabilities=["code_review"])
    fake_catalog = _FakeCatalog([coder, reviewer])
    monkeypatch.setattr(TaskRouter, "_catalog", staticmethod(lambda: fake_catalog))

    router = TaskRouter()
    assert router.route("code") == coder
    assert router.route("review") == reviewer


def test_task_router_fallbacks_to_first_agent_when_capability_missing(monkeypatch):
    only = AgentSpec(role_name="only", capabilities=[])
    fake_catalog = _FakeCatalog([only])
    monkeypatch.setattr(TaskRouter, "_catalog", staticmethod(lambda: fake_catalog))

    assert TaskRouter().route("not-mapped") == only


def test_task_router_route_by_role_supports_legacy_catalog_without_get(monkeypatch):
    qa = AgentSpec(role_name="qa", capabilities=["test_generation"])
    fake_catalog = _LegacyOnlyCatalog([qa])
    monkeypatch.setattr(TaskRouter, "_catalog", staticmethod(lambda: fake_catalog))

    assert TaskRouter().route_by_role("qa") == qa


def test_compose_goal_with_browser_context_appends_block():
    composed = SwarmOrchestrator._compose_goal_with_context(
        "Gorevi yap",
        {
            "browser_session_id": "s-1",
            "browser_signal_status": "warn",
            "browser_signal_risk": "medium",
            "browser_signal_summary": "Sayfada timeout goruldu",
        },
    )

    assert "[BROWSER_SIGNALS]" in composed
    assert "session_id=s-1" in composed
    assert "summary=Sayfada timeout goruldu" in composed


def test_should_fallback_to_supervisor_classifies_json_and_rate_limit_errors():
    assert (
        SwarmOrchestrator._should_fallback_to_supervisor(json.JSONDecodeError("bad", "{}", 0))
        is True
    )
    assert (
        SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("429 Too many requests"))
        is True
    )
    assert (
        SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("network timeout")) is False
    )


def test_goal_fingerprint_normalizes_and_truncates_text():
    fingerprint = SwarmOrchestrator._goal_fingerprint("  A   MIXED\nCase   Goal  ", max_chars=10)
    assert fingerprint == "a mixed ca"


def test_p2p_context_includes_protocol_trace_and_metadata():
    req = DelegationRequest(
        task_id="t1",
        reply_to="reviewer",
        target_agent="coder",
        payload="fix",
        intent="code_generation",
        handoff_depth=2,
        meta={"reason": "need patch"},
    )
    context = SwarmOrchestrator._p2p_context(
        {"k": "v"}, req, session_id="sess", hop=3, route_trace=["a", "b"]
    )

    assert context["k"] == "v"
    assert context["swarm_hop"] == "3"
    assert context["swarm_trace"] == "a -> b"
    assert context["p2p_reason"] == "need patch"


def test_execute_task_returns_skipped_when_no_agent(monkeypatch):
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: None)

    result = __import__("asyncio").run(
        orchestrator._execute_task(SwarmTask(goal="x", intent="unknown"), session_id="s")
    )

    assert result.status == "skipped"
    assert result.agent_role == "none"


def test_execute_task_uses_legacy_run_task_when_handle_missing(monkeypatch):
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    spec = AgentSpec(role_name="researcher", capabilities=["web_search"])
    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: spec)
    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create",
        lambda role_name, **_kwargs: _RunTaskAgent("legacy ok")
        if role_name == "researcher"
        else None,
    )

    result = __import__("asyncio").run(
        orchestrator._execute_task(SwarmTask(goal="Ara", intent="research"), session_id="sess-1")
    )

    assert result.status == "success"
    assert result.summary == "legacy ok"
    assert result.graph["receiver"] == "researcher"
    assert result.graph["session_id"] == "sess-1"


def test_execute_task_handles_delegation_request_and_handoff_chain(monkeypatch):
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    first_spec = AgentSpec(role_name="reviewer", capabilities=["code_review"])
    second_spec = AgentSpec(role_name="coder", capabilities=["code_generation"])

    delegation = DelegationRequest(
        task_id="swarm-1",
        reply_to="reviewer",
        target_agent="coder",
        payload="implement fix",
        intent="code_generation",
        meta={"reason": "patch gerekli"},
    )

    async def _first_handle(_envelope):
        return TaskResult(task_id="swarm-1", status="success", summary=delegation, evidence=[])

    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: first_spec)
    monkeypatch.setattr(
        orchestrator.router, "route_by_role", lambda role: second_spec if role == "coder" else None
    )

    def _create(role_name, **_kwargs):
        if role_name == "reviewer":
            return _HandleAgent(_first_handle)
        if role_name == "coder":
            return _RunTaskAgent("patch hazir")
        raise KeyError(role_name)

    with pytest.raises(KeyError):
        _create("unknown")

    monkeypatch.setattr("agent.swarm.AgentCatalog.create", _create)

    result = __import__("asyncio").run(
        orchestrator._execute_task(SwarmTask(goal="ilk", intent="review"), session_id="sess")
    )

    assert result.status == "success"
    assert result.agent_role == "coder"
    assert result.summary == "patch hazir"
    assert len(result.handoffs) == 1
    assert result.handoffs[0]["sender"] == "reviewer"
    assert result.handoffs[0]["receiver"] == "coder"


def test_execute_task_loop_guard_triggers_on_repeated_step(monkeypatch):
    cfg = SimpleNamespace(SWARM_LOOP_GUARD_MAX_REPEAT=1)
    orchestrator = SwarmOrchestrator(cfg=cfg)
    spec = AgentSpec(role_name="coder", capabilities=["code_generation"])
    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: spec)

    repeated_trace = [f"coder|code|{orchestrator._goal_fingerprint('aynı görev')}"]
    result = __import__("asyncio").run(
        orchestrator._execute_task(
            SwarmTask(goal="aynı görev", intent="code"),
            _route_trace=repeated_trace,
        )
    )

    assert result.status == "failed"
    assert "loop guard" in result.summary.lower()


def test_dispatch_distributed_pushes_task_to_backend(monkeypatch):
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    backend = InMemoryDelegationBackend()
    orchestrator.configure_delegation_backend(backend)

    reviewer = AgentSpec(role_name="reviewer", capabilities=["code_review"])
    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: reviewer)
    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda _role: reviewer)

    task = SwarmTask(goal="Kod incele", intent="review")
    result = __import__("asyncio").run(
        orchestrator.dispatch_distributed(task, session_id="sess-42", sender="supervisor")
    )

    assert result.status == "queued"
    assert result.receiver == "supervisor"
    assert len(backend.dispatched) == 1
    dispatched = backend.dispatched[0]
    assert dispatched.receiver == "reviewer"
    assert dispatched.headers["session_id"] == "sess-42"


def test_is_contracts_module_healthy_rejects_invalid_contract_module():
    empty = SimpleNamespace()
    assert swarm._is_contracts_module_healthy(empty) is False

    bad_type = SimpleNamespace(
        TaskEnvelope=lambda **_k: None,
        TaskResult=lambda **_k: None,
        DelegationRequest=object,
        BrokerTaskEnvelope=object(),
        BrokerTaskResult=object(),
        is_delegation_request=lambda _v: False,
    )
    assert swarm._is_contracts_module_healthy(bad_type) is False


def test_contracts_module_returns_original_when_spec_or_loader_missing(monkeypatch):
    broken = SimpleNamespace(
        TaskEnvelope=lambda **_k: None,
        TaskResult=lambda **_k: None,
        DelegationRequest=object,
        BrokerTaskEnvelope=object(),
        BrokerTaskResult=object(),
        is_delegation_request=lambda _v: False,
    )
    monkeypatch.setattr(swarm.importlib, "import_module", lambda _name: broken)
    monkeypatch.setattr(swarm.importlib.util, "spec_from_file_location", lambda *_a, **_k: None)

    assert swarm._contracts_module() is broken


def test_task_router_catalog_prefers_local_when_live_catalog_invalid(monkeypatch):
    local_catalog = _FakeCatalog([AgentSpec(role_name="coder", capabilities=["code_generation"])])
    monkeypatch.setattr(
        swarm.importlib,
        "import_module",
        lambda _name: SimpleNamespace(AgentCatalog=SimpleNamespace()),
    )
    monkeypatch.setattr(swarm, "AgentCatalog", local_catalog)
    assert TaskRouter._catalog() is local_catalog


def test_task_router_route_by_role_returns_none_when_catalog_without_get_or_list(monkeypatch):
    monkeypatch.setattr(TaskRouter, "_catalog", staticmethod(lambda: SimpleNamespace()))
    assert TaskRouter().route_by_role("anything") is None


def test_looks_like_delegation_request_with_fallback_attributes(monkeypatch):
    monkeypatch.setattr(swarm, "_ensure_contract_aliases", lambda: None)
    monkeypatch.setattr(
        swarm, "is_delegation_request", lambda _v: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    candidate = SimpleNamespace(target_agent="coder", payload="x", reply_to="reviewer")
    assert swarm._looks_like_delegation_request(candidate) is True


def test_dispatch_distributed_requires_backend_and_matching_agent(monkeypatch):
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    task = SwarmTask(goal="x", intent="unknown")

    with pytest.raises(RuntimeError, match="(?i)backend"):
        __import__("asyncio").run(orchestrator.dispatch_distributed(task))

    orchestrator.configure_delegation_backend(InMemoryDelegationBackend())
    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: None)
    with pytest.raises(RuntimeError, match="(?i)uygun ajan"):
        __import__("asyncio").run(orchestrator.dispatch_distributed(task))


def test_loop_repeat_limit_honors_provider_and_floor():
    assert SwarmOrchestrator(cfg=SimpleNamespace(AI_PROVIDER="ollama"))._loop_repeat_limit() == 2
    assert (
        SwarmOrchestrator(cfg=SimpleNamespace(SWARM_LOOP_GUARD_MAX_REPEAT=-1))._loop_repeat_limit()
        == 1
    )


def test_run_supervisor_fallback_success_and_invalid_output(monkeypatch):
    class _Supervisor:
        def __init__(self, _cfg):
            pass

        async def run_task(self, _prompt):
            return "fallback yaniti"

    monkeypatch.setitem(
        sys.modules, "agent.core.supervisor", types.SimpleNamespace(SupervisorAgent=_Supervisor)
    )
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    task = SwarmTask(goal="g", intent="review", task_id="t-1")
    ok = __import__("asyncio").run(
        orch._run_supervisor_fallback(
            task,
            session_id="s-1",
            started_at=0.0,
            route_trace=["r1"],
            handoff_chain=[],
            failed_role="reviewer",
            reason="fallback:JSONDecodeError",
        )
    )
    assert ok.status == "success"
    assert ok.agent_role == "supervisor"

    class _EmptySupervisor(_Supervisor):
        async def run_task(self, _prompt):
            return "   "

    monkeypatch.setitem(
        sys.modules,
        "agent.core.supervisor",
        types.SimpleNamespace(SupervisorAgent=_EmptySupervisor),
    )
    with pytest.raises(RuntimeError, match="geçerli bir çıktı"):
        __import__("asyncio").run(
            orch._run_supervisor_fallback(
                task,
                session_id="s-1",
                started_at=0.0,
                route_trace=["r1"],
                handoff_chain=[],
                failed_role="reviewer",
                reason="fallback:JSONDecodeError",
            )
        )


def test_run_autonomous_feedback_low_score_flags_and_handles_errors(monkeypatch):
    calls = []

    class _Judge:
        enabled = True

        async def evaluate_response(self, **_kwargs):
            return SimpleNamespace(score=4, reasoning="weak", provider="p", model="m")

    async def _flag_weak_response(**kwargs):
        calls.append(kwargs)

    monkeypatch.setitem(
        sys.modules, "core.judge", types.SimpleNamespace(get_llm_judge=lambda: _Judge())
    )
    monkeypatch.setitem(
        sys.modules,
        "core.active_learning",
        types.SimpleNamespace(flag_weak_response=_flag_weak_response),
    )

    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    __import__("asyncio").run(
        orch._run_autonomous_feedback(
            prompt="p",
            response="r",
            context={},
            session_id="s",
            agent_role="coder",
            task_id="t1",
        )
    )
    assert len(calls) == 1
    assert "swarm:auto" in calls[0]["tags"]

    class _BoomJudge(_Judge):
        async def evaluate_response(self, **_kwargs):
            raise RuntimeError("judge down")

    monkeypatch.setitem(
        sys.modules, "core.judge", types.SimpleNamespace(get_llm_judge=lambda: _BoomJudge())
    )
    __import__("asyncio").run(
        orch._run_autonomous_feedback(
            prompt="p",
            response="r",
            context={},
            session_id="s",
            agent_role="coder",
            task_id="t2",
        )
    )


def test_schedule_autonomous_feedback_outside_event_loop_noop():
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    orch._schedule_autonomous_feedback(
        prompt="p",
        response="r",
        context={},
        session_id="s",
        agent_role="coder",
        task_id="t",
    )


def test_direct_handoff_requires_target_agent():
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    bad = DelegationRequest(task_id="t", reply_to="reviewer", target_agent="", payload="x")
    with pytest.raises(RuntimeError, match="target_agent"):
        __import__("asyncio").run(
            orch._direct_handoff(
                SwarmTask(goal="g"),
                bad,
                session_id="s",
                hop=1,
                route_trace=[],
                handoff_chain=[],
            )
        )


def test_run_and_parallel_and_pipeline_methods(monkeypatch):
    orch = SwarmOrchestrator(cfg=SimpleNamespace())

    async def _fake_execute(task, **_kwargs):
        return swarm.SwarmResult(
            task_id=task.task_id,
            agent_role="coder",
            status="success",
            summary=f"ok:{task.goal}",
            elapsed_ms=1,
        )

    monkeypatch.setattr(orch, "_execute_task", _fake_execute)
    single = __import__("asyncio").run(orch.run("tek", intent="code"))
    assert single.summary == "ok:tek"

    parallel = __import__("asyncio").run(
        orch.run_parallel([SwarmTask(goal="a"), SwarmTask(goal="b")], max_concurrency=1)
    )
    assert [r.summary for r in parallel] == ["ok:a", "ok:b"]

    tasks = [SwarmTask(goal="one", context={}), SwarmTask(goal="two", context={})]
    pipeline = __import__("asyncio").run(orch.run_pipeline(tasks))
    assert len(pipeline) == 2
    assert tasks[1].context["prev_coder"] == "ok:one"


def test_execute_task_handles_creation_retry_and_fallback_paths(monkeypatch):
    cfg = SimpleNamespace(SWARM_TASK_MAX_RETRIES=1, SWARM_TASK_RETRY_DELAY_MS=0)
    orch = SwarmOrchestrator(cfg=cfg)
    spec = AgentSpec(role_name="coder", capabilities=["code_generation"])
    monkeypatch.setattr(orch.router, "route", lambda _intent: spec)

    # create error
    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bad create")),
    )
    failed_create = __import__("asyncio").run(
        orch._execute_task(SwarmTask(goal="g", intent="code"))
    )
    assert failed_create.status == "failed"
    assert "oluşturulamadı" in failed_create.summary

    # missing handler methods -> generic failure
    monkeypatch.setattr("agent.swarm.AgentCatalog.create", lambda *_a, **_k: _NoHandlerAgent())
    missing_handler = __import__("asyncio").run(
        orch._execute_task(SwarmTask(goal="g", intent="code"))
    )
    assert missing_handler.status == "failed"
    assert "Görev başarısız" in missing_handler.summary

    # retry path where first call fails, second returns None -> re-raises last exception
    state = {"n": 0}

    class _FlakyAgent:
        async def handle(self, _env):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("temporary")
            return None

    monkeypatch.setattr("agent.swarm.AgentCatalog.create", lambda *_a, **_k: _FlakyAgent())
    retry_failed = __import__("asyncio").run(orch._execute_task(SwarmTask(goal="g", intent="code")))
    assert retry_failed.status == "failed"
    assert "temporary" in retry_failed.summary


def test_execute_task_handles_empty_retry_iteration(monkeypatch):
    orch = SwarmOrchestrator(
        cfg=SimpleNamespace(SWARM_TASK_MAX_RETRIES=0, SWARM_TASK_RETRY_DELAY_MS=0)
    )
    spec = AgentSpec(role_name="coder", capabilities=["code_generation"])
    monkeypatch.setattr(orch.router, "route", lambda _intent: spec)
    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create",
        lambda *_a, **_k: _HandleAgent(
            TaskResult(task_id="t", status="success", summary="done", evidence=[])
        ),
    )
    monkeypatch.setattr(swarm, "range", lambda *_args: [], raising=False)

    result = __import__("asyncio").run(orch._execute_task(SwarmTask(goal="g", intent="code")))
    assert result.status == "failed"
    assert "NoneType" in result.summary


def test_execute_task_fallback_success_failure_and_feedback_coroutine(monkeypatch):
    spec = AgentSpec(role_name="coder", capabilities=["code_generation"])

    # fallback success
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    monkeypatch.setattr(orch.router, "route", lambda _intent: spec)

    class _BoomAgent:
        async def handle(self, _env):
            raise json.JSONDecodeError("bad", "{}", 0)

    monkeypatch.setattr("agent.swarm.AgentCatalog.create", lambda *_a, **_k: _BoomAgent())
    monkeypatch.setattr(
        orch,
        "_run_supervisor_fallback",
        lambda *args, **kwargs: __import__("asyncio").sleep(
            0,
            result=swarm.SwarmResult(
                task_id="t",
                agent_role="supervisor",
                status="success",
                summary="fallback",
                elapsed_ms=1,
            ),
        ),
    )
    fallback_ok = __import__("asyncio").run(orch._execute_task(SwarmTask(goal="x", intent="code")))
    assert fallback_ok.agent_role == "supervisor"

    # fallback fail
    orch2 = SwarmOrchestrator(cfg=SimpleNamespace())
    monkeypatch.setattr(orch2.router, "route", lambda _intent: spec)
    monkeypatch.setattr("agent.swarm.AgentCatalog.create", lambda *_a, **_k: _BoomAgent())

    async def _fallback_fail(*_a, **_k):
        raise RuntimeError("supervisor unavailable")

    monkeypatch.setattr(orch2, "_run_supervisor_fallback", _fallback_fail)
    fallback_fail = __import__("asyncio").run(
        orch2._execute_task(SwarmTask(goal="x", intent="code"))
    )
    assert fallback_fail.status == "failed"
    assert "Supervisor fallback" in fallback_fail.summary

    # success path awaiting feedback coroutine
    orch3 = SwarmOrchestrator(cfg=SimpleNamespace())
    monkeypatch.setattr(orch3.router, "route", lambda _intent: spec)
    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create",
        lambda *_a, **_k: _HandleAgent(
            TaskResult(task_id="t", status="success", summary="done", evidence=[])
        ),
    )
    marker = {"awaited": False}

    async def _waited(**_kwargs):
        marker["awaited"] = True

    monkeypatch.setattr(orch3, "_schedule_autonomous_feedback", lambda **_kwargs: _waited())
    ok = __import__("asyncio").run(orch3._execute_task(SwarmTask(goal="x", intent="code")))
    assert ok.status == "success"
    assert marker["awaited"] is True


def test_execute_task_hop_limit_and_properties(monkeypatch):
    cfg = SimpleNamespace(SWARM_MAX_HANDOFF_HOPS=1)
    orch = SwarmOrchestrator(cfg=cfg)
    hop_fail = __import__("asyncio").run(
        orch._execute_task(
            SwarmTask(goal="g", preferred_agent="coder"), _hop=2, _handoff_chain=[{"x": "y"}]
        )
    )
    assert hop_fail.status == "failed"
    assert hop_fail.handoffs == [{"x": "y"}]

    orch._active_agents["t"] = object()
    assert orch.active_task_count == 1

    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.list_all", lambda: [AgentSpec(role_name="qa", capabilities=[])]
    )
    assert orch.available_agents() == ["qa"]


def test_contract_health_check_handles_constructor_exceptions():
    class _ExplodingModule:
        DelegationRequest = DelegationRequest
        BrokerTaskEnvelope = object()
        BrokerTaskResult = object()
        is_delegation_request = staticmethod(lambda _v: False)

        @staticmethod
        def TaskEnvelope(**_kwargs):
            raise RuntimeError("broken ctor")

        @staticmethod
        def TaskResult(**_kwargs):
            return None

    assert _ExplodingModule.TaskResult() is None
    assert swarm._is_contracts_module_healthy(_ExplodingModule) is False


def test_contracts_module_repairs_when_imported_module_is_unhealthy(monkeypatch):
    broken = SimpleNamespace()

    class _Loader:
        @staticmethod
        def exec_module(module):
            module.TaskEnvelope = lambda **_k: SimpleNamespace(**_k)
            module.TaskResult = lambda **_k: SimpleNamespace(**_k)
            module.DelegationRequest = lambda **_k: SimpleNamespace(**_k)
            module.BrokerTaskEnvelope = object
            module.BrokerTaskResult = object
            module.is_delegation_request = lambda _v: False

    class _Spec:
        loader = _Loader()

    monkeypatch.setattr(swarm.importlib, "import_module", lambda _name: broken)
    monkeypatch.setattr(swarm.importlib.util, "spec_from_file_location", lambda *_a, **_k: _Spec())
    monkeypatch.setattr(swarm.importlib.util, "module_from_spec", lambda _spec: SimpleNamespace())

    repaired = swarm._contracts_module()
    assert callable(repaired.TaskEnvelope)
    assert "agent.core.contracts" in sys.modules


def test_task_router_catalog_prefers_valid_live_catalog_and_last_resort_live(monkeypatch):
    live = _FakeCatalog([AgentSpec(role_name="coder", capabilities=["code_generation"])])
    monkeypatch.setattr(
        swarm.importlib, "import_module", lambda _name: SimpleNamespace(AgentCatalog=live)
    )
    assert TaskRouter._catalog() is live

    invalid_live = SimpleNamespace()
    monkeypatch.setattr(
        swarm.importlib, "import_module", lambda _name: SimpleNamespace(AgentCatalog=invalid_live)
    )
    monkeypatch.setattr(swarm, "AgentCatalog", SimpleNamespace())
    assert TaskRouter._catalog() is invalid_live


def test_task_router_route_by_role_with_get_and_list_iteration(monkeypatch):
    qa = AgentSpec(role_name="qa", capabilities=[])
    with_get = SimpleNamespace(get=lambda role: qa if role == "qa" else None)
    monkeypatch.setattr(TaskRouter, "_catalog", staticmethod(lambda: with_get))
    assert TaskRouter().route_by_role("qa") == qa

    with_list = _LegacyOnlyCatalog(
        [
            AgentSpec(role_name="coder", capabilities=[]),
            AgentSpec(role_name="reviewer", capabilities=[]),
        ]
    )
    monkeypatch.setattr(TaskRouter, "_catalog", staticmethod(lambda: with_list))
    assert TaskRouter().route_by_role("missing") is None


def test_looks_like_delegation_request_when_checker_not_callable(monkeypatch):
    monkeypatch.setattr(swarm, "_ensure_contract_aliases", lambda: None)
    monkeypatch.setattr(swarm, "is_delegation_request", "not-callable")
    candidate = SimpleNamespace(target_agent="coder", payload="x", reply_to="reviewer")
    assert swarm._looks_like_delegation_request(candidate) is True


def test_should_fallback_to_supervisor_json_signals_on_type_and_text():
    class JsonSchemaError(Exception):
        pass

    assert SwarmOrchestrator._should_fallback_to_supervisor(JsonSchemaError("boom")) is True
    assert (
        SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("malformed payload")) is True
    )


def test_run_autonomous_feedback_early_return_paths_and_schedule_guard(monkeypatch):
    orch = SwarmOrchestrator(cfg=SimpleNamespace())

    __import__("asyncio").run(
        orch._run_autonomous_feedback(
            prompt="",
            response="r",
            context={},
            session_id="s",
            agent_role="coder",
            task_id="t0",
        )
    )

    class _Judge:
        enabled = True

        async def evaluate_response(self, **_kwargs):
            return None

    monkeypatch.setitem(
        sys.modules, "core.judge", types.SimpleNamespace(get_llm_judge=lambda: _Judge())
    )
    monkeypatch.setitem(
        sys.modules,
        "core.active_learning",
        types.SimpleNamespace(
            flag_weak_response=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("unused"))
        ),
    )
    __import__("asyncio").run(
        orch._run_autonomous_feedback(
            prompt="p",
            response="r",
            context={},
            session_id="s",
            agent_role="coder",
            task_id="t1",
        )
    )

    orch._schedule_autonomous_feedback(
        prompt="",
        response="r",
        context={},
        session_id="s",
        agent_role="coder",
        task_id="t",
    )


def test_run_pipeline_skips_context_on_failed_result(monkeypatch):
    orch = SwarmOrchestrator(cfg=SimpleNamespace())

    async def _fake_execute(task, **_kwargs):
        status = "failed" if task.goal == "one" else "success"
        return swarm.SwarmResult(
            task_id=task.task_id,
            agent_role="coder",
            status=status,
            summary=f"res:{task.goal}",
            elapsed_ms=1,
        )

    monkeypatch.setattr(orch, "_execute_task", _fake_execute)
    tasks = [SwarmTask(goal="one", context={}), SwarmTask(goal="two", context={})]
    __import__("asyncio").run(orch.run_pipeline(tasks))
    assert "prev_coder" not in tasks[1].context


def test_execute_task_sets_reply_to_and_skips_feedback_for_non_success(monkeypatch):
    orch = SwarmOrchestrator(cfg=SimpleNamespace())
    spec = AgentSpec(role_name="reviewer", capabilities=["code_review"])
    monkeypatch.setattr(orch.router, "route", lambda _intent: spec)

    delegation = DelegationRequest(
        task_id="swarm-r",
        reply_to="",
        target_agent="coder",
        payload="devret",
        intent="code_generation",
    )

    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create",
        lambda *_a, **_k: _HandleAgent(
            TaskResult(task_id="swarm-r", status="success", summary=delegation, evidence=[])
        ),
    )
    seen = {}

    async def _fake_handoff(_task, bumped, **_kwargs):
        seen["reply_to"] = bumped.reply_to
        return swarm.SwarmResult(
            task_id="swarm-r",
            agent_role="coder",
            status="failed",
            summary="handoff done",
            elapsed_ms=1,
        )

    monkeypatch.setattr(orch, "_direct_handoff", _fake_handoff)
    res = __import__("asyncio").run(orch._execute_task(SwarmTask(goal="g", intent="review")))
    assert res.status == "failed"
    assert seen["reply_to"] == "reviewer"

    orch2 = SwarmOrchestrator(cfg=SimpleNamespace())
    spec2 = AgentSpec(role_name="coder", capabilities=["code_generation"])
    monkeypatch.setattr(orch2.router, "route", lambda _intent: spec2)
    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create",
        lambda *_a, **_k: _HandleAgent(
            TaskResult(task_id="t", status="failed", summary="nope", evidence=[])
        ),
    )
    called = {"scheduled": False}
    monkeypatch.setattr(
        orch2,
        "_schedule_autonomous_feedback",
        lambda **_kwargs: called.__setitem__("scheduled", True),
    )
    result = __import__("asyncio").run(orch2._execute_task(SwarmTask(goal="x", intent="code")))
    assert result.status == "failed"
    assert called["scheduled"] is False


def test_swarm_execute_task_is_isolated(monkeypatch):
    orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
    spec = AgentSpec(role_name="researcher", capabilities=["web_search"])

    class _RunTaskAgent:
        async def run_task(self, _goal: str) -> str:
            return "isolated-ok"

    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: spec)
    monkeypatch.setattr(
        "agent.swarm.AgentCatalog.create", lambda *_args, **_kwargs: _RunTaskAgent()
    )

    result = __import__("asyncio").run(
        orchestrator._execute_task(SwarmTask(goal="araştır", intent="research"), session_id="s-1")
    )

    assert result.status == "success"
    assert result.summary == "isolated-ok"
