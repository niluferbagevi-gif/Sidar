import asyncio
import json
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import agent.roles.coverage_agent as _COVERAGE_MODULE
from agent.roles.coverage_agent import CoverageAgent


def make_agent(tmp_path, code_manager):
    a = CoverageAgent.__new__(CoverageAgent)
    a.cfg = SimpleNamespace(BASE_DIR=tmp_path)
    a.role_name = "coverage"
    a.code = code_manager
    a.tools = {}
    a._db = None
    a._db_lock = None

    def register_tool(name, func):
        a.tools[name] = func

    async def call_tool(name, arg):
        return await a.tools[name](arg)

    a.register_tool = register_tool
    a.call_tool = call_tool
    return a


def test_init_registers_tools(monkeypatch, tmp_path):
    events = []

    def fake_base_init(self, cfg=None, role_name="base"):
        self.cfg = cfg or SimpleNamespace(BASE_DIR=tmp_path)
        self.role_name = role_name
        self.tools = {}

    def fake_register_tool(self, name, func):
        self.tools[name] = func
        events.append(name)

    class FakeSecurity:
        def __init__(self, cfg=None):
            self.cfg = cfg

    class FakeCode:
        def __init__(self, security, base_dir):
            self.security = security
            self.base_dir = base_dir

    managers_pkg = ModuleType("managers")
    managers_code = ModuleType("managers.code_manager")
    managers_security = ModuleType("managers.security")
    managers_code.CodeManager = FakeCode
    managers_security.SecurityManager = FakeSecurity

    monkeypatch.setitem(sys.modules, "managers", managers_pkg)
    monkeypatch.setitem(sys.modules, "managers.code_manager", managers_code)
    monkeypatch.setitem(sys.modules, "managers.security", managers_security)
    monkeypatch.setattr(_COVERAGE_MODULE.BaseAgent, "__init__", fake_base_init, raising=False)
    monkeypatch.setattr(_COVERAGE_MODULE.BaseAgent, "register_tool", fake_register_tool, raising=False)

    created = CoverageAgent(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    assert created.role_name == "coverage"
    assert isinstance(created.code, FakeCode)
    assert events == [
        "run_pytest",
        "analyze_pytest_output",
        "analyze_coverage_report",
        "generate_missing_tests",
        "write_missing_tests",
    ]


def test_static_helpers_and_parsers(tmp_path):
    assert CoverageAgent._parse_payload("") == {}
    assert CoverageAgent._parse_payload('{"k":1}') == {"k": 1}
    assert CoverageAgent._parse_payload("[1]") == {"command": "[1]"}
    assert CoverageAgent._parse_payload("pytest -q") == {"command": "pytest -q"}
    assert CoverageAgent._parse_payload("başka") == {
        "instruction": "başka",
        "command": "pytest --cov=. --cov-report=xml --cov-report=term",
    }

    assert CoverageAgent._suggest_test_path("") == "tests/test_generated_coverage_agent.py"
    assert CoverageAgent._suggest_test_path("module.py") == "tests/test_module_coverage.py"
    assert CoverageAgent._suggest_test_path("./pkg/module.py") == "tests/pkg/test_module_coverage.py"

    assert CoverageAgent._clean_code_output("plain") == "plain"
    assert CoverageAgent._clean_code_output("```python\na=1\n```") == "a=1"
    assert CoverageAgent._clean_code_output("```") == ""
    assert CoverageAgent._clean_code_output("```python\na=1") == "a=1"

    assert CoverageAgent._normalize_analysis("x") == {"summary": "", "findings": []}
    normalized = CoverageAgent._normalize_analysis({"summary": None, "findings": [{"a": 1}, "bad"]})
    assert normalized["summary"] == ""
    assert normalized["findings"] == [{"a": 1}]

    cfg_path = tmp_path / ".coveragerc"
    cfg_path.write_text("[run]\ninclude = src/*\n[report]\nomit = tests/*\n", encoding="utf-8")
    parsed_cfg = CoverageAgent._read_coveragerc(str(cfg_path))
    assert parsed_cfg["exists"] is True
    assert parsed_cfg["run"]["include"] == "src/*"
    assert parsed_cfg["report"]["omit"] == "tests/*"
    missing_cfg = CoverageAgent._read_coveragerc(str(tmp_path / "none.rc"))
    assert missing_cfg["exists"] is False


def test_parse_coverage_xml_and_terminal(tmp_path):
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(
        """
<coverage>
  <packages>
    <package>
      <classes>
        <class filename="agent/roles/coverage_agent.py" line-rate="0.5" branch-rate="0.25">
          <lines>
            <line number="10" hits="0"/>
            <line number="11" hits="1"/>
            <line number="12" hits="0" branch="true" condition-coverage="50% (1/2)"/>
          </lines>
        </class>
        <class filename="agent/ok.py" line-rate="1.0" branch-rate="1.0">
          <lines><line number="1" hits="1"/></lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
        """.strip(),
        encoding="utf-8",
    )

    xml_data = CoverageAgent._parse_coverage_xml(str(xml_path), limit=1)
    assert xml_data["exists"] is True
    assert xml_data["total_findings"] == 1
    assert xml_data["findings"][0]["target_path"] == "agent/roles/coverage_agent.py"
    assert xml_data["findings"][0]["missing_lines"] == [10, 12]

    xml_missing = CoverageAgent._parse_coverage_xml(str(tmp_path / "missing.xml"))
    assert xml_missing["exists"] is False

    xml_empty = tmp_path / "coverage_empty.xml"
    xml_empty.write_text("", encoding="utf-8")
    empty_data = CoverageAgent._parse_coverage_xml(str(xml_empty))
    assert empty_data["exists"] is True
    assert empty_data["summary"] == "coverage.xml ayrıştırılamadı."
    assert empty_data["findings"] == []

    xml_invalid = tmp_path / "coverage_invalid.xml"
    xml_invalid.write_text("<coverage><packages>", encoding="utf-8")
    invalid_data = CoverageAgent._parse_coverage_xml(str(xml_invalid))
    assert invalid_data["exists"] is True
    assert invalid_data["summary"] == "coverage.xml ayrıştırılamadı."
    assert invalid_data["findings"] == []

    xml_blank_filename = tmp_path / "coverage_blank_filename.xml"
    xml_blank_filename.write_text(
        """
<coverage>
  <packages>
    <package>
      <classes>
        <class filename="" line-rate="0.3" branch-rate="0.2">
          <lines><line number="1" hits="0"/></lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
        """.strip(),
        encoding="utf-8",
    )
    blank_data = CoverageAgent._parse_coverage_xml(str(xml_blank_filename))
    assert blank_data["files"] == []
    assert blank_data["findings"] == []

    term = """
Name                               Stmts   Miss Branch BrPart   Cover   Missing
agent/roles/coverage_agent.py     260    217     80      1  12%   20
agent/roles/ok.py                 100      0      0      0 100%
"""
    term_data = CoverageAgent._parse_terminal_coverage_output(term, limit=2)
    assert term_data["total_findings"] == 1
    assert term_data["findings"][0]["target_path"] == "agent/roles/coverage_agent.py"

    assert CoverageAgent._parse_terminal_coverage_output("")["summary"] == "Coverage terminal çıktısı boş."
    assert CoverageAgent._parse_terminal_coverage_output("not parsable")["summary"] == "Coverage terminal çıktısı ayrıştırılamadı."


def test_build_dynamic_prompt():
    prompt = CoverageAgent._build_dynamic_pytest_prompt(
        finding={"target_path": "src/a.py", "missing_lines": [1, 2], "missing_branches": ["3:50%"]},
        coveragerc={"run": {"include": "src/*"}, "report": {"omit": "tests/*"}},
    )
    assert "Hedef dosya: src/a.py" in prompt
    assert "Eksik satırlar: 1, 2" in prompt
    assert ".coveragerc include: src/*" in prompt


@pytest.mark.asyncio
async def test_tool_methods(tmp_path, fake_coverage_code_manager):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    run_json = await agent._tool_run_pytest('{"command":"pytest -q","cwd":"/tmp"}')
    assert json.loads(run_json)["analysis"]["summary"] == "ok"

    analyze_json = await agent._tool_analyze_pytest_output('{"output":"ERR"}')
    assert json.loads(analyze_json)["summary"] == "ANALYZED:ERR"

    cov_xml = tmp_path / "coverage.xml"
    cov_xml.write_text("<coverage></coverage>", encoding="utf-8")
    rc = tmp_path / ".coveragerc"
    rc.write_text("[run]\ninclude=src/*\n", encoding="utf-8")
    cov_json = await agent._tool_analyze_coverage_report(
        json.dumps(
            {
                "coverage_xml": str(cov_xml),
                "coveragerc": str(rc),
                "coverage_output": "not parsable",
                "limit": 3,
            }
        )
    )
    cov_data = json.loads(cov_json)
    assert "coverage_xml" in cov_data
    assert "coverage_terminal" in cov_data
    assert cov_data["findings"] == []

    cov_xml2 = tmp_path / "coverage2.xml"
    cov_xml2.write_text(
        """
<coverage>
  <packages><package><classes>
    <class filename="src/covered.py" line-rate="0.5" branch-rate="1.0">
      <lines><line number="9" hits="0"/></lines>
    </class>
  </classes></package></packages>
</coverage>
        """.strip(),
        encoding="utf-8",
    )
    cov_json2 = await agent._tool_analyze_coverage_report(
        json.dumps({"coverage_xml": str(cov_xml2), "coverage_output": ""})
    )
    cov_data2 = json.loads(cov_json2)
    assert cov_data2["findings"][0]["target_path"] == "src/covered.py"

    async def fake_llm(messages, system_prompt, temperature):
        assert system_prompt == CoverageAgent.TEST_GENERATION_PROMPT
        assert temperature == 0.1
        return "```python\ndef test_ok():\n    assert True\n```"

    agent.call_llm = fake_llm
    gen_cov = await agent._tool_generate_missing_tests(
        json.dumps(
            {
                "coverage_finding": {"target_path": "src/m.py", "missing_lines": [5], "missing_branches": []},
                "coveragerc": {"run": {"include": "src/*"}},
            }
        )
    )
    assert "test_ok" in gen_cov

    gen_from_output = await agent._tool_generate_missing_tests(
        json.dumps({"target_path": "src/m.py", "pytest_output": "FAIL"})
    )
    assert "test_ok" in gen_from_output
    gen_from_analysis = await agent._tool_generate_missing_tests(
        json.dumps(
            {
                "target_path": "src/m.py",
                "analysis": {"summary": "ready", "findings": [{"target_path": "src/m.py"}]},
            }
        )
    )
    assert "test_ok" in gen_from_analysis

    write_json = await agent._tool_write_missing_tests(
        '{"suggested_test_path":"tests/a.py","generated_test":"```python\\na=1\\n```","append":false}'
    )
    write_data = json.loads(write_json)
    assert write_data["success"] is True
    assert write_data["suggested_test_path"] == "tests/a.py"


@pytest.mark.asyncio
async def test_write_missing_tests_failure(tmp_path, fake_coverage_code_manager, mocker):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    mocker.patch.object(agent.code, "write_generated_test", return_value=(False, "Permission Denied"))

    write_json = await agent._tool_write_missing_tests(
        '{"suggested_test_path":"tests/fail.py","generated_test":"print(1)","append":false}'
    )
    write_data = json.loads(write_json)
    assert write_data["success"] is False
    assert "Permission Denied" in write_data["message"]


@pytest.mark.asyncio
async def test_ensure_db_timeout_guard(tmp_path, fake_coverage_code_manager):
    agent = make_agent(tmp_path, fake_coverage_code_manager)

    class BlockingLock:
        async def __aenter__(self):
            await asyncio.Future()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    agent._db_lock = BlockingLock()

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(agent._ensure_db(), timeout=0.01)


@pytest.mark.asyncio
async def test_ensure_db_and_record_task(tmp_path, monkeypatch, fake_coverage_code_manager, fake_coverage_db_class):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    core_pkg = ModuleType("core")
    core_db = ModuleType("core.db")
    core_db.Database = fake_coverage_db_class
    monkeypatch.setitem(sys.modules, "core", core_pkg)
    monkeypatch.setitem(sys.modules, "core.db", core_db)

    db1 = await agent._ensure_db()
    db2 = await agent._ensure_db()
    assert db1 is db2
    assert db1.connected == 1
    assert db1.inited == 1

    await agent._record_task(
        command="pytest",
        pytest_output="OUT",
        analysis={"findings": [{"finding_type": "gap", "target_path": "a.py", "summary": "s"}]},
        generated_test="def test_x(): pass",
        review_payload={"target_path": "a.py", "suggested_test_path": "tests/test_a.py"},
        status="tests_written",
    )
    assert db1.created and db1.findings


@pytest.mark.asyncio
async def test_ensure_db_when_lock_already_exists(tmp_path, monkeypatch, fake_coverage_code_manager, fake_coverage_db_class):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    agent._db_lock = asyncio.Lock()
    core_pkg = ModuleType("core")
    core_db = ModuleType("core.db")
    core_db.Database = fake_coverage_db_class
    monkeypatch.setitem(sys.modules, "core", core_pkg)
    monkeypatch.setitem(sys.modules, "core.db", core_db)

    db = await agent._ensure_db()
    assert db.connected == 1
    assert db.inited == 1


@pytest.mark.asyncio
async def test_ensure_db_returns_existing_db_inside_lock(tmp_path, fake_coverage_code_manager):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    existing_db = SimpleNamespace(name="already-ready")

    class LockThatInjectsDB:
        async def __aenter__(self):
            agent._db = existing_db
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    agent._db_lock = LockThatInjectsDB()
    db = await agent._ensure_db()
    assert db is existing_db


@pytest.mark.asyncio
async def test_ensure_db_concurrency(tmp_path, monkeypatch, fake_coverage_code_manager, fake_coverage_db_class):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    core_pkg = ModuleType("core")
    core_db = ModuleType("core.db")
    core_db.Database = fake_coverage_db_class
    monkeypatch.setitem(sys.modules, "core", core_pkg)
    monkeypatch.setitem(sys.modules, "core.db", core_db)

    db_a, db_b = await asyncio.gather(agent._ensure_db(), agent._ensure_db())
    assert db_a is db_b
    assert db_a.connected == 1
    assert db_a.inited == 1


def test_parse_terminal_coverage_skips_empty_path(monkeypatch):
    class FakeMatch:
        @staticmethod
        def groupdict():
            return {"path": "", "miss": "1", "branch": "0", "brpart": "0", "cover": "90", "missing": ""}

    class FakePattern:
        @staticmethod
        def match(_line):
            return FakeMatch()

    monkeypatch.setattr(_COVERAGE_MODULE.re, "compile", lambda _pattern: FakePattern())
    data = CoverageAgent._parse_terminal_coverage_output("dummy")
    assert data["summary"] == "Coverage terminal çıktısı ayrıştırılamadı."


def test_module_sets_agentcatalog_get_fallback(monkeypatch):
    module_path = Path("agent/roles/coverage_agent.py")
    import importlib.util

    from agent.registry import AgentCatalog as RealCatalog

    had_get = hasattr(RealCatalog, "get")
    original_get = getattr(RealCatalog, "get", None)
    if had_get:
        monkeypatch.delattr(RealCatalog, "get", raising=False)

    try:
        base_agent_mod = ModuleType("agent.base_agent")
        base_agent_mod.BaseAgent = type("BaseAgent", (), {})
        monkeypatch.setitem(sys.modules, "agent.base_agent", base_agent_mod)
        spec = importlib.util.spec_from_file_location("coverage_agent_no_get", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["coverage_agent_no_get"] = module
        spec.loader.exec_module(module)
        assert hasattr(RealCatalog, "get")
        assert RealCatalog.get("anything") is None
    finally:
        if had_get and original_get is not None:
            RealCatalog.get = original_get


def test_clean_code_output_handles_closing_fence_without_opening_hint():
    class FakeStr(str):
        def splitlines(self):
            return []

    class WeirdStringable:
        def __str__(self):
            return FakeStr("```synthetic")

    assert CoverageAgent._clean_code_output(WeirdStringable()) == ""


def test_clean_code_output_real_markdown_fence_cleanup():
    cleaned = CoverageAgent._clean_code_output(" ```python\nprint('hi')\n``` ")
    assert cleaned == "print('hi')"


def test_clean_code_output_handles_multiple_and_nested_like_fences():
    multi_block = (
        "```python\n"
        "def test_a():\n"
        "    assert True\n"
        "```\n"
        "Açıklama\n"
        "```python\n"
        "def test_b():\n"
        "    code = \"\"\"```not-a-fence```\"\"\"\n"
        "    assert code\n"
        "```"
    )
    cleaned = CoverageAgent._clean_code_output(multi_block)
    assert "def test_a():" in cleaned
    assert "def test_b():" in cleaned
    assert "Açıklama" not in cleaned


def test_complex_code_sanitization():
    raw = (
        "Giriş metni\n"
        "```python\nx = 1\n```\n"
        "```js\nconsole.log('x')\n```\n"
        "```python\ny = 2\n```"
    )
    cleaned = CoverageAgent._clean_code_output(raw)
    assert cleaned == "x = 1\n\ny = 2"


def test_parse_coverage_xml_branch_line_with_full_coverage_is_ignored(tmp_path):
    xml_path = tmp_path / "coverage_full_branch.xml"
    xml_path.write_text(
        """
<coverage>
  <packages>
    <package>
      <classes>
        <class filename="pkg/mod.py" line-rate="1.0" branch-rate="1.0">
          <lines>
            <line number="5" hits="1" branch="true" condition-coverage="100% (2/2)"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
        """.strip(),
        encoding="utf-8",
    )

    data = CoverageAgent._parse_coverage_xml(str(xml_path))
    assert data["findings"] == []
    assert data["files"][0]["missing_branches_count"] == 0


@pytest.mark.asyncio
async def test_run_task_routes_and_flows(tmp_path, fake_coverage_code_manager):
    agent = make_agent(tmp_path, fake_coverage_code_manager)

    async def fake_tool(name, arg):
        return f"TOOL:{name}:{arg}"

    agent.call_tool = fake_tool
    empty_task_result = await agent.run_task("")
    assert "Boş coverage" in empty_task_result or "UYARI" in empty_task_result
    assert await agent.run_task("run_pytest|{}") == "TOOL:run_pytest:{}"
    assert await agent.run_task("analyze_pytest_output|X") == "TOOL:analyze_pytest_output:X"
    assert await agent.run_task("analyze_coverage_report|Y") == "TOOL:analyze_coverage_report:Y"
    assert await agent.run_task("generate_missing_tests|Z") == "TOOL:generate_missing_tests:Z"
    assert await agent.run_task("write_missing_tests|W") == "TOOL:write_missing_tests:W"

    # no gaps path
    no_gap = await agent.run_task('{"command":"pytest -q","cwd":"."}')
    no_gap_data = json.loads(no_gap)
    assert no_gap_data["status"] == "no_gaps_detected"

    # writing path with successful record
    agent.code.run_pytest_and_collect = lambda command, cwd: {
        "output": "OUT",
        "analysis": {"summary": "HAS GAP", "findings": [{"target_path": "src/a.py", "summary": "gap"}]},
    }

    async def fake_candidate(target_path, pytest_output, analysis):
        assert target_path == "src/a.py"
        return "```python\ndef test_x():\n    assert True\n```"

    agent._generate_test_candidate = fake_candidate

    recorded = {"called": False}

    async def fake_record(**kwargs):
        recorded["called"] = True

    agent._record_task = fake_record
    written = await agent.run_task('{"command":"pytest --cov=.","cwd":"."}')
    written_data = json.loads(written)
    assert written_data["status"] == "tests_written"
    assert written_data["target_path"] == "src/a.py"
    assert written_data["is_approved"] is False
    assert written_data["approval_status"] == "pending_reviewer_or_human"
    assert recorded["called"] is True

    # record exception path is swallowed
    async def boom_record(**kwargs):
        raise RuntimeError("db down")

    agent._record_task = boom_record
    written2 = await agent.run_task('{"command":"pytest --cov=.","cwd":"."}')
    assert json.loads(written2)["success"] is True


@pytest.mark.asyncio
async def test_run_task_analyze_coverage_report_handles_invalid_xml_fail_safe(tmp_path, fake_coverage_code_manager):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    agent.register_tool("analyze_coverage_report", agent._tool_analyze_coverage_report)

    invalid_xml = tmp_path / "broken.xml"
    invalid_xml.write_text("<coverage><packages>", encoding="utf-8")

    payload = json.dumps(
        {
            "coverage_xml": str(invalid_xml),
            "coverage_output": (
                "Name Stmts Miss Branch BrPart Cover Missing\n"
                "src/app.py 10 2 0 0 80% 3-4\n"
            ),
        }
    )
    result = await agent.run_task(f"analyze_coverage_report|{payload}")
    data = json.loads(result)

    assert data["coverage_xml"]["summary"] == "coverage.xml ayrıştırılamadı."
    assert data["coverage_terminal"]["total_findings"] == 1
    assert data["findings"][0]["target_path"] == "src/app.py"
