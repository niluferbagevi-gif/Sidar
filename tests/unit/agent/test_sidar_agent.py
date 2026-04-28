import asyncio
import builtins
import importlib
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, call, create_autospec, patch

import pytest

pytestmark = pytest.mark.asyncio

import agent.sidar_agent as sidar_agent
from agent.core.contracts import ExternalTrigger
from core.llm_client import BaseLLMClient
from managers.code_manager import CodeManager
from managers.github_manager import GitHubManager
from managers.package_info import PackageInfoManager
from managers.system_health import SystemHealthManager
from managers.web_search import WebSearchManager
from tests.helpers import collect_async_chunks as _collect_stream


def _override_cfg(agent, **overrides):
    for key, value in overrides.items():
        setattr(agent.cfg, key, value)


async def test_trace_can_be_set_to_none_for_optional_telemetry(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sidar_agent, "trace", None, raising=False)
    assert sidar_agent.trace is None


async def test_optional_opentelemetry_import_failure_sets_trace_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def _failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "opentelemetry":
            raise RuntimeError("opentelemetry unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    reloaded = importlib.reload(sidar_agent)
    assert reloaded.trace is None
    importlib.reload(reloaded)


async def test_default_derive_correlation_id_returns_first_non_empty_value() -> None:
    result = sidar_agent._default_derive_correlation_id("", "   ", None, "corr-123", "corr-456")
    assert result == "corr-123"
    assert sidar_agent._default_derive_correlation_id("", "   ", None) == ""


async def test_fallback_federation_task_envelope_builds_prompt_and_correlation(
    sidar_agent_factory,
) -> None:
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


async def test_fallback_action_feedback_uses_related_ids_for_correlation(
    sidar_agent_factory,
) -> None:
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


async def test_init_accepts_config_alias_and_prefers_config() -> None:
    cfg = Mock(name="cfg")
    cfg_alias = Mock(name="config_alias")
    deps = sidar_agent.AgentDependencies(
        security=Mock(name="security"),
        code=Mock(name="code"),
        health=Mock(name="health"),
        github=Mock(name="github"),
        memory=Mock(name="memory"),
        llm=Mock(name="llm"),
        web=Mock(name="web"),
        pkg=Mock(name="pkg"),
        docs=Mock(name="docs"),
        todo=Mock(name="todo"),
    )

    agent = sidar_agent.SidarAgent(cfg=cfg, config=cfg_alias, deps=deps)

    assert agent.cfg is cfg_alias


async def test_init_rejects_unexpected_kwargs() -> None:
    with pytest.raises(TypeError, match="Unexpected keyword argument"):
        sidar_agent.SidarAgent(invalid_param="123", another_param="456")


async def test_init_uses_injected_dependencies_without_recreating() -> None:
    cfg = sidar_agent.Config()
    deps = sidar_agent.AgentDependencies(
        security=Mock(name="security"),
        code=Mock(name="code"),
        health=Mock(name="health"),
        github=Mock(name="github"),
        memory=Mock(name="memory"),
        llm=Mock(name="llm"),
        web=Mock(name="web"),
        pkg=Mock(name="pkg"),
        docs=Mock(name="docs"),
        todo=Mock(name="todo"),
    )

    agent = sidar_agent.SidarAgent(cfg=cfg, deps=deps)

    assert agent._deps is deps
    assert agent.llm is deps.llm
    assert agent.memory is deps.memory
    assert agent.docs is deps.docs


@pytest.mark.parametrize(
    ("raw", "expected_tool", "expected_argument"),
    [
        ('{"tool":"docs_search","argument":"lock"}', "docs_search", "lock"),
        ('```json\n{"argument":"done"}\n```', "final_answer", "done"),
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


async def test_build_trigger_prompt_prioritizes_ci_context(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    trigger = ExternalTrigger(
        trigger_id="t-1", source="github", event_name="workflow_run", payload={}
    )
    monkeypatch.setattr(
        sidar_agent, "build_ci_failure_prompt", lambda ctx: f"CI::{ctx['workflow']}"
    )
    prompt = sidar_agent.SidarAgent._build_trigger_prompt(
        trigger, {"kind": "federation_task"}, {"workflow": "backend-ci"}
    )
    assert prompt == "CI::backend-ci"


async def test_build_trigger_prompt_formats_federation_and_action_feedback(
    sidar_agent_factory,
) -> None:
    federation_trigger = ExternalTrigger(
        trigger_id="t-2", source="crm", event_name="sync", payload={}
    )
    federation_prompt = sidar_agent.SidarAgent._build_trigger_prompt(
        federation_trigger,
        {"kind": "federation_task", "task_id": "task-42", "goal": "Push account update"},
        None,
    )
    action_trigger = ExternalTrigger(
        trigger_id="t-3", source="ops", event_name="action_feedback", payload={}
    )
    action_prompt = sidar_agent.SidarAgent._build_trigger_prompt(
        action_trigger,
        {
            "kind": "action_feedback",
            "action_name": "deploy",
            "status": "completed",
            "summary": "Release done",
        },
        None,
    )
    assert "[FEDERATION TASK]" in federation_prompt
    assert "goal=Push account update" in federation_prompt
    assert "[ACTION FEEDBACK]" in action_prompt
    assert "status=completed" in action_prompt


async def test_build_trigger_correlation_matches_history_without_duplicate_ids(
    sidar_agent_factory,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    now = sidar_agent.time.time()
    agent._autonomy_history = [
        {
            "trigger_id": "trig-1",
            "status": "success",
            "source": "github",
            "payload": {"task_id": "task-100"},
            "correlation": {"correlation_id": "corr-100"},
            "meta": {},
            "timestamp": now - 120,
        },
        {
            "trigger_id": "trig-1",
            "status": "success",
            "source": "github",
            "payload": {"task_id": "task-100"},
            "correlation": {"correlation_id": "corr-100"},
            "meta": {},
            "timestamp": now - 60,
        },
        {
            "trigger_id": "trig-2",
            "status": "failed",
            "source": "jira",
            "payload": {"related_task_id": "task-100"},
            "correlation": {"correlation_id": "corr-100"},
            "meta": {},
            "timestamp": now - 10,
        },
    ]
    agent._autonomy_lock = None

    trigger = ExternalTrigger(
        trigger_id="trig-new",
        source="scheduler",
        event_name="nightly",
        payload={},
        meta={"correlation_id": "corr-100"},
    )
    correlation = agent._build_trigger_correlation(trigger, {"task_id": "task-100"})

    assert correlation["correlation_id"] == "corr-100"
    assert correlation["matched_records"] == 2
    assert correlation["related_trigger_ids"] == ["trig-2", "trig-1"]
    assert correlation["related_sources"] == ["jira", "github"]
    assert correlation["latest_related_status"] == "failed"


async def test_execute_self_heal_plan_reverts_on_patch_error(
    sidar_agent_factory,
    mock_config,
    tmp_path: Path,
) -> None:
    cfg = mock_config(BASE_DIR=str(tmp_path))
    agent = sidar_agent_factory(cfg=cfg)
    restored = {}
    code_mock = create_autospec(CodeManager, instance=True, spec_set=True)
    code_mock.read_file.side_effect = lambda path, *args, **kwargs: (True, f"old:{path}")
    code_mock.patch_file.side_effect = lambda path, target, replacement: (False, "boom")
    code_mock.write_file.side_effect = lambda path, content, *args, **kwargs: (
        restored.__setitem__(path, content) or (True, "ok")
    )
    code_mock.run_shell_in_sandbox.side_effect = lambda command, base_dir: (True, "ok")
    agent.code = code_mock
    plan = {
        "operations": [{"path": "a.py", "target": "A", "replacement": "B"}],
        "validation_commands": ["pytest -q"],
    }
    result = await agent._execute_self_heal_plan(remediation_loop={}, plan=plan)
    assert result["status"] == "reverted"
    assert result["reverted"] is True
    assert restored == {"a.py": "old:a.py"}


async def test_restore_self_heal_backups(sidar_agent_factory) -> None:
    """Yedek dosyaların thread üzerinden asenkron biçimde geri yüklendiğini doğrular."""
    agent = sidar_agent_factory()
    write_mock = Mock(return_value=(True, "ok"))
    agent.code = types.SimpleNamespace(write_file=write_mock)

    backups = {
        "src/main.py": "print('old main')",
        "src/utils.py": "print('old utils')",
    }

    await agent._restore_self_heal_backups(backups)

    assert write_mock.call_count == 2
    write_mock.assert_any_call("src/main.py", "print('old main')", False)
    write_mock.assert_any_call("src/utils.py", "print('old utils')", False)


async def test_get_memory_archive_context_sync_filters_by_source_and_score(
    sidar_agent_factory,
) -> None:
    agent = sidar_agent_factory()
    collection = Mock()
    collection.query.return_value = {
        "documents": [["doc-1\nline", "doc-2", "doc-3"]],
        "metadatas": [
            [
                {"source": "memory_archive", "title": "T1"},
                {"source": "other", "title": "T2"},
                {"source": "memory_archive", "title": "T3"},
            ]
        ],
        "distances": [[0.1, 0.1, 0.9]],
    }
    agent.docs = types.SimpleNamespace(collection=collection)
    text = agent._get_memory_archive_context_sync("q", top_k=3, min_score=0.2, max_chars=500)
    assert "T1" in text
    assert "T2" not in text
    assert "T3" not in text


async def test_tool_docs_search_handles_empty_and_async_result(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    empty = await agent._tool_docs_search("")
    assert "sorgusu belirtilmedi" in empty

    async def _search(query, *_args):
        return True, f"found:{query}"

    agent.docs = types.SimpleNamespace(search=lambda *a, **k: _search(*a, **k))
    found = await agent._tool_docs_search("abc|strict")
    assert found == "found:abc"


async def test_tool_docs_search_timeout_invalid_and_empty_payload_edges(
    sidar_agent_factory,
) -> None:
    agent = sidar_agent_factory()

    agent.docs = types.SimpleNamespace(
        search=lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("slow"))
    )
    timeout_msg = await agent._tool_docs_search("query")
    assert any(keyword in timeout_msg.lower() for keyword in ("zaman", "aşım", "timeout"))

    agent.docs = types.SimpleNamespace(search=lambda *_a, **_k: {"invalid": "payload"})
    invalid_msg = await agent._tool_docs_search("query")
    assert "geçersiz yanıt" in invalid_msg


async def test_autonomy_state_and_self_heal_blocked_when_dependencies_missing(
    sidar_agent_factory,
) -> None:
    agent = sidar_agent_factory()
    agent.__dict__.pop("_autonomy_history", None)
    agent.__dict__.pop("_autonomy_lock", None)
    agent._ensure_autonomy_runtime_state()
    assert agent._autonomy_history == []
    assert agent._autonomy_lock is None

    agent.__dict__.pop("code", None)
    remediation = {"remediation_loop": {"status": "planned"}}
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    blocked = await agent._attempt_autonomous_self_heal(
        ci_context={}, diagnosis="x", remediation=remediation
    )
    assert blocked["status"] == "blocked"


async def test_memory_archive_context_empty_snippet_and_char_limit(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    collection = Mock()
    collection.query.return_value = {
        "documents": [["", "second snippet"]],
        "metadatas": [
            [
                {"source": "memory_archive", "title": "T1"},
                {"source": "memory_archive", "title": "T2"},
            ]
        ],
        "distances": [[0.1, 0.1]],
    }
    agent.docs = types.SimpleNamespace(collection=collection)
    text = agent._get_memory_archive_context_sync("q", top_k=5, min_score=0.1, max_chars=10)
    assert text == ""


async def test_build_context_todo_len_and_instruction_trim(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(
        agent,
        AI_PROVIDER="ollama",
        LOCAL_INSTRUCTION_MAX_CHARS=20,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=120,
    )
    agent.code = types.SimpleNamespace(
        status=lambda: "ok", get_metrics=lambda: {"files_read": 1, "files_written": 1}
    )
    health = create_autospec(SystemHealthManager, instance=True, spec_set=True)
    health.full_report.return_value = "ok"
    agent.health = health
    github = create_autospec(GitHubManager, instance=True, spec_set=True)
    github.is_available.return_value = False
    github.status.return_value = "no"
    agent.github = github
    web = create_autospec(WebSearchManager, instance=True, spec_set=True)
    web.status.return_value = "ok"
    web.is_available.return_value = True
    agent.web = web
    pkg = create_autospec(PackageInfoManager, instance=True, spec_set=True)
    pkg.status.return_value = "ok"
    agent.pkg = pkg
    agent.docs = types.SimpleNamespace(status=lambda: "ok")
    agent.memory = types.SimpleNamespace(get_last_file=lambda: "")

    class _Todo:
        def __len__(self):
            raise TypeError("len not direct")

        def list_tasks(self):
            return "task1"

    agent.todo = _Todo()
    assert agent.todo.list_tasks() == "task1"
    monkeypatch.setattr(agent, "_load_instruction_files", lambda: "A" * 200)
    context = await agent._build_context()
    assert "[Proje Ayarları" in context


async def test_load_instruction_files_edge_paths(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, BASE_DIR=str(tmp_path))
    good = tmp_path / "SIDAR.md"
    good.write_text("hello", encoding="utf-8")
    empty = tmp_path / "CLAUDE.md"
    empty.write_text("", encoding="utf-8")

    class _BadPath:
        def is_file(self):
            raise RuntimeError("bad")

    monkeypatch.setattr(Path, "rglob", lambda self, name: [str(good), empty, _BadPath()])
    text = agent._load_instruction_files()
    assert "hello" in text


async def test_tool_docs_search_and_execute_tool_error_branches(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent.docs = types.SimpleNamespace(
        search=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("fail"))
    )
    err = await agent._tool_docs_search("x")
    assert "başarısız" in err

    with pytest.raises(ValueError):
        await agent._execute_tool("", "x")
    with pytest.raises(ValueError):
        await agent._execute_tool("unknown", "x")

    agent._tool_sync = "not-callable"
    with pytest.raises(TypeError):
        await agent._execute_tool("sync", "x")

    agent._tool_sync = lambda arg: f"sync:{arg}"
    assert await agent._execute_tool("sync", "x") == "sync:x"

    agent.docs = types.SimpleNamespace(search=lambda *_a, **_k: (True, "   "))
    empty_msg = await agent._tool_docs_search("query")
    assert "boş yanıt" in empty_msg


async def test_execute_tool_routes_to_handler_and_handles_unknown_tool(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent.docs = types.SimpleNamespace(search=lambda *_a, **_k: (True, "found"))

    assert await agent._execute_tool("docs_search", "hello") == "found"

    with pytest.raises(ValueError, match="Bilinmeyen araç"):
        await agent._execute_tool("not_real_tool", "arg")


async def test_load_instruction_files_reads_and_caches(sidar_agent_factory, tmp_path: Path) -> None:
    root = tmp_path
    (root / "SIDAR.md").write_text("root rules", encoding="utf-8")
    nested = root / "sub"
    nested.mkdir()
    (nested / "CLAUDE.md").write_text("child rules", encoding="utf-8")

    agent = sidar_agent_factory()
    _override_cfg(agent, BASE_DIR=str(root))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = asyncio.Lock()

    first = agent._load_instruction_files()
    second = agent._load_instruction_files()
    assert "root rules" in first
    assert "child rules" in first
    assert second == first


async def test_set_access_level_changed_and_unchanged(sidar_agent_factory) -> None:
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


async def test_status_renders_all_sections(
    sidar_agent_factory,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, AI_PROVIDER="x", CODING_MODEL="m", ACCESS_LEVEL="safe")
    memory = Mock()
    memory.__len__ = Mock(return_value=3)
    agent.memory = memory
    agent._autonomy_history = [{"id": 1, "timestamp": sidar_agent.time.time()}]
    agent._ensure_autonomy_runtime_state = lambda: None
    github = create_autospec(GitHubManager, instance=True, spec_set=True)
    github.status.return_value = "github"
    agent.github = github
    web = create_autospec(WebSearchManager, instance=True, spec_set=True)
    web.status.return_value = "web"
    agent.web = web
    pkg = create_autospec(PackageInfoManager, instance=True, spec_set=True)
    pkg.status.return_value = "pkg"
    agent.pkg = pkg
    agent.docs = types.SimpleNamespace(status=lambda: "docs")
    health = create_autospec(SystemHealthManager, instance=True, spec_set=True)
    health.full_report.return_value = "health"
    agent.health = health
    text = agent.status()
    assert "SidarAgent" in text
    assert (
        "github" in text and "web" in text and "pkg" in text and "docs" in text and "health" in text
    )


async def test_initialize_uses_active_system_prompt(sidar_agent_factory) -> None:
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


async def test_respond_handles_empty_and_success(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent._lock = None
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None

    supervisor = AsyncMock()
    supervisor.run_task.side_effect = lambda prompt: f"ok:{prompt}"
    agent._supervisor = supervisor
    memory = AsyncMock()
    agent.memory = memory

    empty = list(await _collect_stream(agent.respond("   ")))
    assert "Boş girdi" in empty[0]

    ok = list(await _collect_stream(agent.respond("hello")))
    assert ok == ["ok:hello"]
    memory.add.assert_has_awaits([call("user", "hello"), call("assistant", "ok:hello")])


async def test_concurrent_respond(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent._lock = None
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None

    active_multi = 0
    max_active_multi = 0
    memory_events: list[tuple[str, str]] = []
    step1_event = asyncio.Event()
    step2_event = asyncio.Event()

    async def _run_task(prompt):
        nonlocal active_multi, max_active_multi
        active_multi += 1
        max_active_multi = max(max_active_multi, active_multi)

        if prompt == "alpha":
            step1_event.set()
            await step2_event.wait()

        active_multi -= 1
        return f"ok:{prompt}"

    async def _memory_add(role, content):
        memory_events.append((role, content))

    supervisor = AsyncMock()
    supervisor.run_task.side_effect = _run_task
    agent._supervisor = supervisor
    agent.memory = AsyncMock()
    agent.memory.add.side_effect = _memory_add

    async def _ask(prompt: str) -> list[str]:
        return list(await _collect_stream(agent.respond(prompt)))

    task_alpha = asyncio.create_task(_ask("alpha"))
    await step1_event.wait()
    task_beta = asyncio.create_task(_ask("beta"))
    step2_event.set()

    first, second = await asyncio.wait_for(asyncio.gather(task_alpha, task_beta), timeout=5.0)

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


async def test_respond_memory_failure_graceful(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = sidar_agent_factory()
    agent._lock = None
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None
    error_msg = "Memory DB Down"
    agent._memory_add = AsyncMock(side_effect=RuntimeError(error_msg))
    agent._try_multi_agent = AsyncMock(return_value="Kritik Yanıt")
    warning_mock = Mock()
    monkeypatch.setattr(sidar_agent.logger, "warning", warning_mock)
    responses = list(await _collect_stream(agent.respond("test input")))

    assert "Kritik Yanıt" in responses
    agent._memory_add.assert_awaited_once_with("user", "test input")
    warning_mock.assert_called_once()
    assert "Memory add failed during respond flow" in warning_mock.call_args.args[0]
    assert error_msg in str(warning_mock.call_args.args[1])


async def test_append_autonomy_history_caps_to_50(
    sidar_agent_factory,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    base = sidar_agent.time.time()
    agent._autonomy_history = [{"i": i, "timestamp": base - (60 - i)} for i in range(60)]
    agent._autonomy_lock = None
    await agent._append_autonomy_history({"i": 999})
    assert len(agent._autonomy_history) == 50
    assert agent._autonomy_history[-1]["i"] == 999


async def test_collect_and_build_self_heal_plan(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_coverage_code_manager,
) -> None:
    agent = sidar_agent_factory()
    reads = {}

    def _read_file(path: str, _safe: bool) -> tuple[bool, str]:
        reads[path] = True
        return (not path.startswith("x"), f"C:{path}")

    fake_coverage_code_manager.read_file = Mock(side_effect=_read_file)

    async def _chat_side_effect(**kwargs):
        return {"raw": kwargs["messages"][0]["content"]}

    llm = AsyncMock()
    llm.chat.side_effect = _chat_side_effect

    agent.code = fake_coverage_code_manager
    agent.llm = llm
    _override_cfg(agent, CODING_MODEL="m", SELF_HEAL_MAX_PATCHES=2)
    monkeypatch.setattr(sidar_agent, "build_self_heal_patch_prompt", lambda *_a, **_k: "P")
    monkeypatch.setattr(
        sidar_agent,
        "normalize_self_heal_plan",
        lambda raw_plan, **kwargs: {
            "operations": [{"path": "a.py"}],
            "from": raw_plan,
            "kwargs": kwargs,
        },
    )

    empty = await agent._build_self_heal_plan(
        ci_context={}, diagnosis="d", remediation_loop={"scope_paths": []}
    )
    assert empty["operations"] == []

    plan = await agent._build_self_heal_plan(
        ci_context={},
        diagnosis="d",
        remediation_loop={"scope_paths": ["a.py", "x.py"], "validation_commands": ["pytest"]},
    )
    assert "a.py" in reads and "x.py" in reads
    assert plan["kwargs"]["scope_paths"] == ["a.py", "x.py"]


async def test_build_self_heal_plan_falls_back_to_batch_scope(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_coverage_code_manager,
) -> None:
    agent = sidar_agent_factory()
    agent.code = fake_coverage_code_manager
    fake_coverage_code_manager.read_file = Mock(return_value=(True, "C"))
    _override_cfg(agent, CODING_MODEL="m", SELF_HEAL_AUTONOMOUS_BATCH_SIZE=2)

    llm = AsyncMock()
    llm.chat = AsyncMock(side_effect=[{"raw": "first"}, {"raw": "second"}])
    agent.llm = llm

    seen_scopes: list[list[str]] = []

    def _normalize(raw_plan, **kwargs):
        del raw_plan
        scope = list(kwargs.get("scope_paths") or [])
        seen_scopes.append(scope)
        if len(seen_scopes) == 1:
            return {"summary": "empty", "operations": [], "validation_commands": ["pytest -q"]}
        return {
            "summary": "ok",
            "operations": [{"path": scope[0]}],
            "validation_commands": ["pytest -q"],
        }

    monkeypatch.setattr(sidar_agent, "build_self_heal_patch_prompt", lambda *_a, **_k: "P")
    monkeypatch.setattr(sidar_agent, "normalize_self_heal_plan", _normalize)

    plan = await agent._build_self_heal_plan(
        ci_context={},
        diagnosis="d",
        remediation_loop={"scope_paths": ["a.py", "b.py", "c.py"], "validation_commands": ["pytest"]},
    )

    assert seen_scopes == [["a.py", "b.py", "c.py"], ["a.py", "b.py"]]
    assert plan["operations"][0]["path"] == "a.py"
    assert "batch plan" in plan["summary"]


async def test_build_self_heal_plan_skips_full_scope_when_scope_large(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_coverage_code_manager,
) -> None:
    agent = sidar_agent_factory()
    agent.code = fake_coverage_code_manager
    fake_coverage_code_manager.read_file = Mock(return_value=(True, "C"))
    _override_cfg(agent, CODING_MODEL="m", SELF_HEAL_AUTONOMOUS_BATCH_SIZE=2)
    agent.llm = AsyncMock()
    agent.llm.chat = AsyncMock(return_value={"raw": "first"})

    seen_scopes: list[list[str]] = []

    def _normalize(raw_plan: dict[str, str], **kwargs: Any) -> dict[str, Any]:
        del raw_plan
        scope = list(kwargs.get("scope_paths") or [])
        seen_scopes.append(scope)
        return {
            "summary": "ok",
            "operations": [{"path": scope[0]}],
            "validation_commands": ["pytest -q"],
        }

    monkeypatch.setattr(sidar_agent, "build_self_heal_patch_prompt", lambda *_a, **_k: "P")
    monkeypatch.setattr(sidar_agent, "normalize_self_heal_plan", _normalize)

    plan = await agent._build_self_heal_plan(
        ci_context={},
        diagnosis="d",
        remediation_loop={
            "scope_paths": ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"],
            "validation_commands": ["pytest"],
        },
    )

    assert seen_scopes == [["a.py", "b.py"]]
    assert plan["operations"][0]["path"] == "a.py"


async def test_resolve_self_heal_scope_batches_prefers_autonomous_batches(
    sidar_agent_factory,
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, SELF_HEAL_AUTONOMOUS_BATCH_SIZE=2)

    batches = agent._resolve_self_heal_scope_batches(
        ["a.py", "b.py", "c.py", "d.py"],
        {
            "autonomous_batches": [
                {"scope_paths": ["c.py", "d.py"]},
                {"scope_paths": ["a.py", "b.py"]},
                {"scope_paths": ["a.py", "b.py"]},
                {"scope_paths": ["x.py"]},
            ]
        },
    )
    assert batches == [["c.py", "d.py"], ["a.py", "b.py"]]


async def test_build_self_heal_plan_uses_autonomous_batch_order(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_coverage_code_manager,
) -> None:
    agent = sidar_agent_factory()
    agent.code = fake_coverage_code_manager
    fake_coverage_code_manager.read_file = Mock(return_value=(True, "C"))
    _override_cfg(agent, CODING_MODEL="m", SELF_HEAL_AUTONOMOUS_BATCH_SIZE=2)
    agent.llm = AsyncMock()
    agent.llm.chat = AsyncMock(return_value={"raw": "first"})

    seen_scopes: list[list[str]] = []

    def _normalize(raw_plan: dict[str, str], **kwargs: Any) -> dict[str, Any]:
        del raw_plan
        scope = list(kwargs.get("scope_paths") or [])
        seen_scopes.append(scope)
        if len(seen_scopes) == 1:
            return {"summary": "empty", "operations": [], "validation_commands": ["pytest -q"]}
        return {
            "summary": "ok",
            "operations": [{"path": scope[0]}],
            "validation_commands": ["pytest -q"],
        }

    monkeypatch.setattr(sidar_agent, "build_self_heal_patch_prompt", lambda *_a, **_k: "P")
    monkeypatch.setattr(sidar_agent, "normalize_self_heal_plan", _normalize)

    plan = await agent._build_self_heal_plan(
        ci_context={},
        diagnosis="d",
        remediation_loop={
            "scope_paths": ["a.py", "b.py", "c.py"],
            "autonomous_batches": [{"scope_paths": ["c.py"]}, {"scope_paths": ["a.py", "b.py"]}],
            "validation_commands": ["pytest"],
        },
    )
    assert seen_scopes == [["c.py"]]
    assert plan["operations"][0]["path"] == "c.py"


async def test_build_self_heal_plan_retries_until_operation(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_coverage_code_manager,
) -> None:
    agent = sidar_agent_factory()
    agent.code = fake_coverage_code_manager
    fake_coverage_code_manager.read_file = Mock(return_value=(True, "C"))
    _override_cfg(agent, CODING_MODEL="m", SELF_HEAL_PLAN_MAX_RETRIES=3)

    llm = AsyncMock()
    llm.chat = AsyncMock(side_effect=[{"raw": "1"}, {"raw": "2"}])
    agent.llm = llm

    normalize_calls = {"n": 0}

    def _normalize(_raw_plan: dict[str, str], **_kwargs: Any) -> dict[str, Any]:
        normalize_calls["n"] += 1
        if normalize_calls["n"] == 1:
            return {"summary": "empty", "operations": [], "validation_commands": ["pytest -q"]}
        return {
            "summary": "ok",
            "operations": [{"path": "a.py"}],
            "validation_commands": ["pytest -q"],
        }

    monkeypatch.setattr(sidar_agent, "build_self_heal_patch_prompt", lambda *_a, **_k: "P")
    monkeypatch.setattr(sidar_agent, "normalize_self_heal_plan", _normalize)

    plan = await agent._build_self_heal_plan(
        ci_context={},
        diagnosis="d",
        remediation_loop={"scope_paths": ["a.py"], "validation_commands": ["pytest"]},
    )

    assert llm.chat.await_count == 2
    assert plan["operations"][0]["path"] == "a.py"
    assert plan["plan_attempt"] == 2
    assert plan["plan_max_retries"] == 3


async def test_attempt_autonomous_self_heal_blocked_and_applied(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    remediation = {"remediation_loop": {"status": "planned"}}
    blocked = await agent._attempt_autonomous_self_heal(
        ci_context={}, diagnosis="x", remediation=remediation
    )
    assert blocked["status"] == "blocked"

    agent.code = create_autospec(CodeManager, instance=True, spec_set=True)
    agent.llm = create_autospec(BaseLLMClient, instance=True, spec_set=True)
    agent._build_self_heal_plan = AsyncMock(return_value={"operations": [{"path": "a.py"}]})
    agent._execute_self_heal_plan = AsyncMock(
        return_value={"status": "applied", "summary": "ok", "operations_applied": ["a.py"]}
    )
    remediation = {
        "remediation_loop": {
            "status": "planned",
            "steps": [{"name": "patch"}, {"name": "validate"}, {"name": "handoff"}],
        }
    }
    applied = await agent._attempt_autonomous_self_heal(
        ci_context={}, diagnosis="x", remediation=remediation
    )
    assert applied["status"] == "applied"
    assert remediation["remediation_loop"]["status"] == "applied"


async def test_attempt_autonomous_self_heal_marks_human_intervention_after_retry_exhaustion(
    sidar_agent_factory,
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    agent.code = create_autospec(CodeManager, instance=True, spec_set=True)
    agent.llm = create_autospec(BaseLLMClient, instance=True, spec_set=True)
    agent._build_self_heal_plan = AsyncMock(
        return_value={"operations": [], "plan_attempt": 3, "plan_max_retries": 3}
    )
    remediation = {
        "remediation_loop": {
            "status": "planned",
            "steps": [{"name": "patch"}, {"name": "handoff"}],
        }
    }

    result = await agent._attempt_autonomous_self_heal(
        ci_context={}, diagnosis="x", remediation=remediation
    )

    assert result["status"] == "blocked"
    assert remediation["remediation_loop"]["needs_human_intervention"] is True


async def test_attempt_autonomous_self_heal_disabled_skipped_and_awaiting_hitl(
    sidar_agent_factory,
) -> None:
    agent = sidar_agent_factory()

    remediation = {"remediation_loop": {"status": "planned"}}
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=False)
    disabled = await agent._attempt_autonomous_self_heal(
        ci_context={}, diagnosis="x", remediation=remediation
    )
    assert disabled["status"] == "disabled"

    remediation = {"remediation_loop": {"status": "failed"}}
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    skipped = await agent._attempt_autonomous_self_heal(
        ci_context={}, diagnosis="x", remediation=remediation
    )
    assert skipped["status"] == "skipped"

    remediation = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": True,
            "steps": [{"name": "handoff", "status": "planned", "detail": ""}],
        }
    }
    awaiting = await agent._attempt_autonomous_self_heal(
        ci_context={}, diagnosis="x", remediation=remediation
    )
    assert awaiting["status"] == "awaiting_hitl"
    assert remediation["remediation_loop"]["steps"][0]["status"] == "awaiting_hitl"

    remediation = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": True,
            "steps": [{"name": "handoff", "status": "planned", "detail": ""}],
        }
    }
    rejected = await agent._attempt_autonomous_self_heal(
        ci_context={},
        diagnosis="x",
        remediation=remediation,
        human_approval=False,
    )
    assert rejected["status"] == "rejected"
    assert remediation["remediation_loop"]["steps"][0]["status"] == "rejected"


async def test_attempt_autonomous_self_heal_continues_after_human_approval(
    sidar_agent_factory,
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    agent.code = create_autospec(CodeManager, instance=True, spec_set=True)
    agent.llm = create_autospec(BaseLLMClient, instance=True, spec_set=True)
    agent._build_self_heal_plan = AsyncMock(return_value={"operations": [{"path": "a.py"}]})
    agent._execute_self_heal_plan = AsyncMock(
        return_value={"status": "applied", "summary": "ok", "operations_applied": ["a.py"]}
    )
    remediation = {
        "remediation_loop": {
            "status": "planned",
            "needs_human_approval": True,
            "steps": [{"name": "handoff", "status": "planned", "detail": ""}],
        }
    }
    applied = await agent._attempt_autonomous_self_heal(
        ci_context={},
        diagnosis="x",
        remediation=remediation,
        human_approval=True,
    )
    assert applied["status"] == "applied"
    assert remediation["remediation_loop"]["needs_human_approval"] is False


async def test_build_trigger_prompt_fallback_to_trigger_prompt(sidar_agent_factory) -> None:
    trigger = ExternalTrigger(
        trigger_id="tid", source="cron", event_name="run", payload={}, meta={}
    )
    prompt = sidar_agent.SidarAgent._build_trigger_prompt(trigger, {"kind": "other"}, None)
    assert "correlation_id=tid" in prompt


async def test_handle_external_trigger_empty_output_and_ci_self_heal_failure(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch
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
    agent._try_multi_agent = AsyncMock(return_value=" ")
    empty = await agent.handle_external_trigger(
        {"trigger_id": "t1", "source": "s", "event_name": "e", "payload": {}, "meta": {}}
    )
    assert empty["status"] == "empty"

    monkeypatch.setattr(
        sidar_agent,
        "build_ci_failure_context",
        lambda *_a, **_k: {"workflow_name": "ci", "workflow": "ci"},
    )
    monkeypatch.setattr(
        sidar_agent,
        "build_ci_remediation_payload",
        lambda *_a, **_k: {"remediation_loop": {"status": "planned"}},
    )
    agent._try_multi_agent = AsyncMock(return_value="diag")

    async def _self_heal(**_kwargs):
        raise RuntimeError("boom")

    agent._attempt_autonomous_self_heal = _self_heal
    ci = await agent.handle_external_trigger(
        {"trigger_id": "t2", "source": "s", "event_name": "e", "payload": {}, "meta": {}}
    )
    assert ci["status"] == "success"
    assert ci["remediation"]["self_heal_execution"]["status"] == "failed"
    assert "boom" in ci["remediation"]["self_heal_execution"].get(
        "detail", str(ci)
    ), "Asıl hata sebebi (boom) sonuç payload'una veya loglara yansımalıdır."


async def test_run_nightly_memory_maintenance_skipped_paths(
    sidar_agent_factory,
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


async def test_run_nightly_memory_maintenance_disabled_and_success_paths(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    agent.initialize = AsyncMock()

    _override_cfg(agent, ENABLE_NIGHTLY_MEMORY_PRUNING=False)
    disabled = await agent.run_nightly_memory_maintenance()
    assert disabled["status"] == "disabled"

    frozen_time.tick(delta=7200.0)
    agent._last_activity_ts = sidar_agent.time.time() - 7200.0
    _override_cfg(
        agent,
        ENABLE_NIGHTLY_MEMORY_PRUNING=True,
        NIGHTLY_MEMORY_IDLE_SECONDS=60,
        NIGHTLY_MEMORY_KEEP_RECENT_SESSIONS=1,
        NIGHTLY_MEMORY_SESSION_MIN_MESSAGES=2,
        NIGHTLY_MEMORY_RAG_KEEP_RECENT_DOCS=2,
    )
    agent._nightly_maintenance_lock = None
    agent._append_autonomy_history = AsyncMock()

    entity = AsyncMock()
    entity.initialize = AsyncMock()
    entity.purge_expired = AsyncMock(return_value=3)
    monkeypatch.setattr(sidar_agent, "get_entity_memory", lambda *_a, **_k: entity)

    agent.memory = types.SimpleNamespace(
        run_nightly_consolidation=AsyncMock(
            return_value={"session_ids": ["s1"], "sessions_compacted": 1}
        )
    )
    agent.docs = types.SimpleNamespace(
        consolidate_session_documents=lambda *_a, **_k: {"removed_docs": 2}
    )
    result = await agent.run_nightly_memory_maintenance(force=True, reason="test")
    assert result["status"] == "completed"
    assert result["entity_report"]["status"] == "completed"
    assert result["rag_reports"] == [{"removed_docs": 2}]


async def test_get_autonomy_activity_counts(
    sidar_agent_factory,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    agent._ensure_autonomy_runtime_state = lambda: None
    current_time = sidar_agent.time.time()
    agent._autonomy_history = [
        {
            "trigger_id": "old",
            "status": "success",
            "source": "cron",
            "timestamp": current_time - 10000,
        },
        {"trigger_id": "a", "status": "success", "source": "web", "timestamp": current_time - 3600},
        {"trigger_id": "b", "status": "failed", "source": "web", "timestamp": current_time - 1800},
    ]
    activity = agent.get_autonomy_activity(2)
    assert activity["total"] == 3
    assert activity["returned"] == 2
    assert activity["latest_trigger_id"] == "b"
    assert [item["trigger_id"] for item in activity["items"]] == ["a", "b"]


async def test_get_autonomy_activity_handles_limit_edge_cases(
    sidar_agent_factory,
    frozen_time,
) -> None:
    """limit alanında None/negatif/string değerlerin güvenli işlendiğini doğrular."""
    agent = sidar_agent_factory()
    agent._ensure_autonomy_runtime_state = lambda: None
    current_time = sidar_agent.time.time()
    agent._autonomy_history = [
        {"trigger_id": "1", "status": "success", "source": "cron", "timestamp": current_time},
        {"trigger_id": "2", "status": "failed", "source": "api", "timestamp": current_time},
        {"trigger_id": "3", "status": "success", "source": "web", "timestamp": current_time},
    ]

    res_none = agent.get_autonomy_activity(limit=None)
    assert res_none["returned"] == 3

    res_negative = agent.get_autonomy_activity(limit=-5)
    assert res_negative["returned"] == 1
    assert res_negative["items"][0]["trigger_id"] == "3"

    res_str = agent.get_autonomy_activity(limit="2")
    assert res_str["returned"] == 2


async def test_try_multi_agent_and_archive_context_error_paths(sidar_agent_factory) -> None:
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
        side_effect=(
            fake_llm_error if isinstance(error_side_effect, RuntimeError) else _raise_timeout
        )
    )

    result = await agent.handle_external_trigger(
        {
            "trigger_id": "t-llm-1",
            "source": "ci",
            "event_name": "workflow_run",
            "payload": {},
            "meta": {},
        }
    )
    assert result["status"] == "failed"
    assert needle in result["summary"]
    assert history and history[-1]["status"] == "failed"


async def test_build_context_and_instruction_absence(sidar_agent_factory) -> None:
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


async def test_tool_subtask_validation_fallback_success(
    sidar_agent_factory,
    fake_llm_response,
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")
    raw_response = '{"tool":"final_answer","argument":"kurtarıldı","thought":"düşünüyorum"}'

    async def _llm_response(*_args, **_kwargs) -> str:
        await fake_llm_response("subtask")
        return raw_response

    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=_llm_response))

    with patch.object(
        sidar_agent.ToolCall, "model_validate_json", autospec=True
    ) as validate_json_mock:
        validate_json_mock.side_effect = sidar_agent.ValidationError.from_exception_data(
            "error", line_errors=[]
        )
        output = await agent._tool_subtask("job")

    assert "Tamamlandı" in output
    assert "kurtarıldı" in output


async def test_tool_github_smart_pr_requires_token(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent.github = types.SimpleNamespace(is_available=lambda: False)
    assert await agent._tool_github_smart_pr("x") == sidar_agent.GITHUB_SMART_PR_NO_TOKEN_MESSAGE


async def test_tool_github_smart_pr_success_path(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    code = Mock()

    def _run_shell_success(command: str) -> tuple[bool, str]:
        if "branch" in command:
            return True, "feat/x"
        if "status" in command:
            return True, "M a.py"
        if "diff --no-color" in command:
            return True, "diff"
        if "log" in command:
            return True, "c1"
        return True, ""

    code.run_shell.side_effect = _run_shell_success
    git = Mock()
    git.default_branch = "main"
    git.is_available.return_value = True
    git.create_pull_request.return_value = (True, "url")

    agent.code = code
    agent.github = git
    assert (
        await agent._tool_github_smart_pr("title|||main|||note")
        == f"{sidar_agent.GITHUB_SMART_PR_CREATE_SUCCESS_PREFIX} url"
    )


async def test_summarize_memory_and_clear_memory_success(
    sidar_agent_factory, fake_llm_response
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, TEXT_MODEL="tm", CODING_MODEL="cm")
    agent.memory = types.SimpleNamespace(
        get_history=AsyncMock(
            return_value=[
                {"role": "user", "content": "a", "timestamp": 1},
                {"role": "assistant", "content": "b", "timestamp": 1},
                {"role": "user", "content": "c", "timestamp": 1},
                {"role": "assistant", "content": "d", "timestamp": 1},
            ]
        ),
        apply_summary=AsyncMock(),
        clear=AsyncMock(),
    )
    agent.docs = types.SimpleNamespace(add_document=AsyncMock())
    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=fake_llm_response))
    await agent._summarize_memory()
    assert "temizlendi" in await agent.clear_memory()


async def test_clear_memory_handles_exception(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent.memory = AsyncMock()
    agent.memory.clear.side_effect = RuntimeError("Dosya silinemedi")
    with pytest.raises(RuntimeError, match="Dosya silinemedi"):
        await agent.clear_memory()


async def test_update_remediation_step_no_match_keeps_steps(sidar_agent_factory) -> None:
    remediation_loop = {"steps": [{"name": "patch", "status": "planned", "detail": "x"}]}
    agent = sidar_agent_factory()
    agent._update_remediation_step(remediation_loop, "validate", status="completed", detail="ok")
    assert remediation_loop["steps"][0]["status"] == "planned"


async def test_update_remediation_step_match_updates_fields(sidar_agent_factory) -> None:
    remediation_loop = {"steps": [{"name": "patch", "status": "planned", "detail": "x"}]}
    agent = sidar_agent_factory()
    agent._update_remediation_step(remediation_loop, "patch", status="completed", detail="başarılı")
    assert remediation_loop["steps"][0]["status"] == "completed"
    assert remediation_loop["steps"][0]["detail"] == "başarılı"


async def test_collect_self_heal_snapshots_skips_empty_and_failed_reads(
    sidar_agent_factory,
) -> None:
    agent = sidar_agent_factory()

    code = Mock()
    code.read_file.side_effect = (
        lambda path, _safe: (False, "missing") if path == "bad.py" else (True, f"content:{path}")
    )
    agent.code = code
    snapshots = await agent._collect_self_heal_snapshots(["", "./ok.py", "bad.py"])
    assert snapshots == [{"path": "ok.py", "content": "content:ok.py"}]


async def test_execute_self_heal_plan_skipped_blocked_and_backup_failure(
    sidar_agent_factory, tmp_path: Path
) -> None:
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
        plan={
            "operations": [{"path": "a.py", "target": "x", "replacement": "y"}],
            "validation_commands": [],
        },
    )
    assert blocked["status"] == "blocked"

    reverted = await agent._execute_self_heal_plan(
        remediation_loop={},
        plan={
            "operations": [{"path": "a.py", "target": "x", "replacement": "y"}],
            "validation_commands": ["pytest -q"],
        },
    )
    assert reverted["status"] == "reverted"
    assert "yedekleme" in reverted["summary"]


async def test_build_trigger_prompt_prefers_federation_prompt(sidar_agent_factory) -> None:
    trigger = ExternalTrigger(
        trigger_id="tid", source="crm", event_name="sync", payload={}, meta={}
    )
    prompt = sidar_agent.SidarAgent._build_trigger_prompt(
        trigger,
        {"kind": "federation_task", "federation_prompt": "PRESET"},
        None,
    )
    assert prompt == "PRESET"


async def test_build_trigger_correlation_matches_related_ids(
    sidar_agent_factory,
    frozen_time,
) -> None:
    agent = sidar_agent_factory()
    now = sidar_agent.time.time()
    agent._autonomy_history = [
        {
            "trigger_id": "t-old",
            "status": "success",
            "source": "cron",
            "payload": {"task_id": "T"},
            "meta": {},
            "timestamp": now - 180,
        },
        {
            "trigger_id": "t-rel",
            "status": "failed",
            "source": "api",
            "payload": {},
            "meta": {},
            "timestamp": now - 30,
        },
    ]
    agent._autonomy_lock = None
    trigger = ExternalTrigger(trigger_id="t-new", source="api", event_name="e", payload={}, meta={})
    corr = agent._build_trigger_correlation(
        trigger, {"related_trigger_id": "t-rel", "related_task_id": "T"}
    )
    assert corr["matched_records"] == 2
    assert corr["latest_related_status"] == "failed"


async def test_try_multi_agent_imports_supervisor_when_missing(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
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


async def test_try_multi_agent_triggers_reload_if_module_corrupted(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supervisor rol sembolleri stub ise modül reload dalına girildiğini doğrular."""
    agent = sidar_agent_factory()
    agent._supervisor = None

    from agent.core import supervisor as supervisor_mod

    original_researcher = getattr(supervisor_mod, "ResearcherAgent", None)

    with monkeypatch.context() as scoped_monkeypatch:
        corrupted_role = Mock()
        corrupted_role.__module__ = "tests.stub.roles"
        scoped_monkeypatch.setattr(supervisor_mod, "ResearcherAgent", corrupted_role, raising=False)

        reload_mock = Mock(return_value=supervisor_mod)
        scoped_monkeypatch.setattr(sidar_agent.importlib, "reload", reload_mock)

        supervisor_cls = Mock()
        supervisor_instance = AsyncMock()
        supervisor_instance.run_task.return_value = "ok:reloaded"
        supervisor_cls.return_value = supervisor_instance
        scoped_monkeypatch.setattr(supervisor_mod, "SupervisorAgent", supervisor_cls)

        result = await agent._try_multi_agent("hello")

        assert result == "ok:reloaded"
        reload_mock.assert_called_once_with(supervisor_mod)

    assert getattr(supervisor_mod, "ResearcherAgent", None) is original_researcher


async def test_get_memory_archive_context_async_and_sync_edges(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    _override_cfg(
        agent, MEMORY_ARCHIVE_TOP_K=1, MEMORY_ARCHIVE_MIN_SCORE=0.3, MEMORY_ARCHIVE_MAX_CHARS=1200
    )

    agent.docs = types.SimpleNamespace(collection=None)
    assert agent._get_memory_archive_context_sync("x", 1, 0.2, 300) == ""

    collection = Mock()
    collection.query.return_value = {
        "documents": [["x" * 700, ""]],
        "metadatas": [
            [
                {"source": "memory_archive", "title": "Long"},
                {"source": "memory_archive", "title": "Empty"},
            ]
        ],
        "distances": [[0.0, 0.0]],
    }
    agent.docs = types.SimpleNamespace(collection=collection)
    sync_text = agent._get_memory_archive_context_sync("x", 1, 0.2, 1200)
    assert "Long" in sync_text
    assert "..." in sync_text

    async_text = await agent._get_memory_archive_context("x")
    assert sidar_agent.ARCHIVE_CONTEXT_HEADER in async_text


async def test_build_context_non_ollama_and_truncations(sidar_agent_factory) -> None:
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
    assert sidar_agent.CONTEXT_GEMINI_MODEL_LABEL in text
    assert f"{sidar_agent.CONTEXT_GITHUB_CONNECTED_PREFIX}org/repo" in text
    assert sidar_agent.CONTEXT_TASK_LIST_HEADER in text

    agent.cfg.AI_PROVIDER = "ollama"
    agent._load_instruction_files = lambda: "i" * 5000
    short = await agent._build_context()
    assert "yerel model" in short


async def test_load_instruction_files_no_files_and_read_error(
    sidar_agent_factory, tmp_path: Path
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, BASE_DIR=str(tmp_path))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = asyncio.Lock()

    assert agent._load_instruction_files() == ""

    unreadable_path = tmp_path / "SIDAR.md"
    unreadable_path.mkdir()
    assert agent._load_instruction_files() == ""


async def test_tool_subtask_non_string_and_tool_exception(
    sidar_agent_factory, fake_llm_response
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    responses = [{"not": "string"}, '{"tool":"x","argument":"a","thought":"t"}']

    async def _llm_response(*_args, **_kwargs):
        await fake_llm_response("subtask")
        return responses.pop(0)

    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=_llm_response))
    with patch.object(sidar_agent.SidarAgent, "_execute_tool", autospec=True) as execute_tool_mock:
        execute_tool_mock.side_effect = RuntimeError("fail-tool")
        output = await agent._tool_subtask("job")
    assert output == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE


async def test_tool_github_smart_pr_error_branches(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent.github = types.SimpleNamespace(
        is_available=lambda: True,
        default_branch="main",
        create_pull_request=lambda *_a: (False, "err"),
    )

    code = Mock()
    code.run_shell.side_effect = lambda command: (False, "") if "branch" in command else (True, "")
    agent.code = code
    no_branch = await agent._tool_github_smart_pr("x")
    assert no_branch == sidar_agent.GITHUB_SMART_PR_NO_BRANCH_MESSAGE

    code.run_shell.side_effect = (
        lambda command: (True, "feat/a")
        if "branch" in command
        else ((True, "") if "status" in command else (True, ""))
    )
    agent.code = code
    no_changes = await agent._tool_github_smart_pr("x")
    assert no_changes == sidar_agent.GITHUB_SMART_PR_NO_CHANGES_MESSAGE

    def _run_shell_large_diff(command: str) -> tuple[bool, str]:
        if "branch" in command:
            return True, "feat/a"
        if "status" in command:
            return True, "M a.py"
        if "diff --no-color" in command:
            return True, "x" * 12000
        if "log" in command:
            return True, "c1"
        return True, ""

    code.run_shell.side_effect = _run_shell_large_diff
    agent.code = code
    assert (await agent._tool_github_smart_pr("title|||base|||note")).startswith(
        sidar_agent.GITHUB_SMART_PR_CREATE_FAILED_PREFIX
    )


@pytest.mark.parametrize(
    "create_pr_side_effect, expected_fragment",
    [
        (TimeoutError("network timeout"), "zaman aşımı"),
        (RuntimeError("404 Not Found"), "404 Not Found"),
    ],
)
async def test_tool_github_smart_pr_handles_create_pr_exceptions(
    sidar_agent_factory,
    create_pr_side_effect,
    expected_fragment: str,
) -> None:
    agent = sidar_agent_factory()
    code = Mock()

    def _run_shell_success(command: str) -> tuple[bool, str]:
        if "branch" in command:
            return True, "feat/x"
        if "status" in command:
            return True, "M a.py"
        if "diff --no-color" in command:
            return True, "diff"
        if "log" in command:
            return True, "c1"
        return True, ""

    code.run_shell.side_effect = _run_shell_success
    github = Mock()
    github.is_available.return_value = True
    github.default_branch = "main"
    github.create_pull_request.side_effect = create_pr_side_effect
    agent.code = code
    agent.github = github

    result = await agent._tool_github_smart_pr("title|||main|||note")
    assert sidar_agent.GITHUB_SMART_PR_CREATE_FAILED_PREFIX in result
    assert expected_fragment in result


@pytest.mark.parametrize("branch_output", ["", False])
async def test_tool_github_smart_pr_no_branch_when_branch_output_empty_or_false(
    sidar_agent_factory,
    branch_output,
) -> None:
    agent = sidar_agent_factory()
    agent.github = types.SimpleNamespace(is_available=lambda: True, default_branch="main")
    agent.code = Mock()
    agent.code.run_shell.return_value = (True, branch_output)

    result = await agent._tool_github_smart_pr("PR Title|||main|||notes")
    assert sidar_agent.GITHUB_SMART_PR_NO_BRANCH_MESSAGE in result


async def test_summarize_memory_exception_paths_and_memory_add(sidar_agent_factory) -> None:
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


async def test_summarize_memory_early_return_when_history_short(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    memory = AsyncMock()
    memory.get_history.return_value = [
        {"role": "user", "content": "hi", "timestamp": 1},
    ]
    memory.apply_summary = AsyncMock()
    agent.memory = memory
    agent.docs = AsyncMock()

    await agent._summarize_memory()

    agent.docs.add_document.assert_not_called()
    assert agent.memory.apply_summary.call_count == 0


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


async def test_runtime_helpers_and_self_heal_validation_failure(
    sidar_agent_factory, tmp_path: Path
) -> None:
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


async def test_attempt_self_heal_failed_branch_and_workflow_payload_dict(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    agent.code = create_autospec(CodeManager, instance=True, spec_set=True)
    agent.llm = create_autospec(BaseLLMClient, instance=True, spec_set=True)
    agent._build_self_heal_plan = AsyncMock(return_value={"operations": [{"path": "a.py"}]})
    agent._execute_self_heal_plan = AsyncMock(
        return_value={"status": "reverted", "summary": "bad", "operations_applied": []}
    )
    remediation = {
        "remediation_loop": {
            "status": "planned",
            "steps": [{"name": "patch"}, {"name": "validate"}],
        }
    }
    failed = await agent._attempt_autonomous_self_heal(
        ci_context={}, diagnosis="d", remediation=remediation
    )
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

    monkeypatch.setattr(
        sidar_agent, "build_ci_failure_context", lambda *_a, **_k: {"from": "fallback"}
    )
    monkeypatch.setattr(
        sidar_agent,
        "build_ci_remediation_payload",
        lambda *_a, **_k: {"remediation_loop": {"status": "planned"}},
    )
    agent._attempt_autonomous_self_heal = AsyncMock()

    payload = {
        "kind": "workflow_run",
        "workflow_name": "ci",
        "workflow": "ci",
    }
    out = await agent.handle_external_trigger(
        {
            "trigger_id": "w1",
            "source": "gh",
            "event_name": "workflow_run",
            "payload": payload,
            "meta": {},
        }
    )
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
    agent.memory = types.SimpleNamespace(
        run_nightly_consolidation=AsyncMock(
            return_value={"session_ids": [], "sessions_compacted": 0}
        )
    )
    agent.docs = types.SimpleNamespace(
        consolidate_session_documents=lambda *_a, **_k: {"removed_docs": 0}
    )
    report = await agent.run_nightly_memory_maintenance(force=True)
    assert report["entity_report"]["status"] == "failed"


async def test_get_memory_archive_context_sync_filters_distances(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    collection = Mock()
    collection.query.return_value = {
        "documents": [["", "ok"]],
        "metadatas": [
            [{"source": "memory_archive", "title": "E"}, {"source": "memory_archive", "title": "T"}]
        ],
        "distances": [[0.9, 0.1]],
    }
    agent.docs = types.SimpleNamespace(collection=collection)

    result = agent._get_memory_archive_context_sync("q", 3, 0.2, 100)
    assert "T" in result
    assert "E" not in result


async def test_load_instruction_files_handles_fs_errors(
    sidar_agent_factory, tmp_path: Path
) -> None:
    agent = sidar_agent_factory(cfg=types.SimpleNamespace(BASE_DIR=str(tmp_path)))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = asyncio.Lock()

    (tmp_path / "SIDAR.md").mkdir()
    (tmp_path / "CLAUDE.md").write_text("ok-content", encoding="utf-8")

    content = agent._load_instruction_files()
    assert "ok-content" in content


async def test_tool_docs_search_returns_plain_text(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent.docs = types.SimpleNamespace(search=lambda *_a: (True, "plain"))
    assert await agent._tool_docs_search("q") == "plain"


async def test_poyraz_rate_limit_returns_graceful_message_in_sidar_suite(fake_social_api) -> None:
    from agent.roles.poyraz_agent import PoyrazAgent

    poyraz = PoyrazAgent.__new__(PoyrazAgent)
    poyraz.social = fake_social_api
    poyraz.social.set_rate_limit_error()
    poyraz.social.publish_content = AsyncMock(side_effect=RuntimeError("API Rate Limit"))

    output = await PoyrazAgent._tool_publish_social(poyraz, "instagram|||hata testi|||sidar")
    assert output.startswith("[SOCIAL:ERROR]")
    assert "rate_limit" in output
    assert "Lütfen bekleyip tekrar deneyin" in output


async def test_build_context_excludes_todo_section_when_empty(sidar_agent_factory) -> None:
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
    assert sidar_agent.CONTEXT_TASK_LIST_HEADER not in ctx


@pytest.mark.parametrize("offset", [-1, 0, 1])
async def test_build_context_truncates_for_local_models_boundary_values(
    sidar_agent_factory, offset: int
) -> None:
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
        GITHUB_REPO="org/repo",
        LOCAL_INSTRUCTION_MAX_CHARS=5000,
        LOCAL_AGENT_CONTEXT_MAX_CHARS=1000,
        SUBTASK_MAX_STEPS=1,
    )
    agent.security = types.SimpleNamespace(level_name="safe")
    agent.github = types.SimpleNamespace(is_available=lambda: True, status=lambda: "g")
    agent.web = types.SimpleNamespace(is_available=lambda: True, status=lambda: "w")
    agent.docs = types.SimpleNamespace(status=lambda: "d", search=lambda *_a: (True, "plain"))
    agent.code = types.SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 1})
    agent.memory = types.SimpleNamespace(get_last_file=lambda: "")
    agent.todo = types.SimpleNamespace(__len__=lambda *_a: 0)

    # Önce talimatsız baz bağlamı ölç; sonra eşik altı/eşik/eşik üstü uzunlukları üret.
    agent._load_instruction_files = lambda: ""
    base_context = await agent._build_context()
    target_len = 1000 + offset
    filler_len = max(1, target_len - (len(base_context) + 2))
    agent._load_instruction_files = lambda: "x" * filler_len

    built = await agent._build_context()

    if offset <= 0:
        assert "Bağlam yerel model için kırpıldı" not in built
        assert len(built) == target_len
    else:
        assert "Bağlam yerel model için kırpıldı" in built


async def test_tool_subtask_records_metrics_on_failure(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch, fake_llm_response
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")
    metrics_calls = []
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: types.SimpleNamespace(record_step=lambda *a: metrics_calls.append(a)),
    )

    async def _llm_response(*_args, **_kwargs) -> str:
        await fake_llm_response("subtask")
        return '{"tool":"docs_search","argument":"arg","thought":"x"}'

    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=_llm_response))
    with patch.object(sidar_agent.SidarAgent, "_execute_tool", autospec=True) as execute_tool_mock:
        execute_tool_mock.side_effect = RuntimeError("tool-boom")
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

    def _run_shell_success(command: str) -> tuple[bool, str]:
        if "branch" in command:
            return True, "feat/a"
        if "status" in command:
            return True, "M a.py"
        if "diff --no-color" in command:
            return True, "diff"
        if "log" in command:
            return True, "c1"
        return True, ""

    code.run_shell.side_effect = _run_shell_success

    agent.github = github
    agent.code = code
    msg = await agent._tool_github_smart_pr("title")
    assert "oluşturuldu" in msg


async def test_attempt_self_heal_plan_without_operations_and_initialize_no_prompt(
    sidar_agent_factory,
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, ENABLE_AUTONOMOUS_SELF_HEAL=True)
    agent.code = create_autospec(CodeManager, instance=True, spec_set=True)
    agent.llm = create_autospec(BaseLLMClient, instance=True, spec_set=True)
    agent._build_self_heal_plan = AsyncMock(return_value={"operations": []})
    remediation = {"remediation_loop": {"status": "planned", "steps": [{"name": "patch"}]}}
    blocked = await agent._attempt_autonomous_self_heal(
        ci_context={}, diagnosis="d", remediation=remediation
    )
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


async def test_initialize_lazy_init_lock_handles_concurrent_calls(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent._initialized = False
    agent._init_lock = None
    agent.memory = types.SimpleNamespace(initialize=AsyncMock())

    await asyncio.gather(*(agent.initialize() for _ in range(8)))

    assert agent._initialized is True
    assert isinstance(agent._init_lock, asyncio.Lock)
    agent.memory.initialize.assert_awaited_once()


async def test_respond_and_append_history_with_existing_locks(
    sidar_agent_factory,
    frozen_time,
) -> None:
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


async def test_append_autonomy_history_lazy_lock_handles_concurrency(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent._autonomy_lock = None
    agent._autonomy_history = []

    await asyncio.gather(
        *(
            agent._append_autonomy_history({"idx": idx, "timestamp": float(idx)})
            for idx in range(20)
        )
    )

    assert isinstance(agent._autonomy_lock, asyncio.Lock)
    assert len(agent._autonomy_history) == 20
    assert sorted(item["idx"] for item in agent._autonomy_history) == list(range(20))


async def test_execute_self_heal_plan_applied_with_existing_backup(
    sidar_agent_factory, tmp_path: Path
) -> None:
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
    assert (await agent._execute_self_heal_plan(remediation_loop={}, plan=plan))[
        "status"
    ] == "applied"


async def test_tool_subtask_exception_path_records_failed_metrics(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_response,
) -> None:
    agent = sidar_agent_factory()
    metrics_calls = []
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: types.SimpleNamespace(record_step=lambda *a: metrics_calls.append(a)),
    )

    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")

    async def _llm_response(*_args, **_kwargs) -> str:
        await fake_llm_response("subtask")
        return '{"tool":"docs_search","argument":"arg","thought":"x"}'

    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=_llm_response))

    with patch.object(sidar_agent.SidarAgent, "_execute_tool", autospec=True) as execute_tool_mock:
        execute_tool_mock.side_effect = RuntimeError("tool-boom")
        out = await agent._tool_subtask("job")
    assert out == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE
    assert any(call[3] == "failed" for call in metrics_calls)


async def test_handle_external_trigger_instance_path_and_correlation_loop(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    frozen_time,
) -> None:
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

    agent._autonomy_history = [
        {"trigger_id": "x", "payload": {}, "timestamp": sidar_agent.time.time()}
    ]
    agent._autonomy_lock = None
    corr = agent._build_trigger_correlation(trigger, {})
    assert corr["matched_records"] == 0


async def test_initialize_without_db_and_tool_subtask_remaining_branches(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_response,
) -> None:
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

    async def _llm_response(*_args, **_kwargs) -> str:
        await fake_llm_response("subtask")
        return '{"tool":"docs_search","argument":"arg","thought":"x"}'

    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=_llm_response))
    with patch.object(sidar_agent.SidarAgent, "_execute_tool", autospec=True) as execute_tool_mock:
        execute_tool_mock.return_value = "ok"
        assert sidar_agent.SUBTASK_MAX_STEPS_MESSAGE == await agent._tool_subtask("job")

    # generic exception branch with metrics enabled (1125-1137)
    calls = []
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: types.SimpleNamespace(record_step=lambda *a: calls.append(a)),
    )

    with patch.object(sidar_agent.SidarAgent, "_execute_tool", autospec=True) as execute_tool_mock:
        execute_tool_mock.side_effect = RuntimeError("tool-fail")
        out = await agent._tool_subtask("job")
    assert out == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE
    assert any(c[3] == "failed" for c in calls)


async def test_tool_subtask_generic_exception_without_metrics(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_response,
) -> None:
    validation_err = type("ValidationErr", (Exception,), {})
    monkeypatch.setattr(sidar_agent, "ValidationError", validation_err)
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: (_ for _ in ()).throw(RuntimeError("metrics unavailable")),
    )

    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")

    async def _llm_response(*_args, **_kwargs) -> str:
        await fake_llm_response("subtask")
        return '{"tool":"docs_search","argument":"arg","thought":"x"}'

    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=_llm_response))
    with patch.object(sidar_agent.SidarAgent, "_execute_tool", autospec=True) as execute_tool_mock:
        execute_tool_mock.side_effect = RuntimeError("fail")
        assert sidar_agent.SUBTASK_MAX_STEPS_MESSAGE == await agent._tool_subtask("job")


async def test_load_instruction_files_handles_string_candidates(
    sidar_agent_factory, tmp_path: Path
) -> None:
    agent = sidar_agent_factory()
    instruction = tmp_path / "SIDAR.md"
    instruction.write_text("Talimat", encoding="utf-8")

    _override_cfg(agent, BASE_DIR=str(tmp_path))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = asyncio.Lock()

    loaded = agent._load_instruction_files()
    assert "SIDAR.md" in loaded
    assert "Talimat" in loaded


async def test_sidar_agent_respond_critical_flow_uses_shared_fixtures(
    sidar_agent_factory,
    fake_llm_response,
    fake_event_stream,
) -> None:
    agent = sidar_agent_factory()
    agent.initialize = AsyncMock()
    agent._memory_add = AsyncMock()

    async def _fake_multi(user_input: str) -> str:
        llm_payload = await fake_llm_response(user_input)
        last_event = ""
        async for event in fake_event_stream():
            last_event = event.message
        return f"{llm_payload['content']}::{last_event}"

    agent._try_multi_agent = AsyncMock(side_effect=_fake_multi)

    chunks = [chunk async for chunk in agent.respond("kritik akış testi")]

    assert len(chunks) == 1
    assert "mock-response" in chunks[0]
    assert "İşlem tamam." in chunks[0]


async def test_sidar_agent_llm_error_flow(
    sidar_agent_factory,
    fake_llm_error,
    fake_event_stream,
) -> None:
    _ = fake_event_stream
    agent = sidar_agent_factory()
    agent.initialize = AsyncMock()
    agent._try_multi_agent = AsyncMock(side_effect=fake_llm_error)

    with pytest.raises(RuntimeError, match="rate limit exceeded"):
        _chunks = [chunk async for chunk in agent.respond("hata tetikle")]


async def test_normalize_config_defaults_covers_sentinel_and_non_upper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Defaults:
        MAX_MEMORY_TURNS = 12
        not_upper = "skip"

    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = types.SimpleNamespace(MAX_MEMORY_TURNS=8)

    monkeypatch.setattr(sidar_agent, "Config", lambda: _Defaults())
    monkeypatch.setattr(
        sidar_agent, "dir", lambda _obj: ["MISSING", "not_upper", "MAX_MEMORY_TURNS"], raising=False
    )

    sidar_agent.SidarAgent._normalize_config_defaults(agent)
    assert agent.cfg.MAX_MEMORY_TURNS == 8


async def test_normalize_config_defaults_flaky_key_hits_non_upper_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FlakyKey(str):
        def __new__(cls, value: str):
            obj = super().__new__(cls, value)
            obj._called = 0
            return obj

        def isupper(self) -> bool:
            self._called += 1
            return self._called == 1

    flaky_key = _FlakyKey("MIXED")

    class _Defaults:
        pass

    defaults = _Defaults()
    setattr(defaults, flaky_key, "value")

    agent = sidar_agent.SidarAgent.__new__(sidar_agent.SidarAgent)
    agent.cfg = types.SimpleNamespace()
    monkeypatch.setattr(sidar_agent, "Config", lambda: defaults)
    monkeypatch.setattr(sidar_agent, "dir", lambda _obj: [flaky_key], raising=False)

    sidar_agent.SidarAgent._normalize_config_defaults(agent)
    assert not hasattr(agent.cfg, "MIXED")


async def test_respond_awaits_coroutine_result_from_try_multi_agent(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    agent._lock = None
    agent.initialize = AsyncMock()
    agent.mark_activity = lambda *_a, **_k: None
    records = []

    async def _later() -> str:
        return "wrapped"

    async def _multi(_user_input: str):
        return _later()

    async def _memory_add(role: str, content: str):
        records.append((role, content))

    agent._try_multi_agent = _multi
    agent._memory_add = _memory_add
    out = [chunk async for chunk in agent.respond("ping")]
    assert out == ["wrapped"]
    assert records[-1] == ("assistant", "wrapped")


async def test_try_multi_agent_skips_optional_researcher_and_role_llm_binding(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = sidar_agent_factory()
    agent._supervisor = None

    class _Supervisor:
        def __init__(self, _cfg):
            self.researcher = None
            self.coder = types.SimpleNamespace()
            self.reviewer = None
            self.poyraz = None
            self.qa = None
            self.coverage = None

        async def run_task(self, _input):
            return "ok"

    fake_module = types.SimpleNamespace(
        ResearcherAgent=types.SimpleNamespace(__module__="agent.roles.researcher_agent"),
        CoderAgent=types.SimpleNamespace(__module__="agent.roles.coder_agent"),
        ReviewerAgent=types.SimpleNamespace(__module__="agent.roles.reviewer_agent"),
        PoyrazAgent=types.SimpleNamespace(__module__="agent.roles.poyraz_agent"),
        QAAgent=types.SimpleNamespace(__module__="agent.roles.qa_agent"),
        CoverageAgent=types.SimpleNamespace(__module__="agent.roles.coverage_agent"),
        SupervisorAgent=_Supervisor,
    )
    monkeypatch.setattr(sidar_agent, "import_module", lambda _name: fake_module)

    result = await agent._try_multi_agent("x")
    assert result == "ok"


async def test_try_multi_agent_researcher_without_web_or_docs_branches(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = sidar_agent_factory()
    agent._supervisor = None

    class _Researcher:
        pass

    class _Supervisor:
        def __init__(self, _cfg):
            self.researcher = _Researcher()
            self.coder = None
            self.reviewer = None
            self.poyraz = None
            self.qa = None
            self.coverage = None

        async def run_task(self, _input):
            return "ok"

    fake_module = types.SimpleNamespace(
        ResearcherAgent=types.SimpleNamespace(__module__="agent.roles.researcher_agent"),
        CoderAgent=types.SimpleNamespace(__module__="agent.roles.coder_agent"),
        ReviewerAgent=types.SimpleNamespace(__module__="agent.roles.reviewer_agent"),
        PoyrazAgent=types.SimpleNamespace(__module__="agent.roles.poyraz_agent"),
        QAAgent=types.SimpleNamespace(__module__="agent.roles.qa_agent"),
        CoverageAgent=types.SimpleNamespace(__module__="agent.roles.coverage_agent"),
        SupervisorAgent=_Supervisor,
    )
    monkeypatch.setattr(sidar_agent, "import_module", lambda _name: fake_module)
    assert await agent._try_multi_agent("x") == "ok"


async def test_build_context_todo_len_non_callable_and_exception(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, AI_PROVIDER="openai", ACCESS_LEVEL="safe")
    agent.security = types.SimpleNamespace(level_name="safe")
    agent.github = types.SimpleNamespace(is_available=lambda: False)
    agent.web = types.SimpleNamespace(is_available=lambda: True)
    agent.docs = types.SimpleNamespace(status=lambda: "ok")
    agent.code = types.SimpleNamespace(get_metrics=lambda: {"files_read": 0, "files_written": 0})
    agent.memory = types.SimpleNamespace(get_last_file=lambda: "")
    agent._load_instruction_files = lambda: ""

    class _TodoNonCallable:
        def __len__(self):
            raise TypeError("len")

    bad = _TodoNonCallable()
    bad.__len__ = 9
    agent.todo = bad
    ctx = await agent._build_context()
    assert sidar_agent.CONTEXT_TASK_LIST_HEADER not in ctx

    class _TodoBoom:
        def __len__(self):
            raise RuntimeError("boom")

    agent.todo = _TodoBoom()
    ctx2 = await agent._build_context()
    assert sidar_agent.CONTEXT_TASK_LIST_HEADER not in ctx2


async def test_load_instruction_files_handles_stat_and_read_exceptions(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, BASE_DIR=str(tmp_path))
    agent._instructions_cache = None
    agent._instructions_mtimes = {}
    agent._instructions_lock = asyncio.Lock()

    class _BadStatPath:
        def is_file(self):
            return True

        def resolve(self):
            return self

        def stat(self):
            raise RuntimeError("stat")

        def read_text(self, **_kwargs):
            return "ignored"

        def relative_to(self, _root):
            return Path("SIDAR.md")

        def __str__(self):
            return str(tmp_path / "SIDAR.md")

        def __hash__(self):
            return 1

    class _BadReadPath(_BadStatPath):
        def stat(self):
            return types.SimpleNamespace(st_mtime=1.0)

        def read_text(self, **_kwargs):
            raise RuntimeError("read")

        def __str__(self):
            return str(tmp_path / "CLAUDE.md")

        def __hash__(self):
            return 2

    monkeypatch.setattr(Path, "rglob", lambda self, _name: [_BadStatPath(), _BadReadPath()])
    loaded = agent._load_instruction_files()
    assert "ignored" in loaded


async def test_tool_subtask_records_tool_execution_and_validation_error_metrics(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_response,
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")
    metric_calls = []
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: types.SimpleNamespace(record_step=lambda *args: metric_calls.append(args)),
    )

    async def _llm_response(*_args, **_kwargs) -> str:
        await fake_llm_response("subtask")
        return '{"tool":"docs_search","argument":"x","thought":"t"}'

    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=_llm_response))
    with patch.object(sidar_agent.SidarAgent, "_execute_tool", autospec=True, return_value="ok"):
        out = await agent._tool_subtask("job")
    assert out == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE
    assert any(call[1] == "tool_execution" and call[3] == "success" for call in metric_calls)

    validation_error = sidar_agent.ValidationError.from_exception_data("ToolCall", line_errors=[])
    metric_calls.clear()
    with (
        patch.object(
            sidar_agent.ToolCall, "model_validate_json", autospec=True, side_effect=validation_error
        ),
        patch.object(
            sidar_agent.ToolCall,
            "model_validate",
            autospec=True,
            side_effect=validation_error,
        ),
    ):
        out2 = await agent._tool_subtask("job")
    assert out2 == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE
    assert any(call[1] == "llm_decision" and call[3] == "failed" for call in metric_calls)


async def test_tool_subtask_validation_error_without_metrics(
    sidar_agent_factory,
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_response,
) -> None:
    agent = sidar_agent_factory()
    _override_cfg(agent, SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")

    async def _llm_response(*_args, **_kwargs) -> str:
        await fake_llm_response("subtask")
        return '{"tool":"docs_search","argument":"x","thought":"t"}'

    agent.llm = types.SimpleNamespace(chat=AsyncMock(side_effect=_llm_response))
    monkeypatch.setattr(
        sidar_agent,
        "get_agent_metrics_collector",
        lambda: (_ for _ in ()).throw(RuntimeError("metrics unavailable")),
    )
    validation_error = sidar_agent.ValidationError.from_exception_data("ToolCall", line_errors=[])
    with (
        patch.object(
            sidar_agent.ToolCall, "model_validate_json", autospec=True, side_effect=validation_error
        ),
        patch.object(
            sidar_agent.ToolCall,
            "model_validate",
            autospec=True,
            side_effect=validation_error,
        ),
    ):
        assert await agent._tool_subtask("job") == sidar_agent.SUBTASK_MAX_STEPS_MESSAGE


async def test_tool_github_smart_pr_base_defaults_to_main_on_error(sidar_agent_factory) -> None:
    agent = sidar_agent_factory()
    code = Mock()

    def _run(command: str) -> tuple[bool, str]:
        if "branch" in command:
            return True, "feat/test"
        if "status" in command:
            return True, "M a.py"
        if "diff --no-color" in command:
            return True, "diff"
        if "log" in command:
            return True, "c1"
        return True, ""

    code.run_shell.side_effect = _run
    github = Mock()
    github.is_available.return_value = True
    type(github).default_branch = property(
        lambda _self: (_ for _ in ()).throw(RuntimeError("no-default"))
    )
    github.create_pull_request.return_value = (True, "url")

    agent.code = code
    agent.github = github
    msg = await agent._tool_github_smart_pr("title")
    assert "oluşturuldu" in msg


async def test_summarize_memory_logs_info_on_success(
    sidar_agent_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = sidar_agent_factory()
    info_mock = Mock()
    monkeypatch.setattr(sidar_agent.logger, "info", info_mock)
    agent.memory = types.SimpleNamespace(
        get_history=AsyncMock(
            return_value=[
                {"role": "user", "content": "a", "timestamp": 1},
                {"role": "assistant", "content": "b", "timestamp": 1},
                {"role": "user", "content": "c", "timestamp": 1},
                {"role": "assistant", "content": "d", "timestamp": 1},
            ]
        ),
        apply_summary=AsyncMock(),
    )
    agent.docs = types.SimpleNamespace(add_document=AsyncMock())
    agent.llm = types.SimpleNamespace(chat=AsyncMock(return_value="summary"))
    _override_cfg(agent, TEXT_MODEL="tm", CODING_MODEL="cm")

    await agent._summarize_memory()
    info_mock.assert_called()
