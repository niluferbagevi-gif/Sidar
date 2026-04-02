import asyncio
import json
import importlib.util
import sys
import types
from types import MethodType
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("pydantic") is None:
    fake_pydantic = types.ModuleType("pydantic")
    fake_pydantic.BaseModel = object
    fake_pydantic.Field = lambda *a, **k: None
    fake_pydantic.ValidationError = Exception
    sys.modules["pydantic"] = fake_pydantic

if importlib.util.find_spec("jwt") is None:
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.encode = lambda payload, *_args, **_kwargs: f"token:{payload.get('sub', '')}"
    fake_jwt.decode = lambda *_args, **_kwargs: {"sub": "stub"}
    sys.modules["jwt"] = fake_jwt

if importlib.util.find_spec("httpx") is None:
    fake_httpx = types.ModuleType("httpx")

    class AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_httpx.AsyncClient = AsyncClient
    fake_httpx.TimeoutException = Exception
    fake_httpx.ConnectError = Exception
    fake_httpx.HTTPStatusError = Exception
    sys.modules["httpx"] = fake_httpx

if importlib.util.find_spec("bs4") is None:
    fake_bs4 = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, *args, **kwargs) -> None:
            return None

    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

from agent import sidar_agent


def test_default_derive_correlation_id_returns_first_non_empty():
    assert sidar_agent._default_derive_correlation_id("", None, "  ", "abc", "def") == "abc"


def test_fallback_federation_task_envelope_uses_meta_correlation_and_builds_prompt():
    envelope = sidar_agent._FallbackFederationTaskEnvelope(
        task_id="task-1",
        source_system="web",
        source_agent="agent-a",
        target_system="sidar",
        target_agent="reviewer",
        goal="run checks",
        context={"lang": "tr"},
        inputs=[{"path": "core/rag.py"}],
        meta={"correlation_id": "corr-123"},
    )

    prompt = envelope.to_prompt()
    assert envelope.correlation_id == "corr-123"
    assert "[FEDERATION TASK]" in prompt
    assert "target_agent=reviewer" in prompt
    assert f"context={json.dumps({'lang': 'tr'}, ensure_ascii=False, sort_keys=True)}" in prompt


def test_fallback_action_feedback_prefers_explicit_correlation_id():
    feedback = sidar_agent._FallbackActionFeedback(
        feedback_id="fb-1",
        action_name="run_tests",
        summary="ok",
        correlation_id="corr-explicit",
        meta={"correlation_id": "corr-meta"},
    )

    assert feedback.correlation_id == "corr-explicit"
    assert "[ACTION FEEDBACK]" in feedback.to_prompt()
    assert "action_name=run_tests" in feedback.to_prompt()


def test_fallback_action_feedback_uses_related_ids_when_correlation_missing():
    feedback = sidar_agent._FallbackActionFeedback(
        feedback_id="fb-1",
        related_task_id="task-9",
        summary="ok",
    )
    assert feedback.correlation_id == "task-9"


def test_parse_tool_call_handles_markdown_and_invalid_json():
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)

    parsed = agent._parse_tool_call("""```json\n{\"tool\":\"read_file\",\"argument\":\"README.md\"}\n```""")
    assert parsed == {"tool": "read_file", "argument": "README.md"}

    fallback = agent._parse_tool_call("not-json")
    assert fallback == {"tool": "final_answer", "argument": "not-json"}


@pytest.mark.asyncio
async def test_attempt_autonomous_self_heal_disabled_sets_execution_status() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=False)

    remediation = {"remediation_loop": {"status": "planned", "steps": []}}
    execution = await agent._attempt_autonomous_self_heal(
        ci_context={"job": "tests"},
        diagnosis="coverage low",
        remediation=remediation,
    )

    assert execution["status"] == "disabled"
    assert remediation["self_heal_execution"]["status"] == "disabled"


@pytest.mark.asyncio
async def test_attempt_autonomous_self_heal_waits_for_hitl_when_required() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=True)
    agent.code = object()
    agent.llm = object()

    remediation = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": True,
            "steps": [{"name": "handoff", "status": "pending", "detail": ""}],
        }
    }

    execution = await agent._attempt_autonomous_self_heal(
        ci_context={"job": "tests"},
        diagnosis="risky patch",
        remediation=remediation,
    )

    assert execution["status"] == "awaiting_hitl"
    assert remediation["remediation_loop"]["steps"][0]["status"] == "awaiting_hitl"


@pytest.mark.asyncio
async def test_attempt_autonomous_self_heal_marks_applied_when_plan_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=True)
    agent.code = object()
    agent.llm = object()

    async def _fake_build_self_heal_plan(**_kwargs):
        return {"operations": [{"path": "a.py"}], "validation_commands": ["pytest -q"]}

    async def _fake_execute_self_heal_plan(**_kwargs):
        return {
            "status": "applied",
            "summary": "ok",
            "operations_applied": ["a.py"],
            "validation_results": [{"command": "pytest -q", "ok": True}],
        }

    monkeypatch.setattr(agent, "_build_self_heal_plan", _fake_build_self_heal_plan)
    monkeypatch.setattr(agent, "_execute_self_heal_plan", _fake_execute_self_heal_plan)

    remediation = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": False,
            "steps": [
                {"name": "patch", "status": "pending", "detail": ""},
                {"name": "validate", "status": "pending", "detail": ""},
                {"name": "handoff", "status": "pending", "detail": ""},
            ],
        }
    }

    execution = await agent._attempt_autonomous_self_heal(
        ci_context={"job": "tests"},
        diagnosis="lint errors",
        remediation=remediation,
    )

    assert execution["status"] == "applied"
    assert remediation["remediation_loop"]["status"] == "applied"
    step_statuses = {s["name"]: s["status"] for s in remediation["remediation_loop"]["steps"]}
    assert step_statuses == {"patch": "completed", "validate": "completed", "handoff": "completed"}


@pytest.mark.asyncio
async def test_respond_returns_warning_for_empty_input() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    chunks = []
    async for chunk in agent.respond("   "):
        chunks.append(chunk)
    assert chunks == ["⚠ Boş girdi."]


@pytest.mark.asyncio
async def test_respond_streams_supervisor_output_and_updates_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent._lock = None
    agent._last_activity_ts = 0.0
    agent.cfg = SimpleNamespace()

    calls: list[tuple[str, str]] = []

    async def _fake_initialize():
        return None

    async def _fake_try_multi_agent(user_input: str) -> str:
        assert user_input == "merhaba sidar"
        return "tamamlandı"

    async def _fake_memory_add(role: str, content: str) -> None:
        calls.append((role, content))

    monkeypatch.setattr(agent, "initialize", _fake_initialize)
    monkeypatch.setattr(agent, "_try_multi_agent", _fake_try_multi_agent)
    monkeypatch.setattr(agent, "_memory_add", _fake_memory_add)

    chunks = []
    async for chunk in agent.respond("merhaba sidar"):
        chunks.append(chunk)

    assert chunks == ["tamamlandı"]
    assert calls == [("user", "merhaba sidar"), ("assistant", "tamamlandı")]
    assert agent.seconds_since_last_activity() >= 0


@pytest.mark.asyncio
async def test_run_nightly_memory_maintenance_disabled_by_config() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(ENABLE_NIGHTLY_MEMORY_PRUNING=False)

    async def _fake_initialize():
        return None

    agent.initialize = _fake_initialize
    result = await agent.run_nightly_memory_maintenance()
    assert result == {"status": "disabled", "reason": "config_disabled"}


@pytest.mark.asyncio
async def test_run_nightly_memory_maintenance_skips_when_not_idle() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(
        ENABLE_NIGHTLY_MEMORY_PRUNING=True,
        NIGHTLY_MEMORY_IDLE_SECONDS=1800,
    )

    async def _fake_initialize():
        return None

    agent.initialize = _fake_initialize
    agent.seconds_since_last_activity = MethodType(lambda _self: 60.0, agent)

    result = await agent.run_nightly_memory_maintenance(force=False)
    assert result["status"] == "skipped"
    assert result["reason"] == "not_idle"
    assert result["idle_threshold_seconds"] == 1800


@pytest.mark.asyncio
async def test_summarize_memory_archives_and_applies_summary() -> None:
    class _Memory:
        def __init__(self):
            self.summary = None

        async def get_history(self):
            return [
                {"role": "user", "content": "ilk", "timestamp": 1},
                {"role": "assistant", "content": "yanıt", "timestamp": 2},
                {"role": "user", "content": "dosya değişikliği", "timestamp": 3},
                {"role": "assistant", "content": "tamam", "timestamp": 4},
            ]

        async def apply_summary(self, summary: str):
            self.summary = summary

    class _Docs:
        def __init__(self):
            self.calls = []

        async def add_document(self, **kwargs):
            self.calls.append(kwargs)

    class _Llm:
        async def chat(self, **kwargs):
            assert kwargs["stream"] is False
            return "özet metni"

    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.memory = _Memory()
    agent.docs = _Docs()
    agent.llm = _Llm()
    agent.cfg = SimpleNamespace(TEXT_MODEL="text", CODING_MODEL="code")

    await agent._summarize_memory()

    assert len(agent.docs.calls) == 1
    assert agent.docs.calls[0]["source"] == "memory_archive"
    assert agent.memory.summary == "özet metni"


@pytest.mark.asyncio
async def test_tool_subtask_returns_final_answer_immediately() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=3, TEXT_MODEL="gpt-test", CODING_MODEL="gpt-code")

    class _LLM:
        async def chat(self, **_kwargs):
            return '{"thought":"tamamlandı","tool":"final_answer","argument":"bitti"}'

    agent.llm = _LLM()

    result = await agent._tool_subtask("coverage artır")

    assert result == "✓ Alt Görev Tamamlandı: bitti"


@pytest.mark.asyncio
async def test_tool_subtask_handles_tool_exception_and_hits_max_steps() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=1, TEXT_MODEL="gpt-test", CODING_MODEL="gpt-code")

    class _LLM:
        async def chat(self, **_kwargs):
            return '{"tool":"run_tests","argument":"pytest -q"}'

    async def _boom(_tool: str, _arg: str) -> str:
        raise RuntimeError("tool crashed")

    agent.llm = _LLM()
    agent._execute_tool = _boom

    result = await agent._tool_subtask("testleri çalıştır")

    assert "Maksimum adım sınırına ulaşıldı" in result


def test_tool_subtask_non_string_llm_output_hits_max_steps() -> None:
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=1, TEXT_MODEL="gpt-test", CODING_MODEL="gpt-code")

    class _LLM:
        async def chat(self, **_kwargs):
            return {"tool": "final_answer", "argument": "bitti"}  # intentionally non-string

    agent.llm = _LLM()

    result = asyncio.run(agent._tool_subtask("kriz modu"))

    assert "Maksimum adım sınırına ulaşıldı" in result
