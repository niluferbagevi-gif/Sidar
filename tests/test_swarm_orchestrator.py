import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def swarm_module(monkeypatch):
    agent_pkg = types.ModuleType("agent")
    agent_pkg.__path__ = [str(ROOT / "agent")]
    core_pkg = types.ModuleType("agent.core")
    core_pkg.__path__ = [str(ROOT / "agent" / "core")]

    monkeypatch.setitem(sys.modules, "agent", agent_pkg)
    monkeypatch.setitem(sys.modules, "agent.core", core_pkg)

    contracts_spec = importlib.util.spec_from_file_location(
        "agent.core.contracts",
        ROOT / "agent" / "core" / "contracts.py",
    )
    contracts_module = importlib.util.module_from_spec(contracts_spec)
    assert contracts_spec and contracts_spec.loader
    monkeypatch.setitem(sys.modules, "agent.core.contracts", contracts_module)
    contracts_spec.loader.exec_module(contracts_module)

    registry_spec = importlib.util.spec_from_file_location(
        "agent.registry",
        ROOT / "agent" / "registry.py",
    )
    registry_module = importlib.util.module_from_spec(registry_spec)
    assert registry_spec and registry_spec.loader
    monkeypatch.setitem(sys.modules, "agent.registry", registry_module)
    registry_spec.loader.exec_module(registry_module)

    swarm_spec = importlib.util.spec_from_file_location(
        "agent.swarm",
        ROOT / "agent" / "swarm.py",
    )
    swarm = importlib.util.module_from_spec(swarm_spec)
    assert swarm_spec and swarm_spec.loader
    monkeypatch.setitem(sys.modules, "agent.swarm", swarm)
    swarm_spec.loader.exec_module(swarm)
    return swarm


class _DummySpec:
    def __init__(self, role_name: str):
        self.role_name = role_name


def test_swarm_orchestrator_routes_and_executes_task(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())

    class _DummyAgent:
        async def handle(self, envelope):
            assert envelope.goal == "Kod incele"
            assert envelope.intent == "code_review"
            assert envelope.receiver == "reviewer"
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary="İnceleme tamamlandı",
                evidence=["lint", "tests"],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda intent: _DummySpec("reviewer"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda role_name, **kwargs: _DummyAgent())

    result = asyncio.run(orchestrator.run("Kod incele", intent="code_review", session_id="sess-1"))

    assert result.agent_role == "reviewer"
    assert result.status == "success"
    assert result.summary == "İnceleme tamamlandı"
    assert result.evidence == ["lint", "tests"]
    assert orchestrator.active_task_count == 0


def test_swarm_orchestrator_run_parallel_processes_all_tasks(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())

    class _DummyAgent:
        async def handle(self, envelope):
            await asyncio.sleep(0.01)
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary=f"done:{envelope.goal}",
                evidence=[envelope.intent],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda intent: _DummySpec("coder"))
    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role_name: _DummySpec(role_name))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda role_name, **kwargs: _DummyAgent())

    tasks = [
        swarm_module.SwarmTask(goal="Görev-1", intent="code_generation"),
        swarm_module.SwarmTask(goal="Görev-2", intent="code_review"),
        swarm_module.SwarmTask(goal="Görev-3", intent="security_audit"),
    ]
    results = asyncio.run(orchestrator.run_parallel(tasks, session_id="sess-par", max_concurrency=2))

    assert len(results) == 3
    assert {r.summary for r in results} == {"done:Görev-1", "done:Görev-2", "done:Görev-3"}
    assert all(r.status == "success" for r in results)


def test_swarm_orchestrator_retries_when_agent_fails(monkeypatch, swarm_module):
    cfg = SimpleNamespace(SWARM_TASK_MAX_RETRIES=1, SWARM_TASK_RETRY_DELAY_MS=0)
    orchestrator = swarm_module.SwarmOrchestrator(cfg=cfg)
    call_counter = {"count": 0}

    class _FlakyAgent:
        async def handle(self, envelope):
            call_counter["count"] += 1
            if call_counter["count"] == 1:
                raise RuntimeError("geçici hata")
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary="retry ile başarılı",
                evidence=["retry"],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda intent: _DummySpec("researcher"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda role_name, **kwargs: _FlakyAgent())

    result = asyncio.run(orchestrator.run("Araştır", intent="research"))

    assert call_counter["count"] == 2
    assert result.status == "success"
    assert result.summary == "retry ile başarılı"


def test_swarm_orchestrator_returns_failed_after_retry_limit(monkeypatch, swarm_module):
    cfg = SimpleNamespace(SWARM_TASK_MAX_RETRIES=1, SWARM_TASK_RETRY_DELAY_MS=0)
    orchestrator = swarm_module.SwarmOrchestrator(cfg=cfg)
    call_counter = {"count": 0}

    class _AlwaysFailAgent:
        async def handle(self, envelope):
            call_counter["count"] += 1
            raise RuntimeError("kalıcı hata")

    monkeypatch.setattr(orchestrator.router, "route", lambda intent: _DummySpec("reviewer"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda role_name, **kwargs: _AlwaysFailAgent())

    result = asyncio.run(orchestrator.run("Güvenlik kontrolü", intent="security"))

    assert call_counter["count"] == 2
    assert result.status == "failed"
    assert "kalıcı hata" in result.summary


def test_swarm_orchestrator_follows_single_delegation(monkeypatch, swarm_module):
    cfg = SimpleNamespace(SWARM_MAX_HANDOFF_HOPS=4, SWARM_LOOP_GUARD_MAX_REPEAT=3)
    orchestrator = swarm_module.SwarmOrchestrator(cfg=cfg)

    class _DelegatingCoder:
        async def handle(self, envelope):
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary=swarm_module.DelegationRequest(
                    task_id=envelope.task_id,
                    reply_to="coder",
                    target_agent="reviewer",
                    payload="Kod incele",
                    meta={"reason": "need_review"},
                ),
                evidence=[],
            )

    class _Reviewer:
        async def handle(self, envelope):
            assert envelope.receiver == "reviewer"
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary="inceleme tamam",
                evidence=["review-ok"],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda intent: _DummySpec("coder"))
    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role_name: _DummySpec(role_name))
    monkeypatch.setattr(
        swarm_module.AgentRegistry,
        "create",
        lambda role_name, **kwargs: _DelegatingCoder() if role_name == "coder" else _Reviewer(),
    )

    result = asyncio.run(orchestrator.run("Kod yaz", intent="code_generation", session_id="s-1"))
    assert result.status == "success"
    assert result.agent_role == "reviewer"
    assert result.summary == "inceleme tamam"


def test_swarm_orchestrator_loop_guard_stops_recursive_delegation(monkeypatch, swarm_module):
    cfg = SimpleNamespace(
        AI_PROVIDER="ollama",
        SWARM_MAX_HANDOFF_HOPS=10,
        SWARM_LOOP_GUARD_MAX_REPEAT=2,
    )
    orchestrator = swarm_module.SwarmOrchestrator(cfg=cfg)

    class _LoopingAgent:
        async def handle(self, envelope):
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary=swarm_module.DelegationRequest(
                    task_id=envelope.task_id,
                    reply_to="coder",
                    target_agent="coder",
                    payload="Aynı işi tekrar yap",
                    meta={"reason": "loop"},
                ),
                evidence=[],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda intent: _DummySpec("coder"))
    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role_name: _DummySpec(role_name))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda role_name, **kwargs: _LoopingAgent())

    result = asyncio.run(orchestrator.run("Aynı işi tekrar yap", intent="code_generation", session_id="s-loop"))
    assert result.status == "failed"
    assert "Recursive loop guard" in result.summary


def test_swarm_orchestrator_run_pipeline_carries_previous_success_context(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())

    seen_contexts = []

    class _PipelineAgent:
        async def handle(self, envelope):
            seen_contexts.append(dict(envelope.context))
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary=f"ok:{envelope.goal}",
                evidence=[envelope.receiver],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda intent: _DummySpec("coder"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda role_name, **kwargs: _PipelineAgent())

    tasks = [
        swarm_module.SwarmTask(goal="A", intent="code_generation", context={"seed": "1"}),
        swarm_module.SwarmTask(goal="B", intent="code_review", context={}),
    ]
    results = asyncio.run(orchestrator.run_pipeline(tasks, session_id="sess-pipe"))

    assert len(results) == 2
    assert all(r.status == "success" for r in results)
    assert "prev_coder" not in seen_contexts[0]
    assert seen_contexts[1]["prev_coder"].startswith("ok:A")
    assert seen_contexts[1]["session_id"] == "sess-pipe"


def test_swarm_orchestrator_loop_guard_stops_at_max_hops(monkeypatch, swarm_module):
    cfg = SimpleNamespace(SWARM_MAX_HANDOFF_HOPS=1, SWARM_LOOP_GUARD_MAX_REPEAT=99)
    orchestrator = swarm_module.SwarmOrchestrator(cfg=cfg)

    class _DelegatingAgent:
        async def handle(self, envelope):
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary=swarm_module.DelegationRequest(
                    task_id=envelope.task_id,
                    reply_to=envelope.receiver,
                    target_agent="reviewer" if envelope.receiver == "coder" else "researcher",
                    payload=f"next:{envelope.receiver}",
                    meta={"reason": "chain"},
                ),
                evidence=[],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda intent: _DummySpec("coder"))
    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role_name: _DummySpec(role_name))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda role_name, **kwargs: _DelegatingAgent())

    result = asyncio.run(orchestrator.run("delegasyon zinciri", intent="mixed", session_id="s-hop"))

    assert result.status == "failed"
    assert "maksimum devir sayısı aşıldı" in result.summary

def test_task_router_fallback_and_route_by_role(monkeypatch, swarm_module):
    router = swarm_module.TaskRouter()
    monkeypatch.setattr(swarm_module.AgentRegistry, "find_by_capability", lambda _c: [])
    monkeypatch.setattr(swarm_module.AgentRegistry, "list_all", lambda: [_DummySpec("coder")])
    monkeypatch.setattr(swarm_module.AgentRegistry, "get", lambda role: _DummySpec(role))

    spec = router.route("unknown_intent")
    assert spec.role_name == "coder"
    by_role = router.route_by_role("reviewer")
    assert by_role.role_name == "reviewer"


def test_swarm_handles_agent_create_failure_and_empty_delegation_target(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())
    task = swarm_module.SwarmTask(goal="x", intent="mixed")
    monkeypatch.setattr(orchestrator.router, "route", lambda _i: _DummySpec("coder"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))

    failed = asyncio.run(orchestrator._execute_task(task, session_id="s"))
    assert failed.status == "failed"
    assert "Ajan oluşturulamadı" in failed.summary

    class _DelegatingAgent:
        async def handle(self, envelope):
            req = swarm_module.DelegationRequest(task_id=envelope.task_id, reply_to="coder", target_agent="  ", payload="p")
            return swarm_module.TaskResult(task_id=envelope.task_id, status="success", summary=req, evidence=[])

    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda *_a, **_k: _DelegatingAgent())
    failed2 = asyncio.run(orchestrator._execute_task(task, session_id="s"))
    assert failed2.status == "failed"
    assert "target_agent boş" in failed2.summary


def test_swarm_available_agents_lists_role_names(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())
    monkeypatch.setattr(swarm_module.AgentRegistry, "list_all", lambda: [_DummySpec("coder"), _DummySpec("reviewer")])
    assert orchestrator.available_agents() == ["coder", "reviewer"]