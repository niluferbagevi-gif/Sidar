import asyncio
import importlib
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import agent.roles.coverage_agent as _COVERAGE_MODULE
from agent.roles.coverage_agent import CoverageAgent

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reload_coverage_agent_module():
    """CoverageAgent testlerini diğer testlerin module stub etkilerinden izole et."""
    global _COVERAGE_MODULE, CoverageAgent
    base_agent_module = importlib.import_module("agent.base_agent")
    importlib.reload(base_agent_module)
    coverage_module = importlib.import_module("agent.roles.coverage_agent")
    _COVERAGE_MODULE = importlib.reload(coverage_module)
    CoverageAgent = _COVERAGE_MODULE.CoverageAgent


def make_agent(tmp_path, code_manager):
    a = CoverageAgent(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    a.code = code_manager
    return a


async def test_init_registers_tools(mocker, tmp_path):
    events = []

    def fake_base_init(self, cfg=None, role_name="base"):
        self.cfg = cfg or SimpleNamespace(BASE_DIR=tmp_path)
        self.role_name = role_name
        self.tools = {}

    def fake_register_tool(self, name, func):
        self.tools[name] = func
        events.append(name)

    security_cls = mocker.patch("managers.security.SecurityManager", autospec=True)
    code_cls = mocker.patch("managers.code_manager.CodeManager", autospec=True)
    mocker.patch.object(
        _COVERAGE_MODULE.BaseAgent, "__init__", side_effect=fake_base_init, autospec=True
    )
    mocker.patch.object(
        _COVERAGE_MODULE.BaseAgent, "register_tool", side_effect=fake_register_tool, autospec=True
    )

    created = CoverageAgent(cfg=SimpleNamespace(BASE_DIR=tmp_path))
    assert created.role_name == "coverage"
    security_cls.assert_called_once_with(cfg=created.cfg)
    code_cls.assert_called_once_with(security_cls.return_value, base_dir=created.cfg.BASE_DIR)
    assert created.code is code_cls.return_value
    assert events == [
        "run_pytest",
        "analyze_pytest_output",
        "analyze_coverage_report",
        "generate_missing_tests",
        "write_missing_tests",
    ]


async def test_reload_fixture_recovers_from_stubbed_base_agent(monkeypatch, tmp_path):
    class _BrokenBaseAgent:
        def __init__(self, cfg=None, role_name="broken"):
            self.cfg = cfg
            self.role_name = role_name

    monkeypatch.setattr(_COVERAGE_MODULE, "BaseAgent", _BrokenBaseAgent, raising=True)
    reloaded = importlib.reload(_COVERAGE_MODULE)
    recovered_cls = reloaded.CoverageAgent
    created = recovered_cls(cfg=SimpleNamespace(BASE_DIR=tmp_path))

    assert hasattr(reloaded.BaseAgent, "register_tool")
    assert "run_pytest" in created.tools


async def test_static_helpers_and_parsers(tmp_path):
    assert CoverageAgent._parse_payload("") == {}
    assert CoverageAgent._parse_payload('{"k":1}') == {"k": 1}
    assert CoverageAgent._parse_payload("[1]") == {"command": "[1]"}
    assert CoverageAgent._parse_payload("pytest -q") == {"command": "pytest -q"}
    assert CoverageAgent._parse_payload("başka") == {
        "instruction": "başka",
        "command": "pytest --cov=. --cov-report=xml --cov-report=term",
    }

    assert CoverageAgent._suggest_test_path("") == "tests/test_generated.py"
    assert CoverageAgent._suggest_test_path("module.py") == "tests/test_module.py"
    assert CoverageAgent._suggest_test_path("./pkg/module.py") == "tests/pkg/test_module.py"
    assert "_coverage" not in CoverageAgent._suggest_test_path("module.py")
    assert "_coverage" not in CoverageAgent._suggest_test_path("./pkg/module.py")

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


async def test_parse_coverage_xml_and_terminal(tmp_path):
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

    assert (
        CoverageAgent._parse_terminal_coverage_output("")["summary"]
        == "Coverage terminal çıktısı boş."
    )
    assert (
        CoverageAgent._parse_terminal_coverage_output("not parsable")["summary"]
        == "Coverage terminal çıktısı ayrıştırılamadı."
    )


async def test_build_dynamic_prompt():
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
                "coverage_finding": {
                    "target_path": "src/m.py",
                    "missing_lines": [5],
                    "missing_branches": [],
                },
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
    mocker.patch.object(
        agent.code, "write_generated_test", return_value=(False, "Permission Denied")
    )

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
    assert await agent._db_lock.__aexit__(None, None, None) is False


@pytest.mark.asyncio
async def test_ensure_db_and_record_task(
    tmp_path, monkeypatch, fake_coverage_code_manager, fake_coverage_db_class
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    core_pkg = ModuleType("core")
    core_db = ModuleType("core.db")
    core_db.Database = fake_coverage_db_class
    monkeypatch.setitem(sys.modules, "core", core_pkg)
    monkeypatch.setitem(sys.modules, "core.db", core_db)

    db1 = await agent._ensure_db()
    db2 = await agent._ensure_db()
    assert db1 is db2
    db1.connect.assert_awaited_once()
    db1.init_schema.assert_awaited_once()

    await agent._record_task(
        command="pytest",
        pytest_output="OUT",
        analysis={"findings": [{"finding_type": "gap", "target_path": "a.py", "summary": "s"}]},
        generated_test="def test_x(): pass",
        review_payload={"target_path": "a.py", "suggested_test_path": "tests/test_a.py"},
        status="tests_written",
    )
    db1.create_coverage_task.assert_awaited_once()
    db1.add_coverage_finding.assert_awaited()


@pytest.mark.asyncio
async def test_ensure_db_when_lock_already_exists(
    tmp_path, monkeypatch, fake_coverage_code_manager, fake_coverage_db_class
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    agent._db_lock = asyncio.Lock()
    core_pkg = ModuleType("core")
    core_db = ModuleType("core.db")
    core_db.Database = fake_coverage_db_class
    monkeypatch.setitem(sys.modules, "core", core_pkg)
    monkeypatch.setitem(sys.modules, "core.db", core_db)

    db = await agent._ensure_db()
    db.connect.assert_awaited_once()
    db.init_schema.assert_awaited_once()


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
async def test_ensure_db_concurrency(
    tmp_path, monkeypatch, fake_coverage_code_manager, fake_coverage_db_class
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    core_pkg = ModuleType("core")
    core_db = ModuleType("core.db")
    core_db.Database = fake_coverage_db_class
    monkeypatch.setitem(sys.modules, "core", core_pkg)
    monkeypatch.setitem(sys.modules, "core.db", core_db)

    db_a, db_b = await asyncio.gather(agent._ensure_db(), agent._ensure_db())
    assert db_a is db_b
    db_a.connect.assert_awaited_once()
    db_a.init_schema.assert_awaited_once()


async def test_parse_terminal_coverage_skips_empty_path():
    class FakeMatch:
        @staticmethod
        def groupdict():
            return {
                "path": "   ",
                "stmts": "10",
                "miss": "1",
                "branch": "0",
                "brpart": "0",
                "cover": "90",
                "missing": "1",
            }

    class FakePattern:
        @staticmethod
        def match(_line):
            return FakeMatch()

    original_compile = _COVERAGE_MODULE.re.compile
    _COVERAGE_MODULE.re.compile = lambda _pattern: FakePattern()
    try:
        coverage_output = "agent/roles/coverage_agent.py 10 1 0 0 90% 1\n"
        data = CoverageAgent._parse_terminal_coverage_output(coverage_output)
    finally:
        _COVERAGE_MODULE.re.compile = original_compile
    assert data["summary"] == "Coverage terminal çıktısı ayrıştırılamadı."


async def test_clean_code_output_handles_closing_fence_without_opening_hint():
    class FakeStr(str):
        def splitlines(self):
            return []

    class WeirdStringable:
        def __str__(self):
            return FakeStr("```synthetic")

    assert CoverageAgent._clean_code_output(WeirdStringable()) == ""
    assert FakeStr("```synthetic").splitlines() == []


async def test_clean_code_output_real_markdown_fence_cleanup():
    cleaned = CoverageAgent._clean_code_output(" ```python\nprint('hi')\n``` ")
    assert cleaned == "print('hi')"


async def test_clean_code_output_handles_multiple_and_nested_like_fences():
    multi_block = (
        "```python\n"
        "def test_a():\n"
        "    assert True\n"
        "```\n"
        "Açıklama\n"
        "```python\n"
        "def test_b():\n"
        '    code = """```not-a-fence```"""\n'
        "    assert code\n"
        "```"
    )
    cleaned = CoverageAgent._clean_code_output(multi_block)
    assert "def test_a():" in cleaned
    assert "def test_b():" in cleaned
    assert "Açıklama" not in cleaned


async def test_complex_code_sanitization():
    raw = (
        "Giriş metni\n"
        "```python\nx = 1\n```\n"
        "```js\nconsole.log('x')\n```\n"
        "```python\ny = 2\n```"
    )
    cleaned = CoverageAgent._clean_code_output(raw)
    assert cleaned == "x = 1\n\ny = 2"


async def test_parse_coverage_xml_branch_line_with_full_coverage_is_ignored(tmp_path):
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
        "analysis": {
            "summary": "HAS GAP",
            "findings": [{"target_path": "src/a.py", "summary": "gap"}],
        },
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
async def test_run_task_analyze_coverage_report_handles_invalid_xml_fail_safe(
    tmp_path, fake_coverage_code_manager
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    agent.register_tool("analyze_coverage_report", agent._tool_analyze_coverage_report)

    invalid_xml = tmp_path / "broken.xml"
    invalid_xml.write_text("<coverage><packages>", encoding="utf-8")

    payload = json.dumps(
        {
            "coverage_xml": str(invalid_xml),
            "coverage_output": (
                "Name Stmts Miss Branch BrPart Cover Missing\n" "src/app.py 10 2 0 0 80% 3-4\n"
            ),
        }
    )
    result = await agent.run_task(f"analyze_coverage_report|{payload}")
    data = json.loads(result)

    assert data["coverage_xml"]["summary"] == "coverage.xml ayrıştırılamadı."
    assert data["coverage_terminal"]["total_findings"] == 1
    assert data["findings"][0]["target_path"] == "src/app.py"


@pytest.mark.asyncio
async def test_coverage_agent_generate_candidate_with_fake_llm(
    tmp_path, fake_coverage_code_manager
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)

    async def _coverage_llm(*_args, **_kwargs):
        return "# mock-response:coverage\ndef test_generated_coverage_case():\n    assert 1 == 1\n"

    agent.call_llm = _coverage_llm
    generated = await agent._tool_generate_missing_tests(
        json.dumps(
            {
                "coverage_finding": {
                    "target_path": "core/llm_client.py",
                    "missing_lines": [10, 11],
                },
                "coveragerc": {"fail_under": 90},
            }
        )
    )

    assert "test_generated_coverage_case" in generated


@pytest.mark.asyncio
async def test_coverage_agent_run_task_marks_pending_approval(
    tmp_path, monkeypatch, fake_coverage_code_manager
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    monkeypatch.setattr(
        agent.code,
        "run_pytest_and_collect",
        lambda *_args, **_kwargs: {
            "analysis": {
                "summary": "coverage gap",
                "findings": [{"target_path": "core/llm_client.py", "summary": "line gaps"}],
            },
            "output": "pytest output",
        },
    )
    monkeypatch.setattr(
        agent,
        "_generate_test_candidate",
        AsyncMock(return_value="def test_generated_coverage_case():\n    assert True\n"),
    )
    monkeypatch.setattr(agent.code, "write_generated_test", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(agent, "_record_task", AsyncMock(return_value=None))

    run_task_payload = json.loads(await agent.run_task("pytest --cov=. --cov-report=xml"))
    assert run_task_payload["approval_status"] == "pending_reviewer_or_human"
    assert run_task_payload["is_approved"] is False
