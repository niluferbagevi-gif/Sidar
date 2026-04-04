from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from types import MethodType, SimpleNamespace



def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("httpx"):
    fake_httpx = types.ModuleType("httpx")

    class _Timeout:
        def __init__(self, *args, **kwargs):
            return None

    class _AsyncClient:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.Timeout = _Timeout
    fake_httpx.AsyncClient = _AsyncClient
    fake_httpx.TimeoutException = Exception
    fake_httpx.RequestError = Exception
    fake_httpx.HTTPStatusError = Exception
    sys.modules["httpx"] = fake_httpx

if not _has_module("jwt"):
    fake_jwt = types.ModuleType("jwt")
    fake_jwt.PyJWTError = Exception
    fake_jwt.decode = lambda *_a, **_k: {}
    fake_jwt.encode = lambda *_a, **_k: "token"
    sys.modules["jwt"] = fake_jwt

if not _has_module("redis"):
    redis_mod = types.ModuleType("redis")
    redis_async = types.ModuleType("redis.asyncio")
    redis_exc = types.ModuleType("redis.exceptions")
    redis_async.Redis = object
    redis_exc.ResponseError = Exception
    sys.modules["redis"] = redis_mod
    sys.modules["redis.asyncio"] = redis_async
    sys.modules["redis.exceptions"] = redis_exc

if not _has_module("bs4"):
    fake_bs4 = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, html, _parser):
            self._html = html

        def __call__(self, *_args, **_kwargs):
            return []

        def get_text(self, **_kwargs):
            return self._html

    fake_bs4.BeautifulSoup = BeautifulSoup
    sys.modules["bs4"] = fake_bs4

from agent.roles.coder_agent import CoderAgent


def test_init_wires_dependencies_and_registers_expected_tools(monkeypatch) -> None:
    created = {}
    registered = []

    def fake_base_init(self, cfg=None, role_name=None):
        self.cfg = SimpleNamespace(BASE_DIR="/tmp/project", ACCESS_LEVEL="limited")

    class FakeSecurity:
        def __init__(self, cfg, access_level):
            created["security"] = (cfg, access_level)

    class FakeCode:
        def __init__(self, security, base_dir):
            created["code"] = (security, base_dir)

    class FakePkg:
        def __init__(self, cfg):
            created["pkg"] = cfg

    class FakeTodo:
        def __init__(self, cfg):
            created["todo"] = cfg

    monkeypatch.setattr("agent.roles.coder_agent.BaseAgent.__init__", fake_base_init)
    monkeypatch.setattr("agent.roles.coder_agent.SecurityManager", FakeSecurity)
    monkeypatch.setattr("agent.roles.coder_agent.CodeManager", FakeCode)
    monkeypatch.setattr("agent.roles.coder_agent.PackageInfoManager", FakePkg)
    monkeypatch.setattr("agent.roles.coder_agent.TodoManager", FakeTodo)
    monkeypatch.setattr("agent.roles.coder_agent.get_agent_event_bus", lambda: "bus")
    monkeypatch.setattr(CoderAgent, "register_tool", lambda self, name, fn: registered.append(name))

    agent = CoderAgent()

    assert created["security"][1] == "limited"
    assert created["code"][1] == "/tmp/project"
    assert created["pkg"] is agent.cfg
    assert created["todo"] is agent.cfg
    assert agent.events == "bus"
    assert registered == [
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
    ]


def test_tool_methods_cover_all_code_manager_paths() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    class _Code:
        def read_file(self, arg):
            return True, f"read:{arg}"

        def write_file(self, path, content):
            return True, f"write:{path}:{content}"

        def patch_file(self, path, target, repl):
            return True, f"patch:{path}:{target}:{repl}"

        def execute_code(self, arg):
            return True, f"exec:{arg}"

        def list_directory(self, arg):
            return True, f"ls:{arg}"

        def glob_search(self, pattern, base):
            return True, f"glob:{pattern}:{base}"

        def grep_files(self, pattern, path, file_glob, context_lines):
            return True, f"grep:{pattern}:{path}:{file_glob}:{context_lines}"

        def audit_project(self, path):
            return f"audit:{path}"

    agent.code = _Code()
    agent.cfg = SimpleNamespace(BASE_DIR="/repo")
    agent.todo = SimpleNamespace(scan_project_todos=lambda directory, _opts: f"todos:{directory}")
    agent.pkg = SimpleNamespace(
        pypi_info=lambda pkg: asyncio.sleep(0, result=(True, f"pkg:{pkg}")),
    )

    assert asyncio.run(agent._tool_read_file("a.py")) == "read:a.py"
    assert asyncio.run(agent._tool_write_file("x.py|print(1)")) == "write:x.py:print(1)"
    assert "Kullanım: write_file" in asyncio.run(agent._tool_write_file("x.py"))
    assert asyncio.run(agent._tool_patch_file("x.py|a|b")) == "patch:x.py:a:b"
    assert "Kullanım: patch_file" in asyncio.run(agent._tool_patch_file("x.py|a"))
    assert asyncio.run(agent._tool_execute_code("echo 1")) == "exec:echo 1"
    assert asyncio.run(agent._tool_list_directory("")) == "ls:."
    assert asyncio.run(agent._tool_glob_search("*.py|||src")) == "glob:*.py:src"
    assert asyncio.run(agent._tool_glob_search("*.md")) == "glob:*.md:."
    assert asyncio.run(agent._tool_grep_search("needle|||src|||*.py|||5")) == "grep:needle:src:*.py:5"
    assert asyncio.run(agent._tool_grep_search("needle|||src|||*.py|||bad")) == "grep:needle:src:*.py:2"
    assert asyncio.run(agent._tool_audit_project("")) == "audit:."
    assert asyncio.run(agent._tool_get_package_info(" requests ")) == "pkg:requests"
    assert asyncio.run(agent._tool_scan_project_todos("")) == "todos:/repo"


def test_parse_qa_feedback_empty_and_non_dict_json_paths() -> None:
    assert CoderAgent._parse_qa_feedback("") == {}
    assert CoderAgent._parse_qa_feedback("[]") == {"raw": "[]"}


def test_run_task_empty_and_tool_prefix_routes() -> None:
    agent = CoderAgent.__new__(CoderAgent)
    called = []

    async def _publish(*_args, **_kwargs):
        return None

    async def _call_tool(name: str, arg: str) -> str:
        called.append((name, arg))
        return f"ok:{name}:{arg}"

    agent.events = SimpleNamespace(publish=_publish)
    agent.call_tool = MethodType(lambda _self, name, arg: _call_tool(name, arg), agent)

    assert asyncio.run(agent.run_task("")) == "[UYARI] Boş kodlayıcı görevi verildi."
    assert asyncio.run(agent.run_task("read_file|README.md")) == "ok:read_file:README.md"
    assert asyncio.run(agent.run_task("write_file|a.py|1")) == "ok:write_file:a.py|1"
    assert asyncio.run(agent.run_task("patch_file|a.py|x|y")) == "ok:patch_file:a.py|x|y"
    assert asyncio.run(agent.run_task("execute_code|pytest -q")) == "ok:execute_code:pytest -q"
    assert called == [
        ("read_file", "README.md"),
        ("write_file", "a.py|1"),
        ("patch_file", "a.py|x|y"),
        ("execute_code", "pytest -q"),
    ]


def test_run_task_qa_feedback_approved_path_uses_default_summary() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    agent.events = SimpleNamespace(publish=_publish)
    result = asyncio.run(agent.run_task("qa_feedback|decision=approve"))
    assert result == "[CODER:APPROVED] Reviewer onayı alındı: decision=approve"


def test_run_task_reject_without_test_outputs_uses_dash() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    agent.events = SimpleNamespace(publish=_publish)
    result = asyncio.run(agent.run_task("qa_feedback|decision=reject;summary=bad"))
    assert "[CODER:REWORK_REQUIRED]" in result
    assert "[FAILED_TESTS] -" in result



def test_run_task_handles_reject_feedback_with_remediation_summary() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    agent.events = SimpleNamespace(publish=_publish)

    payload = (
        'qa_feedback|{"decision":"reject","summary":"tests failed",'
        '"dynamic_test_output":"dyn","regression_test_output":"reg",'
        '"remediation_loop":{"summary":"patch required"}}'
    )
    result = asyncio.run(agent.run_task(payload))

    assert "[CODER:REWORK_REQUIRED]" in result
    assert "[REMEDIATION_LOOP] patch required" in result
    assert "[FAILED_TESTS] dyn\n\nreg" in result


def test_run_task_routes_natural_language_write_file_to_tool() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    async def _call_tool(name: str, arg: str) -> str:
        assert name == "write_file"
        assert arg == "notes.txt|Merhaba Dünya"
        return "ok"

    agent.events = SimpleNamespace(publish=_publish)
    agent.call_tool = MethodType(lambda _self, name, arg: _call_tool(name, arg), agent)

    result = asyncio.run(agent.run_task("notes.txt isimli bir dosyaya 'Merhaba Dünya' yaz"))
    assert result == "ok"


def test_run_task_request_review_delegates_to_reviewer() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    agent.events = SimpleNamespace(publish=_publish)
    agent.delegate_to = MethodType(
        lambda _self, role, payload, reason=None: f"{role}|{payload}|{reason}",
        agent,
    )

    result = asyncio.run(agent.run_task("request_review|src/main.py"))
    assert result == "reviewer|review_code|src/main.py|coder_request_review"


def test_parse_qa_feedback_supports_json_key_value_and_raw() -> None:
    parsed_json = CoderAgent._parse_qa_feedback('{"decision":"approve","summary":"ok"}')
    parsed_kv = CoderAgent._parse_qa_feedback("decision=reject;summary=broken")
    parsed_raw = CoderAgent._parse_qa_feedback("{invalid json")

    assert parsed_json["decision"] == "approve"
    assert parsed_kv["decision"] == "reject"
    assert parsed_kv["summary"] == "broken"
    assert parsed_raw["raw"] == "{invalid json"


def test_run_task_returns_legacy_fallback_for_unhandled_prompt() -> None:
    agent = CoderAgent.__new__(CoderAgent)

    async def _publish(*_args, **_kwargs):
        return None

    agent.events = SimpleNamespace(publish=_publish)
    agent.call_tool = MethodType(lambda _self, _name, _arg: "should-not-be-called", agent)

    result = asyncio.run(agent.run_task("buna özel bir araç eşlemesi yok"))

    assert result.startswith("[LEGACY_FALLBACK]")
    assert "coder_unhandled" in result
