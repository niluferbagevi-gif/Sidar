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
