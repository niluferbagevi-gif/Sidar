import asyncio
import importlib
import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _patched_modules(*pairs):
    saved = {}
    try:
        for name, module in pairs:
            saved[name] = sys.modules.get(name)
            sys.modules[name] = module
        yield
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _make_httpx_stub():
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.AsyncClient = object
    httpx_stub.Client = object
    httpx_stub.TimeoutException = RuntimeError
    httpx_stub.ReadTimeout = RuntimeError
    httpx_stub.ConnectError = RuntimeError
    httpx_stub.HTTPError = RuntimeError
    httpx_stub.Timeout = lambda *args, **kwargs: SimpleNamespace(args=args, kwargs=kwargs)
    return httpx_stub


def _make_event_stream_stub():
    event_stream_stub = types.ModuleType("agent.core.event_stream")

    class _DummyBus:
        async def publish(self, *_args, **_kwargs):
            return None

        def subscribe(self):
            queue = asyncio.Queue()
            return "sub-1", queue

        def unsubscribe(self, _sub_id):
            return None

    event_stream_stub.get_agent_event_bus = lambda: _DummyBus()
    return event_stream_stub


def _make_auto_handle_stub():
    auto_handle_stub = types.ModuleType("agent.auto_handle")
    auto_handle_stub.AutoHandle = object
    return auto_handle_stub


def _make_sidar_agent_stub():
    sidar_agent_stub = types.ModuleType("agent.sidar_agent")
    sidar_agent_stub.SidarAgent = object
    return sidar_agent_stub


def _make_researcher_agent_stub():
    researcher_agent_stub = types.ModuleType("agent.roles.researcher_agent")
    researcher_agent_stub.ResearcherAgent = type("ResearcherAgent", (), {})
    return researcher_agent_stub


def _make_bs4_stub():
    bs4_stub = types.ModuleType("bs4")

    class _BeautifulSoup:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_text(self, *args, **kwargs):
            return ""

    bs4_stub.BeautifulSoup = _BeautifulSoup
    return bs4_stub


@contextmanager
def _load_agent_test_symbols():
    saved_modules = {
        name: sys.modules.get(name)
        for name in (
            "agent",
            "agent.auto_handle",
            "agent.base_agent",
            "agent.core",
            "agent.core.contracts",
            "agent.core.event_stream",
            "agent.core.memory_hub",
            "agent.core.registry",
            "agent.core.supervisor",
            "agent.registry",
            "agent.roles",
            "agent.roles.coder_agent",
            "agent.roles.researcher_agent",
            "agent.roles.reviewer_agent",
            "agent.sidar_agent",
            "agent.swarm",
            "bs4",
            "core",
            "core.llm_client",
            "httpx",
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

    class _LLMClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def chat(self, *args, **kwargs):
            return {"args": args, "kwargs": kwargs}

    llm_client_mod.LLMClient = _LLMClient
    root_core_pkg.llm_client = llm_client_mod

    stub_pairs = (
        ("agent", agent_pkg),
        ("agent.auto_handle", _make_auto_handle_stub()),
        ("agent.core", core_pkg),
        ("agent.core.event_stream", _make_event_stream_stub()),
        ("agent.roles", roles_pkg),
        ("agent.roles.researcher_agent", _make_researcher_agent_stub()),
        ("agent.sidar_agent", _make_sidar_agent_stub()),
        ("bs4", _make_bs4_stub()),
        ("core", root_core_pkg),
        ("core.llm_client", llm_client_mod),
        ("httpx", _make_httpx_stub()),
    )
    module_specs = (
        ("agent.core.contracts", "agent/core/contracts.py"),
        ("agent.core.memory_hub", "agent/core/memory_hub.py"),
        ("agent.base_agent", "agent/base_agent.py"),
        ("agent.core.registry", "agent/core/registry.py"),
        ("agent.roles.coder_agent", "agent/roles/coder_agent.py"),
        ("agent.roles.reviewer_agent", "agent/roles/reviewer_agent.py"),
        ("agent.core.supervisor", "agent/core/supervisor.py"),
        ("agent.registry", "agent/registry.py"),
        ("agent.swarm", "agent/swarm.py"),
    )

    try:
        with _patched_modules(*stub_pairs):
            importlib.invalidate_caches()
            loaded = {}
            for name, rel_path in module_specs:
                spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
                mod = importlib.util.module_from_spec(spec)
                assert spec and spec.loader
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                loaded[name] = mod
            yield {
                "BaseAgent": loaded["agent.base_agent"].BaseAgent,
                "DelegationRequest": loaded["agent.core.contracts"].DelegationRequest,
                "TaskEnvelope": loaded["agent.core.contracts"].TaskEnvelope,
                "is_delegation_request": loaded["agent.core.contracts"].is_delegation_request,
                "SupervisorAgent": loaded["agent.core.supervisor"].SupervisorAgent,
                "CoderAgent": loaded["agent.roles.coder_agent"].CoderAgent,
                "ReviewerAgent": loaded["agent.roles.reviewer_agent"].ReviewerAgent,
                "AgentRegistry": loaded["agent.swarm"].AgentRegistry,
                "SwarmOrchestrator": loaded["agent.swarm"].SwarmOrchestrator,
                "SwarmTask": loaded["agent.swarm"].SwarmTask,
                "TaskResult": loaded["agent.swarm"].TaskResult,
            }
    finally:
        for name, previous in saved_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_base_agent_handle_backfills_delegation_metadata_from_envelope():
    with _load_agent_test_symbols() as symbols:
        BaseAgent = symbols["BaseAgent"]
        DelegationRequest = symbols["DelegationRequest"]
        TaskEnvelope = symbols["TaskEnvelope"]
        is_delegation_request = symbols["is_delegation_request"]

        class _MiniAgent(BaseAgent):
            def __init__(self):
                self.cfg = SimpleNamespace(AI_PROVIDER="ollama")
                self.role_name = "mini"
                self.llm = None
                self.tools = {}
                self._summary = None

            async def run_task(self, task_prompt: str):
                del task_prompt
                return self._summary

        agent = _MiniAgent()
        agent._summary = DelegationRequest(
            task_id="",
            reply_to="mini",
            target_agent="reviewer",
            payload="review_code|diff",
            parent_task_id=None,
            handoff_depth=0,
        )
        envelope = TaskEnvelope(
            task_id="task-1",
            sender="supervisor",
            receiver="mini",
            goal="review this",
            parent_task_id="parent-1",
            context={"p2p_handoff_depth": "3"},
        )

        result = asyncio.run(agent.handle(envelope))

        assert is_delegation_request(result.summary)
        assert result.summary.task_id == "task-1"
        assert result.summary.parent_task_id == "parent-1"
        assert result.summary.handoff_depth == 3


def test_supervisor_reject_feedback_payload_handles_empty_invalid_and_valid_json():
    with _load_agent_test_symbols() as symbols:
        SupervisorAgent = symbols["SupervisorAgent"]

        assert SupervisorAgent._is_reject_feedback_payload("qa_feedback|") is False
        assert SupervisorAgent._is_reject_feedback_payload("qa_feedback|plain text decision=reject") is True
        assert SupervisorAgent._is_reject_feedback_payload('qa_feedback|{"decision":"reject", decision=reject') is True
        assert SupervisorAgent._is_reject_feedback_payload('qa_feedback|{"decision":"approve"}') is False
        assert SupervisorAgent._is_reject_feedback_payload('qa_feedback|{"decision":"reject"}') is True


def test_swarm_autonomous_feedback_short_circuits_and_swallows_judge_errors(caplog):
    with _load_agent_test_symbols() as symbols:
        SwarmOrchestrator = symbols["SwarmOrchestrator"]
        orchestrator = SwarmOrchestrator(cfg=SimpleNamespace())
        flagged = []

        judge_mod = types.ModuleType("core.judge")
        active_learning_mod = types.ModuleType("core.active_learning")
        active_learning_mod.flag_weak_response = lambda **kwargs: flagged.append(kwargs) or asyncio.sleep(0)

        disabled_judge = SimpleNamespace(enabled=False)
        judge_mod.get_llm_judge = lambda: disabled_judge
        with _patched_modules(("core.judge", judge_mod), ("core.active_learning", active_learning_mod)):
            asyncio.run(
                orchestrator._run_autonomous_feedback(
                    prompt="fix bug",
                    response="done",
                    context={"intent": "code"},
                    session_id="sess-1",
                    agent_role="coder",
                    task_id="task-1",
                )
            )
        assert flagged == []

        async def _high_score(*_args, **_kwargs):
            return SimpleNamespace(score=9, reasoning="ok", provider="stub", model="m")

        judge_mod.get_llm_judge = lambda: SimpleNamespace(enabled=True, evaluate_response=_high_score)
        with _patched_modules(("core.judge", judge_mod), ("core.active_learning", active_learning_mod)):
            asyncio.run(
                orchestrator._run_autonomous_feedback(
                    prompt="fix bug",
                    response="done",
                    context={"intent": "code"},
                    session_id="sess-1",
                    agent_role="coder",
                    task_id="task-2",
                )
            )
        assert flagged == []

        async def _judge_boom(*_args, **_kwargs):
            raise RuntimeError("judge boom")

        judge_mod.get_llm_judge = lambda: SimpleNamespace(enabled=True, evaluate_response=_judge_boom)
        with caplog.at_level("DEBUG", logger="agent.swarm"):
            with _patched_modules(("core.judge", judge_mod), ("core.active_learning", active_learning_mod)):
                asyncio.run(
                    orchestrator._run_autonomous_feedback(
                        prompt="fix bug",
                        response="done",
                        context={"intent": "code"},
                        session_id="sess-1",
                        agent_role="coder",
                        task_id="task-3",
                    )
                )

        assert flagged == []
        assert "judge boom" in caplog.text


def test_swarm_execute_task_skips_missing_preferred_agent_and_backfills_reply_to(monkeypatch):
    with _load_agent_test_symbols() as symbols:
        SwarmOrchestrator = symbols["SwarmOrchestrator"]
        SwarmTask = symbols["SwarmTask"]
        AgentRegistry = symbols["AgentRegistry"]
        TaskResult = symbols["TaskResult"]

        orchestrator = SwarmOrchestrator(cfg=SimpleNamespace(SWARM_TASK_MAX_RETRIES=0, SWARM_TASK_RETRY_DELAY_MS=0))

        missing = asyncio.run(
            orchestrator._execute_task(
                SwarmTask(goal="review this", intent="review", preferred_agent="ghost"),
                session_id="sess-1",
            )
        )
        assert missing.status == "skipped"
        assert missing.agent_role == "none"

        class _DelegatingAgent:
            async def handle(self, envelope):
                return TaskResult(
                    task_id=envelope.task_id,
                    status="success",
                    summary=symbols["DelegationRequest"](
                        task_id=envelope.task_id,
                        reply_to="",
                        target_agent="reviewer",
                        payload="review_code|diff",
                    ),
                    evidence=[],
                )

        monkeypatch.setattr(orchestrator.router, "route", lambda _intent: SimpleNamespace(role_name="coder"))
        monkeypatch.setattr(AgentRegistry, "create", lambda *_args, **_kwargs: _DelegatingAgent())

        seen = {}

        async def _direct_handoff(task, delegation, **kwargs):
            seen["task_id"] = task.task_id
            seen["reply_to"] = delegation.reply_to
            seen["target_agent"] = delegation.target_agent
            seen["kwargs"] = kwargs
            return SimpleNamespace(status="success", agent_role="reviewer", summary="handoff-ok", elapsed_ms=1)

        monkeypatch.setattr(orchestrator, "_direct_handoff", _direct_handoff)
        handoff = asyncio.run(orchestrator._execute_task(SwarmTask(goal="implement", intent="code"), session_id="sess-2"))

        assert handoff.summary == "handoff-ok"
        assert seen["reply_to"] == "coder"
        assert seen["target_agent"] == "reviewer"
        assert seen["kwargs"]["hop"] == 1


def test_coder_agent_parse_qa_feedback_preserves_raw_invalid_json_payload():
    with _load_agent_test_symbols() as symbols:
        CoderAgent = symbols["CoderAgent"]

        parsed = CoderAgent._parse_qa_feedback('{"decision":"reject"')
        assert parsed == {"raw": '{"decision":"reject"'}

        agent = object.__new__(CoderAgent)
        agent.events = SimpleNamespace(publish=lambda *_args, **_kwargs: asyncio.sleep(0))
        output = asyncio.run(agent.run_task('qa_feedback|{"decision":"reject"'))
        assert output.startswith("[CODER:APPROVED]")
        assert '{"decision":"reject"' in output


def test_reviewer_dynamic_test_generation_fail_closes_for_plain_text_and_llm_error(monkeypatch):
    with _load_agent_test_symbols() as symbols:
        ReviewerAgent = symbols["ReviewerAgent"]
        reviewer = ReviewerAgent()

        async def _plain_text(*_args, **_kwargs):
            return "Bence birkaç senaryo ekleyebilirsin ama aşağıda test yok."

        monkeypatch.setattr(reviewer, "call_llm", _plain_text)
        plain = asyncio.run(reviewer._build_dynamic_test_content("core logic"))
        assert "geçerli pytest test fonksiyonu içermedi" in plain

        async def _llm_boom(*_args, **_kwargs):
            raise RuntimeError("llm down")

        monkeypatch.setattr(reviewer, "call_llm", _llm_boom)
        errored = asyncio.run(reviewer._build_dynamic_test_content("core logic"))
        assert "Reviewer LLM dinamik test üretimi başarısız oldu: llm down" in errored