import json
from types import SimpleNamespace

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
    assert SwarmOrchestrator._should_fallback_to_supervisor(json.JSONDecodeError("bad", "{}", 0)) is True
    assert SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("429 Too many requests")) is True
    assert SwarmOrchestrator._should_fallback_to_supervisor(RuntimeError("network timeout")) is False


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
    context = SwarmOrchestrator._p2p_context({"k": "v"}, req, session_id="sess", hop=3, route_trace=["a", "b"])

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
        lambda role_name, **_kwargs: _RunTaskAgent("legacy ok") if role_name == "researcher" else None,
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
    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role: second_spec if role == "coder" else None)

    def _create(role_name, **_kwargs):
        if role_name == "reviewer":
            return _HandleAgent(_first_handle)
        if role_name == "coder":
            return _RunTaskAgent("patch hazir")
        raise KeyError(role_name)

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
