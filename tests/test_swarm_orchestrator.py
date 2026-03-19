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


def test_swarm_direct_handoff_preserves_sender_and_p2p_context(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace(SWARM_MAX_HANDOFF_HOPS=3))
    seen = []

    class _CoderAgent:
        async def handle(self, envelope):
            seen.append(("coder", envelope.sender, envelope.receiver, dict(envelope.context)))
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary=swarm_module.DelegationRequest(
                    task_id=envelope.task_id,
                    reply_to="coder",
                    target_agent="reviewer",
                    payload="review_code|patch-v1",
                    intent="review",
                    parent_task_id="root-task",
                    handoff_depth=0,
                    meta={"reason": "coder_request_review"},
                ),
                evidence=[],
            )

    class _ReviewerAgent:
        async def handle(self, envelope):
            seen.append(("reviewer", envelope.sender, envelope.receiver, dict(envelope.context)))
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary="review:ok",
                evidence=["qa"],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: _DummySpec("coder"))
    monkeypatch.setattr(orchestrator.router, "route_by_role", lambda role_name: _DummySpec(role_name))
    monkeypatch.setattr(
        swarm_module.AgentRegistry,
        "create",
        lambda role_name, **_kwargs: _CoderAgent() if role_name == "coder" else _ReviewerAgent(),
    )

    result = asyncio.run(orchestrator.run("patch hazırla", intent="code", session_id="sess-p2p"))

    assert result.status == "success"
    assert result.agent_role == "reviewer"
    assert result.summary == "review:ok"
    assert seen[0][0] == "coder"
    assert seen[1][0] == "reviewer"
    assert seen[1][1] == "coder"
    assert seen[1][2] == "reviewer"
    assert seen[1][3]["p2p_reason"] == "coder_request_review"
    assert seen[1][3]["p2p_sender"] == "coder"
    assert seen[1][3]["p2p_receiver"] == "reviewer"


def test_swarm_success_schedules_autonomous_feedback(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())
    scheduled = []

    class _DummyAgent:
        async def handle(self, envelope):
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary="otomasyon adayı yanıt",
                evidence=["lint"],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: _DummySpec("reviewer"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda *_a, **_k: _DummyAgent())
    monkeypatch.setattr(orchestrator, "_schedule_autonomous_feedback", lambda **kwargs: scheduled.append(kwargs))

    result = asyncio.run(orchestrator.run("yanıtı değerlendir", intent="review", session_id="sess-auto"))

    assert result.status == "success"
    assert len(scheduled) == 1
    assert scheduled[0]["prompt"] == "yanıtı değerlendir"
    assert scheduled[0]["agent_role"] == "reviewer"
    assert scheduled[0]["session_id"] == "sess-auto"


def test_swarm_autonomous_feedback_flags_only_weak_responses(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())
    calls = []

    class _Judge:
        enabled = True

        async def evaluate_response(self, prompt, response, context):
            assert prompt == "Görevi çöz"
            assert response == "eksik özet"
            assert context["agent_role"] == "coder"
            return SimpleNamespace(score=7, reasoning="Kilit ayrıntılar eksik", provider="openai", model="gpt-4o-mini")

    async def _flag_weak_response(**kwargs):
        calls.append(kwargs)
        return True

    judge_mod = types.ModuleType("core.judge")
    judge_mod.get_llm_judge = lambda: _Judge()
    active_mod = types.ModuleType("core.active_learning")
    active_mod.flag_weak_response = _flag_weak_response

    monkeypatch.setitem(sys.modules, "core.judge", judge_mod)
    monkeypatch.setitem(sys.modules, "core.active_learning", active_mod)

    asyncio.run(
        orchestrator._run_autonomous_feedback(
            prompt="Görevi çöz",
            response="eksik özet",
            context={"agent_role": "coder"},
            session_id="sess-weak",
            agent_role="coder",
            task_id="task-1",
        )
    )

    assert len(calls) == 1
    assert calls[0]["score"] == 7
    assert "swarm:auto" in calls[0]["tags"]
    assert "agent:coder" in calls[0]["tags"]
    assert calls[0]["session_id"] == "sess-weak"



def test_task_router_prefers_first_capability_match(monkeypatch, swarm_module):
    router = swarm_module.TaskRouter()
    monkeypatch.setattr(
        swarm_module.AgentRegistry,
        "find_by_capability",
        lambda _c: [_DummySpec("reviewer"), _DummySpec("coder")],
    )

    spec = router.route("review")

    assert spec.role_name == "reviewer"


def test_swarm_orchestrator_skips_when_no_agent_matches(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())
    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: None)

    result = asyncio.run(orchestrator.run("eşleşme yok", intent="unknown"))

    assert result.status == "skipped"
    assert result.agent_role == "none"
    assert result.summary == "Uygun ajan bulunamadı."


def test_swarm_orchestrator_treats_unexpected_summary_string_as_plain_result(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())

    class _OddAgent:
        async def handle(self, envelope):
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary="DELEGATE?? target=coder but malformed",
                evidence=["raw-string"],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: _DummySpec("coder"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda *_a, **_k: _OddAgent())

    result = asyncio.run(orchestrator.run("garip çıktı", intent="mixed"))

    assert result.status == "success"
    assert result.agent_role == "coder"
    assert result.summary == "DELEGATE?? target=coder but malformed"
    assert result.evidence == ["raw-string"]


def test_swarm_orchestrator_raises_last_retry_error_when_retry_loop_exits_without_result(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace(SWARM_TASK_MAX_RETRIES=1, SWARM_TASK_RETRY_DELAY_MS=0))

    class _AlwaysFailAgent:
        async def handle(self, envelope):
            raise RuntimeError("yarım kalan retry döngüsü")

    def _single_attempt_range(*args):
        if args == (2,):
            return iter([0])
        return range(*args)

    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: _DummySpec("coder"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda *_a, **_k: _AlwaysFailAgent())
    monkeypatch.setattr(swarm_module, "range", _single_attempt_range, raising=False)

    result = asyncio.run(orchestrator.run("retry anomalisi", intent="mixed"))

    assert result.status == "failed"
    assert "yarım kalan retry döngüsü" in result.summary

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


def test_swarm_loop_repeat_limit_respects_provider_defaults_and_minimum(swarm_module):
    local = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace(AI_PROVIDER="ollama"))
    remote = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace(AI_PROVIDER="openai"))
    forced_min = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace(AI_PROVIDER="openai", SWARM_LOOP_GUARD_MAX_REPEAT=-2))

    assert local._loop_repeat_limit() == 2
    assert remote._loop_repeat_limit() == 3
    assert forced_min._loop_repeat_limit() == 1


def test_swarm_pipeline_only_carries_successful_results_to_next_context(monkeypatch, swarm_module):
    orchestrator = swarm_module.SwarmOrchestrator(cfg=SimpleNamespace())
    seen = []

    class _Agent:
        async def handle(self, envelope):
            seen.append(dict(envelope.context))
            if envelope.goal == "first":
                return swarm_module.TaskResult(task_id=envelope.task_id, status="failed", summary="nope", evidence=[])
            return swarm_module.TaskResult(task_id=envelope.task_id, status="success", summary="ok", evidence=[])

    monkeypatch.setattr(orchestrator.router, "route", lambda intent: _DummySpec("coder"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda *_a, **_k: _Agent())

    tasks = [
        swarm_module.SwarmTask(goal="first", intent="code_generation", context={"seed": "1"}),
        swarm_module.SwarmTask(goal="second", intent="code_review", context={}),
    ]
    results = asyncio.run(orchestrator.run_pipeline(tasks))

    assert results[0].status == "failed"
    assert results[1].status == "success"
    assert "prev_coder" not in seen[1]

def test_swarm_orchestrator_loop_guard_stops_repeated_same_route(monkeypatch, swarm_module):
    cfg = SimpleNamespace(SWARM_LOOP_GUARD_MAX_REPEAT=2, AI_PROVIDER="openai")
    orchestrator = swarm_module.SwarmOrchestrator(cfg=cfg)

    class _Agent:
        async def handle(self, envelope):
            return swarm_module.TaskResult(
                task_id=envelope.task_id,
                status="success",
                summary="ok",
                evidence=[],
            )

    monkeypatch.setattr(orchestrator.router, "route", lambda _intent: _DummySpec("coder"))
    monkeypatch.setattr(swarm_module.AgentRegistry, "create", lambda *_a, **_k: _Agent())

    task = swarm_module.SwarmTask(goal="aynı görev", intent="mixed")
    result = asyncio.run(
        orchestrator._execute_task(
            task,
            _route_trace=[
                "coder|mixed|aynı görev",
                "coder|mixed|aynı görev",
            ],
        )
    )

    assert result.status == "failed"
    assert "aynı ajan/intente aynı görev tekrarlandı" in result.summary