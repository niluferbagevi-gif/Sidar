"""Unit tests for ``agent.roles.coder_agent``."""

import importlib
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, create_autospec

import pytest


def _import_coder_module(module_name: str):
    module = importlib.import_module(module_name)
    required_attrs = ("CoderAgent", "BaseAgent", "CodeManager", "SecurityManager")
    if not all(hasattr(module, attr) for attr in required_attrs):
        sys.modules.pop(module_name, None)
        module = importlib.import_module(module_name)
    return module


@pytest.fixture
def coder_module(monkeypatch: pytest.MonkeyPatch):
    """Import ``agent.roles.coder_agent`` with httpx and redis replaced by stub modules."""
    module_name = "agent.roles.coder_agent"
    monkeypatch.setitem(sys.modules, "httpx", ModuleType("httpx"))

    redis_module = ModuleType("redis")
    redis_asyncio = ModuleType("redis.asyncio")
    redis_exceptions = ModuleType("redis.exceptions")
    redis_asyncio.Redis = object
    redis_exceptions.ResponseError = Exception
    redis_module.asyncio = redis_asyncio
    redis_module.exceptions = redis_exceptions
    monkeypatch.setitem(sys.modules, "redis", redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_asyncio)
    monkeypatch.setitem(sys.modules, "redis.exceptions", redis_exceptions)

    return _import_coder_module(module_name)


def test_import_coder_module_reimports_when_required_attrs_are_missing(monkeypatch):
    """Import coder module reimports when required attrs are missing."""
    module_name = "agent.roles.coder_agent"
    imported = ModuleType(module_name)
    reloaded = ModuleType(module_name)
    reloaded.CoderAgent = object
    reloaded.BaseAgent = object
    reloaded.CodeManager = object
    reloaded.SecurityManager = object

    import_calls = []

    def _import(_name):
        import_calls.append(_name)
        return imported if len(import_calls) == 1 else reloaded

    monkeypatch.setattr(importlib, "import_module", _import)
    monkeypatch.setitem(sys.modules, module_name, imported)

    module = _import_coder_module(module_name)
    assert module is reloaded
    assert module_name not in sys.modules or sys.modules[module_name] is not imported
    assert import_calls == [module_name, module_name]


class DummyEvents:
    """Event bus stand-in that records published messages."""

    def __init__(self):
        """Start with no messages."""
        self.messages = []

    async def publish(self, role, message):
        """Record the role and message."""
        self.messages.append((role, message))


def _build_code_manager_mock(code_manager_cls):
    code_manager = create_autospec(code_manager_cls, instance=True, spec_set=True)
    code_manager.read_file.side_effect = lambda path: (True, f"read:{path}")
    code_manager.write_file.side_effect = lambda path, content: (True, f"write:{path}:{content}")
    code_manager.write_file_hitl.side_effect = lambda path, content: (
        True,
        f"write:{path}:{content}",
    )
    code_manager.patch_file.side_effect = lambda path, target, replacement: (
        True,
        f"patch:{path}:{target}->{replacement}",
    )
    code_manager.patch_file_hitl.side_effect = lambda path, target, replacement: (
        True,
        f"patch:{path}:{target}->{replacement}",
    )
    code_manager.execute_code.side_effect = lambda command: (True, f"exec:{command}")
    code_manager.list_directory.side_effect = lambda path: (True, f"list:{path}")
    code_manager.glob_search.side_effect = lambda pattern, base: (True, f"glob:{pattern}:{base}")
    code_manager.grep_files.side_effect = (
        lambda pattern, path, file_glob, case_sensitive=True, context_lines=0, max_results=100: (
            True,
            f"grep:{pattern}:{path}:{file_glob}:{context_lines}",
        )
    )
    code_manager.audit_project.side_effect = lambda path: f"audit:{path}"
    return code_manager


def _build_pkg_manager_mock(pkg_manager_cls):
    pkg_manager = create_autospec(pkg_manager_cls, instance=True, spec_set=True)
    pkg_manager.pypi_info = AsyncMock(
        side_effect=lambda package_name: (True, f"pkg:{package_name}")
    )
    return pkg_manager


def _build_todo_manager_mock(todo_manager_cls):
    todo_manager = create_autospec(todo_manager_cls, instance=True, spec_set=True)
    todo_manager.scan_project_todos.side_effect = lambda directory, _filters: f"todos:{directory}"
    return todo_manager


def test_init_registers_tools(monkeypatch, tmp_path, coder_module):
    """Init registers tools."""
    CoderAgent = coder_module.CoderAgent

    def fake_base_init(self, cfg=None, *, role_name="base"):
        self.cfg = cfg
        self.role_name = role_name
        self.tools = {}

        def _register_tool(name, func):
            self.tools[name] = func

        self.register_tool = _register_tool

    monkeypatch.setattr(coder_module.BaseAgent, "__init__", fake_base_init)
    monkeypatch.setattr(
        coder_module, "SecurityManager", lambda cfg, access_level: (cfg, access_level)
    )
    code_manager_mock = _build_code_manager_mock(coder_module.CodeManager)
    pkg_manager_mock = _build_pkg_manager_mock(coder_module.PackageInfoManager)
    todo_manager_mock = _build_todo_manager_mock(coder_module.TodoManager)
    monkeypatch.setattr(coder_module, "CodeManager", lambda *_args, **_kwargs: code_manager_mock)
    monkeypatch.setattr(
        coder_module, "PackageInfoManager", lambda *_args, **_kwargs: pkg_manager_mock
    )
    monkeypatch.setattr(coder_module, "TodoManager", lambda *_args, **_kwargs: todo_manager_mock)

    events = DummyEvents()
    monkeypatch.setattr(coder_module, "get_agent_event_bus", lambda: events)

    cfg = SimpleNamespace(BASE_DIR=tmp_path, ACCESS_LEVEL="restricted")
    agent = CoderAgent(cfg)

    assert agent.role_name == "coder"
    assert agent.security == (cfg, "restricted")
    assert agent.events is events
    assert set(agent.tools.keys()) == {
        "read_file",
        "write_file",
        "patch_file",
        "execute_code",
        "list_directory",
        "glob_search",
        "grep_search",
        "audit_project",
        "get_package_info",
        "scan_project_todos",
        "read_test_artifacts",
    }


def test_parse_qa_feedback_variants(monkeypatch, coder_module):
    """Parse qa feedback variants."""
    CoderAgent = coder_module.CoderAgent
    assert CoderAgent._parse_qa_feedback("") == {}
    assert CoderAgent._parse_qa_feedback(' {"decision":"approve"} ') == {"decision": "approve"}

    malformed = CoderAgent._parse_qa_feedback("{not-json")
    assert malformed == {"raw": "{not-json"}

    json_not_dict = CoderAgent._parse_qa_feedback('["not", "a", "dict"]')
    assert json_not_dict == {"raw": '["not", "a", "dict"]'}

    # startswith("{") dalında json.loads sözlük dışı bir tip döndürürse fallback'e düşmeli
    monkeypatch.setattr(coder_module.json, "loads", lambda _payload: ["forced", "list"])
    forced_non_dict = CoderAgent._parse_qa_feedback('{"decision":"approve"}')
    assert forced_non_dict == {"raw": '{"decision":"approve"}'}

    parsed = CoderAgent._parse_qa_feedback("decision=reject; summary=Fix tests; x=y")
    assert parsed["decision"] == "reject"
    assert parsed["summary"] == "Fix tests"
    assert parsed["x"] == "y"

    # "=" içermeyen parça atlanmalı ve sözlüğe eklenmemeli
    parsed_with_noise = CoderAgent._parse_qa_feedback(
        "decision=approve;note without equals;summary=ok"
    )
    assert parsed_with_noise["decision"] == "approve"
    assert parsed_with_noise["summary"] == "ok"
    assert "note without equals" not in parsed_with_noise


async def _new_runtime_agent(coder_module):
    coder_agent_class = coder_module.CoderAgent
    agent = coder_agent_class.__new__(coder_agent_class)
    agent.cfg = SimpleNamespace(BASE_DIR="/tmp/base")
    agent.events = DummyEvents()
    agent.code = _build_code_manager_mock(coder_module.CodeManager)
    agent.pkg = _build_pkg_manager_mock(coder_module.PackageInfoManager)
    agent.todo = _build_todo_manager_mock(coder_module.TodoManager)
    agent.role_name = "coder"
    return agent


@pytest.mark.asyncio
async def test_tool_methods_are_routed_correctly(coder_module):
    """Tool methods are routed correctly."""
    agent = await _new_runtime_agent(coder_module)

    assert await agent._tool_read_file("a.py") == "read:a.py"
    assert "Kullanım" in await agent._tool_write_file("only-path")
    assert await agent._tool_write_file("a.py|print(1)") == "write:a.py:print(1)"

    assert "Kullanım" in await agent._tool_patch_file("a.py|x")
    assert await agent._tool_patch_file("a.py|old|new") == "patch:a.py:old->new"

    assert await agent._tool_execute_code("pytest -q") == "exec:pytest -q"
    assert await agent._tool_list_directory("") == "list:."
    assert await agent._tool_list_directory("src") == "list:src"

    assert await agent._tool_glob_search("*.py|||tests") == "glob:*.py:tests"
    assert await agent._tool_glob_search("*.md") == "glob:*.md:."

    assert await agent._tool_grep_search("TODO|||src|||*.py|||5") == "grep:TODO:src:*.py:5"
    assert await agent._tool_grep_search("TODO|||src|||*.py|||x") == "grep:TODO:src:*.py:2"

    assert await agent._tool_audit_project("") == "audit:."
    assert await agent._tool_get_package_info(" requests ") == "pkg:requests"
    assert await agent._tool_scan_project_todos("") == "todos:/tmp/base"
    assert await agent._tool_scan_project_todos("src") == "todos:src"


@pytest.mark.asyncio
async def test_tool_read_test_artifacts_empty_input_returns_empty_payload(coder_module):
    """Tool read test artifacts empty input returns empty payload."""
    agent = await _new_runtime_agent(coder_module)

    assert await agent._tool_read_test_artifacts("  ") == "[TEST_ARTIFACTS] {}"
    agent.code.read_file.assert_not_called()


@pytest.mark.asyncio
async def test_tool_read_test_artifacts_reads_named_and_default_artifacts(coder_module):
    """Tool read test artifacts reads named and default artifacts."""
    agent = await _new_runtime_agent(coder_module)

    result = await agent._tool_read_test_artifacts(
        " coverage = coverage.xml ; ignored ; =fallback.txt; blank= ; junit= reports/junit.xml "
    )

    prefix, payload = result.split(" ", 1)
    assert prefix == "[TEST_ARTIFACTS]"
    assert json.loads(payload) == {
        "coverage": "read:coverage.xml",
        "artifact": "read:fallback.txt",
        "junit": "read:reports/junit.xml",
    }
    assert [call.args[0] for call in agent.code.read_file.call_args_list] == [
        "coverage.xml",
        "fallback.txt",
        "reports/junit.xml",
    ]


@pytest.mark.asyncio
async def test_run_task_paths(monkeypatch, coder_module):
    """Run task paths."""
    agent = await _new_runtime_agent(coder_module)

    async def fake_call_tool(name, arg):
        return f"tool:{name}:{arg}"

    def fake_delegate(target, payload, reason=""):
        return SimpleNamespace(target=target, payload=payload, reason=reason)

    agent.call_tool = fake_call_tool
    agent.delegate_to = fake_delegate

    assert await agent.run_task("   ") == "[UYARI] Boş kodlayıcı görevi verildi."

    assert await agent.run_task("read_file|a.py") == "tool:read_file:a.py"
    assert await agent.run_task("WRITE_FILE|a.py|x") == "tool:write_file:a.py|x"
    assert await agent.run_task("patch_file|a.py|x|y") == "tool:patch_file:a.py|x|y"
    assert await agent.run_task("execute_code|pytest -q") == "tool:execute_code:pytest -q"
    assert (
        await agent.run_task(
            "read_test_artifacts|coverage_json=coverage.json;junit_xml=test_results.xml"
        )
        == "tool:read_test_artifacts:coverage_json=coverage.json;junit_xml=test_results.xml"
    )

    approve = await agent.run_task("qa_feedback|decision=approve;summary=looks good")
    assert approve == "[CODER:APPROVED] Reviewer onayı alındı: looks good"

    reject_feedback = (
        'qa_feedback|{"decision":"reject","summary":"fix this",'
        '"dynamic_test_output":"dyn fail","regression_test_output":"reg fail",'
        '"remediation_loop":{"summary":"rerun needed"}}'
    )
    reject = await agent.run_task(reject_feedback)
    assert reject.startswith("[CODER:REWORK_REQUIRED]")
    assert "[REMEDIATION_LOOP] rerun needed" in reject
    assert "[FAILED_TESTS] dyn fail\n\nreg fail" in reject

    reject_no_outputs = await agent.run_task("qa_feedback|decision=reject;summary=needs work")
    assert "[FAILED_TESTS] -" in reject_no_outputs

    req = await agent.run_task("request_review|src changed")
    assert req.target == "reviewer"
    assert req.payload == "review_code|src changed"
    assert req.reason == "coder_request_review"

    nl = await agent.run_task("foo.py isimli bir dosyaya 'hello' yaz")
    assert nl == "tool:write_file:foo.py|hello"

    async def fake_call_llm(messages, **kwargs):
        assert "unknown command" in messages[-1]["content"]
        assert kwargs["json_mode"] is True
        return '{"final":"LLM handled unknown command"}'

    agent.call_llm = fake_call_llm
    fallback = await agent.run_task("unknown command")
    assert fallback == "LLM handled unknown command"

    assert len(agent.events.messages) >= 1
    assert all(role == "coder" for role, _ in agent.events.messages)


@pytest.mark.asyncio
async def test_run_task_general_prompt_uses_llm_tool_loop(coder_module):
    """Run task general prompt uses llm tool loop."""
    agent = await _new_runtime_agent(coder_module)
    calls: list[tuple[str, str]] = []
    llm_messages: list[list[dict[str, str]]] = []
    agent.tools = {"read_file": agent._tool_read_file, "patch_file": agent._tool_patch_file}

    async def fake_call_tool(name: str, arg: str) -> str:
        calls.append((name, arg))
        return f"result:{name}:{arg}"

    responses = iter(
        [
            '{"tool_calls":[{"name":"read_file","arg":"src/app.py"}],"final":""}',
            '{"tool_calls":[{"name":"patch_file","arg":"src/app.py|old|new"}],"final":"patched"}',
            '{"final":"Implemented requested change"}',
        ]
    )

    async def fake_call_llm(messages, **kwargs):
        llm_messages.append(messages)
        assert kwargs["json_mode"] is True
        return next(responses)

    agent.call_tool = fake_call_tool
    agent.call_llm = fake_call_llm

    result = await agent.run_task("Implement the requested app change")

    assert result == "Implemented requested change"
    assert calls == [("read_file", "src/app.py"), ("patch_file", "src/app.py|old|new")]
    assert "Araç sonuçları" in llm_messages[-1][-1]["content"]


@pytest.mark.asyncio
async def test_run_task_general_prompt_returns_plain_llm_response(coder_module):
    """Run task general prompt returns plain llm response."""
    agent = await _new_runtime_agent(coder_module)
    agent.tools = {}

    async def fake_call_llm(messages, **kwargs):
        assert "Kullanabileceğin araçlar" in messages[0]["content"]
        assert kwargs["json_mode"] is True
        return "Kod değişikliği için önce dosya yolu gerekli."

    agent.call_llm = fake_call_llm

    assert (
        await agent.run_task("bir özellik implement et")
        == "Kod değişikliği için önce dosya yolu gerekli."
    )


@pytest.mark.asyncio
async def test_run_task_qa_feedback_conflict_and_long_outputs(coder_module):
    """Run task qa feedback conflict and long outputs."""
    agent = await _new_runtime_agent(coder_module)

    dynamic_fail = "D" * 1200
    regression_fail = "R" * 1200
    conflicting_feedback = (
        "qa_feedback|decision=approve;"
        "summary=ilk karar approve;"
        "decision=reject;"
        "summary=son karar reject;"
        f"dynamic_test_output={dynamic_fail};"
        f"regression_test_output={regression_fail}"
    )

    result = await agent.run_task(conflicting_feedback)

    assert result.startswith("[CODER:REWORK_REQUIRED]")
    assert "son karar reject" in result
    assert "[FAILED_TESTS]" in result
    failed_excerpt = result.split("[FAILED_TESTS] ", 1)[1]
    assert len(failed_excerpt) == 1500


@pytest.mark.asyncio
async def test_call_maybe_async_with_sync_callable(coder_module):
    """Call maybe async with sync callable."""
    result = await coder_module.CoderAgent._call_maybe_async(lambda x, y: x + y, 2, 3)
    assert result == 5


@pytest.mark.asyncio
async def test_call_maybe_async_with_async_callable(coder_module):
    """Call maybe async with async callable."""

    async def _async_sum(x, y):
        return x + y

    result = await coder_module.CoderAgent._call_maybe_async(_async_sum, 4, 6)
    assert result == 10


def test_parse_llm_tool_plan_handles_fenced_json_lists_malformed_and_scalars(coder_module):
    """Parse llm tool plan handles fenced json lists malformed and scalars."""
    CoderAgent = coder_module.CoderAgent

    assert CoderAgent._parse_llm_tool_plan('```json\n{"final":"ok"}\n```') == {"final": "ok"}
    assert CoderAgent._parse_llm_tool_plan('[{"name":"read_file","arg":"a.py"}]') == {
        "tool_calls": [{"name": "read_file", "arg": "a.py"}],
        "final": "",
    }
    assert CoderAgent._parse_llm_tool_plan("{not-json") == {"final": "{not-json"}
    assert CoderAgent._parse_llm_tool_plan('"done"') == {"final": "done"}
    assert CoderAgent._parse_llm_tool_plan("   ") == {"final": ""}


def test_parse_llm_tool_plan_maps_react_single_tool_shape(coder_module):
    """Sidar's ``{"thought","tool","argument"}`` shape becomes a runnable tool plan."""
    CoderAgent = coder_module.CoderAgent

    assert CoderAgent._parse_llm_tool_plan(
        '{"thought":"oku","tool":"read_file","argument":"a.py"}'
    ) == {"tool_calls": [{"name": "read_file", "arg": "a.py"}], "final": ""}
    assert CoderAgent._parse_llm_tool_plan(
        '{"thought":"bitti","tool":"final_answer","argument":"özet"}'
    ) == {"final": "özet"}
    # The documented contract and non-string tool values stay untouched.
    contract = {"tool_calls": [{"name": "read_file", "arg": "b.py"}], "tool": "x", "final": ""}
    assert CoderAgent._normalize_single_tool_plan(contract) is contract
    assert CoderAgent._parse_llm_tool_plan('{"tool": 3, "final": "ok"}') == {
        "tool": 3,
        "final": "ok",
    }


@pytest.mark.asyncio
async def test_llm_tool_loop_runs_react_single_tool_calls(coder_module):
    """A local model's ReAct-style tool call runs instead of leaking as raw JSON."""
    agent = coder_module.CoderAgent.__new__(coder_module.CoderAgent)
    agent.tools = {"read_file": object()}
    calls = []

    async def fake_call_tool(name, arg):
        calls.append((name, arg))
        return "def mean(xs): ..."

    responses = iter(
        [
            '{"thought":"dosyayı oku","tool":"read_file","argument":"stats.py"}',
            '{"thought":"tamam","tool":"final_answer","argument":"mean() yazıldı"}',
        ]
    )

    async def fake_call_llm(_messages, **_kwargs):
        return next(responses)

    agent.call_tool = fake_call_tool
    agent.call_llm = fake_call_llm

    assert await agent._run_llm_tool_loop("ortalama") == "mean() yazıldı"
    assert calls == [("read_file", "stats.py")]


@pytest.mark.asyncio
async def test_llm_tool_loop_handles_unknown_tool_dict_call_then_final(coder_module):
    """Llm tool loop handles unknown tool dict call then final."""
    agent = await _new_runtime_agent(coder_module)
    agent.tools = {"read_file": agent._tool_read_file}
    llm_messages: list[list[dict[str, str]]] = []

    responses = iter(
        [
            '{"tool_calls":{"name":"not_registered","arg":"x"},"final":""}',
            '{"final":"unknown tool reported"}',
        ]
    )

    async def fake_call_llm(messages, **kwargs):
        llm_messages.append(messages)
        assert kwargs["json_mode"] is True
        return next(responses)

    agent.call_llm = fake_call_llm

    result = await agent._run_llm_tool_loop("use a tool")

    assert result == "unknown tool reported"
    assert "Bilinmeyen araç: not_registered" in llm_messages[-1][-1]["content"]


@pytest.mark.asyncio
async def test_llm_tool_loop_handles_list_tool_calls_and_ignores_non_dict_items(coder_module):
    """Llm tool loop handles list tool calls and ignores non dict items."""
    agent = await _new_runtime_agent(coder_module)
    agent.tools = {"read_file": agent._tool_read_file}
    calls: list[tuple[str, str]] = []

    async def fake_call_tool(name: str, arg: str) -> str:
        calls.append((name, arg))
        return f"ok:{arg}"

    responses = iter(
        [
            '["skip-me", {"tool":"read_file","input":"src/app.py"}]',
            '{"final":"read complete"}',
        ]
    )

    async def fake_call_llm(_messages, **_kwargs):
        return next(responses)

    agent.call_tool = fake_call_tool
    agent.call_llm = fake_call_llm

    assert await agent._run_llm_tool_loop("read") == "read complete"
    assert calls == [("read_file", "src/app.py")]


@pytest.mark.asyncio
async def test_llm_tool_loop_returns_raw_response_when_tool_calls_are_not_valid_dicts(
    coder_module,
) -> None:
    """Llm tool loop returns raw response when tool calls are not valid dicts."""
    agent = await _new_runtime_agent(coder_module)
    agent.tools = {"read_file": agent._tool_read_file}

    async def fake_call_llm(_messages, **_kwargs):
        return '{"tool_calls":["skip-me"],"final":""}'

    agent.call_llm = fake_call_llm

    assert await agent._run_llm_tool_loop("read") == '{"tool_calls":["skip-me"],"final":""}'


@pytest.mark.asyncio
async def test_llm_tool_loop_returns_limit_message_after_repeated_tool_calls(coder_module):
    """Llm tool loop returns limit message after repeated tool calls."""
    agent = await _new_runtime_agent(coder_module)
    agent.tools = {"read_file": agent._tool_read_file}
    calls: list[tuple[str, str]] = []

    async def fake_call_tool(name: str, arg: str) -> str:
        calls.append((name, arg))
        return f"still looping:{arg}"

    async def fake_call_llm(_messages, **_kwargs):
        return '{"tool_calls":[{"name":"read_file","arg":"loop.py"}],"final":""}'

    agent.call_tool = fake_call_tool
    agent.call_llm = fake_call_llm

    assert (
        await agent._run_llm_tool_loop("loop")
        == "[CODER:TOOL_LOOP_LIMIT] Araç döngüsü sınırına ulaşıldı."
    )
    assert calls == [("read_file", "loop.py")] * 3


@pytest.mark.asyncio
async def test_llm_tool_loop_forces_final_answer_after_tool_budget(coder_module):
    """An exhausted tool budget gets one tool-free turn instead of a bare limit marker."""
    agent = await _new_runtime_agent(coder_module)
    agent.tools = {"list_directory": agent._tool_list_directory}
    calls: list[tuple[str, str]] = []
    prompts: list[str] = []

    async def fake_call_tool(name: str, arg: str) -> str:
        calls.append((name, arg))
        return "a.py\nb.py"

    responses = iter(
        ['{"tool":"list_directory","argument":"."}'] * 3
        + ['{"final":"def mean(xs):\\n    return sum(xs) / len(xs)"}']
    )

    async def fake_call_llm(messages, **_kwargs):
        prompts.append(messages[-1]["content"])
        return next(responses)

    agent.call_tool = fake_call_tool
    agent.call_llm = fake_call_llm

    assert (
        await agent._run_llm_tool_loop("ortalama") == "def mean(xs):\n    return sum(xs) / len(xs)"
    )
    assert calls == [("list_directory", ".")] * 3
    assert "artık araç çağırma" in prompts[-1]


@pytest.mark.asyncio
async def test_run_task_qa_feedback_malformed_json_defaults_to_approved_raw_summary(coder_module):
    """Run task qa feedback malformed json defaults to approved raw summary."""
    agent = await _new_runtime_agent(coder_module)

    result = await agent.run_task("qa_feedback|{bad json")

    assert result == "[CODER:APPROVED] Reviewer onayı alındı: {bad json"


@pytest.mark.asyncio
async def test_llm_tool_loop_keeps_last_final_without_extra_turn(coder_module):
    """A final given alongside the last tool calls is returned without a forced turn."""
    agent = await _new_runtime_agent(coder_module)
    agent.tools = {"read_file": agent._tool_read_file}
    llm_calls = 0

    async def fake_call_tool(_name: str, _arg: str) -> str:
        return "content"

    async def fake_call_llm(_messages, **_kwargs):
        nonlocal llm_calls
        llm_calls += 1
        return '{"tool_calls":[{"name":"read_file","arg":"a.py"}],"final":"ara özet"}'

    agent.call_tool = fake_call_tool
    agent.call_llm = fake_call_llm

    assert await agent._run_llm_tool_loop("oku") == "ara özet"
    assert llm_calls == 3


@pytest.mark.asyncio
async def test_llm_tool_loop_forced_turn_accepts_plain_text_without_json_mode(coder_module):
    """Replays qwen's real loop: the tool-free turn drops JSON mode and keeps plain code."""
    agent = await _new_runtime_agent(coder_module)
    agent.tools = {"read_test_artifacts": agent._tool_read_test_artifacts}
    json_modes: list[bool] = []

    async def fake_call_tool(_name: str, _arg: str) -> str:
        return "[TEST_ARTIFACTS] {}"

    responses = iter(
        ['{"thought":"...","tool":"read_test_artifacts","argument":"ortalama.py"}'] * 3
        + ["def ortalama(xs):\n    return sum(xs) / len(xs)"]
    )

    async def fake_call_llm(_messages, **kwargs):
        json_modes.append(kwargs["json_mode"])
        return next(responses)

    agent.call_tool = fake_call_tool
    agent.call_llm = fake_call_llm

    assert await agent._run_llm_tool_loop("ortalama") == (
        "def ortalama(xs):\n    return sum(xs) / len(xs)"
    )
    assert json_modes == [True, True, True, False]


def test_tool_contract_lists_argument_formats(coder_module):
    """Pipe-delimited argument shapes are spelled out; unknown tools stay bare."""
    agent = coder_module.CoderAgent.__new__(coder_module.CoderAgent)
    agent.tools = {"write_file": object(), "plugin_tool": object()}

    contract = agent._format_tool_contract()

    assert "write_file(<yol>|<dosyanın tam içeriği>)" in contract
    assert "plugin_tool," in contract or "plugin_tool." in contract
    assert '"name":"write_file","arg":"<yeni_dosya>.py|' in contract
    # A concrete example filename gets copied verbatim and every request then
    # overwrites the same file, which stalls on the HITL overwrite gate.
    assert "ornek.py" not in contract


@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        (
            "core/utils/date_diff.py",
            'from datetime import date\\n\\ndef f(a: date) -> str:\\n    return \\"x\\"\\n',
            'from datetime import date\n\ndef f(a: date) -> str:\n    return "x"\n',
        ),
        ("notes.txt", "satir1\\nsatir2", "satir1\nsatir2"),
        ("a.py", "```python\nx = 1\n```", "x = 1\n"),
        ("a.py", '```python\\nx = \\"a\\"\\n```', 'x = "a"\n'),
        ("a.py", 'print("a\\nb")', 'print("a\\nb")'),
        ("a.py", "x = 1\ny = 2\n", "x = 1\ny = 2\n"),
    ],
)
def test_normalize_file_content_repairs_escaped_and_fenced_payloads(
    coder_module, path, content, expected
):
    """Double-escaped newlines and a surrounding code fence are undone before writing."""
    assert coder_module._normalize_file_content(path, content) == expected


@pytest.mark.asyncio
async def test_write_file_tool_writes_normalized_content(coder_module):
    """The write_file tool passes the repaired content to the HITL writer."""
    agent = await _new_runtime_agent(coder_module)

    result = await agent._tool_write_file("a.py|```python\nx = 1\n```")

    assert result == "write:a.py:x = 1\n"


_ROOM_PROMPT = (
    "[COLLABORATION WORKSPACE]\n"
    "room_id=workspace:sidar\n"
    "participants=Operatör<user>\n"
    "requesting_user=Operatör\n"
    "requesting_role=user\n"
    "requesting_write_scopes=/home/sidar/Sidar\n"
    "recent_transcript=\n"
    "[assistant] SİDAR: scan_project_todos sonucu: README.md TODO\n\n"
    "Kullanıcılar ortak bir çalışma alanında SİDAR ile iş birliği yapıyor.\n\n"
    "Current command:\n@Sidar core/utils/date_diff.py dosyasına days_between yaz"
)


def test_compact_collaboration_prompt_keeps_scope_and_command_only(coder_module):
    """The room transcript is dropped; the write scope and the command remain."""
    compact = coder_module.CoderAgent._compact_collaboration_prompt(_ROOM_PROMPT)

    assert compact == (
        "Yazma kapsamı (yalnız bu dizinlere yaz): /home/sidar/Sidar\n\n"
        "@Sidar core/utils/date_diff.py dosyasına days_between yaz"
    )
    assert "scan_project_todos" not in compact


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("plain task", "plain task"),
        ("[COLLABORATION WORKSPACE]\nno marker", "[COLLABORATION WORKSPACE]\nno marker"),
        (
            "[COLLABORATION WORKSPACE]\nCurrent command:\n   ",
            "[COLLABORATION WORKSPACE]\nCurrent command:\n   ",
        ),
        ("[COLLABORATION WORKSPACE]\nrecent_transcript=x\nCurrent command:\ngörev", "görev"),
    ],
)
def test_compact_collaboration_prompt_edge_cases(coder_module, prompt, expected):
    """Non-room prompts, missing/empty commands and missing scopes are handled."""
    assert coder_module.CoderAgent._compact_collaboration_prompt(prompt) == expected


@pytest.mark.asyncio
async def test_run_task_sends_compacted_room_prompt_to_llm_loop(coder_module):
    """run_task hands only the compacted prompt to the LLM tool loop."""
    agent = await _new_runtime_agent(coder_module)
    seen = []

    async def fake_loop(prompt):
        seen.append(prompt)
        return "ok"

    agent._run_llm_tool_loop = fake_loop

    assert await agent.run_task(_ROOM_PROMPT) == "ok"
    assert seen == [coder_module.CoderAgent._compact_collaboration_prompt(_ROOM_PROMPT)]
