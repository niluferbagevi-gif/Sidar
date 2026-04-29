import importlib
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
    def __init__(self):
        self.messages = []

    async def publish(self, role, message):
        self.messages.append((role, message))


def _build_code_manager_mock(code_manager_cls):
    code_manager = create_autospec(code_manager_cls, instance=True, spec_set=True)
    code_manager.read_file.side_effect = lambda path: (True, f"read:{path}")
    code_manager.write_file.side_effect = lambda path, content: (True, f"write:{path}:{content}")
    code_manager.patch_file.side_effect = lambda path, target, replacement: (
        True,
        f"patch:{path}:{target}->{replacement}",
    )
    code_manager.execute_code.side_effect = lambda command: (True, f"exec:{command}")
    code_manager.list_directory.side_effect = lambda path: (True, f"list:{path}")
    code_manager.glob_search.side_effect = lambda pattern, base: (True, f"glob:{pattern}:{base}")
    code_manager.grep_files.side_effect = lambda pattern, path, file_glob, case_sensitive=True, context_lines=0, max_results=100: (
        True,
        f"grep:{pattern}:{path}:{file_glob}:{context_lines}",
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
    }


def test_parse_qa_feedback_variants(monkeypatch, coder_module):
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
async def test_run_task_paths(monkeypatch, coder_module):
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

    fallback = await agent.run_task("unknown command")
    assert fallback == "[LEGACY_FALLBACK] coder_unhandled task=unknown command"

    assert len(agent.events.messages) >= 1
    assert all(role == "coder" for role, _ in agent.events.messages)


@pytest.mark.asyncio
async def test_run_task_qa_feedback_conflict_and_long_outputs(coder_module):
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
