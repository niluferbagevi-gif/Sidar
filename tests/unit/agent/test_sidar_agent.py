import importlib
import sys
import types
import asyncio
from pathlib import Path

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


def test_execute_self_heal_plan_success_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    writes = {}

    class _Code:
        def read_file(self, path, _safe):
            return True, f"old:{path}"

        def patch_file(self, path, target, replacement):
            writes[path] = (target, replacement)
            return True, "ok"

        def write_file(self, path, content, _safe):
            writes[path] = ("restore", content)
            return True, "ok"

        def run_shell_in_sandbox(self, command, base_dir):
            return True, f"ok:{command}:{base_dir}"

    agent.code = _Code()
    agent.cfg = types.SimpleNamespace(BASE_DIR="/tmp/project")

    plan = {
        "summary": "patching",
        "confidence": "high",
        "operations": [{"path": "a.py", "target": "A", "replacement": "B"}],
        "validation_commands": ["pytest -q"],
    }
    remediation_loop = {"validation_commands": ["pytest -q"]}
    result = asyncio.run(agent._execute_self_heal_plan(remediation_loop=remediation_loop, plan=plan))

    assert result["status"] == "applied"
    assert result["operations_applied"] == ["a.py"]
    assert len(result["validation_results"]) == 1
    assert writes["a.py"] == ("A", "B")


def test_execute_self_heal_plan_reverts_on_patch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    restored = {}

    class _Code:
        def read_file(self, path, _safe):
            return True, f"old:{path}"

        def patch_file(self, path, target, replacement):
            return False, "boom"

        def write_file(self, path, content, _safe):
            restored[path] = content
            return True, "ok"

        def run_shell_in_sandbox(self, command, base_dir):
            return True, "ok"

    agent.code = _Code()
    agent.cfg = types.SimpleNamespace(BASE_DIR="/tmp/project")
    plan = {
        "operations": [{"path": "a.py", "target": "A", "replacement": "B"}],
        "validation_commands": ["pytest -q"],
    }
    result = asyncio.run(agent._execute_self_heal_plan(remediation_loop={}, plan=plan))
    assert result["status"] == "reverted"
    assert result["reverted"] is True
    assert restored == {"a.py": "old:a.py"}


def test_attempt_autonomous_self_heal_core_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = types.SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=False)
    remediation = {"remediation_loop": {"status": "planned"}}
    disabled = asyncio.run(agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation))
    assert disabled["status"] == "disabled"

    agent.cfg = types.SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=True)
    remediation = {"remediation_loop": {"status": "queued"}}
    skipped = asyncio.run(agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation))
    assert skipped["status"] == "skipped"

    remediation = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": True,
            "steps": [{"name": "handoff", "status": "planned", "detail": ""}],
        }
    }
    hitl = asyncio.run(agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation))
    assert hitl["status"] == "awaiting_hitl"
    assert remediation["remediation_loop"]["steps"][0]["status"] == "awaiting_hitl"


def test_handle_external_trigger_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    records = []
    memory_rows = []
    agent.initialize = _dummy_async
    agent._ensure_autonomy_runtime_state = lambda: None
    agent.mark_activity = lambda source="runtime": None
    agent._build_trigger_correlation = lambda trigger, payload: {"correlation_id": "cid"}
    agent._build_trigger_prompt = lambda trigger, payload, ci: "PROMPT"

    async def _append(record):
        records.append(record)
    agent._append_autonomy_history = _append

    async def _memory_add(role, content):
        memory_rows.append((role, content))
    agent._memory_add = _memory_add

    async def _ok(prompt):
        return "summary"
    agent._try_multi_agent = _ok

    result = asyncio.run(agent.handle_external_trigger({"trigger_id": "tr-1", "source": "s", "event_name": "e", "payload": {}, "meta": {}}))
    assert result["status"] == "success"
    assert records and records[0]["summary"] == "summary"
    assert memory_rows[0][0] == "user"
    assert memory_rows[1][0] == "assistant"

    async def _fail(prompt):
        raise RuntimeError("x")
    agent._try_multi_agent = _fail
    failed = asyncio.run(agent.handle_external_trigger({"trigger_id": "tr-2", "source": "s", "event_name": "e", "payload": {}, "meta": {}}))
    assert failed["status"] == "failed"
    assert "işlenemedi" in failed["summary"]


def test_run_nightly_memory_maintenance_disabled_and_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.initialize = _dummy_async
    agent._append_autonomy_history = _dummy_async
    agent._nightly_maintenance_lock = None
    agent.seconds_since_last_activity = lambda: 9999.0
    agent.cfg = types.SimpleNamespace(
        ENABLE_NIGHTLY_MEMORY_PRUNING=False,
        NIGHTLY_MEMORY_IDLE_SECONDS=100,
        NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=2,
        NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=3,
        NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=1,
    )
    disabled = asyncio.run(agent.run_nightly_memory_maintenance())
    assert disabled["status"] == "disabled"

    agent.cfg.ENABLE_NIGHTLY_MEMORY_PRUNING = True
    agent.memory = types.SimpleNamespace(run_nightly_consolidation=_dummy_async)
    async def _consolidate(**kwargs):
        return {"session_ids": ["s1"], "sessions_compacted": 1}
    agent.memory.run_nightly_consolidation = _consolidate
    agent.docs = types.SimpleNamespace(consolidate_session_documents=lambda session_id, keep_recent_docs=0: {"removed_docs": 2})
    completed = asyncio.run(agent.run_nightly_memory_maintenance(force=True, reason="test"))
    assert completed["status"] == "completed"
    assert completed["sessions_compacted"] == 1
    assert completed["rag_docs_pruned"] == 2


def test_get_memory_archive_context_sync_filters_by_source_and_score(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)

    class _Collection:
        def query(self, **kwargs):
            return {
                "documents": [["doc-1\nline", "doc-2", "doc-3"]],
                "metadatas": [[
                    {"source": "memory_archive", "title": "T1"},
                    {"source": "other", "title": "T2"},
                    {"source": "memory_archive", "title": "T3"},
                ]],
                "distances": [[0.1, 0.1, 0.9]],
            }

    agent.docs = types.SimpleNamespace(collection=_Collection())
    text = agent._get_memory_archive_context_sync("q", top_k=3, min_score=0.2, max_chars=500)
    assert "T1" in text
    assert "T2" not in text
    assert "T3" not in text


def test_tool_docs_search_handles_empty_and_async_result(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    empty = asyncio.run(agent._tool_docs_search(""))
    assert "sorgusu belirtilmedi" in empty

    async def _search(query, *_args):
        return True, f"found:{query}"

    agent.docs = types.SimpleNamespace(search=lambda *a, **k: _search(*a, **k))
    found = asyncio.run(agent._tool_docs_search("abc|strict"))
    assert found == "found:abc"


def test_load_instruction_files_reads_and_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    root = tmp_path
    (root / "SIDAR.md").write_text("root rules", encoding="utf-8")
    nested = root / "sub"
    nested.mkdir()
    (nested / "CLAUDE.md").write_text("child rules", encoding="utf-8")

    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = types.SimpleNamespace(BASE_DIR=str(root))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = __import__("threading").Lock()

    first = agent._load_instruction_files()
    second = agent._load_instruction_files()
    assert "root rules" in first
    assert "child rules" in first
    assert second == first


def test_set_access_level_changed_and_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    added = []

    class _Memory:
        async def add(self, role, content):
            added.append((role, content))

    class _Security:
        level_name = "safe"

        def set_level(self, new_level):
            if new_level == "strict" and self.level_name != "strict":
                self.level_name = "strict"
                return True
            return False

    agent.memory = _Memory()
    agent.security = _Security()
    agent.cfg = types.SimpleNamespace(ACCESS_LEVEL="safe")

    changed = asyncio.run(agent.set_access_level("strict"))
    unchanged = asyncio.run(agent.set_access_level("strict"))
    assert "güncellendi" in changed
    assert "zaten" in unchanged
    assert len(added) == 2


def test_status_renders_all_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = types.SimpleNamespace(AI_PROVIDER="x", CODING_MODEL="m", ACCESS_LEVEL="safe")
    class _Memory:
        def __len__(self):
            return 3
    agent.memory = _Memory()
    agent._autonomy_history = [{"id": 1}]
    agent._ensure_autonomy_runtime_state = lambda: None
    agent.github = types.SimpleNamespace(status=lambda: "github")
    agent.web = types.SimpleNamespace(status=lambda: "web")
    agent.pkg = types.SimpleNamespace(status=lambda: "pkg")
    agent.docs = types.SimpleNamespace(status=lambda: "docs")
    agent.health = types.SimpleNamespace(full_report=lambda: "health")
    text = agent.status()
    assert "SidarAgent" in text
    assert "github" in text and "web" in text and "pkg" in text and "docs" in text and "health" in text


def test_initialize_uses_active_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent._initialized = False
    agent._init_lock = None
    agent.system_prompt = "default"

    class _Prompt:
        prompt_text = "live prompt"

    class _DB:
        async def get_active_prompt(self, _name):
            return _Prompt()

    class _Memory:
        db = _DB()

        async def initialize(self):
            return None

    agent.memory = _Memory()
    asyncio.run(agent.initialize())
    assert agent._initialized is True
    assert agent.system_prompt == "live prompt"


def test_respond_handles_empty_and_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent._lock = None
    agent.initialize = _dummy_async
    agent.mark_activity = lambda *_a, **_k: None

    added = []

    async def _memory_add(role, content):
        added.append((role, content))

    async def _multi(prompt):
        return f"ok:{prompt}"

    agent._memory_add = _memory_add
    agent._try_multi_agent = _multi

    empty = list(asyncio.run(_collect_stream(agent.respond("   "))))
    assert "Boş girdi" in empty[0]

    ok = list(asyncio.run(_collect_stream(agent.respond("hello"))))
    assert ok == ["ok:hello"]
    assert added == [("user", "hello"), ("assistant", "ok:hello")]


async def _collect_stream(stream):
    items = []
    async for piece in stream:
        items.append(piece)
    return items


def test_append_autonomy_history_caps_to_50(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent._autonomy_history = [{"i": i} for i in range(60)]
    agent._autonomy_lock = None
    asyncio.run(agent._append_autonomy_history({"i": 999}))
    assert len(agent._autonomy_history) == 50
    assert agent._autonomy_history[-1]["i"] == 999


def test_collect_and_build_self_heal_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    reads = {}

    class _Code:
        def read_file(self, path, _safe):
            reads[path] = True
            return (not path.startswith("x"), f"C:{path}")

    class _LLM:
        async def chat(self, **kwargs):
            return {"raw": kwargs["messages"][0]["content"]}

    agent.code = _Code()
    agent.llm = _LLM()
    agent.cfg = types.SimpleNamespace(CODING_MODEL="m", SELF_HEAL_MAX_PATCHES=2)
    monkeypatch.setattr(sidar_agent, "build_self_heal_patch_prompt", lambda *_a, **_k: "P")
    monkeypatch.setattr(sidar_agent, "normalize_self_heal_plan", lambda raw_plan, **kwargs: {"operations": [{"path": "a.py"}], "from": raw_plan, "kwargs": kwargs})

    empty = asyncio.run(agent._build_self_heal_plan(ci_context={}, diagnosis="d", remediation_loop={"scope_paths": []}))
    assert empty["operations"] == []

    plan = asyncio.run(
        agent._build_self_heal_plan(
            ci_context={},
            diagnosis="d",
            remediation_loop={"scope_paths": ["a.py", "x.py"], "validation_commands": ["pytest"]},
        )
    )
    assert "a.py" in reads and "x.py" in reads
    assert plan["kwargs"]["scope_paths"] == ["a.py", "x.py"]


def test_attempt_autonomous_self_heal_blocked_and_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = types.SimpleNamespace(ENABLE_AUTONOMOUS_SELF_HEAL=True)
    remediation = {"remediation_loop": {"status": "planned"}}
    blocked = asyncio.run(agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation))
    assert blocked["status"] == "blocked"

    agent.code = object()
    agent.llm = object()
    agent._build_self_heal_plan = _dummy_async
    agent._execute_self_heal_plan = _dummy_async
    agent._build_self_heal_plan = lambda **_k: _async_value({"operations": [{"path": "a.py"}]})
    agent._execute_self_heal_plan = lambda **_k: _async_value({"status": "applied", "summary": "ok", "operations_applied": ["a.py"]})
    remediation = {"remediation_loop": {"status": "planned", "steps": [{"name": "patch"}, {"name": "validate"}, {"name": "handoff"}]}}
    applied = asyncio.run(agent._attempt_autonomous_self_heal(ci_context={}, diagnosis="x", remediation=remediation))
    assert applied["status"] == "applied"
    assert remediation["remediation_loop"]["status"] == "applied"


async def _async_value(value):
    return value


def test_build_trigger_prompt_fallback_to_trigger_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    trigger = ExternalTrigger(trigger_id="tid", source="cron", event_name="run", payload={}, meta={})
    prompt = sidar_agent.SidarAgent._build_trigger_prompt(trigger, {"kind": "other"}, None)
    assert "correlation_id=tid" in prompt


def test_handle_external_trigger_empty_output_and_ci_self_heal_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    history = []
    agent.initialize = _dummy_async
    agent.mark_activity = lambda *_a, **_k: None
    agent._ensure_autonomy_runtime_state = lambda: None
    agent._build_trigger_correlation = lambda *_a, **_k: {}
    agent._build_trigger_prompt = lambda *_a, **_k: "PROMPT"
    agent._append_autonomy_history = lambda record: _async_value(history.append(record))
    agent._memory_add = _dummy_async
    agent._try_multi_agent = lambda *_a, **_k: _async_value(" ")
    empty = asyncio.run(agent.handle_external_trigger({"trigger_id": "t1", "source": "s", "event_name": "e", "payload": {}, "meta": {}}))
    assert empty["status"] == "empty"

    monkeypatch.setattr(sidar_agent, "build_ci_failure_context", lambda *_a, **_k: {"workflow_name": "ci", "workflow": "ci"})
    monkeypatch.setattr(sidar_agent, "build_ci_remediation_payload", lambda *_a, **_k: {"remediation_loop": {"status": "planned"}})
    agent._try_multi_agent = lambda *_a, **_k: _async_value("diag")

    async def _self_heal(**_kwargs):
        raise RuntimeError("boom")

    agent._attempt_autonomous_self_heal = _self_heal
    ci = asyncio.run(agent.handle_external_trigger({"trigger_id": "t2", "source": "s", "event_name": "e", "payload": {}, "meta": {}}))
    assert ci["status"] == "success"
    assert ci["remediation"]["self_heal_execution"]["status"] == "failed"


def test_run_nightly_memory_maintenance_skipped_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.initialize = _dummy_async
    agent.seconds_since_last_activity = lambda: 5.0
    agent.cfg = types.SimpleNamespace(ENABLE_NIGHTLY_MEMORY_PRUNING=True, NIGHTLY_MEMORY_IDLE_SECONDS=100)
    agent._nightly_maintenance_lock = None
    not_idle = asyncio.run(agent.run_nightly_memory_maintenance())
    assert not_idle["reason"] == "not_idle"

    lock = asyncio.Lock()
    asyncio.run(lock.acquire())
    agent._nightly_maintenance_lock = lock
    running = asyncio.run(agent.run_nightly_memory_maintenance(force=True))
    assert running["reason"] == "already_running"
    lock.release()


def test_get_autonomy_activity_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent._ensure_autonomy_runtime_state = lambda: None
    agent._autonomy_history = [
        {"trigger_id": "a", "status": "success", "source": "web"},
        {"trigger_id": "b", "status": "failed", "source": "web"},
        {"trigger_id": "c", "status": "success", "source": "cron"},
    ]
    activity = agent.get_autonomy_activity(2)
    assert activity["total"] == 3
    assert activity["returned"] == 2
    assert activity["latest_trigger_id"] == "c"


def test_try_multi_agent_and_archive_context_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)

    class _Sup:
        async def run_task(self, _u):
            return ""

    agent._supervisor = _Sup()
    warning = asyncio.run(agent._try_multi_agent("x"))
    assert "geçerli bir çıktı" in warning

    class _Collection:
        def query(self, **_k):
            raise RuntimeError("bad")

    agent.docs = types.SimpleNamespace(collection=_Collection())
    assert agent._get_memory_archive_context_sync("x", 1, 0.1, 1000) == ""


def test_build_context_and_instruction_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = types.SimpleNamespace(
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
    class _Memory:
        def get_last_file(self):
            return ""

    class _Todo:
        def __len__(self):
            return 0

    agent.memory = _Memory()
    agent.todo = _Todo()
    agent._load_instruction_files = lambda: "abcdefghi"
    text = asyncio.run(agent._build_context())
    assert "AI Sağlayıcı : OLLAMA" in text
    assert "abcdefghi" in text


def test_tool_subtask_and_github_smart_pr_and_summary_and_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    sidar_agent = _load_sidar_agent_module(monkeypatch)
    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = types.SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    class _LLM:
        def __init__(self):
            self.i = 0

        async def chat(self, **_k):
            self.i += 1
            if self.i == 1:
                return '{"thought":"t","tool":"final_answer","argument":"done"}'
            return "x"

    agent.llm = _LLM()
    class _ToolCall:
        @staticmethod
        def model_validate_json(_raw):
            return types.SimpleNamespace(tool="final_answer", argument="done")

        @staticmethod
        def model_validate(_obj):
            return types.SimpleNamespace(tool="final_answer", argument="done")

    monkeypatch.setattr(sidar_agent, "ToolCall", _ToolCall)
    done = asyncio.run(agent._tool_subtask("job"))
    assert "Tamamlandı" in done
    assert "belirtilmedi" in asyncio.run(agent._tool_subtask(""))

    agent.github = types.SimpleNamespace(is_available=lambda: False)
    assert "token" in asyncio.run(agent._tool_github_smart_pr("x"))

    class _Code:
        def run_shell(self, command):
            if "branch" in command:
                return True, "feat/x"
            if "status" in command:
                return True, "M a.py"
            if "log" in command:
                return True, "c1"
            if "diff --no-color" in command:
                return True, "diff"
            return True, ""

    class _Git:
        default_branch = "main"

        def is_available(self):
            return True

        def create_pull_request(self, *_a):
            return True, "url"

    agent.code = _Code()
    agent.github = _Git()
    assert "oluşturuldu" in asyncio.run(agent._tool_github_smart_pr("title|||main|||note"))

    agent.memory = types.SimpleNamespace(
        get_history=lambda: _async_value([{"role": "user", "content": "a", "timestamp": 1}, {"role": "assistant", "content": "b", "timestamp": 1}, {"role": "user", "content": "c", "timestamp": 1}, {"role": "assistant", "content": "d", "timestamp": 1}]),
        apply_summary=_dummy_async,
        clear=_dummy_async,
    )
    agent.docs = types.SimpleNamespace(add_document=_dummy_async)
    agent.llm = types.SimpleNamespace(chat=lambda **_k: _async_value("sum"))
    asyncio.run(agent._summarize_memory())
    assert "temizlendi" in asyncio.run(agent.clear_memory())
