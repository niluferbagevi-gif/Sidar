import types
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, create_autospec

import pytest

pytestmark = pytest.mark.asyncio

from agent.core.contracts import ExternalTrigger
from managers.code_manager import CodeManager
from core.llm_client import BaseLLMClient
from tests.helpers import collect_async_chunks as _collect_stream
import agent.sidar_agent as sidar_agent




def _override_cfg(agent, **overrides):
    for key, value in overrides.items():
        setattr(agent.cfg, key, value)

async def test_trace_can_be_set_to_none_for_optional_telemetry(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sidar_agent, "trace", None, raising=False)
    assert sidar_agent.trace is None


async def test_default_derive_correlation_id_returns_first_non_empty_value() -> None:
    result = sidar_agent._default_derive_correlation_id("", "   ", None, "corr-123", "corr-456")
    assert result == "corr-123"
    assert sidar_agent._default_derive_correlation_id("", "   ", None) == ""


async def test_fallback_federation_task_envelope_builds_prompt_and_correlation(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
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


async def test_fallback_action_feedback_uses_related_ids_for_correlation(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
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


async def test_init_accepts_config_alias_and_prefers_config(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Mock(name="cfg")
    cfg_alias = Mock(name="config_alias")

    agent = sidar_agent.SidarAgent(cfg=cfg, config=cfg_alias)

    assert agent.cfg is cfg_alias


@pytest.mark.parametrize(
    ("raw", "expected_tool", "expected_argument"),
    [
        ('{"tool":"docs_search","argument":"lock"}', "docs_search", "lock"),
        ("```json\n{\"argument\":\"done\"}\n```", "final_answer", "done"),
        ("this is not json", "final_answer", "this is not json"),
    ],
)
async def test_parse_tool_call_handles_json_markdown_and_invalid_input(
    sidar_agent_factory,
    raw: str,
    expected_tool: str,
    expected_argument: str,
) -> None:
    agent = sidar_agent_factory()
    parsed = agent._parse_tool_call(raw)
    assert parsed is not None
    assert parsed["tool"] == expected_tool
    assert parsed["argument"] == expected_argument


async def test_build_trigger_prompt_prioritizes_ci_context(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = ExternalTrigger(trigger_id="t-1", source="github", event_name="workflow_run", payload={})
    monkeypatch.setattr(sidar_agent, "build_ci_failure_prompt", lambda ctx: f"CI::{ctx['workflow']}")
    prompt = sidar_agent.SidarAgent._build_trigger_prompt(trigger, {"kind": "federation_task"}, {"workflow": "backend-ci"})
    assert prompt == "CI::backend-ci"


async def test_build_trigger_prompt_formats_federation_and_action_feedback(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
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


async def test_build_trigger_correlation_matches_history_without_duplicate_ids(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    now = sidar_agent.time.time()
    agent._autonomy_history = [
        {"trigger_id": "trig-1", "status": "success", "source": "github", "payload": {"task_id": "task-100"}, "correlation": {"correlation_id": "corr-100"}, "meta": {}, "timestamp": now - 120},
        {"trigger_id": "trig-1", "status": "success", "source": "github", "payload": {"task_id": "task-100"}, "correlation": {"correlation_id": "corr-100"}, "meta": {}, "timestamp": now - 60},
        {"trigger_id": "trig-2", "status": "failed", "source": "jira", "payload": {"related_task_id": "task-100"}, "correlation": {"correlation_id": "corr-100"}, "meta": {}, "timestamp": now - 10},
    ]
    agent._autonomy_lock = None

    trigger = ExternalTrigger(trigger_id="trig-new", source="scheduler", event_name="nightly", payload={}, meta={"correlation_id": "corr-100"})
    correlation = agent._build_trigger_correlation(trigger, {"task_id": "task-100"})

    assert correlation["correlation_id"] == "corr-100"
    assert correlation["matched_records"] == 2
    assert correlation["related_trigger_ids"] == ["trig-2", "trig-1"]
    assert correlation["related_sources"] == ["jira", "github"]
    assert correlation["latest_related_status"] == "failed"


async def test_execute_self_heal_plan_success_and_validation(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    agent = sidar_agent_factory()
    writes = {}
    code_mock = create_autospec(CodeManager, instance=True, spec_set=True)
    code_mock.read_file.side_effect = lambda path, *args, **kwargs: (True, f"old:{path}")
    code_mock.patch_file.side_effect = lambda path, target, replacement: (
        writes.__setitem__(path, (target, replacement)) or (True, "ok")
    )
    code_mock.write_file.side_effect = lambda path, content, *args, **kwargs: (
        writes.__setitem__(path, ("restore", content)) or (True, "ok")
    )
    code_mock.run_shell_in_sandbox.side_effect = lambda command, base_dir: (True, f"ok:{command}:{base_dir}")
    agent.code = code_mock
    _override_cfg(agent, BASE_DIR=str(tmp_path))

    plan = {
        "summary": "patching",
        "confidence": "high",
        "operations": [{"path": "a.py", "target": "A", "replacement": "B"}],
        "validation_commands": ["pytest -q"],
    }
    remediation_loop = {"validation_commands": ["pytest -q"]}
    result = await agent._execute_self_heal_plan(remediation_loop=remediation_loop, plan=plan)

    assert result["status"] == "applied"
    assert result["operations_applied"] == ["a.py"]
    assert len(result["validation_results"]) == 1
    assert writes["a.py"] == ("A", "B")


async def test_execute_self_heal_plan_reverts_on_patch_error(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    agent = sidar_agent_factory()
    restored = {}
    code_mock = create_autospec(CodeManager, instance=True, spec_set=True)
    code_mock.read_file.side_effect = lambda path, *args, **kwargs: (True, f"old:{path}")
    code_mock.patch_file.side_effect = lambda path, target, replacement: (False, "boom")
    code_mock.write_file.side_effect = lambda path, content, *args, **kwargs: (
        restored.__setitem__(path, content) or (True, "ok")
    )
    code_mock.run_shell_in_sandbox.side_effect = lambda command, base_dir: (True, "ok")
    agent.code = code_mock
    _override_cfg(agent, BASE_DIR=str(tmp_path))
    plan = {
        "operations": [{"path": "a.py", "target": "A", "replacement": "B"}],
        "validation_commands": ["pytest -q"],
    }
    result = await agent._execute_self_heal_plan(remediation_loop={}, plan=plan)
    assert result["status"] == "reverted"
    assert result["reverted"] is True
    assert restored == {"a.py": "old:a.py"}


async def test_attempt_autonomous_self_heal_core_branches(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=False)
    remediation = {"remediation_loop": {"status": "planned"}}
    disabled = await agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation)
    assert disabled["status"] == "disabled"

    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    remediation = {"remediation_loop": {"status": "queued"}}
    skipped = await agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation)
    assert skipped["status"] == "skipped"

    remediation = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": True,
            "steps": [{"name": "handoff", "status": "planned", "detail": ""}],
        }
    }
    hitl = await agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation)
    assert hitl["status"] == "awaiting_hitl"
    assert remediation["remediation_loop"]["steps"][0]["status"] == "awaiting_hitl"


async def test_handle_external_trigger_success_and_failure(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    records = []
    agent.initialize = AsyncMock()
    agent._ensure_autonomy_runtime_state = lambda: None
    agent.mark_activity = lambda source="runtime": None
    agent._build_trigger_correlation = lambda trigger, payload: {"correlation_id": "cid"}
    agent._build_trigger_prompt = lambda trigger, payload, ci: "PROMPT"

    agent._append_autonomy_history = AsyncMock(side_effect=lambda record: records.append(record))
    agent._memory_add = AsyncMock()
    agent._try_multi_agent = AsyncMock(return_value="summary")

    result = await agent.handle_external_trigger({"trigger_id": "tr-1", "source": "s", "event_name": "e", "payload": {}, "meta": {}})
    assert result["status"] == "success"
    assert records and records[0]["summary"] == "summary"
    agent._memory_add.assert_any_await("user", "[AUTONOMY_TRIGGER] PROMPT")
    agent._memory_add.assert_any_await("assistant", "summary")

    agent._try_multi_agent = AsyncMock(side_effect=RuntimeError("x"))
    failed = await agent.handle_external_trigger({"trigger_id": "tr-2", "source": "s", "event_name": "e", "payload": {}, "meta": {}})
    assert failed["status"] == "failed"
    assert "x" in failed["summary"]


async def test_run_nightly_memory_maintenance_disabled_and_completed(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    agent.initialize = AsyncMock()
    agent._append_autonomy_history = AsyncMock()
    agent._nightly_maintenance_lock = None
    frozen_time.tick(delta=9999.0)
    agent._last_activity_ts = sidar_agent.time.time() - 9999.0
    _override_cfg(
        agent,
        ENABLE_NIGHTLY_MEMORY_PRUNING=False,
        NIGHTLY_MEMORY_IDLE_SECONDS=100,
        NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=2,
        NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=3,
        NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=1,
    )
    disabled = await agent.run_nightly_memory_maintenance()
    assert disabled["status"] == "disabled"

    agent.cfg.ENABLE_NIGHTLY_MEMORY_PRUNING = True
    agent.memory = types.SimpleNamespace(run_nightly_consolidation=AsyncMock())
    async def _consolidate(**kwargs):
        return {"session_ids": ["s1"], "sessions_compacted": 1}
    agent.memory.run_nightly_consolidation = _consolidate
    agent.docs = types.SimpleNamespace(consolidate_session_documents=lambda session_id, keep_recent_docs=0: {"removed_docs": 2})
    completed = await agent.run_nightly_memory_maintenance(force=True, reason="test")
    assert completed["status"] == "completed"
    assert completed["sessions_compacted"] == 1
    assert completed["rag_docs_pruned"] == 2


async def test_get_memory_archive_context_sync_filters_by_source_and_score(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    collection = Mock()
    collection.query.return_value = {
        "documents": [["doc-1\nline", "doc-2", "doc-3"]],
        "metadatas": [[
            {"source": "memory_archive", "title": "T1"},
            {"source": "other", "title": "T2"},
            {"source": "memory_archive", "title": "T3"},
        ]],
        "distances": [[0.1, 0.1, 0.9]],
    }
    agent.docs = types.SimpleNamespace(collection=collection)
    text = agent._get_memory_archive_context_sync("q", top_k=3, min_score=0.2, max_chars=500)
    assert "T1" in text
    assert "T2" not in text
    assert "T3" not in text


async def test_tool_docs_search_handles_empty_and_async_result(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    empty = await agent._tool_docs_search("")
    assert "sorgusu belirtilmedi" in empty

    async def _search(query, *_args):
        return True, f"found:{query}"

    agent.docs = types.SimpleNamespace(search=lambda *a, **k: _search(*a, **k))
    found = await agent._tool_docs_search("abc|strict")
    assert found == "found:abc"


async def test_load_instruction_files_reads_and_caches(sidar_agent_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    (root / "SIDAR.md").write_text("root rules", encoding="utf-8")
    nested = root / "sub"
    nested.mkdir()
    (nested / "CLAUDE.md").write_text("child rules", encoding="utf-8")

    agent = sidar_agent_factory()
    _override_cfg(agent, BASE_DIR=str(root))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = __import__("threading").Lock()

    first = agent._load_instruction_files()
    second = agent._load_instruction_files()
    assert "root rules" in first
    assert "child rules" in first
    assert second == first


async def test_set_access_level_changed_and_unchanged(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    memory = AsyncMock()
    security = Mock()
    security.level_name = "safe"

    def _set_level(new_level):
        if new_level == "strict" and security.level_name != "strict":
            security.level_name = "strict"
            return True
        return False

    security.set_level.side_effect = _set_level
    agent.memory = memory
    agent.security = security
    _override_cfg(agent, ACCESS_LEVEL="safe")

    changed = await agent.set_access_level("strict")
    unchanged = await agent.set_access_level("strict")
    assert changed.startswith("✓")
    assert unchanged.startswith("ℹ")
    assert security.level_name == "strict"
    assert memory.add.await_count == 2


async def test_status_renders_all_sections(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, AI_PROVIDER="x", CODING_MODEL="m", ACCESS_LEVEL="safe")
    memory = Mock()
    memory.__len__ = Mock(return_value=3)
    agent.memory = memory
    agent._autonomy_history = [{"id": 1, "timestamp": sidar_agent.time.time()}]
    agent._ensure_autonomy_runtime_state = lambda: None
    agent.github = types.SimpleNamespace(status=lambda: "github")
    agent.web = types.SimpleNamespace(status=lambda: "web")
    agent.pkg = types.SimpleNamespace(status=lambda: "pkg")
    agent.docs = types.SimpleNamespace(status=lambda: "docs")
    agent.health = types.SimpleNamespace(full_report=lambda: "health")
    text = agent.status()
    assert "SidarAgent" in text
    assert "github" in text and "web" in text and "pkg" in text and "docs" in text and "health" in text


async def test_initialize_uses_active_system_prompt(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    agent._initialized = False
    agent._init_lock = None
    agent.system_prompt = "default"

    db = AsyncMock()
    db.get_active_prompt.return_value = types.SimpleNamespace(prompt_text="live prompt")
    memory = AsyncMock()
    memory.db = db
    agent.memory = memory
    await agent.initialize()
    assert agent._initialized is True
    assert agent.system_prompt == "live prompt"


async def test_respond_handles_empty_and_success(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    agent._lock = None
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None

    added = []

    async def _memory_add(role, content):
        added.append((role, content))

    async def _multi(prompt):
        return f"ok:{prompt}"

    agent._memory_add = _memory_add
    agent._try_multi_agent = _multi

    empty = list(await _collect_stream(agent.respond("   ")))
    assert "Boş girdi" in empty[0]

    ok = list(await _collect_stream(agent.respond("hello")))
    assert ok == ["ok:hello"]
    assert added == [("user", "hello"), ("assistant", "ok:hello")]


async def test_concurrent_respond(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent._lock = None
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None

    active_multi = 0
    max_active_multi = 0
    memory_events: list[tuple[str, str]] = []

    async def _multi(prompt):
        nonlocal active_multi, max_active_multi
        active_multi += 1
        max_active_multi = max(max_active_multi, active_multi)
        await asyncio.sleep(0.01)
        active_multi -= 1
        return f"ok:{prompt}"

    async def _memory_add(role, content):
        await asyncio.sleep(0.005)
        memory_events.append((role, content))

    agent._try_multi_agent = _multi
    agent._memory_add = _memory_add

    async def _ask(prompt: str) -> list[str]:
        return list(await _collect_stream(agent.respond(prompt)))

    first, second = await asyncio.wait_for(
        asyncio.gather(_ask("alpha"), _ask("beta")),
        timeout=1.0,
    )

    assert first == ["ok:alpha"]
    assert second == ["ok:beta"]
    assert max_active_multi >= 2
    assert sorted(memory_events) == sorted(
        [
            ("user", "alpha"),
            ("assistant", "ok:alpha"),
            ("user", "beta"),
            ("assistant", "ok:beta"),
        ]
    )


async def test_respond_memory_failure_graceful(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent._lock = None
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None
    error_msg = "Memory DB Down"
    agent._memory_add = AsyncMock(side_effect=RuntimeError(error_msg))
    agent._try_multi_agent = AsyncMock(return_value="Kritik Yanıt")
    warning_mock = Mock()
    original_warning = sidar_agent.logger.warning
    sidar_agent.logger.warning = warning_mock

    try:
        responses = list(await _collect_stream(agent.respond("test input")))
    finally:
        sidar_agent.logger.warning = original_warning

    assert "Kritik Yanıt" in responses
    agent._memory_add.assert_awaited_once_with("user", "test input")
    warning_mock.assert_called_once()
    assert "Memory add failed during respond flow" in warning_mock.call_args.args[0]
    assert error_msg in str(warning_mock.call_args.args[1])


async def test_append_autonomy_history_caps_to_50(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    base = sidar_agent.time.time()
    agent._autonomy_history = [{"i": i, "timestamp": base - (60 - i)} for i in range(60)]
    agent._autonomy_lock = None
    await agent._append_autonomy_history({"i": 999})
    assert len(agent._autonomy_history) == 50
    assert agent._autonomy_history[-1]["i"] == 999


async def test_collect_and_build_self_heal_plan(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    reads = {}
    code = Mock()
    code.read_file.side_effect = lambda path, _safe: (
        reads.__setitem__(path, True) or (not path.startswith("x"), f"C:{path}")
    )
    async def _chat_side_effect(**kwargs):
        return {"raw": kwargs["messages"][0]["content"]}

    llm = AsyncMock()
    llm.chat.side_effect = _chat_side_effect

    agent.code = code
    agent.llm = llm
    _override_cfg(agent, CODING_MODEL="m", SELF_HEAL_MAX_PATCHES=2)
    monkeypatch.setattr(sidar_agent, "build_self_heal_patch_prompt", lambda *_a, **_k: "P")
    monkeypatch.setattr(sidar_agent, "normalize_self_heal_plan", lambda raw_plan, **kwargs: {"operations": [{"path": "a.py"}], "from": raw_plan, "kwargs": kwargs})

    empty = await agent._build_self_heal_plan(ci_context={}, diagnosis="d", remediation_loop={"scope_paths": []})
    assert empty["operations"] == []

    plan = await agent._build_self_heal_plan(
        ci_context={},
        diagnosis="d",
        remediation_loop={"scope_paths": ["a.py", "x.py"], "validation_commands": ["pytest"]},
   )
    assert "a.py" in reads and "x.py" in reads
    assert plan["kwargs"]["scope_paths"] == ["a.py", "x.py"]


async def test_attempt_autonomous_self_heal_blocked_and_applied(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    remediation = {"remediation_loop": {"status": "planned"}}
    blocked = await agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation)
    assert blocked["status"] == "blocked"

    agent.code = create_autospec(CodeManager, instance=True, spec_set=True)
    agent.llm = create_autospec(BaseLLMClient, instance=True, spec_set=True)
    agent._build_self_heal_plan = AsyncMock(return_value={"operations": [{"path": "a.py"}]})
    agent._execute_self_heal_plan = AsyncMock(return_value={"status": "applied", "summary": "ok", "operations_applied": ["a.py"]})
    remediation = {"remediation_loop": {"status": "planned", "steps": [{"name": "patch"}, {"name": "validate"}, {"name": "handoff"}]}}
    applied = await agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation)
    assert applied["status"] == "applied"
    assert remediation["remediation_loop"]["status"] == "applied"


async def test_build_trigger_prompt_fallback_to_trigger_prompt(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = ExternalTrigger(trigger_id="tid", source="cron", event_name="run", payload={}, meta={})
    prompt = sidar_agent.SidarAgent._build_trigger_prompt(trigger, {"kind": "other"}, None)
    assert "correlation_id=tid" in prompt


async def test_handle_external_trigger_empty_output_and_ci_self_heal_failure(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    history = []
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None
    agent._ensure_autonomy_runtime_state = lambda: None
    agent._build_trigger_correlation = lambda *_a, **_k: {}
    agent._build_trigger_prompt = lambda *_a, **_k: "PROMPT"
    agent._append_autonomy_history = AsyncMock(side_effect=lambda record: history.append(record))
    agent._memory_add = AsyncMock()
    agent._try_multi_agent = AsyncMock(return_value=" ")
    empty = await agent.handle_external_trigger({"trigger_id": "t1", "source": "s", "event_name": "e", "payload": {}, "meta": {}})
    assert empty["status"] == "empty"

    monkeypatch.setattr(sidar_agent, "build_ci_failure_context", lambda *_a, **_k: {"workflow_name": "ci", "workflow": "ci"})
    monkeypatch.setattr(sidar_agent, "build_ci_remediation_payload", lambda *_a, **_k: {"remediation_loop": {"status": "planned"}})
    agent._try_multi_agent = AsyncMock(return_value="diag")

    async def _self_heal(**_kwargs):
        raise RuntimeError("boom")

    agent._attempt_autonomous_self_heal = _self_heal
    ci = await agent.handle_external_trigger({"trigger_id": "t2", "source": "s", "event_name": "e", "payload": {}, "meta": {}})
    assert ci["status"] == "success"
    assert ci["remediation"]["self_heal_execution"]["status"] == "failed"
    assert "boom" in ci["remediation"]["self_heal_execution"].get("detail", str(ci)), (
        "Asıl hata sebebi (boom) sonuç payload'una veya loglara yansımalıdır."
   )


async def test_run_nightly_memory_maintenance_skipped_paths(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    agent.initialize = AsyncMock()
    frozen_time.tick(delta=5.0)
    agent._last_activity_ts = sidar_agent.time.time() - 5.0
    _override_cfg(agent, ENABLE_NIGHTLY_MEMORY_PRUNING=True, NIGHTLY_MEMORY_IDLE_SECONDS=100)
    agent._nightly_maintenance_lock = None
    not_idle = await agent.run_nightly_memory_maintenance()
    assert not_idle["reason"] == "not_idle"

    lock = asyncio.Lock()
    await lock.acquire()
    agent._nightly_maintenance_lock = lock
    try:
        running = await agent.run_nightly_memory_maintenance(force=True)
        assert running["reason"] == "already_running"
    finally:
        lock.release()


async def test_get_autonomy_activity_counts(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    agent._ensure_autonomy_runtime_state = lambda: None
    current_time = sidar_agent.time.time()
    agent._autonomy_history = [
        {"trigger_id": "old", "status": "success", "source": "cron", "timestamp": current_time - 10000},
        {"trigger_id": "a", "status": "success", "source": "web", "timestamp": current_time - 3600},
        {"trigger_id": "b", "status": "failed", "source": "web", "timestamp": current_time - 1800},
    ]
    activity = agent.get_autonomy_activity(2)
    assert activity["total"] == 3
    assert activity["returned"] == 2
    assert activity["latest_trigger_id"] == "b"
    assert [item["trigger_id"] for item in activity["items"]] == ["a", "b"]


async def test_try_multi_agent_and_archive_context_error_paths(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    supervisor = AsyncMock()
    supervisor.run_task.return_value = ""
    agent._supervisor = supervisor
    warning = await agent._try_multi_agent("x")
    assert "geçerli bir çıktı" in warning

    collection = Mock()
    collection.query.side_effect = RuntimeError("bad")
    agent.docs = types.SimpleNamespace(collection=collection)
    assert agent._get_memory_archive_context_sync("x", 1, 0.1, 1000) == ""


@pytest.mark.parametrize(
    ("error_side_effect", "needle"),
    [
        (TimeoutError("timeout exceeded"), "timeout exceeded"),
        (RuntimeError("rate limit exceeded"), "rate limit exceeded"),
    ],
)
async def test_handle_external_trigger_llm_timeout_and_rate_limit_errors_are_captured(
    sidar_agent_factory,
    fake_llm_error,
    error_side_effect: Exception,
    needle: str,
) -> None:
    agent = sidar_agent_factory()
    history = []
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None
    agent._ensure_autonomy_runtime_state = lambda: None
    agent._build_trigger_correlation = lambda *_a, **_k: {}
    agent._build_trigger_prompt = lambda *_a, **_k: "PROMPT"
    agent._append_autonomy_history = AsyncMock(side_effect=lambda record: history.append(record))
    agent._memory_add = AsyncMock()

    async def _raise_timeout(*_args, **_kwargs):
        raise error_side_effect

    agent._try_multi_agent = AsyncMock(
        side_effect=(fake_llm_error if isinstance(error_side_effect, RuntimeError) else _raise_timeout)
    )

    result = await agent.handle_external_trigger(
        {"trigger_id": "t-llm-1", "source": "ci", "event_name": "workflow_run", "payload": {}, "meta": {}}
    )
    assert result["status"] == "failed"
    assert needle in result["summary"]
    assert history and history[-1]["status"] == "failed"


async def test_build_context_and_instruction_absence(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(
        agent,
        AI_PROVIDER="ollama",
        PROJECT_NAME="p",
        VERSION="1",
        CODING_MODEL="cm",
        TEXT_MODEL="tm",
        GEMINI_MODEL="gm",
        ACCESS_LEVEL="safe",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="0",
        GITHUB_REPO="owner/repo",
        LOCAL_INSTRUCTION_MAX_CHARS=5,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=50,
    )
    agent.security = types.SimpleNamespace(level_name="safe")
    agent.github = types.SimpleNamespace(is_available=lambda: False)
    agent.web = types.SimpleNamespace(is_available=lambda: False)
    agent.docs = types.SimpleNamespace(status=lambda: "docs")
    agent.code = types.SimpleNamespace(get_metrics=lambda: {"files_read": 0, "files_written": 0})
    memory = Mock()
    memory.get_last_file.return_value = ""
    todo = Mock()
    todo.__len__ = Mock(return_value=0)

    agent.memory = memory
    agent.todo = todo
    agent._load_instruction_files = lambda: "abcdefghi"
    text = await agent._build_context()
    assert "AI Sağlayıcı : OLLAMA" in text
    assert "abcdefghi" in text


async def test_tool_subtask_returns_done_and_empty_warning(
    sidar_agent_factory,
    fake_llm_response,
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    async def _tool_done_response(*_args, **_kwargs) -> str:
        await fake_llm_response("subtask")
        return '{"thought":"t","tool":"final_answer","argument":"done"}'

    agent.llm = AsyncMock()
    agent.llm.chat = AsyncMock(side_effect=_tool_done_response)
    done = await agent._tool_subtask("job")
    assert "Tamamlandı" in done
    assert "belirtilmedi" in await agent._tool_subtask("")


async def test_tool_github_smart_pr_requires_token(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent.github = types.SimpleNamespace(is_available=lambda: False)
    assert await agent._tool_github_smart_pr("x") == sidar_agent.GITHUB_SMART_PR_NO_TOKEN_MESSAGE


async def test_tool_github_smart_pr_success_path(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    code = Mock()
    code.run_shell.side_effect = lambda command: (
        (True, "feat/x")
        if "branch" in command
        else (True, "M a.py")
        if "status" in command
        else (True, "c1")
        if "log" in command
        else (True, "diff")
        if "diff --no-color" in command
        else (True, "")
    )
    git = Mock()
    git.default_branch = "main"
    git.is_available.return_value = True
    git.create_pull_request.return_value = (True, "url")

    agent.code = code
    agent.github = git
    assert await agent._tool_github_smart_pr("title|||main|||note") == f"{sidar_agent.GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX} url"


async def test_summarize_memory_and_clear_memory_success(sidar_agent_factory, fake_llm_response) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, TEXT_MODEL="tm", CODING_MODEL="cm")
    agent.memory = types.SimpleNamespace(
        get_history=AsyncMock(return_value=[{"role": "user", "content": "a", "timestamp": 1}, {"role": "assistant", "content": "b", "timestamp": 1}, {"role": "user", "content": "c", "timestamp": 1}, {"role": "assistant", "content": "d", "timestamp": 1}]),
        apply_summary=AsyncMock(),
        clear=AsyncMock(),
   )
    agent.docs = types.SimpleNamespace(add_document=AsyncMock())
    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=fake_llm_response))
    await agent._summarize_memory()
    assert "temizlendi" in await agent.clear_memory()


async def test_update_remediation_step_no_match_keeps_steps(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    remediation_loop = {"steps": [{"name": "patch", "status": "planned", "detail": "x"}]}
    agent = sidar_agent_factory()
    agent._update_remediation_step(remediation_loop, "validate", status="completed", detail="ok")
    assert remediation_loop["steps"][0]["status"] == "planned"


async def test_collect_self_heal_snapshots_skips_empty_and_failed_reads(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()

    code = Mock()
    code.read_file.side_effect = lambda path, _safe: (False, "missing") if path == "bad.py" else (True, f"content:{path}")
    agent.code = code
    snapshots = await agent._collect_self_heal_snapshots(["", "./ok.py", "bad.py"])
    assert snapshots == [{"path": "ok.py", "content": "content:ok.py"}]


async def test_execute_self_heal_plan_skipped_blocked_and_backup_failure(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, BASE_DIR=str(tmp_path))

    code = Mock()
    code.read_file.return_value = (False, "nope")
    code.patch_file.return_value = (True, "ok")
    code.write_file.return_value = (True, "ok")
    code.run_shell_in_sandbox.return_value = (True, "ok")

    agent.code = code

    skipped = await agent._execute_self_heal_plan(remediation_loop={}, plan={"operations": []})
    assert skipped["status"] == "skipped"

    blocked = await agent._execute_self_heal_plan(
        remediation_loop={},
        plan={"operations": [{"path": "a.py", "target": "x", "replacement": "y"}], "validation_commands": []},
   )
    assert blocked["status"] == "blocked"

    reverted = await agent._execute_self_heal_plan(
        remediation_loop={},
        plan={"operations": [{"path": "a.py", "target": "x", "replacement": "y"}], "validation_commands": ["pytest -q"]},
   )
    assert reverted["status"] == "reverted"
    assert "yedekleme" in reverted["summary"]


async def test_build_trigger_prompt_prefers_federation_prompt(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    trigger = ExternalTrigger(trigger_id="tid", source="crm", event_name="sync", payload={}, meta={})
    prompt = sidar_agent.SidarAgent._build_trigger_prompt(
        trigger,
        {"kind": "federation_task", "federation_prompt": "PRESET"},
        None,
   )
    assert prompt == "PRESET"


async def test_build_trigger_correlation_matches_related_ids(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    now = sidar_agent.time.time()
    agent._autonomy_history = [
        {"trigger_id": "t-old", "status": "success", "source": "cron", "payload": {"task_id": "T"}, "meta": {}, "timestamp": now - 180},
        {"trigger_id": "t-rel", "status": "failed", "source": "api", "payload": {}, "meta": {}, "timestamp": now - 30},
    ]
    agent._autonomy_lock = None
    trigger = ExternalTrigger(trigger_id="t-new", source="api", event_name="e", payload={}, meta={})
    corr = agent._build_trigger_correlation(trigger, {"related_trigger_id": "t-rel", "related_task_id": "T"})
    assert corr["matched_records"] == 2
    assert corr["latest_related_status"] == "failed"


async def test_try_multi_agent_imports_supervisor_when_missing(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    agent._supervisor = None

    from agent.core import supervisor as supervisor_mod
    supervisor_cls = Mock()
    supervisor_instance = AsyncMock()
    supervisor_instance.run_task.return_value = "ok:hello"
    supervisor_cls.return_value = supervisor_instance
    monkeypatch.setattr(supervisor_mod, "SupervisorAgent", supervisor_cls)

    result = await agent._try_multi_agent("hello")
    assert result == "ok:hello"


async def test_get_memory_archive_context_async_and_sync_edges(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, MEMORY_ARCHIVE_TOP_K=1, MEMORY_ARCHIVE_MIN_SCORE=0.3, MEMORY_ARCHIVE_MAX_CHARS=1200)

    agent.docs = types.SimpleNamespace(collection=None)
    assert agent._get_memory_archive_context_sync("x", 1, 0.2, 300) == ""

    collection = Mock()
    collection.query.return_value = {
        "documents": [["x" * 700, ""]],
        "metadatas": [[{"source": "memory_archive", "title": "Long"}, {"source": "memory_archive", "title": "Empty"}]],
        "distances": [[0.0, 0.0]],
    }
    agent.docs = types.SimpleNamespace(collection=collection)
    sync_text = agent._get_memory_archive_context_sync("x", 1, 0.2, 1200)
    assert "Long" in sync_text
    assert "..." in sync_text

    async_text = await agent._get_memory_archive_context("x")
    assert sidar_agent.ARCHIVE_CONTEXT_HEADER in async_text


async def test_build_context_non_ollama_and_truncations(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(
        agent,
        AI_PROVIDER="openai",
        PROJECT_NAME="proj",
        VERSION="2",
        CODING_MODEL="cm",
        TEXT_MODEL="tm",
        GEMINI_MODEL="gem",
        ACCESS_LEVEL="strict",
        USE_GPU=True,
        GPU_INFO="RTX",
        CUDA_VERSION="12.0",
        GITHUB_REPO="org/repo",
        LOCAL_INSTRUCTION_MAX_CHARS=20,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=120,
    )
    agent.security = types.SimpleNamespace(level_name="strict")
    agent.github = types.SimpleNamespace(is_available=lambda: True)
    agent.web = types.SimpleNamespace(is_available=lambda: True)
    agent.docs = types.SimpleNamespace(status=lambda: "docs-ready")
    agent.code = types.SimpleNamespace(get_metrics=lambda: {"files_read": 2, "files_written": 1})
    agent.memory = types.SimpleNamespace(get_last_file=lambda: "/tmp/work/demo.py")

    todo = Mock()
    todo.__len__ = Mock(return_value=1)
    todo.list_tasks.return_value = "task-1"
    agent.todo = todo
    agent._load_instruction_files = lambda: "instructions"

    text = await agent._build_context()
    assert "Gemini Modeli" in text
    assert "Bağlı — org/repo" in text
    assert "Aktif Görev Listesi" in text

    agent.cfg.AI_PROVIDER = "ollama"
    agent._load_instruction_files = lambda: "i" * 5000
    short = await agent._build_context()
    assert "yerel model" in short


async def test_load_instruction_files_no_files_and_read_error(sidar_agent_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, BASE_DIR=str(tmp_path))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = __import__("threading").Lock()

    assert agent._load_instruction_files() == ""

    unreadable_path = tmp_path / "SIDAR.md"
    unreadable_path.mkdir()
    assert agent._load_instruction_files() == ""


async def test_tool_subtask_non_string_and_tool_exception(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    agent.llm = AsyncMock(chat=AsyncMock(side_effect=[{"not": "string"}, '{"tool":"x","argument":"a","thought":"t"}']))
    agent._execute_tool = AsyncMock(side_effect=RuntimeError("fail-tool"))

    output = await agent._tool_subtask("job")
    assert output == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE


async def test_tool_github_smart_pr_error_branches(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    agent.github = types.SimpleNamespace(is_available=lambda: True, default_branch="main", create_pull_request=lambda *_a: (False, "err"))

    code = Mock()
    code.run_shell.side_effect = lambda command: (False, "") if "branch" in command else (True, "")
    agent.code = code
    no_branch = await agent._tool_github_smart_pr("x")
    assert no_branch == sidar_agent.GITHUB_SMART_PR_NO_BRANCH_MESSAGE

    code.run_shell.side_effect = lambda command: (True, "feat/a") if "branch" in command else ((True, "") if "status" in command else (True, ""))
    agent.code = code
    no_changes = await agent._tool_github_smart_pr("x")
    assert no_changes == sidar_agent.GITHUB_SMART_PR_NO_CHANGES_MESSAGE

    code.run_shell.side_effect = lambda command: (
        (True, "feat/a")
        if "branch" in command
        else (True, "M a.py")
        if "status" in command
        else (True, "x" * 12000)
        if "diff --no-color" in command
        else (True, "c1")
        if "log" in command
        else (True, "")
    )
    agent.code = code
    assert (await agent._tool_github_smart_pr("title|||base|||note")).startswith(sidar_agent.GITHUB_SMART_PR_CREATE_FAILED_PREFIX)


async def test_summarize_memory_exception_paths_and_memory_add(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    added = []
    memory = AsyncMock()
    memory.get_history.return_value = [
        {"role": "user", "content": "a", "timestamp": 1},
        {"role": "assistant", "content": "b", "timestamp": 1},
        {"role": "user", "content": "c", "timestamp": 1},
        {"role": "assistant", "content": "d", "timestamp": 1},
    ]
    memory.apply_summary.side_effect = RuntimeError("sum-fail")

    async def _capture_add(role, content):
        added.append((role, content))

    memory.add.side_effect = _capture_add
    docs = AsyncMock()
    docs.add_document.side_effect = RuntimeError("rag-fail")

    agent.memory = memory
    agent.docs = docs
    agent.llm = types.SimpleNamespace(chat=AsyncMock(return_value="summary"))
    _override_cfg(agent, TEXT_MODEL="tm", CODING_MODEL="cm")

    await agent._summarize_memory()
    await agent._memory_add("user", "hello")
    assert added == [("user", "hello")]


async def test_init_accepts_namespace_cfg(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    base_dir.mkdir(parents=True, exist_ok=True)

    cfg = types.SimpleNamespace(
        BASE_DIR=str(base_dir),
        DOCKER_PYTHON_IMAGE="img",
        DOCKER_EXEC_TIMEOUT=3,
        USE_GPU=False,
        GITHUB_TOKEN="t",
        GITHUB_REPO="org/repo",
        DATABASE_URL="sqlite:///x",
        MEMORY_FILE="mem.json",
        MAX_MEMORY_TURNS=7,
        MEMORY_ENCRYPTION_KEY="",
        MEMORY_SUMMARY_KEEP_LAST=2,
        AI_PROVIDER="openai",
        RAG_DIR="rag",
        RAG_TOP_K=2,
        RAG_CHUNK_SIZE=100,
        RAG_CHUNK_OVERLAP=5,
        GPU_DEVICE=0,
        GPU_MIXED_PRECISION=False,
        ENABLE_TRACING=False,
        CODING_MODEL="cm",
        ACCESS_LEVEL="safe",
    )
    agent = sidar_agent.SidarAgent(cfg)
    assert agent.cfg.BASE_DIR == str(base_dir)


async def test_normalize_config_defaults_reverts_invalid_types() -> None:
    invalid_cfg = types.SimpleNamespace(
        MAX_MEMORY_TURNS="beş",
        ENABLE_TRACING="evet",
        AI_PROVIDER=123,
    )

    agent = sidar_agent.SidarAgent(cfg=invalid_cfg)

    assert isinstance(agent.cfg.MAX_MEMORY_TURNS, int)
    assert isinstance(agent.cfg.ENABLE_TRACING, bool)
    assert isinstance(agent.cfg.AI_PROVIDER, str)


async def test_parse_tool_call_non_dict_returns_final_answer(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    parsed = agent._parse_tool_call("[1,2,3]")
    assert parsed == {"tool": "final_answer", "argument": "[1,2,3]"}


async def test_initialize_returns_immediately_when_already_initialized(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent._initialized = True
    await agent.initialize()



async def test_runtime_helpers_and_self_heal_validation_failure(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    agent = sidar_agent_factory()
    agent._last_activity_ts = 0
    agent.mark_activity("test")
    assert agent.seconds_since_last_activity() >= 0

    agent._autonomy_history = []
    agent._autonomy_lock = None
    agent._ensure_autonomy_runtime_state()
    assert agent._autonomy_history == [] and agent._autonomy_lock is None

    code = Mock()
    code.read_file.return_value = (True, "old")
    code.patch_file.return_value = (True, "ok")
    code.write_file.return_value = (True, "ok")
    code.run_shell_in_sandbox.return_value = (False, "bad")
    agent.code = code
    _override_cfg(agent, BASE_DIR=str(tmp_path))
    reverted = await agent._execute_self_heal_plan(
        remediation_loop={"validation_commands": ["pytest -q"]},
        plan={"operations": [{"path": "a.py", "target": "a", "replacement": "b"}]},
   )
    assert reverted["status"] == "reverted"
    assert "Sandbox doğrulaması" in reverted["summary"]



async def test_attempt_self_heal_failed_branch_and_workflow_payload_dict(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    agent.code = create_autospec(CodeManager, instance=True, spec_set=True)
    agent.llm = create_autospec(BaseLLMClient, instance=True, spec_set=True)
    agent._build_self_heal_plan = AsyncMock(return_value={"operations": [{"path": "a.py"}]})
    agent._execute_self_heal_plan = AsyncMock(return_value={"status": "reverted", "summary": "bad", "operations_applied": []})
    remediation = {"remediation_loop": {"status": "planned", "steps": [{"name": "patch"}, {"name": "validate"}]}}
    failed = await agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="d", remediation=remediation)
    assert failed["status"] == "reverted"
    assert remediation["remediation_loop"]["status"] == "reverted"

    history = []
    agent.initialize = AsyncMock()
    agent._ensure_autonomy_runtime_state = lambda: None
    agent.mark_activity = lambda *_a, **_k: None
    agent._build_trigger_correlation = lambda *_a, **_k: {}
    agent._build_trigger_prompt = lambda *_a, **_k: "PROMPT"
    agent._append_autonomy_history = AsyncMock(side_effect=lambda record: history.append(record))
    agent._memory_add = AsyncMock()
    agent._try_multi_agent = AsyncMock(return_value="diag")

    monkeypatch.setattr(sidar_agent, "build_ci_failure_context", lambda *_a, **_k: {"from": "fallback"})
    monkeypatch.setattr(sidar_agent, "build_ci_remediation_payload", lambda *_a, **_k: {"remediation_loop": {"status": "planned"}})
    agent._attempt_autonomous_self_heal = AsyncMock()

    payload = {
        "kind": "workflow_run",
        "workflow_name": "ci",
        "workflow": "ci",
    }
    out = await agent.handle_external_trigger({"trigger_id": "w1", "source": "gh", "event_name": "workflow_run", "payload": payload, "meta": {}})
    assert out["status"] == "success"
    assert out["payload"]["workflow_name"] == "ci"



async def test_nightly_maintenance_handles_entity_failure(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    agent.initialize = AsyncMock()
    agent._append_autonomy_history = AsyncMock()
    agent._nightly_maintenance_lock = None
    frozen_time.tick(delta=9999.0)
    agent._last_activity_ts = sidar_agent.time.time() - 9999.0
    _override_cfg(
        agent,
        ENABLE_NIGHTLY_MEMORY_PRUNING=True,
        NIGHTLY_MEMORY_IDLE_SECONDS=100,
        NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=2,
        NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=3,
        NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=1,
    )

    entity = AsyncMock()
    entity.initialize.side_effect = RuntimeError("entity-boom")
    entity.purge_expired.return_value = 0
    monkeypatch.setattr(sidar_agent, "get_entity_memory", lambda *_a, **_k: entity)
    agent.memory = types.SimpleNamespace(run_nightly_consolidation=AsyncMock(return_value={"session_ids": [], "sessions_compacted": 0}))
    agent.docs = types.SimpleNamespace(consolidate_session_documents=lambda *_a, **_k: {"removed_docs": 0})
    report = await agent.run_nightly_memory_maintenance(force=True)
    assert report["entity_report"]["status"] == "failed"

async def test_get_memory_archive_context_sync_filters_distances(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    collection = Mock()
    collection.query.return_value = {
        "documents": [["", "ok"]],
        "metadatas": [[{"source": "memory_archive", "title": "E"}, {"source": "memory_archive", "title": "T"}]],
        "distances": [[0.9, 0.1]],
    }
    agent.docs = types.SimpleNamespace(collection=collection)

    result = agent._get_memory_archive_context_sync("q", 3, 0.2, 100)
    assert "T" in result
    assert "E" not in result


async def test_load_instruction_files_handles_fs_errors(sidar_agent_factory, tmp_path: Path) -> None:
    agent = sidar_agent_factory(cfg=types.SimpleNamespace(BASE_DIR=str(tmp_path)))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = __import__("threading").Lock()

    (tmp_path / "SIDAR.md").mkdir()
    (tmp_path / "CLAUDE.md").write_text("ok-content", encoding="utf-8")

    content = agent._load_instruction_files()
    assert "ok-content" in content



async def test_tool_docs_search_returns_plain_text(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent.docs = types.SimpleNamespace(search=lambda *_a: (True, "plain"))
    assert await agent._tool_docs_search("q") == "plain"


async def test_build_context_truncates_for_local_models(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    _override_cfg(
        agent,
        AI_PROVIDER="openai",
        PROJECT_NAME="p",
        VERSION="1",
        CODING_MODEL="cm",
        TEXT_MODEL="tm",
        GEMINI_MODEL="gm",
        ACCESS_LEVEL="safe",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="0",
        GITHUB_REPO="org/repo",
        LOCAL_INSTRUCTION_MAX_CHARS=10,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=9999,
        SUBTASK_MAX_STEPS=1,
    )
    agent.security = types.SimpleNamespace(level_name="safe")
    agent.github = types.SimpleNamespace(is_available=lambda: True, status=lambda: "g")
    agent.web = types.SimpleNamespace(is_available=lambda: True, status=lambda: "w")
    agent.docs = types.SimpleNamespace(status=lambda: "d", search=lambda *_a: (True, "plain"))
    agent.code = types.SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 1})
    agent.memory = types.SimpleNamespace(get_last_file=lambda: "")
    agent.todo = types.SimpleNamespace(__len__=lambda *_a: 0)
    agent._load_instruction_files = lambda: ""
    ctx = await agent._build_context()
    assert "Aktif Görev Listesi" not in ctx

    agent.cfg.AI_PROVIDER = "ollama"
    agent.cfg.LOCAL_INSTRUCTION_MAX_CHARS = 5000
    agent.cfg.LOCAL_AGENT_CONTEXT_MAX_CHARS = 1
    agent._load_instruction_files = lambda: "x" * 5000
    tiny = await agent._build_context()
    assert "Bağlam yerel model için kırpıldı" in tiny

async def test_tool_subtask_records_metrics_on_failure(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")
    metrics_calls = []
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: types.SimpleNamespace(record_step=lambda *a: metrics_calls.append(a)),
    )

    agent.llm = AsyncMock(chat=AsyncMock(return_value='{"tool":"docs_search","argument":"arg","thought":"x"}'))
    agent._execute_tool = AsyncMock(side_effect=RuntimeError("tool-boom"))
    out = await agent._tool_subtask("job")
    assert out == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE
    assert any(call[3] == "failed" for call in metrics_calls)


async def test_tool_github_smart_pr_creates_pr_successfully(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()

    github = Mock()
    github.is_available.return_value = True
    github.create_pull_request.return_value = (True, "ok")
    github.default_branch = "main"

    code = Mock()
    code.run_shell.side_effect = lambda command: (
        (True, "feat/a")
        if "branch" in command
        else (True, "M a.py")
        if "status" in command
        else (True, "diff")
        if "diff --no-color" in command
        else (True, "c1")
        if "log" in command
        else (True, "")
    )

    agent.github = github
    agent.code = code
    msg = await agent._tool_github_smart_pr("title")
    assert "oluşturuldu" in msg


async def test_attempt_self_heal_plan_without_operations_and_initialize_no_prompt(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    agent.code = create_autospec(CodeManager, instance=True, spec_set=True)
    agent.llm = create_autospec(BaseLLMClient, instance=True, spec_set=True)
    agent._build_self_heal_plan = AsyncMock(return_value={"operations": []})
    remediation = {"remediation_loop": {"status": "planned", "steps": [{"name": "patch"}]}}
    blocked = await agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="d", remediation=remediation)
    assert blocked["status"] == "blocked"
    assert remediation["remediation_loop"]["steps"][0]["status"] == "blocked"

    agent2 = sidar_agent_factory()
    agent2._initialized = False
    agent2._init_lock = asyncio.Lock()
    agent2.system_prompt = "default"

    db = AsyncMock()
    db.get_active_prompt.return_value = types.SimpleNamespace(prompt_text="   ")
    memory = AsyncMock()
    memory.db = db
    agent2.memory = memory
    await agent2.initialize()
    assert agent2.system_prompt == "default"


async def test_initialize_inner_early_return_branch(sidar_agent_factory) -> None:
    agent_init = sidar_agent_factory()
    agent_init._initialized = False

    lock = AsyncMock()
    async def _enter():
        agent_init._initialized = True
        return lock
    lock.__aenter__.side_effect = _enter
    lock.__aexit__.return_value = False
    agent_init._init_lock = lock
    agent_init.memory = types.SimpleNamespace(initialize=AsyncMock())
    await agent_init.initialize()


async def test_respond_and_append_history_with_existing_locks(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent._lock = asyncio.Lock()
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None
    mem = []
    agent._memory_add = AsyncMock(side_effect=lambda role, content: mem.append((role, content)))
    agent._try_multi_agent = AsyncMock(return_value="ok")
    assert list(await _collect_stream(agent.respond("hi"))) == ["ok"]

    # _append_autonomy_history(): existing lock branch
    agent._autonomy_history = []
    agent._autonomy_lock = asyncio.Lock()
    await agent._append_autonomy_history({"x": 1, "timestamp": sidar_agent.time.time()})


async def test_execute_self_heal_plan_applied_with_existing_backup(sidar_agent_factory, tmp_path: Path) -> None:
    agent = sidar_agent_factory()
    code = Mock()
    code.read_file.return_value = (True, "old")
    code.patch_file.return_value = (True, "ok")
    code.run_shell_in_sandbox.return_value = (True, "ok")
    code.write_file.return_value = (True, "ok")
    agent.code = code
    _override_cfg(agent, BASE_DIR=str(tmp_path))
    plan = {
        "operations": [
            {"path": "a.py", "target": "x", "replacement": "y"},
            {"path": "a.py", "target": "y", "replacement": "z"},
        ],
        "validation_commands": ["pytest -q"],
    }
    assert (await agent._execute_self_heal_plan(remediation_loop={}, plan=plan))["status"] == "applied"


async def test_tool_subtask_exception_path_records_failed_metrics(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    metrics_calls = []
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: types.SimpleNamespace(record_step=lambda *a: metrics_calls.append(a)),
    )

    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")
    agent.llm = AsyncMock(chat=AsyncMock(return_value='{"tool":"docs_search","argument":"arg","thought":"x"}'))

    agent._execute_tool = AsyncMock(side_effect=RuntimeError("tool-boom"))
    out = await agent._tool_subtask("job")
    assert out == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE
    assert any(call[3] == "failed" for call in metrics_calls)


async def test_handle_external_trigger_instance_path_and_correlation_loop(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = sidar_agent_factory()
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None
    agent._ensure_autonomy_runtime_state = lambda: None
    agent._append_autonomy_history = AsyncMock()
    agent._memory_add = AsyncMock()
    agent._try_multi_agent = AsyncMock(return_value="ok")
    monkeypatch.setattr(sidar_agent, "build_ci_failure_context", lambda *_a, **_k: None)

    trigger = ExternalTrigger(trigger_id="t", source="s", event_name="e", payload={}, meta={})
    out = await agent.handle_external_trigger(trigger)
    assert out["status"] == "success"

    agent._autonomy_history = [{"trigger_id": "x", "payload": {}, "timestamp": sidar_agent.time.time()}]
    agent._autonomy_lock = None
    corr = agent._build_trigger_correlation(trigger, {})
    assert corr["matched_records"] == 0


async def test_initialize_without_db_and_tool_subtask_remaining_branches(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:

    # initialize branch where memory has no db
    agent = sidar_agent_factory()
    agent._initialized = False
    agent._init_lock = None

    agent.memory = types.SimpleNamespace(initialize=AsyncMock(return_value=None))
    agent.system_prompt = "default"
    await agent.initialize()
    assert agent._initialized is True

    # Make ValidationError distinct so generic exception branch can execute
    validation_err = type("ValidationErr", (Exception,), {})
    monkeypatch.setattr(sidar_agent, "ValidationError", validation_err)

    # _metrics None + successful tool execution branch (1106->1114)
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: (_ for _ in ()).throw(RuntimeError("metrics unavailable")),
    )

    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")
    agent.llm = AsyncMock(chat=AsyncMock(return_value='{"tool":"docs_search","argument":"arg","thought":"x"}'))
    agent._execute_tool = AsyncMock(return_value="ok")
    assert sidar_agent.SUBTASK_MAX_STEPS_MESSAGE == await agent._tool_subtask("job")

    # generic exception branch with metrics enabled (1125-1137)
    calls = []
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: types.SimpleNamespace(record_step=lambda *a: calls.append(a)),
    )

    agent._execute_tool = AsyncMock(side_effect=RuntimeError("tool-fail"))
    out = await agent._tool_subtask("job")
    assert out == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE
    assert any(c[3] == "failed" for c in calls)


async def test_tool_subtask_generic_exception_without_metrics(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    validation_err = type("ValidationErr", (Exception,), {})
    monkeypatch.setattr(sidar_agent, "ValidationError", validation_err)
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: (_ for _ in ()).throw(RuntimeError("metrics unavailable")),
    )

    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")

    agent.llm = AsyncMock(chat=AsyncMock(return_value='{"tool":"docs_search","argument":"arg","thought":"x"}'))
    agent._execute_tool = AsyncMock(side_effect=RuntimeError("fail"))
    assert sidar_agent.SUBTASK_MAX_STEPS_MESSAGE == await agent._tool_subtask("job")


async def test_load_instruction_files_handles_string_candidates(sidar_agent_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    agent = sidar_agent_factory()
    instruction = tmp_path / "SIDAR.md"
    instruction.write_text("Talimat", encoding="utf-8")

    _override_cfg(agent, BASE_DIR=str(tmp_path))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = __import__("threading").Lock()

    loaded = agent._load_instruction_files()
    assert "SIDAR.md" in loaded
    assert "Talimat" in loaded
