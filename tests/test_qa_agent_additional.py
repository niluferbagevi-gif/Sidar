from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return name in sys.modules


if not _has_module("httpx"):
    fake_httpx = types.ModuleType("httpx")

    class Timeout:
        def __init__(self, *args, **kwargs):
            return None

    fake_httpx.Timeout = Timeout
    fake_httpx.TimeoutException = Exception
    fake_httpx.RequestError = Exception
    fake_httpx.HTTPStatusError = Exception
    fake_httpx.AsyncClient = object
    fake_httpx.Request = object
    fake_httpx.Response = object
    sys.modules["httpx"] = fake_httpx

_module_path = Path(__file__).resolve().parents[1] / "agent" / "roles" / "qa_agent.py"
_spec = importlib.util.spec_from_file_location("qa_agent_direct", _module_path)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)
QAAgent = _mod.QAAgent


def _build_agent() -> QAAgent:
    agent = QAAgent.__new__(QAAgent)
    agent.cfg = SimpleNamespace(BASE_DIR=".")
    agent.code = SimpleNamespace(
        read_file=lambda path: (True, f"READ:{path}"),
        list_directory=lambda path: (True, f"LIST:{path}"),
        grep_files=lambda p, path, glob, c: (True, f"GREP:{p}:{path}:{glob}:{c}"),
        write_generated_test=lambda path, content, append=True: (True, f"WROTE:{path}:{append}:{len(content)}"),
        run_pytest_and_collect=lambda cmd, cwd: {"command": cmd, "cwd": cwd, "returncode": 0},
    )
    return agent


def test_qa_agent_parse_and_sanitize_helpers() -> None:
    assert QAAgent._parse_json_payload("") == {}
    assert QAAgent._parse_json_payload("{bad") == {"failure_summary": "{bad"}
    assert QAAgent._parse_json_payload("[1,2]") == {"failure_summary": "[1,2]"}
    assert QAAgent._suggest_test_path("") == "tests/test_generated_coverage.py"

    cleaned = QAAgent._sanitize_llm_code("```python\nassert True\n```")
    assert cleaned == "assert True"


def test_qa_agent_tools_and_run_task_routes(monkeypatch) -> None:
    agent = _build_agent()
    monkeypatch.setattr(agent, "_coverage_config_summary", lambda: {"fail_under": 90, "omit": [], "path": ".coveragerc", "exists": True, "show_missing": True, "skip_covered": False})

    async def _call_tool(name: str, arg: str):
        return f"TOOL:{name}:{arg}"

    async def _build(payload: str):
        return f"PLAN:{payload}"

    async def _gen(_target: str, _ctx: str):
        return "def test_generated():\n    assert True"

    monkeypatch.setattr(agent, "call_tool", _call_tool, raising=False)
    monkeypatch.setattr(agent, "_build_coverage_plan", _build)
    monkeypatch.setattr(agent, "_generate_test_code", _gen)

    assert asyncio.run(agent.run_task("")) == "[UYARI] Boş QA/Coverage görevi verildi."
    assert asyncio.run(agent.run_task("coverage_config")) == "TOOL:coverage_config:"
    assert asyncio.run(agent.run_task("read_file|core/a.py")) == "TOOL:read_file:core/a.py"
    assert asyncio.run(agent.run_task("coverage_plan|abc")) == "PLAN:abc"

    out = asyncio.run(agent.run_task("write_missing_tests|core/mod.py|ctx"))
    parsed = json.loads(out)
    assert parsed["success"] is True
    assert parsed["test_path"] == "tests/core/test_mod.py"

    assert asyncio.run(agent.run_task("coverage açığını kapat")) == "PLAN:coverage açığını kapat"


def test_qa_agent_tool_write_file_and_pytest() -> None:
    agent = _build_agent()

    empty = asyncio.run(agent._tool_write_file("{}"))
    assert json.loads(empty)["success"] is False

    payload = json.dumps({"path": "tests/test_x.py", "content": "assert True", "append": False})
    done = asyncio.run(agent._tool_write_file(payload))
    assert json.loads(done)["success"] is True

    run = asyncio.run(agent._tool_run_pytest(json.dumps({"command": "pytest -q tests", "cwd": "/tmp"})))
    assert json.loads(run)["command"] == "pytest -q tests"


def test_qa_agent_build_coverage_plan_payload(monkeypatch) -> None:
    agent = _build_agent()
    monkeypatch.setattr(agent, "_coverage_config_summary", lambda: {"fail_under": 90, "omit": ["web_server.py"], "path": ".coveragerc", "exists": True, "show_missing": True, "skip_covered": False})

    def _fake_remediation(payload, diagnosis):
        assert diagnosis
        return {
            "suspected_targets": ["managers/web_search.py", "agent/roles/qa_agent.py"],
            "remediation_loop": {"step": "write tests"},
            "root_cause_summary": "eksik branch testleri",
        }

    monkeypatch.setattr(_mod, "build_ci_remediation_payload", _fake_remediation)
    out = asyncio.run(agent._build_coverage_plan('{"diagnosis":"x"}'))
    parsed = json.loads(out)

    assert parsed["coverage"]["omit"] == ["web_server.py"]
    assert parsed["suggested_tests"][0] == "tests/managers/test_web_search.py"
    assert parsed["root_cause_summary"] == "eksik branch testleri"


def test_qa_agent_init_registers_tools(monkeypatch) -> None:
    registered: list[str] = []

    def fake_base_init(self, cfg=None, role_name=None):
        self.cfg = SimpleNamespace(BASE_DIR="/tmp/project")

    def fake_register_tool(self, name, fn):
        registered.append(name)

    monkeypatch.setattr(_mod.BaseAgent, "__init__", fake_base_init)
    monkeypatch.setattr(_mod.BaseAgent, "register_tool", fake_register_tool)
    monkeypatch.setattr(_mod, "SecurityManager", lambda cfg: "SEC")
    monkeypatch.setattr(_mod, "CodeManager", lambda security, base_dir: SimpleNamespace(security=security, base_dir=base_dir))

    agent = QAAgent()

    assert agent.security == "SEC"
    assert agent.code.base_dir == "/tmp/project"
    assert registered == [
        "read_file",
        "list_directory",
        "grep_search",
        "coverage_config",
        "ci_remediation",
        "write_file",
        "run_pytest",
    ]


def test_qa_agent_tool_helpers_and_remediation(monkeypatch, tmp_path) -> None:
    agent = _build_agent()
    agent.cfg = SimpleNamespace(BASE_DIR=str(tmp_path))

    (tmp_path / ".coveragerc").write_text(
        "[run]\nomit =\n  web_server.py,\n  tests/*\n[report]\nfail_under = 88\nshow_missing = true\nskip_covered = false\n",
        encoding="utf-8",
    )

    summary = agent._coverage_config_summary()
    assert summary["exists"] is True
    assert summary["fail_under"] == 88
    assert summary["omit"] == ["web_server.py", "tests/*"]

    assert json.loads(asyncio.run(agent._tool_coverage_config("")))["fail_under"] == 88

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(_mod.asyncio, "to_thread", fake_to_thread)

    assert asyncio.run(agent._tool_read_file("x.py")) == "READ:x.py"
    assert asyncio.run(agent._tool_list_directory("")) == "LIST:."
    assert asyncio.run(agent._tool_grep_search("needle|||src|||*.py|||5")) == "GREP:needle:src:*.py:5"
    assert asyncio.run(agent._tool_grep_search("needle|||src|||*.py|||oops")) == "GREP:needle:src:*.py:2"

    monkeypatch.setattr(_mod, "build_ci_remediation_payload", lambda payload, diagnosis: {"payload": payload, "diagnosis": diagnosis})
    rem = json.loads(asyncio.run(agent._tool_ci_remediation('{"diagnosis":"ozet","x":1}')))
    assert rem == {"payload": {"x": 1}, "diagnosis": "ozet"}


def test_qa_agent_generate_test_code_and_run_task_paths(monkeypatch) -> None:
    agent = _build_agent()

    monkeypatch.setattr(agent, "_coverage_config_summary", lambda: {"fail_under": 91, "omit": ["a.py"], "path": ".coveragerc", "exists": True, "show_missing": True, "skip_covered": False})

    captured = {}

    async def fake_call_llm(messages, system_prompt=None, temperature=None):
        captured["messages"] = messages
        captured["system_prompt"] = system_prompt
        captured["temperature"] = temperature
        return "```python\nassert 1\n```"

    monkeypatch.setattr(agent, "call_llm", fake_call_llm, raising=False)

    generated = asyncio.run(agent._generate_test_code("agent/roles/qa_agent.py", "  context here  "))
    assert generated == "assert 1"
    assert "Coverage fail_under: 91" in captured["messages"][0]["content"]
    assert "[BAGLAM]\ncontext here" in captured["messages"][0]["content"]
    assert captured["system_prompt"] == QAAgent.TEST_GENERATION_PROMPT

    async def fake_call_tool(name: str, arg: str):
        return f"TOOL:{name}:{arg}"

    async def fake_gen(target: str, ctx: str):
        return f"GEN:{target}:{ctx}"

    monkeypatch.setattr(agent, "call_tool", fake_call_tool, raising=False)
    monkeypatch.setattr(agent, "_generate_test_code", fake_gen)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(_mod.asyncio, "to_thread", fake_to_thread)

    assert asyncio.run(agent.run_task("list_directory|docs")) == "TOOL:list_directory:docs"
    assert asyncio.run(agent.run_task("grep_search|x|||.")) == "TOOL:grep_search:x|||."
    assert asyncio.run(agent.run_task("ci_remediation|{}")) == "TOOL:ci_remediation:{}"
    assert asyncio.run(agent.run_task("write_file|{}")) == "TOOL:write_file:{}"
    assert asyncio.run(agent.run_task("run_pytest|{}")) == "TOOL:run_pytest:{}"

    out = json.loads(asyncio.run(agent.run_task("write_missing_tests|mod.py|ctx")))
    assert out["generated_test"] == "GEN:mod.py:ctx"
    assert out["test_path"] == "tests/test_mod.py"

    assert asyncio.run(agent.run_task("düz bir istem")) == "GEN::düz bir istem"
