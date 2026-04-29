import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_qa_agent():
    module_name = "qa_agent_under_test"
    if module_name in sys.modules:
        return sys.modules[module_name].QAAgent
    if "httpx" not in sys.modules:
        sys.modules["httpx"] = ModuleType("httpx")
    module_path = Path("agent/roles/qa_agent.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.QAAgent


_load_qa_agent()
_QA_MODULE = sys.modules["qa_agent_under_test"]
QAAgent = _QA_MODULE.QAAgent


def test_load_qa_agent_returns_cached_module(monkeypatch):
    sentinel = object()
    cached_module = SimpleNamespace(QAAgent=sentinel)
    monkeypatch.setitem(sys.modules, "qa_agent_under_test", cached_module)

    assert _load_qa_agent() is sentinel


def test_load_qa_agent_injects_httpx_when_missing(monkeypatch):
    sentinel = object()

    class _Loader:
        def exec_module(self, module):
            module.QAAgent = sentinel

    fake_spec = SimpleNamespace(loader=_Loader())
    monkeypatch.delitem(sys.modules, "qa_agent_under_test", raising=False)
    monkeypatch.delitem(sys.modules, "httpx", raising=False)
    monkeypatch.setattr(
        importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: fake_spec
    )
    monkeypatch.setattr(
        importlib.util, "module_from_spec", lambda _spec: ModuleType("qa_agent_under_test")
    )

    loaded = _load_qa_agent()
    assert loaded is sentinel
    assert "httpx" in sys.modules


class DummyCode:
    def __init__(self):
        self.calls = []

    def read_file(self, arg):
        self.calls.append(("read_file", arg))
        return True, f"READ:{arg}"

    def list_directory(self, arg):
        self.calls.append(("list_directory", arg))
        return True, f"LIST:{arg}"

    def grep_files(self, pattern, path, file_glob, case_sensitive=True, context_lines=0, max_results=100):
        self.calls.append(("grep_files", pattern, path, file_glob, context_lines))
        return True, f"GREP:{pattern}:{path}:{file_glob}:{context_lines}"

    def write_generated_test(self, path, content, append=True):
        self.calls.append(("write_generated_test", path, content, append))
        return True, f"WROTE:{path}:{append}"

    def run_pytest_and_collect(self, command, cwd):
        self.calls.append(("run_pytest_and_collect", command, cwd))
        return {"success": True, "command": command, "cwd": cwd}


@pytest.fixture
def qa(tmp_path):
    agent = QAAgent.__new__(QAAgent)
    agent.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    agent.code = DummyCode()
    agent.tools = {}

    def register_tool(name, func):
        agent.tools[name] = func

    async def call_tool(name, arg):
        return await agent.tools[name](arg)

    agent.register_tool = register_tool
    agent.call_tool = call_tool
    return agent


def test_qa_fixture_register_tool_and_call_tool(qa):
    async def _tool(arg):
        return f"T:{arg}"

    qa.register_tool("x_tool", _tool)
    assert asyncio.run(qa.call_tool("x_tool", "arg")) == "T:arg"


def test_init_registers_tools(monkeypatch, tmp_path):
    events = []

    def fake_base_init(self, cfg=None, role_name="base"):
        self.cfg = cfg or SimpleNamespace(BASE_DIR=tmp_path)
        self.role_name = role_name
        self.tools = {}

    def fake_register_tool(self, name, func):
        self.tools[name] = func
        events.append(name)

    monkeypatch.setattr(_QA_MODULE.BaseAgent, "__init__", fake_base_init, raising=False)
    monkeypatch.setattr(_QA_MODULE.BaseAgent, "register_tool", fake_register_tool, raising=False)
    monkeypatch.setattr(_QA_MODULE, "SecurityManager", lambda cfg=None: object())

    class FakeCode:
        def __init__(self, security, base_dir):
            self.security = security
            self.base_dir = base_dir

    monkeypatch.setattr(_QA_MODULE, "CodeManager", FakeCode)

    a = QAAgent(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    assert a.role_name == "qa"
    assert isinstance(a.code, FakeCode)
    assert events == [
        "read_file",
        "list_directory",
        "grep_search",
        "coverage_config",
        "ci_remediation",
        "write_file",
        "run_pytest",
    ]


def test_helpers_and_parsers(tmp_path, qa):
    (tmp_path / ".coveragerc").write_text(
        "[run]\nomit = a.py, b.py\n c.py\n[report]\nfail_under=90\nshow_missing=true\nskip_covered=false\n",
        encoding="utf-8",
    )
    summary = qa._coverage_config_summary()
    assert summary["exists"] is True
    assert summary["fail_under"] == 90
    assert summary["show_missing"] is True
    assert summary["skip_covered"] is False
    assert summary["omit"] == ["a.py", "b.py", "c.py"]

    assert QAAgent._parse_json_payload("") == {}
    assert QAAgent._parse_json_payload('{"k":1}') == {"k": 1}
    assert QAAgent._parse_json_payload("[1,2]") == {"failure_summary": "[1,2]"}
    assert QAAgent._parse_json_payload("not-json") == {"failure_summary": "not-json"}

    assert QAAgent._suggest_test_path("") == "tests/test_generated_coverage.py"
    assert QAAgent._suggest_test_path("./pkg/module.py") == "tests/pkg/test_module.py"
    assert QAAgent._suggest_test_path("module.py") == "tests/test_module.py"

    assert QAAgent._sanitize_llm_code("plain") == "plain"
    assert QAAgent._sanitize_llm_code("```python\nassert True\n```") == "assert True"
    assert QAAgent._sanitize_llm_code("```python\nassert True") == "assert True"


def test_tool_methods(qa):
    assert asyncio.run(qa._tool_read_file("x.py")) == "READ:x.py"
    assert asyncio.run(qa._tool_list_directory("")) == "LIST:."

    grep = asyncio.run(qa._tool_grep_search("needle|||src|||*.py|||3"))
    assert grep == "GREP:needle:src:*.py:3"
    grep_default = asyncio.run(qa._tool_grep_search("needle"))
    assert grep_default == "GREP:needle:.:*:2"

    coverage_json = asyncio.run(qa._tool_coverage_config(""))
    assert json.loads(coverage_json)["path"].endswith(".coveragerc")

    rem = asyncio.run(qa._tool_ci_remediation('{"failure_summary":"boom","diagnosis":"d"}'))
    rem_data = json.loads(rem)
    assert isinstance(rem_data, dict) and rem_data

    wr = asyncio.run(qa._tool_write_file('{"path":"tests/t.py","content":"x=1","append":false}'))
    wr_data = json.loads(wr)
    assert wr_data["success"] is True
    assert wr_data["path"] == "tests/t.py"

    missing_path = asyncio.run(qa._tool_write_file('{"content":"x"}'))
    assert json.loads(missing_path)["success"] is False

    run = asyncio.run(qa._tool_run_pytest('{"command":"pytest -q tests","cwd":"/tmp"}'))
    run_data = json.loads(run)
    assert run_data["command"] == "pytest -q tests"
    run_default = asyncio.run(qa._tool_run_pytest("{}"))
    assert json.loads(run_default)["command"] == "pytest -q"


def test_generate_and_build_plan(qa, monkeypatch):
    async def fake_llm(messages, system_prompt, temperature):
        assert "Hedef modül: src/a.py" in messages[0]["content"]
        assert system_prompt == QAAgent.TEST_GENERATION_PROMPT
        assert temperature == 0.1
        return "```python\ndef test_x():\n    assert True\n```"

    qa.call_llm = fake_llm

    code = asyncio.run(qa._generate_test_code("src/a.py", "ctx"))
    assert "def test_x" in code

    plan = asyncio.run(
        qa._build_coverage_plan('{"diagnosis":"plan","suspected_targets":["a.py","pkg/b.py"]}')
    )
    plan_data = json.loads(plan)
    assert plan_data["coverage"]["path"].endswith(".coveragerc")
    assert isinstance(plan_data["suggested_tests"], list)


def test_run_task_routes(qa, monkeypatch):
    async def fake_tool(name, arg):
        return f"TOOL:{name}:{arg}"

    async def fake_build(payload):
        return f"PLAN:{payload}"

    async def fake_generate(target, context):
        return f"GEN:{target}:{context}"

    qa.call_tool = fake_tool
    qa._build_coverage_plan = fake_build
    qa._generate_test_code = fake_generate

    assert asyncio.run(qa.run_task("")) == "[UYARI] Boş QA/Coverage görevi verildi."
    assert asyncio.run(qa.run_task("coverage_config")) == "TOOL:coverage_config:"
    assert asyncio.run(qa.run_task("read_file| a.py ")) == "TOOL:read_file:a.py"
    assert asyncio.run(qa.run_task("list_directory| src ")) == "TOOL:list_directory:src"
    assert asyncio.run(qa.run_task("grep_search|x|||.")) == "TOOL:grep_search:x|||."
    assert asyncio.run(qa.run_task("ci_remediation|{}")) == "TOOL:ci_remediation:{}"
    assert asyncio.run(qa.run_task("coverage_plan|abc")) == "PLAN:abc"
    assert asyncio.run(qa.run_task("write_file|{}")) == "TOOL:write_file:{}"
    assert asyncio.run(qa.run_task("run_pytest|{}")) == "TOOL:run_pytest:{}"

    # write_missing_tests path
    qa.code = DummyCode()
    qa._generate_test_code = fake_generate
    res = asyncio.run(qa.run_task("write_missing_tests|src/m.py|ctx"))
    data = json.loads(res)
    assert data["success"] is True
    assert data["test_path"] == "tests/src/test_m.py"
    assert data["generated_test"] == "GEN:src/m.py:ctx"

    assert asyncio.run(qa.run_task("coverage sorunu var")) == "PLAN:coverage sorunu var"
    assert asyncio.run(qa.run_task("tamamen farklı bir istek")) == "GEN::tamamen farklı bir istek"
