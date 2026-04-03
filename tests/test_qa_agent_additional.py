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

    monkeypatch.setattr(agent, "call_tool", _call_tool)
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
