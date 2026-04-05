import importlib
import sys
import types

import pytest

from agent.core.contracts import ExternalTrigger


class _Dummy:
    def __init__(self, *args, **kwargs):
        pass


async def _dummy_async(*args, **kwargs):
    return None


def _install_stub_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    pydantic_stub = types.ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    pydantic_stub.BaseModel = _BaseModel
    pydantic_stub.Field = lambda default=None, **kwargs: default
    pydantic_stub.ValidationError = Exception
    monkeypatch.setitem(sys.modules, "pydantic", pydantic_stub)

    config_stub = types.ModuleType("config")
    config_stub.Config = _Dummy
    monkeypatch.setitem(sys.modules, "config", config_stub)

    ci_stub = types.ModuleType("core.ci_remediation")
    ci_stub.build_ci_failure_context = lambda *a, **k: {}
    ci_stub.build_ci_failure_prompt = lambda ctx: "ci_prompt"
    ci_stub.build_ci_remediation_payload = lambda *a, **k: {}
    ci_stub.build_self_heal_patch_prompt = lambda *a, **k: ""
    ci_stub.normalize_self_heal_plan = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "core.ci_remediation", ci_stub)

    entity_stub = types.ModuleType("core.entity_memory")
    entity_stub.get_entity_memory = lambda *a, **k: types.SimpleNamespace(initialize=_dummy_async, purge_expired=_dummy_async)
    monkeypatch.setitem(sys.modules, "core.entity_memory", entity_stub)

    memory_stub = types.ModuleType("core.memory")
    memory_stub.ConversationMemory = _Dummy
    monkeypatch.setitem(sys.modules, "core.memory", memory_stub)

    llm_stub = types.ModuleType("core.llm_client")
    llm_stub.LLMClient = _Dummy
    monkeypatch.setitem(sys.modules, "core.llm_client", llm_stub)

    rag_stub = types.ModuleType("core.rag")
    rag_stub.DocumentStore = _Dummy
    monkeypatch.setitem(sys.modules, "core.rag", rag_stub)

    for module_name, class_name in [
        ("managers.code_manager", "CodeManager"),
        ("managers.system_health", "SystemHealthManager"),
        ("managers.github_manager", "GitHubManager"),
        ("managers.security", "SecurityManager"),
        ("managers.web_search", "WebSearchManager"),
        ("managers.package_info", "PackageInfoManager"),
        ("managers.todo_manager", "TodoManager"),
    ]:
        stub = types.ModuleType(module_name)
        setattr(stub, class_name, _Dummy)
        monkeypatch.setitem(sys.modules, module_name, stub)


def _load_sidar_agent_module(monkeypatch: pytest.MonkeyPatch):
    _install_stub_modules(monkeypatch)
    sys.modules.pop("agent.sidar_agent", None)
    return importlib.import_module("agent.sidar_agent")


def test_default_derive_correlation_id_returns_first_non_empty_value(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    result = sidar_agent._default_derive_correlation_id("", "   ", None, "corr-123", "corr-456")
    assert result == "corr-123"


def test_fallback_federation_task_envelope_builds_prompt_and_correlation(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    envelope = sidar_agent._FallbackFederationTaskEnvelope(
        task_id="task-9",
        source_system="crm",
        source_agent="planner",
        target_system="sidar",
        target_agent="supervisor",
        goal="Sync roadmap",
        context={"tenant": "acme"},
        inputs=["backlog"],
        meta={"priority": "high"},
    )
    prompt = envelope.to_prompt()
    assert envelope.correlation_id == "task-9"
    assert "[FEDERATION TASK]" in prompt
    assert "goal=Sync roadmap" in prompt


def test_fallback_action_feedback_uses_related_ids_for_correlation(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    feedback = sidar_agent._FallbackActionFeedback(
        feedback_id="fb-1",
        action_name="create_ticket",
        related_task_id="task-21",
        summary="Ticket opened",
    )
    prompt = feedback.to_prompt()
    assert feedback.correlation_id == "task-21"
    assert "[ACTION FEEDBACK]" in prompt
    assert "summary=Ticket opened" in prompt


@pytest.mark.parametrize(
    ("raw", "expected_tool", "expected_argument"),
    [
        ('{"tool":"docs_search","argument":"lock"}', "docs_search", "lock"),
        ("```json\n{\"argument\":\"done\"}\n```", "final_answer", "done"),
        ("this is not json", "final_answer", "this is not json"),
    ],
)
def test_parse_tool_call_handles_json_markdown_and_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected_tool: str,
    expected_argument: str,
) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    parsed = agent._parse_tool_call(raw)
    assert parsed is not None
    assert parsed["tool"] == expected_tool
    assert parsed["argument"] == expected_argument


def test_build_trigger_prompt_prioritizes_ci_context(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    trigger = ExternalTrigger(trigger_id="t-1", source="github", event_name="workflow_run", payload={})
    monkeypatch.setattr(sidar_agent, "build_ci_failure_prompt", lambda ctx: f"CI::{ctx['workflow']}")
    prompt = sidar_agent.SidarAgent._build_trigger_prompt(trigger, {"kind": "federation_task"}, {"workflow": "backend-ci"})
    assert prompt == "CI::backend-ci"


def test_build_trigger_prompt_formats_federation_and_action_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    federation_trigger = ExternalTrigger(trigger_id="t-2", source="crm", event_name="sync", payload={})
    federation_prompt = sidar_agent.SidarAgent._build_trigger_prompt(
        federation_trigger,
        {"kind": "federation_task", "task_id": "task-42", "goal": "Push account update"},
        None,
    )
    action_trigger = ExternalTrigger(trigger_id="t-3", source="ops", event_name="action_feedback", payload={})
    action_prompt = sidar_agent.SidarAgent._build_trigger_prompt(
        action_trigger,
        {"kind": "action_feedback", "action_name": "deploy", "status": "completed", "summary": "Release done"},
        None,
    )
    assert "[FEDERATION TASK]" in federation_prompt
    assert "goal=Push account update" in federation_prompt
    assert "[ACTION FEEDBACK]" in action_prompt
    assert "status=completed" in action_prompt


def test_build_trigger_correlation_matches_history_without_duplicate_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent._autonomy_history = [
        {"trigger_id": "trig-1", "status": "success", "source": "github", "payload": {"task_id": "task-100"}, "correlation": {"correlation_id": "corr-100"}, "meta": {}},
        {"trigger_id": "trig-1", "status": "success", "source": "github", "payload": {"task_id": "task-100"}, "correlation": {"correlation_id": "corr-100"}, "meta": {}},
        {"trigger_id": "trig-2", "status": "failed", "source": "jira", "payload": {"related_task_id": "task-100"}, "correlation": {"correlation_id": "corr-100"}, "meta": {}},
    ]
    agent._autonomy_lock = None

    trigger = ExternalTrigger(trigger_id="trig-new", source="scheduler", event_name="nightly", payload={}, meta={"correlation_id": "corr-100"})
    correlation = agent._build_trigger_correlation(trigger, {"task_id": "task-100"})

    assert correlation["correlation_id"] == "corr-100"
    assert correlation["matched_records"] == 2
    assert correlation["related_trigger_ids"] == ["trig-2", "trig-1"]
    assert correlation["related_sources"] == ["jira", "github"]
    assert correlation["latest_related_status"] == "failed"
