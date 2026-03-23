import asyncio
import importlib.util
import json
import sys
import threading
import types
import pytest
from pathlib import Path
from types import SimpleNamespace


def _load_sidar_agent_module():
    stubs = {
        "pydantic": types.ModuleType("pydantic"),
        "config": types.ModuleType("config"),
        "core.memory": types.ModuleType("core.memory"),
        "core.llm_client": types.ModuleType("core.llm_client"),
        "core.rag": types.ModuleType("core.rag"),
        "managers.code_manager": types.ModuleType("managers.code_manager"),
        "managers.system_health": types.ModuleType("managers.system_health"),
        "managers.github_manager": types.ModuleType("managers.github_manager"),
        "managers.security": types.ModuleType("managers.security"),
        "managers.web_search": types.ModuleType("managers.web_search"),
        "managers.package_info": types.ModuleType("managers.package_info"),
        "managers.todo_manager": types.ModuleType("managers.todo_manager"),
        "agent.auto_handle": types.ModuleType("agent.auto_handle"),
        "agent.definitions": types.ModuleType("agent.definitions"),
        "agent.tooling": types.ModuleType("agent.tooling"),
        "agent.core.contracts": types.ModuleType("agent.core.contracts"),
    }

    class ValidationError(Exception):
        pass

    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        @classmethod
        def model_validate(cls, data):
            for key in ("thought", "tool", "argument"):
                if key not in data:
                    raise ValidationError(key)
            return cls(**data)

        @classmethod
        def model_validate_json(cls, raw):
            data = json.loads(raw)
            for key in ("thought", "tool", "argument"):
                if key not in data:
                    raise ValidationError(key)
            return cls(**data)

    def Field(*args, **kwargs):
        return None

    stubs["pydantic"].BaseModel = BaseModel
    stubs["pydantic"].Field = Field
    stubs["pydantic"].ValidationError = ValidationError

    class _Cfg:
        pass

    stubs["config"].Config = _Cfg

    for mod_name, cls_name in (
        ("core.memory", "ConversationMemory"),
        ("core.llm_client", "LLMClient"),
        ("core.rag", "DocumentStore"),
        ("managers.code_manager", "CodeManager"),
        ("managers.system_health", "SystemHealthManager"),
        ("managers.github_manager", "GitHubManager"),
        ("managers.security", "SecurityManager"),
        ("managers.web_search", "WebSearchManager"),
        ("managers.package_info", "PackageInfoManager"),
        ("managers.todo_manager", "TodoManager"),
        ("agent.auto_handle", "AutoHandle"),
    ):
        setattr(stubs[mod_name], cls_name, object)

    stubs["agent.definitions"].SIDAR_SYSTEM_PROMPT = "sys"
    class ExternalTrigger:
        def __init__(self, trigger_id="", source="", event_name="", payload=None, meta=None, correlation_id=""):
            self.trigger_id = trigger_id
            self.source = source
            self.event_name = event_name
            self.payload = payload or {}
            self.meta = meta or {}
            self.correlation_id = correlation_id or self.meta.get("correlation_id", "") or self.payload.get("correlation_id", "") or trigger_id

        def to_prompt(self):
            return f"[TRIGGER]\nsource={self.source}\nevent={self.event_name}"

    class FederationTaskEnvelope:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def to_prompt(self):
            return "[FEDERATION TASK]\n" + json.dumps(self.kwargs, ensure_ascii=False, sort_keys=True)

    class ActionFeedback:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def to_prompt(self):
            return "[ACTION FEEDBACK]\n" + json.dumps(self.kwargs, ensure_ascii=False, sort_keys=True)

    def derive_correlation_id(*values):
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    stubs["agent.core.contracts"].ExternalTrigger = ExternalTrigger
    stubs["agent.core.contracts"].FederationTaskEnvelope = FederationTaskEnvelope
    stubs["agent.core.contracts"].ActionFeedback = ActionFeedback
    stubs["agent.core.contracts"].derive_correlation_id = derive_correlation_id

    class _Schema:
        pass

    for n in (
        "GithubCloseIssueSchema",
        "GithubCommentIssueSchema",
        "GithubCreateBranchSchema",
        "GithubCreateIssueSchema",
        "GithubCreatePRSchema",
        "GithubListFilesSchema",
        "GithubListIssuesSchema",
        "GithubListPRsSchema",
        "GithubPRDiffSchema",
        "GithubWriteSchema",
        "PatchFileSchema",
        "WriteFileSchema",
        "ScanProjectTodosSchema",
    ):
        setattr(stubs["agent.tooling"], n, _Schema)

    stubs["agent.tooling"].build_tool_dispatch = lambda _agent: {}
    stubs["agent.tooling"].parse_tool_argument = lambda _tool, arg: arg

    saved = {k: sys.modules.get(k) for k in stubs}
    try:
        for k, v in stubs.items():
            sys.modules[k] = v

        spec = importlib.util.spec_from_file_location("sidar_agent_under_test", Path("agent/sidar_agent.py"))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, old in saved.items():
            if old is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = old


SA_MOD = _load_sidar_agent_module()
SidarAgent = SA_MOD.SidarAgent
ExternalTrigger = SA_MOD.ExternalTrigger


async def _collect(aiter):
    return [x async for x in aiter]


def _make_agent_for_runtime():
    a = SidarAgent.__new__(SidarAgent)
    a.cfg = SimpleNamespace(AI_PROVIDER="ollama", CODING_MODEL="m", ACCESS_LEVEL="sandbox")
    a._lock = None
    a._initialized = True
    a._init_lock = None
    a.tracer = None
    a._tools = {}

    class _Mem:
        def __init__(self):
            self.items = []

        async def add(self, role, text):
            self.items.append((role, text))

        def needs_summarization(self):
            return False

        def __len__(self):
            return len(self.items)

        def clear(self):
            self.items.clear()

    a.memory = _Mem()
    a.auto = SimpleNamespace(handle=None)
    a.github = SimpleNamespace(status=lambda: "gh")
    a.web = SimpleNamespace(status=lambda: "web")
    a.pkg = SimpleNamespace(status=lambda: "pkg")
    a.docs = SimpleNamespace(status=lambda: "docs")
    a.health = SimpleNamespace(full_report=lambda: "health")
    a.security = SimpleNamespace(
        level_name="sandbox",
        set_level=lambda _lvl: False,
    )
    return a


def test_respond_empty_and_handled_short_path():
    a = _make_agent_for_runtime()

    async def fake_multi(_):
        return "multi"

    a._try_multi_agent = fake_multi

    out = asyncio.run(_collect(a.respond("   ")))
    assert out == ["⚠ Boş girdi."]

    out = asyncio.run(_collect(a.respond("merhaba")))
    assert out == ["multi"]
    assert a.memory.items[0] == ("user", "merhaba")
    assert a.memory.items[1] == ("assistant", "multi")


def test_respond_react_and_summarize_path():
    a = _make_agent_for_runtime()

    async def fake_multi(_):
        return "supervised"

    a._try_multi_agent = fake_multi

    out = asyncio.run(_collect(a.respond("istek")))
    assert out == ["supervised"]


def test_respond_reuses_existing_lock_for_memory_writes():
    a = _make_agent_for_runtime()
    existing_lock = asyncio.Lock()
    a._lock = existing_lock

    async def fake_multi(_):
        return "locked"

    a._try_multi_agent = fake_multi

    out = asyncio.run(_collect(a.respond("kilit testi")))

    assert out == ["locked"]
    assert a._lock is existing_lock
    assert a.memory.items == [("user", "kilit testi"), ("assistant", "locked")]


def test_handle_external_trigger_records_activity_and_memory():
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)

    async def fake_multi(prompt):
        assert "[TRIGGER]" in prompt
        return "proaktif-yanit"

    a._try_multi_agent = fake_multi

    trigger = ExternalTrigger(trigger_id="tr-1", source="webhook:ci", event_name="build_failed", payload={"job": "test"})
    record = asyncio.run(a.handle_external_trigger(trigger))

    assert record["trigger_id"] == "tr-1"
    assert record["status"] == "success"
    assert record["summary"] == "proaktif-yanit"
    assert any(role == "user" and "[AUTONOMY_TRIGGER]" in text for role, text in a.memory.items)
    assert a.get_autonomy_activity(limit=5)["counts_by_source"]["webhook:ci"] == 1


def test_handle_external_trigger_builds_ci_remediation_payload():
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)

    async def fake_multi(prompt):
        assert "[CI_REMEDIATION]" in prompt
        assert "logs_url=https://github.com/acme/sidar/actions/runs/77/logs" in prompt
        return "Kök neden pytest failure. Önerilen patch: flaky assertion düzelt."

    a._try_multi_agent = fake_multi

    trigger = ExternalTrigger(
        trigger_id="tr-ci-1",
        source="webhook:github:ci_failure",
        event_name="workflow_run",
        payload={
            "repository": {"full_name": "acme/sidar", "default_branch": "main"},
            "workflow_run": {
                "id": 77,
                "run_number": 14,
                "name": "CI",
                "status": "completed",
                "conclusion": "failure",
                "head_branch": "feature/remediate",
                "head_sha": "abc123",
                "html_url": "https://github.com/acme/sidar/actions/runs/77",
                "jobs_url": "https://github.com/acme/sidar/actions/runs/77/jobs",
                "logs_url": "https://github.com/acme/sidar/actions/runs/77/logs",
                "display_title": "pytest failure",
            },
        },
    )
    record = asyncio.run(a.handle_external_trigger(trigger))

    assert record["status"] == "success"
    assert record["remediation"]["context"]["workflow_name"] == "CI"
    assert record["remediation"]["prompt"].startswith("[CI_REMEDIATION]")
    assert isinstance(record["remediation"]["suspected_targets"], list)
    assert isinstance(record["remediation"]["diagnostic_hints"], list)
    assert record["remediation"]["root_cause_summary"].startswith("Kök neden")
    assert record["remediation"]["pr_proposal"]["auto_create_ready"] is True
    assert record["remediation"]["pr_proposal"]["head_branch_suggestion"] == "ci-remediation/77"


def test_handle_external_trigger_applies_self_heal_when_plan_is_safe(tmp_path):
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)
    a.cfg = SimpleNamespace(
        AI_PROVIDER="ollama",
        CODING_MODEL="m",
        ACCESS_LEVEL="full",
        BASE_DIR=tmp_path,
        ENABLE_AUTONOMOUS_SELF_HEAL=True,
        SELF_HEAL_MAX_PATCHES=2,
    )
    target = tmp_path / "main.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    class _Code:
        def read_file(self, path, line_numbers=False):
            return True, (tmp_path / path).read_text(encoding="utf-8")

        def patch_file(self, path, target_block, replacement_block):
            file_path = tmp_path / path
            content = file_path.read_text(encoding="utf-8")
            if target_block not in content:
                return False, "missing target"
            file_path.write_text(content.replace(target_block, replacement_block, 1), encoding="utf-8")
            return True, "patched"

        def write_file(self, path, content, validate=False):
            (tmp_path / path).write_text(content, encoding="utf-8")
            return True, "written"

        def run_shell_in_sandbox(self, command, cwd):
            assert cwd == str(tmp_path)
            return True, f"ok:{command}"

    class _LLM:
        async def chat(self, **kwargs):
            prompt = kwargs["messages"][0]["content"]
            assert "[SELF_HEAL_PLAN]" in prompt
            return json.dumps(
                {
                    "summary": "VALUE sabitini düzelt",
                    "confidence": "medium",
                    "operations": [
                        {
                            "action": "patch",
                            "path": "main.py",
                            "target": "VALUE = 1",
                            "replacement": "VALUE = 2",
                        }
                    ],
                    "validation_commands": ["python -m pytest"],
                }
            )

    async def fake_multi(prompt):
        assert "[CI_REMEDIATION]" in prompt
        return "Kök neden: VALUE = 1 sabiti artık 2 olmalı."

    a.code = _Code()
    a.llm = _LLM()
    a._try_multi_agent = fake_multi

    trigger = ExternalTrigger(
        trigger_id="tr-ci-safe",
        source="webhook:github:ci_failure",
        event_name="ci_pipeline_failed",
        payload={
            "ci_failure": True,
            "repo": "acme/sidar",
            "workflow_name": "CI",
            "pipeline_id": 91,
            "branch": "main",
            "base_branch": "main",
            "failure_summary": "AssertionError in main.py",
            "log_excerpt": "AssertionError: expected VALUE = 2 in main.py",
        },
    )
    record = asyncio.run(a.handle_external_trigger(trigger))

    assert record["remediation"]["self_heal_execution"]["status"] == "applied"
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert record["remediation"]["remediation_loop"]["status"] == "applied"


def test_handle_external_trigger_reverts_self_heal_when_validation_fails(tmp_path):
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)
    a.cfg = SimpleNamespace(
        AI_PROVIDER="ollama",
        CODING_MODEL="m",
        ACCESS_LEVEL="full",
        BASE_DIR=tmp_path,
        ENABLE_AUTONOMOUS_SELF_HEAL=True,
        SELF_HEAL_MAX_PATCHES=2,
    )
    target = tmp_path / "main.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    class _Code:
        def read_file(self, path, line_numbers=False):
            return True, (tmp_path / path).read_text(encoding="utf-8")

        def patch_file(self, path, target_block, replacement_block):
            file_path = tmp_path / path
            content = file_path.read_text(encoding="utf-8")
            file_path.write_text(content.replace(target_block, replacement_block, 1), encoding="utf-8")
            return True, "patched"

        def write_file(self, path, content, validate=False):
            (tmp_path / path).write_text(content, encoding="utf-8")
            return True, "written"

        def run_shell_in_sandbox(self, command, cwd):
            return False, f"failed:{command}"

    class _LLM:
        async def chat(self, **kwargs):
            return json.dumps(
                {
                    "summary": "VALUE sabitini düzelt",
                    "confidence": "medium",
                    "operations": [
                        {
                            "action": "patch",
                            "path": "main.py",
                            "target": "VALUE = 1",
                            "replacement": "VALUE = 2",
                        }
                    ],
                    "validation_commands": ["python -m pytest"],
                }
            )

    async def fake_multi(_prompt):
        return "Kök neden: VALUE = 1 sabiti artık 2 olmalı."

    a.code = _Code()
    a.llm = _LLM()
    a._try_multi_agent = fake_multi

    trigger = ExternalTrigger(
        trigger_id="tr-ci-revert",
        source="webhook:github:ci_failure",
        event_name="ci_pipeline_failed",
        payload={
            "ci_failure": True,
            "repo": "acme/sidar",
            "workflow_name": "CI",
            "pipeline_id": 92,
            "branch": "main",
            "base_branch": "main",
            "failure_summary": "AssertionError in main.py",
            "log_excerpt": "AssertionError: expected VALUE = 2 in main.py",
        },
    )
    record = asyncio.run(a.handle_external_trigger(trigger))

    assert record["remediation"]["self_heal_execution"]["status"] == "reverted"
    assert target.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_handle_external_trigger_records_self_heal_disabled_state(tmp_path):
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)
    a.cfg = SimpleNamespace(
        AI_PROVIDER="ollama",
        CODING_MODEL="m",
        ACCESS_LEVEL="full",
        BASE_DIR=tmp_path,
        ENABLE_AUTONOMOUS_SELF_HEAL=False,
        SELF_HEAL_MAX_PATCHES=2,
    )

    class _LLM:
        async def chat(self, **kwargs):
            raise AssertionError("self-heal plan should not be requested when disabled")

    async def fake_multi(_prompt):
        return "Kök neden: VALUE = 1 sabiti artık 2 olmalı."

    a.llm = _LLM()
    a._try_multi_agent = fake_multi

    trigger = ExternalTrigger(
        trigger_id="tr-ci-disabled",
        source="webhook:github:ci_failure",
        event_name="ci_pipeline_failed",
        payload={
            "ci_failure": True,
            "repo": "acme/sidar",
            "workflow_name": "CI",
            "pipeline_id": 93,
            "branch": "main",
            "base_branch": "main",
            "failure_summary": "AssertionError in main.py",
            "log_excerpt": "AssertionError: expected VALUE = 2 in main.py",
        },
    )
    record = asyncio.run(a.handle_external_trigger(trigger))

    assert record["status"] == "success"
    assert record["remediation"]["self_heal_execution"]["status"] == "disabled"


def test_execute_self_heal_plan_blocks_when_no_safe_validation_commands(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)

    class _Code:
        def read_file(self, path, line_numbers=False):
            return True, (tmp_path / path).read_text(encoding="utf-8")

        def patch_file(self, path, target_block, replacement_block):
            raise AssertionError("patch should not run without validation commands")

        def write_file(self, path, content, validate=False):
            (tmp_path / path).write_text(content, encoding="utf-8")
            return True, "written"

        def run_shell_in_sandbox(self, command, cwd):
            raise AssertionError("sandbox should not run without validation commands")

    a.code = _Code()
    (tmp_path / "main.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = asyncio.run(
        a._execute_self_heal_plan(
            remediation_loop={"validation_commands": []},
            plan={
                "summary": "unsafe",
                "confidence": "low",
                "operations": [
                    {
                        "action": "patch",
                        "path": "main.py",
                        "target": "VALUE = 1",
                        "replacement": "VALUE = 2",
                    }
                ],
                "validation_commands": [],
            },
        )
    )

    assert result["status"] == "blocked"
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_handle_external_trigger_correlates_action_feedback_with_prior_record():
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)

    async def fake_multi(prompt):
        if prompt.startswith("[ACTION FEEDBACK]"):
            assert '"correlation_id": "fed-1"' in prompt
            return "Dış sistem action feedback işlendi."
        return "İlk federation görev özeti."

    a._try_multi_agent = fake_multi

    first = asyncio.run(
        a.handle_external_trigger(
            {
                "trigger_id": "tr-fed-1",
                "source": "federation:autogen",
                "event_name": "federation_task",
                "payload": {"kind": "federation_task", "task_id": "fed-1", "correlation_id": "fed-1"},
                "meta": {"correlation_id": "fed-1"},
            }
        )
    )
    second = asyncio.run(
        a.handle_external_trigger(
            {
                "trigger_id": "fb-1",
                "source": "federation:autogen:action_feedback",
                "event_name": "action_feedback",
                "payload": {
                    "kind": "action_feedback",
                    "feedback_id": "fb-1",
                    "source_system": "autogen",
                    "source_agent": "planner",
                    "action_name": "open_pr",
                    "status": "success",
                    "summary": "PR açıldı",
                    "related_task_id": "fed-1",
                    "correlation_id": "fed-1",
                },
                "meta": {"correlation_id": "fed-1"},
            }
        )
    )

    assert first["correlation"]["correlation_id"] == "fed-1"
    assert second["correlation"]["correlation_id"] == "fed-1"
    assert second["correlation"]["matched_records"] == 1
    assert second["correlation"]["related_trigger_ids"] == ["tr-fed-1"]


def test_build_trigger_prompt_prefers_explicit_federation_prompt():
    trigger = ExternalTrigger(trigger_id="tr-fed-prompt", source="federation", event_name="federation_task")

    prompt = SidarAgent._build_trigger_prompt(
        trigger,
        {
            "kind": "federation_task",
            "task_id": "fed-2",
            "goal": "ignored",
            "federation_prompt": "Doğrudan federation promptunu kullan",
        },
        None,
    )

    assert prompt == "Doğrudan federation promptunu kullan"


def test_build_trigger_correlation_matches_related_task_id_without_other_links():
    a = _make_agent_for_runtime()
    a._autonomy_history = [
        {
            "trigger_id": "older-1",
            "source": "federation:x",
            "status": "done",
            "payload": {"task_id": "task-7"},
            "meta": {},
            "correlation": {"correlation_id": ""},
        }
    ]

    correlation = a._build_trigger_correlation(
        ExternalTrigger(trigger_id="new-related", source="external", event_name="feedback"),
        {"related_task_id": "task-7"},
    )

    assert correlation["matched_records"] == 1
    assert correlation["related_trigger_ids"] == ["older-1"]
    assert correlation["latest_related_status"] == "done"


def test_build_trigger_correlation_matches_related_trigger_and_task_and_deduplicates():
    a = _make_agent_for_runtime()
    a._autonomy_history = [
        {
            "trigger_id": "dup-1",
            "source": "federation:a",
            "status": "done",
            "payload": {"task_id": "task-1"},
            "meta": {},
            "correlation": {"correlation_id": ""},
        },
        {
            "trigger_id": "dup-1",
            "source": "federation:a",
            "status": "done",
            "payload": {"task_id": "task-1"},
            "meta": {},
            "correlation": {"correlation_id": ""},
        },
        {
            "trigger_id": "other-2",
            "source": "federation:b",
            "status": "queued",
            "payload": {"task_id": "task-2"},
            "meta": {},
            "correlation": {"correlation_id": ""},
        },
    ]

    correlation = a._build_trigger_correlation(
        ExternalTrigger(trigger_id="new-1", source="external", event_name="feedback"),
        {"related_trigger_id": "dup-1", "related_task_id": "task-2"},
    )

    assert correlation["matched_records"] == 2
    assert correlation["related_trigger_ids"] == ["other-2", "dup-1"]
    assert correlation["related_sources"] == ["federation:b", "federation:a"]
    assert correlation["latest_related_status"] == "queued"


def test_build_trigger_correlation_skips_unrelated_history_entries():
    a = _make_agent_for_runtime()
    a._autonomy_history = [
        {
            "trigger_id": "noise-1",
            "source": "cron",
            "status": "ignored",
            "payload": {"task_id": "task-x"},
            "meta": {"correlation_id": "corr-x"},
            "correlation": {"correlation_id": "corr-x"},
        },
        {
            "trigger_id": "match-1",
            "source": "federation:c",
            "status": "done",
            "payload": {"task_id": "task-9"},
            "meta": {},
            "correlation": {"correlation_id": ""},
        },
    ]

    correlation = a._build_trigger_correlation(
        ExternalTrigger(trigger_id="new-task", source="external", event_name="feedback"),
        {"related_task_id": "task-9"},
    )

    assert correlation["matched_records"] == 1
    assert correlation["related_trigger_ids"] == ["match-1"]
    assert correlation["related_sources"] == ["federation:c"]


def test_handle_external_trigger_ci_empty_output_skips_self_heal_attempt():
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)
    calls = {"heal": 0}

    async def _blank_multi(_prompt):
        return "   "

    async def _heal(**_kwargs):
        calls["heal"] += 1

    a._try_multi_agent = _blank_multi
    a._attempt_autonomous_self_heal = _heal

    record = asyncio.run(
        a.handle_external_trigger(
            ExternalTrigger(
                trigger_id="tr-empty-ci",
                source="webhook",
                event_name="workflow_run",
                payload={"kind": "workflow_run", "workflow_name": "CI", "task_id": "ci-1"},
            )
        )
    )

    assert record["status"] == "empty"
    assert "remediation" not in record
    assert calls["heal"] == 0


def test_handle_external_trigger_marks_empty_output_when_multi_agent_returns_blank():
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)

    async def _blank_multi(_prompt):
        return "   "

    a._try_multi_agent = _blank_multi

    record = asyncio.run(
        a.handle_external_trigger(
            ExternalTrigger(trigger_id="tr-empty", source="cron", event_name="tick", payload={"job": "noop"})
        )
    )

    assert record["status"] == "empty"
    assert record["summary"] == "⚠ Proaktif tetik işlendikten sonra boş çıktı üretildi."
    assert a.memory.items[-1] == ("assistant", "⚠ Proaktif tetik işlendikten sonra boş çıktı üretildi.")


def test_handle_external_trigger_marks_failed_status_when_multi_agent_raises():
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)

    async def _boom(_prompt):
        raise RuntimeError("llm unavailable")

    a._try_multi_agent = _boom

    record = asyncio.run(
        a.handle_external_trigger(
            ExternalTrigger(trigger_id="tr-fail", source="webhook", event_name="deploy_failed", payload={"job": "deploy"})
        )
    )

    assert record["status"] == "failed"
    assert record["summary"] == "⚠ Proaktif tetik işlenemedi: llm unavailable"
    assert a.memory.items[-1] == ("assistant", "⚠ Proaktif tetik işlenemedi: llm unavailable")



def test_handle_external_trigger_records_self_heal_exception_without_failing_trigger():
    a = _make_agent_for_runtime()
    a.initialize = lambda: asyncio.sleep(0)

    async def _multi(_prompt):
        return "ci teşhisi"

    async def _heal(**_kwargs):
        raise RuntimeError("self heal boom")

    a._try_multi_agent = _multi
    a._attempt_autonomous_self_heal = _heal

    record = asyncio.run(
        a.handle_external_trigger(
            ExternalTrigger(
                trigger_id="tr-self-heal-fail",
                source="webhook:github",
                event_name="workflow_run",
                payload={"kind": "workflow_run", "workflow_name": "CI", "task_id": "ci-77"},
            )
        )
    )

    assert record["status"] == "success"
    assert record["summary"] == "ci teşhisi"
    assert record["remediation"]["self_heal_execution"]["status"] == "failed"
    assert "self heal boom" in record["remediation"]["self_heal_execution"]["summary"]



def test_set_access_level_clear_memory_and_status():
    a = _make_agent_for_runtime()

    class _Sec:
        level_name = "sandbox"

        def set_level(self, lvl):
            if lvl == "full":
                self.level_name = "full"
                return True
            return False

    class _Mem:
        def __init__(self):
            self.items = []

        async def add(self, role, text):
            self.items.append((role, text))

        async def clear(self):
            self.items.clear()

        def __len__(self):
            return 3

    a.security = _Sec()
    a.memory = _Mem()

    changed = asyncio.run(a.set_access_level("full"))
    assert "güncellendi" in changed
    unchanged = asyncio.run(a.set_access_level("restricted"))
    assert "zaten" in unchanged

    assert "temizlendi" in asyncio.run(a.clear_memory())

    status = a.status()
    assert "SidarAgent" in status
    assert "Sağlayıcı" in status
def test_build_context_and_instruction_file_cache(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        PROJECT_NAME="Sidar",
        VERSION="2.0",
        BASE_DIR=tmp_path,
        AI_PROVIDER="ollama",
        CODING_MODEL="code-m",
        TEXT_MODEL="text-m",
        OLLAMA_URL="http://localhost:11434",
        ACCESS_LEVEL="sandbox",
        USE_GPU=False,
        GPU_INFO="none",
        CUDA_VERSION="N/A",
        GITHUB_REPO="owner/repo",
        GEMINI_MODEL="gemini",
    )
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 2})
    a.github = SimpleNamespace(is_available=lambda: True)
    a.web = SimpleNamespace(is_available=lambda: True)
    a.docs = SimpleNamespace(status=lambda: "docs-ok")
    class _Todo:
        def __len__(self):
            return 1

        def list_tasks(self):
            return "- t1"

    a.todo = _Todo()
    a.memory = SimpleNamespace(get_last_file=lambda: "README.md")
    a.security = SimpleNamespace(level_name="sandbox")

    (tmp_path / "SIDAR.md").write_text("main rules", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("sub rules", encoding="utf-8")

    loaded = a._load_instruction_files()
    assert "SIDAR.md" in loaded and "CLAUDE.md" in loaded
    cached = a._load_instruction_files()
    assert cached == loaded

    ctx = asyncio.run(a._build_context())
    assert "[Proje Ayarları" in ctx
    assert "[Araç Durumu]" in ctx
    assert "[Proje Talimat Dosyaları" in ctx


def test_load_instruction_files_empty_tree_returns_cached_empty(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()

    assert a._load_instruction_files() == ""
    assert a._load_instruction_files() == ""
def test_memory_archive_context_truncation_and_error_fallback():
    a = _make_agent_for_runtime()

    class _Collection:
        def query(self, **kwargs):
            return {
                "documents": [["x" * 900, "short note"]],
                "metadatas": [[{"source": "memory_archive", "title": "A"}, {"source": "memory_archive", "title": "B"}]],
                "distances": [[0.1, 0.2]],
            }

    a.docs = SimpleNamespace(collection=_Collection())
    text = a._get_memory_archive_context_sync("q", top_k=3, min_score=0.1, max_chars=800)
    assert "[Geçmiş Sohbet Arşivinden İlgili Notlar]" in text
    assert "..." in text

    class _BrokenCollection:
        def query(self, **kwargs):
            raise RuntimeError("db down")

    a.docs = SimpleNamespace(collection=_BrokenCollection())
    assert a._get_memory_archive_context_sync("q", top_k=1, min_score=0.1, max_chars=300) == ""


def test_summarize_memory_success_and_exception_paths(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm")

    class _Mem:
        def __init__(self):
            self.summary = None

        async def get_history(self):
            return [
                {"role": "user", "content": "u1", "timestamp": 1},
                {"role": "assistant", "content": "a1", "timestamp": 2},
                {"role": "user", "content": "u2", "timestamp": 3},
                {"role": "assistant", "content": "a2", "timestamp": 4},
            ]

        async def apply_summary(self, s):
            self.summary = s

    a.memory = _Mem()

    class _Docs:
        def __init__(self):
            self.called = 0

        def add_document(self, **kwargs):
            self.called += 1

    docs = _Docs()
    a.docs = docs

    class _LLM:
        async def chat(self, **kwargs):
            return "özet"

    a.llm = _LLM()
    asyncio.run(a._summarize_memory())
    assert docs.called == 1
    assert a.memory.summary == "özet"

    class _BrokenDocs:
        def add_document(self, **kwargs):
            raise RuntimeError("docs fail")

    class _BrokenLLM:
        async def chat(self, **kwargs):
            raise RuntimeError("llm fail")

    a.docs = _BrokenDocs()
    a.llm = _BrokenLLM()
    # sadece exception path'leri çalışsın, raise etmesin
    asyncio.run(a._summarize_memory())


def test_summarize_memory_logs_vector_archive_success(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(TEXT_MODEL="tm", CODING_MODEL="cm")

    class _Mem:
        def __init__(self):
            self.summary = None

        async def get_history(self):
            return [
                {"role": "user", "content": "u1", "timestamp": 1},
                {"role": "assistant", "content": "a1", "timestamp": 2},
                {"role": "user", "content": "u2", "timestamp": 3},
                {"role": "assistant", "content": "a2", "timestamp": 4},
            ]

        async def apply_summary(self, s):
            self.summary = s

    class _Docs:
        def __init__(self):
            self.calls = []

        async def add_document(self, **kwargs):
            self.calls.append(kwargs)
            return "doc-1"

    class _LLM:
        async def chat(self, **kwargs):
            return "özet"

    infos = []
    monkeypatch.setattr(SA_MOD.logger, "info", lambda msg, *args: infos.append(msg % args if args else msg))

    a.memory = _Mem()
    a.docs = _Docs()
    a.llm = _LLM()

    asyncio.run(a._summarize_memory())

    assert a.docs.calls and a.docs.calls[0]["source"] == "memory_archive"
    assert a.memory.summary == "özet"
    assert any("RAG (Vektör) belleğine arşivlendi" in msg for msg in infos)


def test_instruction_file_loader_stat_and_read_failures_and_summarize_short_history(tmp_path, monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()

    good = tmp_path / "SIDAR.md"
    good.write_text("ok", encoding="utf-8")
    bad = tmp_path / "CLAUDE.md"
    bad.write_text("", encoding="utf-8")

    real_read = Path.read_text

    def _read(self, *args, **kwargs):
        if self.name == "SIDAR.md":
            raise OSError("read fail")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read)
    assert a._load_instruction_files() == ""

    b = _make_agent_for_runtime()

    async def _short_history():
        return [{"role": "u", "content": "x"}] * 3

    b.memory = SimpleNamespace(get_history=_short_history)
    asyncio.run(b._summarize_memory())
def test_get_memory_archive_context_sync_filters_and_limits():
    a = _make_agent_for_runtime()

    class _Collection:
        def query(self, **kwargs):
            return {
                "documents": [["", "uygun metin", "atla"]],
                "metadatas": [[{"source": "memory_archive", "title": "boş"}, {"source": "memory_archive", "title": "başlık"}, {"source": "other"}]],
                "distances": [[0.1, 0.2, 0.1]],
            }

    a.docs = SimpleNamespace(collection=_Collection())
    txt = a._get_memory_archive_context_sync("q", top_k=2, min_score=0.5, max_chars=1000)
    assert "Geçmiş Sohbet Arşivinden" in txt
    assert "başlık" in txt
    assert "atla" not in txt


def test_get_memory_archive_context_sync_empty_and_query_error():
    a = _make_agent_for_runtime()
    a.docs = SimpleNamespace(collection=None)
    assert a._get_memory_archive_context_sync("q", 1, 0.1, 300) == ""

    class _BadCollection:
        def query(self, **kwargs):
            raise RuntimeError("db err")

    a.docs = SimpleNamespace(collection=_BadCollection())
    assert a._get_memory_archive_context_sync("q", 1, 0.1, 300) == ""
def test_archive_context_min_score_max_chars_and_empty_selected():
    a = _make_agent_for_runtime()

    class _ColLow:
        def query(self, **kwargs):
            return {
                'documents': [['d1']],
                'metadatas': [[{'source': 'memory_archive', 'title': 'T'}]],
                'distances': [[0.95]],
            }

    a.docs = SimpleNamespace(collection=_ColLow())
    out_low = a._get_memory_archive_context_sync('q', top_k=3, min_score=0.2, max_chars=1000)
    assert out_low == ''

    class _ColChars:
        def query(self, **kwargs):
            return {
                'documents': [['x' * 300, 'ikinci not']],
                'metadatas': [[
                    {'source': 'memory_archive', 'title': 'A'},
                    {'source': 'memory_archive', 'title': 'B'},
                ]],
                'distances': [[0.1, 0.1]],
            }

    a.docs = SimpleNamespace(collection=_ColChars())
    out_chars = a._get_memory_archive_context_sync('q', top_k=3, min_score=0.1, max_chars=40)
    assert out_chars == '' or 'Geçmiş Sohbet' in out_chars


def test_load_instruction_files_stat_error_is_swallowed(tmp_path, monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()

    f = tmp_path / 'SIDAR.md'
    f.write_text('kural', encoding='utf-8')

    import pathlib
    real_stat = pathlib.Path.stat
    real_rglob = pathlib.Path.rglob

    def _fake_rglob(self, pattern):
        if self == tmp_path and pattern == 'SIDAR.md':
            return [f]
        if self == tmp_path and pattern == 'CLAUDE.md':
            return []
        return list(real_rglob(self, pattern))

    def _fake_is_file(self):
        if self == f:
            return True
        return pathlib.Path.exists(self)

    def _boom_stat(self):
        if self.name == 'SIDAR.md':
            raise OSError('stat fail')
        return real_stat(self)

    monkeypatch.setattr(pathlib.Path, 'rglob', _fake_rglob)
    monkeypatch.setattr(pathlib.Path, 'is_file', _fake_is_file)
    monkeypatch.setattr(pathlib.Path, 'stat', _boom_stat)
    out = a._load_instruction_files()
    assert 'SIDAR.md' in out and 'kural' in out


def test_load_instruction_files_permission_error_on_one_file_is_ignored(tmp_path, monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._instructions_lock = threading.Lock()

    readable = tmp_path / "SIDAR.md"
    readable.write_text("root rules", encoding="utf-8")
    denied = tmp_path / "CLAUDE.md"
    denied.write_text("secret", encoding="utf-8")

    real_read_text = Path.read_text

    def _read_text(self, *args, **kwargs):
        if self.name == "CLAUDE.md":
            raise PermissionError("permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)

    out = a._load_instruction_files()
    assert "SIDAR.md" in out
    assert "root rules" in out
    assert "secret" not in out

def test_tool_docs_search_handles_sync_result_without_pipe_mode(monkeypatch):
    agent = SidarAgent.__new__(SidarAgent)

    class _Docs:
        def search(self, query, _none, mode, session_id):
            assert query == "needle"
            assert mode == "auto"
            assert session_id == "global"
            return True, "sync-found"

    async def passthrough(func, *args):
        return func(*args)

    agent.docs = _Docs()
    monkeypatch.setattr(asyncio, "to_thread", passthrough)

    assert asyncio.run(agent._tool_docs_search("needle")) == "sync-found"


def test_try_multi_agent_always_uses_supervisor(monkeypatch):
    mod = _load_sidar_agent_module()

    class _Sup:
        async def run_task(self, prompt: str) -> str:
            return f"ok:{prompt}"

    a = SimpleNamespace(
        cfg=SimpleNamespace(),
        _supervisor=_Sup(),
    )

    out1 = asyncio.run(mod.SidarAgent._try_multi_agent(a, "gorev1"))
    out2 = asyncio.run(mod.SidarAgent._try_multi_agent(a, "gorev2"))

    assert out1 == "ok:gorev1"
    assert out2 == "ok:gorev2"


def test_try_multi_agent_uses_supervisor_when_enabled(monkeypatch):
    mod = _load_sidar_agent_module()

    class _Sup:
        async def run_task(self, prompt: str) -> str:
            return f"ok:{prompt}"

    a = SimpleNamespace(
        cfg=SimpleNamespace(),
        _supervisor=_Sup(),
    )

    out = asyncio.run(mod.SidarAgent._try_multi_agent(a, "gorev"))
    assert out == "ok:gorev"


def test_try_multi_agent_returns_warning_when_supervisor_returns_none(monkeypatch):
    mod = _load_sidar_agent_module()

    class _Sup:
        async def run_task(self, _prompt: str):
            return None

    a = SimpleNamespace(
        cfg=SimpleNamespace(),
        _supervisor=_Sup(),
    )

    out = asyncio.run(mod.SidarAgent._try_multi_agent(a, "gorev"))
    assert "geçerli bir çıktı" in out


def test_tool_subtask_records_metrics_for_success_validation_and_tool_failure(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=3, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"t1","tool":"echo","argument":"ok"}',
        '{"thought":"t2","tool":"missing-argument"}',
        '{"thought":"t3","tool":"explode","argument":"boom"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            assert kwargs["model"] == "tm"
            return next(replies)

    async def _exec(tool, arg):
        if tool == "explode":
            raise RuntimeError(f"tool failed:{arg}")
        return f"{tool}:{arg}"

    calls = []

    class _Collector:
        def record_step(self, agent_name, step_name, target, status, duration):
            calls.append((agent_name, step_name, target, status, duration >= 0))

    agent_metrics_mod = types.ModuleType("core.agent_metrics")
    agent_metrics_mod.get_agent_metrics_collector = lambda: _Collector()
    monkeypatch.setitem(sys.modules, "core.agent_metrics", agent_metrics_mod)

    a.llm = _LLM()
    a._execute_tool = _exec

    out = asyncio.run(a._tool_subtask("metric coverage"))

    assert "Maksimum adım" in out
    assert ("sidar_agent", "tool_execution", "echo", "success", True) in calls
    assert ("sidar_agent", "llm_decision", "tm", "failed", True) in calls
    assert ("sidar_agent", "tool_execution", "explode", "failed", True) in calls


def test_tool_subtask_metrics_use_coding_model_fallback_when_text_model_missing(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=1, CODING_MODEL="cm")

    class _LLM:
        async def chat(self, **kwargs):
            assert kwargs["model"] == "cm"
            raise RuntimeError("llm unavailable")

    calls = []

    class _Collector:
        def record_step(self, agent_name, step_name, target, status, duration):
            calls.append((agent_name, step_name, target, status, duration >= 0))

    agent_metrics_mod = types.ModuleType("core.agent_metrics")
    agent_metrics_mod.get_agent_metrics_collector = lambda: _Collector()
    monkeypatch.setitem(sys.modules, "core.agent_metrics", agent_metrics_mod)

    a.llm = _LLM()
    a._execute_tool = lambda *_args, **_kwargs: asyncio.sleep(0)

    out = asyncio.run(a._tool_subtask("fallback model testi"))

    assert "Maksimum adım" in out
    assert calls == [("sidar_agent", "llm_decision", "cm", "failed", True)]


def test_memory_archive_context_stops_at_top_k_break():
    a = _make_agent_for_runtime()

    class _Collection:
        def query(self, **kwargs):
            return {
                "documents": [["ilk belge", "ikinci belge"]],
                "metadatas": [[
                    {"source": "memory_archive", "title": "T1"},
                    {"source": "memory_archive", "title": "T2"},
                ]],
                "distances": [[0.1, 0.2]],
            }

    a.docs = SimpleNamespace(collection=_Collection())

    out = a._get_memory_archive_context_sync("q", top_k=1, min_score=0.1, max_chars=2000)
    assert "Geçmiş Sohbet Arşivinden İlgili Notlar" in out
    assert "T1" in out
    assert "T2" not in out


def test_tool_subtask_validation_error_and_tool_exception_paths():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"eksik","tool":"list_dir"}',
        '{"thought":"done","tool":"final_answer","argument":"kurtarıldı"}',
    ])

    class _LLMValidation:
        async def chat(self, **kwargs):
            return next(replies)

    async def _should_not_run(_tool, _arg):
        raise AssertionError("tool should not execute on schema failure")

    a.llm = _LLMValidation()
    a._execute_tool = _should_not_run

    out = asyncio.run(a._tool_subtask("şema testi"))
    assert out == "✓ Alt Görev Tamamlandı: kurtarıldı"

    a2 = _make_agent_for_runtime()
    a2.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")
    replies2 = iter([
        '{"thought":"t","tool":"dangerous","argument":"bad-param"}',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])

    class _LLMToolError:
        async def chat(self, **kwargs):
            return next(replies2)

    calls = []

    async def _boom(tool, arg):
        calls.append((tool, arg))
        raise RuntimeError("unexpected db response")

    a2.llm = _LLMToolError()
    a2._execute_tool = _boom

    out2 = asyncio.run(a2._tool_subtask("araç hatası"))
    assert out2 == "✓ Alt Görev Tamamlandı: tamam"
    assert calls == [("dangerous", "bad-param")]


def test_tool_subtask_invalid_tool_call_records_failed_metric_and_recovers(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"eksik alan","tool":"list_dir"}',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            assert kwargs["model"] == "tm"
            return next(replies)

    calls = []

    class _Collector:
        def record_step(self, agent_name, step_name, target, status, duration):
            calls.append((agent_name, step_name, target, status, duration >= 0))

    agent_metrics_mod = types.ModuleType("core.agent_metrics")
    agent_metrics_mod.get_agent_metrics_collector = lambda: _Collector()
    monkeypatch.setitem(sys.modules, "core.agent_metrics", agent_metrics_mod)

    a.llm = _LLM()
    a._execute_tool = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("tool should not run on invalid tool call"))

    out = asyncio.run(a._tool_subtask("invalid tool call"))

    assert out == "✓ Alt Görev Tamamlandı: tamam"
    assert ("sidar_agent", "llm_decision", "tm", "failed", True) in calls



def test_tool_subtask_validation_error_without_metrics_recovers_to_final_answer(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"eksik alan","tool":"list_dir"}',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            return next(replies)

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "core.agent_metrics":
            raise ImportError("metrics unavailable")
        return real_import(name, globals, locals, fromlist, level)

    real_import = __import__
    monkeypatch.setattr("builtins.__import__", _blocked_import)

    a.llm = _LLM()
    a._execute_tool = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("tool should not run on invalid schema"))

    out = asyncio.run(a._tool_subtask("metricsiz şema hatası"))

    assert out == "✓ Alt Görev Tamamlandı: tamam"



def test_tool_subtask_tool_exception_without_metrics_recovers_to_final_answer(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"t1","tool":"list_dir","argument":"."}',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            return next(replies)

    async def _fail(_tool, _arg):
        raise RuntimeError("tool patladı")

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "core.agent_metrics":
            raise ImportError("metrics unavailable")
        return real_import(name, globals, locals, fromlist, level)

    real_import = __import__
    monkeypatch.setattr("builtins.__import__", _blocked_import)

    a.llm = _LLM()
    a._execute_tool = _fail

    out = asyncio.run(a._tool_subtask("metricsiz araç hatası"))

    assert out == "✓ Alt Görev Tamamlandı: tamam"


def test_tool_subtask_normalizes_tool_name_before_dispatch():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"t","tool":"  LiSt_DiR  ","argument":"."}',
        '{"thought":"done","tool":" FINAL_ANSWER ","argument":"tamam"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            return next(replies)

    calls = []

    async def _exec(tool, arg):
        calls.append((tool, arg))
        return f"ok:{tool}:{arg}"

    a.llm = _LLM()
    a._execute_tool = _exec

    out = asyncio.run(a._tool_subtask("normalize araç adı"))

    assert out == "✓ Alt Görev Tamamlandı: tamam"
    assert calls == [("list_dir", ".")]



def test_tool_subtask_invalid_json_falls_back_to_general_failure_then_recovers():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            return next(replies)

    a.llm = _LLM()
    a._execute_tool = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("tool should not run"))

    out = asyncio.run(a._tool_subtask("bozuk json"))

    assert out == "✓ Alt Görev Tamamlandı: tamam"


def test_tool_subtask_returns_max_steps_after_non_string_llm_output():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=1, TEXT_MODEL="tm", CODING_MODEL="cm")

    class _LLM:
        async def chat(self, **kwargs):
            return {"tool": "list_dir"}

    a.llm = _LLM()
    a._execute_tool = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not run"))

    out = asyncio.run(a._tool_subtask("ham çıktı"))
    assert "Maksimum adım sınırına ulaşıldı" in out


def test_tool_subtask_returns_max_steps_after_repeated_tool_failures():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"t1","tool":"list_dir","argument":"."}',
        '{"thought":"t2","tool":"read_file","argument":"missing.txt"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            return next(replies)

    async def _fail(_tool, _arg):
        raise RuntimeError("tool unavailable")

    a.llm = _LLM()
    a._execute_tool = _fail

    out = asyncio.run(a._tool_subtask("araç limiti testi"))

    assert out == "✗ Maksimum adım sınırına ulaşıldı. Alt görev tamamlanamadı."


def test_tool_subtask_continues_when_metrics_import_is_unavailable(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    class _LLM:
        async def chat(self, **kwargs):
            return '{"thought":"done","tool":"final_answer","argument":"tamam"}'

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "core.agent_metrics":
            raise ImportError("metrics unavailable")
        return real_import(name, globals, locals, fromlist, level)

    real_import = __import__
    a.llm = _LLM()
    a._execute_tool = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("tool should not run"))

    monkeypatch.setattr(__import__("builtins"), "__import__", _blocked_import)

    out = asyncio.run(a._tool_subtask("metriksiz alt görev"))
    assert out == "✓ Alt Görev Tamamlandı: tamam"


def test_tool_subtask_uses_tool_result_feedback_when_metrics_import_is_unavailable(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=2, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"t","tool":"list_dir","argument":"."}',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])
    feedback_messages = []

    class _LLM:
        async def chat(self, **kwargs):
            feedback_messages.append(kwargs["messages"][0]["content"])
            return next(replies)

    async def _exec(tool, arg):
        assert (tool, arg) == ("list_dir", ".")
        return "ok:list_dir:."

    def _blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "core.agent_metrics":
            raise ImportError("metrics unavailable")
        return real_import(name, globals, locals, fromlist, level)

    real_import = __import__
    a.llm = _LLM()
    a._execute_tool = _exec

    monkeypatch.setattr(__import__("builtins"), "__import__", _blocked_import)

    out = asyncio.run(a._tool_subtask("araç geri bildirimi"))

    assert out == "✓ Alt Görev Tamamlandı: tamam"
    assert feedback_messages == ["araç geri bildirimi", "Araç sonucu: ok:list_dir:."]


def test_tool_subtask_empty_and_execute_tool_then_final_answer():
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=4, TEXT_MODEL="tm", CODING_MODEL="cm")

    assert "Alt görev belirtilmedi" in asyncio.run(a._tool_subtask("   "))

    replies = iter([
        '{"thought":"t","tool":"list_dir","argument":"."}',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            return next(replies)

    calls = {"n": 0}

    async def _exec(tool, arg):
        calls["n"] += 1
        return f"ok:{tool}:{arg}"

    a.llm = _LLM()
    a._execute_tool = _exec

    out = asyncio.run(a._tool_subtask("alt görev"))
    assert out == "✓ Alt Görev Tamamlandı: tamam"
    assert calls["n"] == 1


def test_tool_subtask_records_llm_and_tool_step_metrics(monkeypatch):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(SUBTASK_MAX_STEPS=3, TEXT_MODEL="tm", CODING_MODEL="cm")

    replies = iter([
        '{"thought":"t","tool":"list_dir","argument":"."}',
        '{"thought":"done","tool":"final_answer","argument":"tamam"}',
    ])

    class _LLM:
        async def chat(self, **kwargs):
            return next(replies)

    metrics_calls = []

    class _Collector:
        def record_step(self, agent, step, target, status, duration_s):
            metrics_calls.append((agent, step, target, status, duration_s))

    async def _exec(tool, arg):
        return f"ok:{tool}:{arg}"

    a.llm = _LLM()
    a._execute_tool = _exec

    metrics_mod = types.ModuleType("core.agent_metrics")
    metrics_mod.get_agent_metrics_collector = lambda: _Collector()
    monkeypatch.setitem(sys.modules, "core.agent_metrics", metrics_mod)

    out = asyncio.run(a._tool_subtask("metrikli alt görev"))

    assert out == "✓ Alt Görev Tamamlandı: tamam"
    assert any(call[1] == "llm_decision" and call[2] == "tm" and call[3] == "success" for call in metrics_calls)
    assert any(call[1] == "tool_execution" and call[2] == "list_dir" and call[3] == "success" for call in metrics_calls)


def test_tool_github_smart_pr_success_branch_returns_created_message():
    a = _make_agent_for_runtime()

    class _Code:
        def run_shell(self, cmd):
            mapping = {
                "git branch --show-current": (True, "feat-1\n"),
                "git status --short": (True, " M a.py"),
                "git diff --stat HEAD": (True, "stat"),
                "git diff --no-color HEAD": (True, "diff"),
                "git log --oneline main..HEAD": (True, "abc msg"),
            }
            return mapping.get(cmd, (False, ""))

    class _Github:
        def is_available(self):
            return True

        default_branch = "main"

        def create_pull_request(self, title, body, head, base):
            return True, "https://example/pr/1"

    a.code = _Code()
    a.github = _Github()

    out = asyncio.run(a._tool_github_smart_pr("Başlık|||main|||not"))
    assert out == "✓ PR oluşturuldu: https://example/pr/1"

def test_initialize_applies_active_system_prompt_from_memory_db():
    a = _make_agent_for_runtime()
    a._initialized = False
    a._init_lock = asyncio.Lock()
    a.system_prompt = "default"

    class _Prompt:
        prompt_text = "  özel prompt  "

    class _DB:
        async def get_active_prompt(self, _name):
            return _Prompt()

    class _Mem:
        db = _DB()

        async def initialize(self):
            return None

    a.memory = _Mem()
    asyncio.run(a.initialize())
    assert a.system_prompt == "  özel prompt  "


def test_build_context_includes_last_file_for_remote_provider(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        PROJECT_NAME="Sidar",
        VERSION="3.0",
        BASE_DIR=tmp_path,
        AI_PROVIDER="openai",
        CODING_MODEL="code",
        TEXT_MODEL="text",
        OLLAMA_URL="http://localhost:11434",
        ACCESS_LEVEL="full",
        USE_GPU=True,
        GPU_INFO="RTX",
        CUDA_VERSION="12.0",
        GITHUB_REPO="org/repo",
        GEMINI_MODEL="gemini",
    )
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 1})
    a.github = SimpleNamespace(is_available=lambda: True)
    a.web = SimpleNamespace(is_available=lambda: True)
    a.docs = SimpleNamespace(status=lambda: "ok")
    a.security = SimpleNamespace(level_name="full")
    a.todo = []
    a.memory = SimpleNamespace(get_last_file=lambda: "demo.py")
    a._instructions_lock = threading.Lock()
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._load_instruction_files = lambda: ""

    txt = asyncio.run(a._build_context())
    assert "Son dosya  : demo.py" in txt


def test_build_context_treats_mixed_case_ollama_as_local_provider(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        PROJECT_NAME="Sidar",
        VERSION="3.0",
        BASE_DIR=tmp_path,
        AI_PROVIDER="Ollama",
        CODING_MODEL="code",
        TEXT_MODEL="text",
        OLLAMA_URL="http://localhost:11434",
        ACCESS_LEVEL="full",
        USE_GPU=True,
        GPU_INFO="RTX",
        CUDA_VERSION="12.0",
        GITHUB_REPO="org/repo",
        GEMINI_MODEL="gemini",
        LOCAL_AGENT_CONTEXT_MAX_CHARS=5000,
        LOCAL_INSTRUCTION_MAX_CHARS=5000,
    )
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 1})
    a.github = SimpleNamespace(is_available=lambda: True)
    a.web = SimpleNamespace(is_available=lambda: True)
    a.docs = SimpleNamespace(status=lambda: "ok")
    a.security = SimpleNamespace(level_name="full")
    a.todo = []
    a.memory = SimpleNamespace(get_last_file=lambda: "demo.py")
    a._instructions_lock = threading.Lock()
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._load_instruction_files = lambda: ""

    txt = asyncio.run(a._build_context())
    assert "Coding Modeli: code" in txt
    assert "Text Modeli  : text" in txt
    assert "Gemini Modeli:" not in txt
    assert "Ollama URL" not in txt
    assert "Son dosya  : demo.py" not in txt


def test_build_context_truncates_for_local_provider(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        PROJECT_NAME="Sidar",
        VERSION="3.0",
        BASE_DIR=tmp_path,
        AI_PROVIDER="ollama",
        CODING_MODEL="code",
        TEXT_MODEL="text",
        OLLAMA_URL="http://localhost:11434",
        ACCESS_LEVEL="full",
        USE_GPU=True,
        GPU_INFO="RTX",
        CUDA_VERSION="12.0",
        GITHUB_REPO="org/repo",
        GEMINI_MODEL="gemini",
        LOCAL_AGENT_CONTEXT_MAX_CHARS=300,
        LOCAL_INSTRUCTION_MAX_CHARS=5000,
    )
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 1})
    a.github = SimpleNamespace(is_available=lambda: True)
    a.web = SimpleNamespace(is_available=lambda: True)
    a.docs = SimpleNamespace(status=lambda: "ok")
    a.security = SimpleNamespace(level_name="full")
    a.todo = []
    a.memory = SimpleNamespace(get_last_file=lambda: "demo.py")
    a._instructions_lock = threading.Lock()
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._load_instruction_files = lambda: "X" * 6000

    txt = asyncio.run(a._build_context())
    assert txt.endswith("[Not] Bağlam yerel model için kırpıldı.")


def test_build_context_truncates_instruction_block_before_total_context_limit(tmp_path):
    a = _make_agent_for_runtime()
    a.cfg = SimpleNamespace(
        PROJECT_NAME="Sidar",
        VERSION="3.0",
        BASE_DIR=tmp_path,
        AI_PROVIDER="ollama",
        CODING_MODEL="code",
        TEXT_MODEL="text",
        OLLAMA_URL="http://localhost:11434",
        ACCESS_LEVEL="full",
        USE_GPU=False,
        GPU_INFO="CPU",
        CUDA_VERSION="N/A",
        GITHUB_REPO="org/repo",
        GEMINI_MODEL="gemini",
        LOCAL_AGENT_CONTEXT_MAX_CHARS=8000,
        LOCAL_INSTRUCTION_MAX_CHARS=80,
    )
    a.code = SimpleNamespace(get_metrics=lambda: {"files_read": 1, "files_written": 0})
    a.github = SimpleNamespace(is_available=lambda: False)
    a.web = SimpleNamespace(is_available=lambda: False)
    a.docs = SimpleNamespace(status=lambda: "ok")
    a.security = SimpleNamespace(level_name="full")
    a.todo = []
    a.memory = SimpleNamespace(get_last_file=lambda: None)
    a._instructions_lock = threading.Lock()
    a._instructions_cache = None
    a._instructions_mtimes = {}
    a._load_instruction_files = lambda: "Y" * 1000

    txt = asyncio.run(a._build_context())

    assert "[Not] Talimatlar yerel model bağlam sınırı için kırpıldı." in txt
    assert not txt.endswith("[Not] Bağlam yerel model için kırpıldı.")