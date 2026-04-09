import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest


def _import_coder_module(module_name: str):
    module = importlib.import_module(module_name)
    required_attrs = ("CoderAgent", "BaseAgent", "CodeManager", "SecurityManager")
    if not all(hasattr(module, attr) for attr in required_attrs):
        module = importlib.reload(module)
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


def test_import_coder_module_reloads_when_required_attrs_are_missing(monkeypatch):
    module_name = "agent.roles.coder_agent"
    imported = ModuleType(module_name)
    reloaded = ModuleType(module_name)
    reloaded.CoderAgent = object
    reloaded.BaseAgent = object
    reloaded.CodeManager = object
    reloaded.SecurityManager = object

    monkeypatch.setattr(importlib, "import_module", lambda _name: imported)
    calls = []

    def _reload(mod):
        calls.append(mod)
        return reloaded

    monkeypatch.setattr(importlib, "reload", _reload)

    module = _import_coder_module(module_name)
    assert module is reloaded
    assert calls == [imported]


class DummyEvents:
    def __init__(self):
        self.messages = []

    async def publish(self, role, message):
        self.messages.append((role, message))


class DummyCodeManager:
    def __init__(self, *_args, **_kwargs):
        self.calls = []

    def read_file(self, path):
        self.calls.append(("read_file", path))
        return True, f"read:{path}"

    def write_file(self, path, content):
        self.calls.append(("write_file", path, content))
        return True, f"write:{path}:{content}"

    def patch_file(self, path, target, replacement):
        self.calls.append(("patch_file", path, target, replacement))
        return True, f"patch:{path}:{target}->{replacement}"

    def execute_code(self, command):
        self.calls.append(("execute_code", command))
        return True, f"exec:{command}"

    def list_directory(self, path):
        self.calls.append(("list_directory", path))
        return True, f"list:{path}"

    def glob_search(self, pattern, base):
        self.calls.append(("glob_search", pattern, base))
        return True, f"glob:{pattern}:{base}"

    def grep_files(self, pattern, path, file_glob, context_lines):
        self.calls.append(("grep_files", pattern, path, file_glob, context_lines))
        return True, f"grep:{pattern}:{path}:{file_glob}:{context_lines}"

    def audit_project(self, path):
        self.calls.append(("audit_project", path))
        return f"audit:{path}"


class DummyPkgManager:
    def __init__(self, *_args, **_kwargs):
        self.calls = []

    async def pypi_info(self, package_name):
        self.calls.append(package_name)
        return True, f"pkg:{package_name}"


class DummyTodoManager:
    def __init__(self, *_args, **_kwargs):
        self.calls = []

    def scan_project_todos(self, directory, _filters):
        self.calls.append((directory, _filters))
        return f"todos:{directory}"


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
    monkeypatch.setattr(coder_module, "SecurityManager", lambda cfg, access_level: (cfg, access_level))
    monkeypatch.setattr(coder_module, "CodeManager", DummyCodeManager)
    monkeypatch.setattr(coder_module, "PackageInfoManager", DummyPkgManager)
    monkeypatch.setattr(coder_module, "TodoManager", DummyTodoManager)

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
    forced_non_dict = CoderAgent._parse_qa_feedback("{\"decision\":\"approve\"}")
    assert forced_non_dict == {"raw": '{"decision":"approve"}'}

    parsed = CoderAgent._parse_qa_feedback("decision=reject; summary=Fix tests; x=y")
    assert parsed["decision"] == "reject"
    assert parsed["summary"] == "Fix tests"
    assert parsed["x"] == "y"

    # "=" içermeyen parça atlanmalı ve sözlüğe eklenmemeli
    parsed_with_noise = CoderAgent._parse_qa_feedback("decision=approve;note without equals;summary=ok")
    assert parsed_with_noise["decision"] == "approve"
    assert parsed_with_noise["summary"] == "ok"
    assert "note without equals" not in parsed_with_noise


async def _new_runtime_agent(coder_agent_class):
    agent = coder_agent_class.__new__(coder_agent_class)
    agent.cfg = SimpleNamespace(BASE_DIR="/tmp/base")
    agent.events = DummyEvents()
    agent.code = DummyCodeManager()
    agent.pkg = DummyPkgManager()
    agent.todo = DummyTodoManager()
    agent.role_name = "coder"
    return agent


def test_tool_methods_are_routed_correctly(coder_module):
    agent = asyncio.run(_new_runtime_agent(coder_module.CoderAgent))

    assert asyncio.run(agent._tool_read_file("a.py")) == "read:a.py"
    assert "Kullanım" in asyncio.run(agent._tool_write_file("only-path"))
    assert asyncio.run(agent._tool_write_file("a.py|print(1)")) == "write:a.py:print(1)"

    assert "Kullanım" in asyncio.run(agent._tool_patch_file("a.py|x"))
    assert asyncio.run(agent._tool_patch_file("a.py|old|new")) == "patch:a.py:old->new"

    assert asyncio.run(agent._tool_execute_code("pytest -q")) == "exec:pytest -q"
    assert asyncio.run(agent._tool_list_directory("")) == "list:."
    assert asyncio.run(agent._tool_list_directory("src")) == "list:src"

    assert asyncio.run(agent._tool_glob_search("*.py|||tests")) == "glob:*.py:tests"
    assert asyncio.run(agent._tool_glob_search("*.md")) == "glob:*.md:."

    assert asyncio.run(agent._tool_grep_search("TODO|||src|||*.py|||5")) == "grep:TODO:src:*.py:5"
    assert asyncio.run(agent._tool_grep_search("TODO|||src|||*.py|||x")) == "grep:TODO:src:*.py:2"

    assert asyncio.run(agent._tool_audit_project("")) == "audit:."
    assert asyncio.run(agent._tool_get_package_info(" requests ")) == "pkg:requests"
    assert asyncio.run(agent._tool_scan_project_todos("")) == "todos:/tmp/base"
    assert asyncio.run(agent._tool_scan_project_todos("src")) == "todos:src"


def test_run_task_paths(monkeypatch, coder_module):
    agent = asyncio.run(_new_runtime_agent(coder_module.CoderAgent))

    async def fake_call_tool(name, arg):
        return f"tool:{name}:{arg}"

    def fake_delegate(target, payload, reason=""):
        return SimpleNamespace(target=target, payload=payload, reason=reason)

    agent.call_tool = fake_call_tool
    agent.delegate_to = fake_delegate

    assert asyncio.run(agent.run_task("   ")) == "[UYARI] Boş kodlayıcı görevi verildi."

    assert asyncio.run(agent.run_task("read_file|a.py")) == "tool:read_file:a.py"
    assert asyncio.run(agent.run_task("WRITE_FILE|a.py|x")) == "tool:write_file:a.py|x"
    assert asyncio.run(agent.run_task("patch_file|a.py|x|y")) == "tool:patch_file:a.py|x|y"
    assert asyncio.run(agent.run_task("execute_code|pytest -q")) == "tool:execute_code:pytest -q"

    approve = asyncio.run(agent.run_task("qa_feedback|decision=approve;summary=looks good"))
    assert approve == "[CODER:APPROVED] Reviewer onayı alındı: looks good"

    reject_feedback = (
        'qa_feedback|{"decision":"reject","summary":"fix this",'
        '"dynamic_test_output":"dyn fail","regression_test_output":"reg fail",'
        '"remediation_loop":{"summary":"rerun needed"}}'
    )
    reject = asyncio.run(agent.run_task(reject_feedback))
    assert reject.startswith("[CODER:REWORK_REQUIRED]")
    assert "[REMEDIATION_LOOP] rerun needed" in reject
    assert "[FAILED_TESTS] dyn fail\n\nreg fail" in reject

    reject_no_outputs = asyncio.run(agent.run_task("qa_feedback|decision=reject;summary=needs work"))
    assert "[FAILED_TESTS] -" in reject_no_outputs

    req = asyncio.run(agent.run_task("request_review|src changed"))
    assert req.target == "reviewer"
    assert req.payload == "review_code|src changed"
    assert req.reason == "coder_request_review"

    nl = asyncio.run(agent.run_task("foo.py isimli bir dosyaya 'hello' yaz"))
    assert nl == "tool:write_file:foo.py|hello"

    fallback = asyncio.run(agent.run_task("unknown command"))
    assert fallback == "[LEGACY_FALLBACK] coder_unhandled task=unknown command"

    assert len(agent.events.messages) >= 1
    assert all(role == "coder" for role, _ in agent.events.messages)
