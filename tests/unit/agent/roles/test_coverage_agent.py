import asyncio
import hashlib
import importlib
import json
import sys
from pathlib import Path
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
        "analyze_test_artifacts",
        "generate_missing_tests",
        "write_missing_tests",
        "autonomous_batch_heal",
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
        source_excerpt="def target():\n    return 1",
    )
    assert "Hedef dosya: src/a.py" in prompt
    assert "Eksik satırlar: 1, 2" in prompt
    assert ".coveragerc include: src/*" in prompt
    assert "[KAYNAK DOSYA]" in prompt
    assert "def target():" in prompt
    assert "'assert True' veya tautolojik kontroller YASAK" in prompt
    assert "Her test fonksiyonu en az 1 anlamlı assertion içermeli" in prompt
    assert "tests/conftest.py" in prompt
    assert "fake_db_session" in prompt


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
        prompt_text = messages[0]["content"]
        if "Eksik satırlar: 5" in prompt_text:
            assert "[KAYNAK DOSYA]" in prompt_text
            assert "SOURCE:src/m.py" in prompt_text
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
        json.dumps(
            {
                "suggested_test_path": "tests/a.py",
                "generated_test": "```python\ndef test_generated():\n    value = 'x'.upper()\n    assert value == 'X'\n```",
                "append": False,
            }
        )
    )
    write_data = json.loads(write_json)
    assert write_data["success"] is True
    assert write_data["suggested_test_path"] == "tests/a.py"


@pytest.mark.asyncio
async def test_tool_analyze_test_artifacts_with_structured_payload(
    tmp_path, fake_coverage_code_manager
):
    """Yapılandırılmış JSON payload doğrudan _tool_analyze_coverage_report'a yönlendirilir."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    cov_xml = tmp_path / "coverage.xml"
    cov_xml.write_text("<coverage></coverage>", encoding="utf-8")

    structured_arg = json.dumps(
        {
            "coverage_xml": str(cov_xml),
            "coverage_output": "",
            "limit": 5,
        }
    )
    artifact_json = await agent._tool_analyze_test_artifacts(structured_arg)
    artifact_data = json.loads(artifact_json)
    assert "coverage_xml" in artifact_data
    assert "coverage_terminal" in artifact_data
    assert artifact_data["findings"] == []


@pytest.mark.asyncio
async def test_tool_analyze_test_artifacts_falls_back_when_payload_unparsable(
    tmp_path, fake_coverage_code_manager
):
    """Boş/parse edilemeyen argüman düz coverage_xml yolu olarak ele alınmalı."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    cov_xml = tmp_path / "coverage.xml"
    cov_xml.write_text("<coverage></coverage>", encoding="utf-8")

    artifact_json = await agent._tool_analyze_test_artifacts(str(cov_xml))
    artifact_data = json.loads(artifact_json)
    assert artifact_data["coverage_xml"]["exists"] is True


@pytest.mark.asyncio
async def test_tool_analyze_test_artifacts_treats_raw_non_json_as_path(
    tmp_path, fake_coverage_code_manager
):
    """JSON olmayan artifact girdisi komut/instruction yerine coverage path kabul edilmeli."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    artifact = tmp_path / "coverage-artifact.txt"
    artifact.write_text("not xml", encoding="utf-8")

    artifact_json = await agent._tool_analyze_test_artifacts(str(artifact))
    artifact_data = json.loads(artifact_json)

    assert artifact_data["coverage_xml"]["path"] == str(artifact)
    assert artifact_data["coverage_xml"]["exists"] is True
    assert artifact_data["coverage_xml"]["summary"] == "coverage.xml ayrıştırılamadı."


@pytest.mark.asyncio
async def test_tool_analyze_test_artifacts_handles_empty_argument(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    """Tamamen boş arg durumunda da fallback (coverage_xml=arg) çalışmalı."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    monkeypatch.chdir(tmp_path)

    artifact_json = await agent._tool_analyze_test_artifacts("")
    artifact_data = json.loads(artifact_json)
    assert "coverage_xml" in artifact_data
    assert artifact_data["coverage_xml"]["exists"] is False
    assert artifact_data["findings"] == []


@pytest.mark.asyncio
async def test_write_missing_tests_failure(tmp_path, fake_coverage_code_manager, mocker):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    mocker.patch.object(
        agent.code, "write_generated_test", return_value=(False, "Permission Denied")
    )

    write_json = await agent._tool_write_missing_tests(
        json.dumps(
            {
                "suggested_test_path": "tests/fail.py",
                "generated_test": "def test_fail():\n    value = 'x'.upper()\n    assert value == 'X'",
                "append": False,
            }
        )
    )
    write_data = json.loads(write_json)
    assert write_data["success"] is False
    assert "Permission Denied" in write_data["message"]


@pytest.mark.asyncio
async def test_write_missing_tests_rejects_duplicate_test_function(
    tmp_path, fake_coverage_code_manager
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    test_file = tmp_path / "tests" / "test_dup.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_same():\n    assert 1 == 1\n", encoding="utf-8")

    write_json = await agent._tool_write_missing_tests(
        json.dumps(
            {
                "suggested_test_path": "tests/test_dup.py",
                "generated_test": "def test_same():\n    value = 'x'.upper()\n    assert value == 'X'\n",
                "append": True,
            }
        )
    )
    write_data = json.loads(write_json)

    assert write_data["success"] is False
    assert "çakışması" in write_data["message"]
    assert write_data["validation"]["collisions"] == ["test_same"]
    agent.code.write_generated_test.assert_not_awaited()


@pytest.mark.asyncio
async def test_autonomous_coverage_batch_writes_multiple_findings(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    findings = [
        {"target_path": "src/a.py", "suggested_test_path": "tests/test_a.py"},
        {"target_path": "src/b.py", "suggested_test_path": "tests/test_b.py"},
    ]

    async def fake_analyze(_arg):
        return json.dumps({"summary": "two gaps", "coveragerc": {}, "findings": findings})

    async def fake_generate(arg):
        target_path = json.loads(arg)["coverage_finding"]["target_path"]
        target = target_path.split("/")[-1].split(".")[0]
        module = target_path.removesuffix(".py").replace("/", ".")
        return (
            f"from {module} import compute\n\n"
            f"def test_{target}_generated():\n"
            "    result = compute()\n"
            f"    assert result == {target!r}\n"
        )

    monkeypatch.setattr(agent, "_tool_analyze_coverage_report", fake_analyze)
    monkeypatch.setattr(agent, "_tool_generate_missing_tests", fake_generate)

    result = await agent.run_autonomous_coverage_batch(limit=10, batch_size=1)

    assert result["status"] == "batch_completed"
    assert result["batch_count"] == 2
    assert [item["status"] for item in result["results"]] == ["tests_written", "tests_written"]
    assert fake_coverage_code_manager.write_generated_test.await_count == 2


async def test_cap_autonomous_finding_scope_limits_context() -> None:
    finding = {
        "target_path": "core/rag.py",
        "summary": "large gap",
        "missing_lines": list(range(1, 101)),
        "missing_branches": [f"{line}:50%" for line in range(1, 21)],
    }

    capped = CoverageAgent._cap_autonomous_finding_scope(
        finding,
        max_missing_lines=25,
        max_missing_branches=10,
    )

    assert capped["missing_lines"] == list(range(1, 26))
    assert capped["missing_branches"] == [f"{line}:50%" for line in range(1, 11)]
    assert capped["autonomous_scope_cap"] == {
        "max_missing_lines": 25,
        "max_missing_branches": 10,
        "original_missing_lines": 100,
        "original_missing_branches": 20,
    }
    assert finding["missing_lines"] == list(range(1, 101))


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
    assert await agent.run_task("analyze_test_artifacts|K") == "TOOL:analyze_test_artifacts:K"
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
        return (
            "```python\n"
            "from src.a import compute\n\n"
            "def test_x():\n"
            "    result = compute()\n"
            "    assert result == 'a'\n"
            "```"
        )

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


@pytest.mark.asyncio
async def test_validate_candidate_with_isolated_pytest_uses_uv_command(
    tmp_path, fake_coverage_code_manager
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)

    generated_test = "def test_candidate():\n    value = 'x'.upper()\n    assert value == 'X'\n"
    expected_digest = hashlib.sha256(generated_test.encode("utf-8", errors="ignore")).hexdigest()[
        :12
    ]

    ok, reason, details = await agent._validate_candidate_with_isolated_pytest(
        suggested_test_path="tests/test_candidate.py",
        generated_test=generated_test,
    )

    assert ok is True
    assert reason == "isolated_pytest_passed"
    assert details["isolated_pytest_command"].startswith("uv run pytest -q ")
    assert (
        f"artifacts/coverage_candidate_validation/test_candidate_{expected_digest}.py"
        in details["isolated_pytest_command"]
    )
    assert not Path(details["isolated_test_file"]).exists()
    fake_coverage_code_manager.run_pytest_and_collect.assert_awaited_once()


@pytest.mark.asyncio
async def test_autonomous_batch_rejects_candidate_when_isolated_pytest_fails(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    fake_coverage_code_manager.run_pytest_and_collect.return_value = {
        "success": False,
        "command": "uv run pytest -q artifacts/candidate.py",
        "output": "FAILED",
        "analysis": {"has_failures": True},
    }

    async def fake_analyze(_arg):
        return json.dumps(
            {
                "summary": "isolated fail",
                "coveragerc": {},
                "findings": [{"target_path": "src/isolated.py"}],
            }
        )

    async def fake_generate(_arg):
        return (
            "from src.isolated import compute\n\n"
            "def test_isolated_candidate():\n"
            "    result = compute()\n"
            "    assert result == 'ok'\n"
        )

    reviewer_calls = []

    async def reviewer_gate(candidate, finding):
        reviewer_calls.append((candidate, finding))
        return True

    monkeypatch.setattr(agent, "_tool_analyze_coverage_report", fake_analyze)
    monkeypatch.setattr(agent, "_tool_generate_missing_tests", fake_generate)

    result = await agent.run_autonomous_coverage_batch(reviewer_gate=reviewer_gate)

    rejected = result["results"][0]
    assert rejected["status"] == "review_rejected"
    assert rejected["review_reason"] == "generated_candidate_isolated_pytest_failed"
    assert rejected["validation"]["isolated_pytest_command"].startswith("uv run pytest -q ")
    assert reviewer_calls == []
    fake_coverage_code_manager.write_generated_test.assert_not_awaited()


@pytest.mark.asyncio
async def test_autonomous_batch_reviewer_gate_reject_payload(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    finding = {
        "target_path": "agent/roles/coverage_agent.py",
        "suggested_test_path": "tests/test_cov.py",
    }

    async def fake_analyze(_arg):
        return json.dumps({"summary": "one gap", "coveragerc": {}, "findings": [finding]})

    async def fake_generate(_arg):
        return (
            "from agent.roles.coverage_agent import CoverageAgent\n\n"
            "def test_meaningful_candidate():\n"
            "    result = CoverageAgent._module_import_path('x.py')\n"
            "    assert result == 'x'\n"
        )

    async def reviewer_gate(candidate, gate_finding):
        assert "test_meaningful_candidate" in candidate
        assert gate_finding == {**finding, "batch_index": 1, "finding_index": 1}
        return False

    monkeypatch.setattr(agent, "_tool_analyze_coverage_report", fake_analyze)
    monkeypatch.setattr(agent, "_tool_generate_missing_tests", fake_generate)

    result = await agent.run_autonomous_coverage_batch(reviewer_gate=reviewer_gate)

    assert result["success"] is False
    assert result["status"] == "batch_completed"
    assert result["results"] == [
        {
            "success": False,
            "status": "review_rejected",
            "batch_index": 1,
            "finding_index": 1,
            "target_path": "agent/roles/coverage_agent.py",
            "suggested_test_path": "tests/test_cov.py",
            "review_reason": "rejected",
            "generated_test_candidate": (
                "from agent.roles.coverage_agent import CoverageAgent\n\n"
                "def test_meaningful_candidate():\n"
                "    result = CoverageAgent._module_import_path('x.py')\n"
                "    assert result == 'x'"
            ),
        }
    ]
    fake_coverage_code_manager.write_generated_test.assert_not_awaited()


@pytest.mark.asyncio
async def test_autonomous_batch_reviewer_gate_exception_is_rejected(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)

    async def fake_analyze(_arg):
        return json.dumps(
            {
                "summary": "gate boom",
                "coveragerc": {},
                "findings": [{"target_path": "src/explode.py"}],
            }
        )

    async def fake_generate(_arg):
        return (
            "```python\n"
            "from src.explode import compute\n\n"
            "def test_exception_candidate():\n"
            "    result = compute()\n"
            "    assert result == 'ok'\n"
            "```"
        )

    async def reviewer_gate(_candidate, _finding):
        raise RuntimeError("reviewer unavailable")

    monkeypatch.setattr(agent, "_tool_analyze_coverage_report", fake_analyze)
    monkeypatch.setattr(agent, "_tool_generate_missing_tests", fake_generate)

    result = await agent.run_autonomous_coverage_batch(reviewer_gate=reviewer_gate)
    rejected = result["results"][0]

    assert result["success"] is False
    assert rejected["status"] == "review_rejected"
    assert rejected["review_reason"] == "reviewer_gate_exception:RuntimeError"
    assert rejected["review_error"] == "reviewer unavailable"
    assert rejected["suggested_test_path"] == "tests/src/test_explode.py"
    assert "def test_exception_candidate" in rejected["generated_test_candidate"]
    fake_coverage_code_manager.write_generated_test.assert_not_awaited()


@pytest.mark.asyncio
async def test_autonomous_batch_rejects_missing_and_trivial_candidates_before_reviewer(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    findings = [
        {"target_path": "src/empty.py", "suggested_test_path": "tests/test_empty.py"},
        {"target_path": "src/trivial.py", "suggested_test_path": "tests/test_trivial.py"},
    ]
    generated_by_target = {
        "src/empty.py": "```python\n```",
        "src/trivial.py": "def test_trivial_candidate():\n    assert True\n",
    }
    reviewer_calls = []

    async def fake_analyze(_arg):
        return json.dumps({"summary": "bad candidates", "coveragerc": {}, "findings": findings})

    async def fake_generate(arg):
        payload = json.loads(arg)
        return generated_by_target[payload["coverage_finding"]["target_path"]]

    async def reviewer_gate(candidate, finding):
        reviewer_calls.append((candidate, finding))
        return True

    monkeypatch.setattr(agent, "_tool_analyze_coverage_report", fake_analyze)
    monkeypatch.setattr(agent, "_tool_generate_missing_tests", fake_generate)

    result = await agent.run_autonomous_coverage_batch(reviewer_gate=reviewer_gate)

    assert result["success"] is False
    assert [item["review_reason"] for item in result["results"]] == [
        "generated_candidate_empty",
        "generated_candidate_trivial_or_missing_assertion",
    ]
    assert reviewer_calls == []
    fake_coverage_code_manager.write_generated_test.assert_not_awaited()


@pytest.mark.asyncio
async def test_autonomous_batch_partial_success_and_all_rejected_scenarios(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    findings = [
        {"target_path": "src/a.py", "suggested_test_path": "tests/test_a.py"},
        {"target_path": "src/b.py", "suggested_test_path": "tests/test_b.py"},
        {"target_path": "src/c.py", "suggested_test_path": "tests/test_c.py"},
    ]

    async def fake_analyze(_arg):
        return json.dumps({"summary": "partial", "coveragerc": {}, "findings": findings})

    async def fake_generate(arg):
        target_path = json.loads(arg)["coverage_finding"]["target_path"]
        target = target_path.removesuffix(".py").split("/")[-1]
        module = target_path.removesuffix(".py").replace("/", ".")
        return (
            f"from {module} import compute\n\n"
            f"def test_{target}_candidate():\n"
            "    result = compute()\n"
            f"    assert result == {target!r}\n"
        )

    async def partial_reviewer_gate(_candidate, finding):
        return finding["target_path"] != "src/b.py"

    monkeypatch.setattr(agent, "_tool_analyze_coverage_report", fake_analyze)
    monkeypatch.setattr(agent, "_tool_generate_missing_tests", fake_generate)

    partial = await agent.run_autonomous_coverage_batch(
        batch_size=2,
        reviewer_gate=partial_reviewer_gate,
    )

    assert partial["success"] is True
    assert partial["batch_count"] == 2
    assert [item["status"] for item in partial["results"]] == [
        "tests_written",
        "review_rejected",
        "tests_written",
    ]
    assert partial["results"][1]["batch_index"] == 1
    assert partial["results"][2]["batch_index"] == 2
    assert fake_coverage_code_manager.write_generated_test.await_count == 2

    fake_coverage_code_manager.write_generated_test.reset_mock()

    async def reject_all(_candidate, _finding):
        return False

    all_rejected = await agent.run_autonomous_coverage_batch(
        batch_size=2,
        reviewer_gate=reject_all,
    )

    assert all_rejected["success"] is False
    assert all(item["status"] == "review_rejected" for item in all_rejected["results"])
    assert [item["review_reason"] for item in all_rejected["results"]] == [
        "rejected",
        "rejected",
        "rejected",
    ]
    fake_coverage_code_manager.write_generated_test.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_rejection_and_cleaning_edge_cases():
    assert CoverageAgent._candidate_rejection_reason("") == "generated_candidate_empty"
    assert (
        CoverageAgent._candidate_rejection_reason("def helper():\n    return True")
        == "generated_candidate_missing_pytest_function"
    )
    assert (
        CoverageAgent._candidate_rejection_reason("def test_only_true():\n    assert True")
        == "generated_candidate_trivial_or_missing_assertion"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            "def test_constant_math():\n    assert 2 + 2 == 4"
        )
        == "generated_candidate_trivial_or_missing_assertion"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            "def test_mock_called(mock):\n    assert mock.called"
        )
        == "generated_candidate_tautological_mock_assertion"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            "from unittest.mock import Mock\n\n"
            "def test_mock_without_call_verification():\n"
            "    service = Mock(return_value=1)\n"
            "    assert service() == 1"
        )
        == "generated_candidate_direct_mock_creation_instead_of_shared_fixture"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            "def test_mocker_without_call_verification(mocker):\n"
            "    service = mocker.Mock(return_value=1)\n"
            "    assert service() == 1"
        )
        == "generated_candidate_direct_mock_creation_instead_of_shared_fixture"
    )

    assert (
        CoverageAgent._candidate_rejection_reason(
            "def test_exception_path_without_raises():\n"
            "    value = 'x'.upper()\n"
            "    assert value == 'X'",
            finding={"summary": "missing exception path"},
        )
        == "generated_candidate_missing_pytest_raises_for_exception_path"
    )
    assert (
        CoverageAgent._candidate_rejection_reason("def test_broken(:\n    assert True")
        == "generated_candidate_invalid_python"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            "import pytest\n\ndef test_raises():\n    with pytest.raises(ValueError):\n        raise ValueError"
        )
        == ""
    )
    assert CoverageAgent._clean_code_output("```Python\ndef test_x():\n    assert 1\n```") == (
        "def test_x():\n    assert 1"
    )
    assert CoverageAgent._clean_code_output("```py\ndef test_y():\n    assert 2\n```") == (
        "def test_y():\n    assert 2"
    )


@pytest.mark.asyncio
async def test_candidate_rejection_requires_target_coupled_behavior():
    finding = {"target_path": "src/service.py", "summary": "line gap"}

    assert (
        CoverageAgent._candidate_rejection_reason(
            "def test_unrelated_local_computation():\n"
            "    value = 'x'.upper()\n"
            "    assert value == 'X'",
            finding=finding,
        )
        == "generated_candidate_no_target_behavior_reference"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            "import importlib\n\n"
            "def test_import_only_contract():\n"
            "    module = importlib.import_module('src.service')\n"
            "    assert module is not None\n"
            "    assert getattr(module, '__name__', '') == 'src.service'",
            finding=finding,
        )
        == "generated_candidate_import_only_contract"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            "from src.service import compute\n\n"
            "def test_uncoupled_assertion_after_target_call():\n"
            "    compute()\n"
            "    assert 'x'.upper() == 'X'",
            finding=finding,
        )
        == "generated_candidate_uncoupled_assertion"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            "from src.service import compute\n\n"
            "def test_target_result_contract():\n"
            "    result = compute()\n"
            "    assert result == 'ok'",
            finding=finding,
        )
        == ""
    )


@pytest.mark.asyncio
async def test_resolve_repo_path_returns_absolute_path_unchanged(
    tmp_path, fake_coverage_code_manager
):
    """Line 122: mutlak path verildiğinde olduğu gibi döner."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    abs_path = tmp_path / "tests" / "test_abs.py"
    resolved = agent._resolve_repo_path(str(abs_path))
    assert resolved == abs_path
    assert resolved.is_absolute()


@pytest.mark.asyncio
async def test_validate_generated_test_before_write_empty_path_or_test(
    tmp_path, fake_coverage_code_manager
):
    """Lines 135, 137: suggested_test_path veya generated_test boşsa False döner."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    ok, msg, _ = agent._validate_generated_test_before_write(
        suggested_test_path="", generated_test="def test_x():\n    assert 1\n", append=False
    )
    assert ok is False
    assert "suggested_test_path boş" in msg

    ok2, msg2, _ = agent._validate_generated_test_before_write(
        suggested_test_path="tests/test_x.py", generated_test="   ", append=False
    )
    assert ok2 is False
    assert "generated_test boş" in msg2


@pytest.mark.asyncio
async def test_validate_generated_test_before_write_invalid_python_syntax(
    tmp_path, fake_coverage_code_manager
):
    """Lines 141-142: üretilen test geçersiz Python ise SyntaxError yakalanır."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    ok, msg, _ = agent._validate_generated_test_before_write(
        suggested_test_path="tests/test_x.py",
        generated_test="def test_broken(:\n    assert 1",
        append=False,
    )
    assert ok is False
    assert "geçerli Python AST değil" in msg


@pytest.mark.asyncio
async def test_validate_generated_test_before_write_no_test_function(
    tmp_path, fake_coverage_code_manager
):
    """Line 146: test_ ile başlayan fonksiyon yoksa fail-closed mesajı döner."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    ok, msg, _ = agent._validate_generated_test_before_write(
        suggested_test_path="tests/test_x.py",
        generated_test="def helper():\n    return 1\n",
        append=False,
    )
    assert ok is False
    assert "test_ ile başlayan" in msg


@pytest.mark.asyncio
async def test_validate_generated_test_before_write_duplicate_function_names(
    tmp_path, fake_coverage_code_manager
):
    """Line 157: aynı modülde yinelenen test fonksiyonu adı reddedilir."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    duplicated = "def test_dup():\n    assert 1 == 1\n\ndef test_dup():\n    assert 2 == 2\n"
    ok, msg, _ = agent._validate_generated_test_before_write(
        suggested_test_path="tests/test_x.py", generated_test=duplicated, append=False
    )
    assert ok is False
    assert "yinelenen test fonksiyon adı" in msg


@pytest.mark.asyncio
async def test_validate_generated_test_before_write_existing_file_syntax_error(
    tmp_path, fake_coverage_code_manager
):
    """Lines 169-170: mevcut test dosyası geçersiz Python ise hata mesajı döner."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    target = Path(agent.cfg.BASE_DIR) / "tests/test_existing_bad.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def broken(:\n    pass\n", encoding="utf-8")

    ok, msg, _ = agent._validate_generated_test_before_write(
        suggested_test_path="tests/test_existing_bad.py",
        generated_test="def test_new():\n    value = 'x'.upper()\n    assert value == 'X'\n",
        append=True,
    )
    assert ok is False
    assert "Mevcut test dosyası AST" in msg


@pytest.mark.asyncio
async def test_validate_generated_test_before_write_existing_file_unreadable(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    """Lines 171-172: mevcut test dosyası okunamazsa OSError yakalanır."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    target = Path(agent.cfg.BASE_DIR) / "tests/test_unreadable.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_existing():\n    assert 1\n", encoding="utf-8")

    original_read_text = Path.read_text

    def raising_read_text(self, *args, **kwargs):
        if str(self).endswith("test_unreadable.py"):
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", raising_read_text)

    ok, msg, _ = agent._validate_generated_test_before_write(
        suggested_test_path="tests/test_unreadable.py",
        generated_test="def test_new():\n    value = 'x'.upper()\n    assert value == 'X'\n",
        append=True,
    )
    assert ok is False
    assert "okunamadı" in msg


@pytest.mark.asyncio
async def test_validate_generated_test_before_write_no_collisions(
    tmp_path, fake_coverage_code_manager
):
    """Line 184: çakışma yoksa True döner."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    target = Path(agent.cfg.BASE_DIR) / "tests/test_no_dup.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_existing():\n    assert 1\n", encoding="utf-8")

    ok, msg, _ = agent._validate_generated_test_before_write(
        suggested_test_path="tests/test_no_dup.py",
        generated_test="def test_brand_new():\n    value = 'x'.upper()\n    assert value == 'X'\n",
        append=True,
    )
    assert ok is True
    assert "çakışma bulunmadı" in msg


async def test_module_import_path_strips_init_suffix():
    """Line 220: __init__ ile biten path için __init__ kaldırılır."""
    assert CoverageAgent._module_import_path("agent/__init__.py") == "agent"
    # Branch 217->219: .py ile bitmeyen path
    assert CoverageAgent._module_import_path("pkg/module") == "pkg.module"


async def test_build_deterministic_test_template_exception_path():
    """Zayıf LLM çıktısı artık coverage artıran pytest.raises iskeleti üretmez."""
    finding = {"target_path": "src/m.py", "summary": "exception path missing"}
    template = CoverageAgent._build_deterministic_test_template(finding=finding, llm_idea="")
    assert "CoverageAgent blocked weak generated test" in template
    assert "with pytest.raises" not in template

    template_with_idea = CoverageAgent._build_deterministic_test_template(
        finding=finding, llm_idea="bir fikir"
    )
    assert "LLM idea: bir fikir" in template_with_idea


async def test_has_runtime_behavior_signal_attribute_and_subscript():
    """Lines 321, 323: Attribute ve Subscript düğümleri runtime sinyal sayılır."""
    import ast

    attr_tree = ast.parse("obj.method")
    assert CoverageAgent._has_runtime_behavior_signal(attr_tree) is True

    subscript_tree = ast.parse("data[0]")
    assert CoverageAgent._has_runtime_behavior_signal(subscript_tree) is True


async def test_has_mock_call_verification_returns_true_for_assert_called():
    """Line 335: mock.assert_called_with gibi assert_called_* çağrısı tespit edilmeli."""
    import ast

    tree = ast.parse("mock_obj.assert_called_with('arg')")
    assert CoverageAgent._has_mock_call_verification(tree) is True


async def test_uses_mocking_attribute_and_mocker_signals():
    """Lines 347, 349: Attribute (unittest.mock.Mock) ve `mocker` adı tespit edilmeli."""
    import ast

    attr_tree = ast.parse("import unittest.mock\nx = unittest.mock.Mock()")
    assert CoverageAgent._uses_mocking(attr_tree) is True

    # Sadece `mocker` Name düğümü (Attribute tetiklemesin) — Line 349'u izole eder
    mocker_only_tree = ast.parse("value = mocker")
    assert CoverageAgent._uses_mocking(mocker_only_tree) is True


@pytest.mark.asyncio
async def test_tool_analyze_test_artifacts_structured_payload_without_coverage_xml(
    tmp_path, fake_coverage_code_manager
):
    """Line 701: structured JSON içinde coverage_xml yoksa boş string atanır."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    arg = json.dumps({"coverage_output": "Name Stmts Miss Branch BrPart Cover Missing\n"})
    out = await agent._tool_analyze_test_artifacts(arg)
    data = json.loads(out)
    # coverage_xml anahtarı eklenmiş olmalı (Line 701 satırı çalışmış olmalı)
    assert "coverage_xml" in data
    assert "coverage_terminal" in data


@pytest.mark.asyncio
async def test_tool_generate_missing_tests_returns_cleaned_candidate(
    tmp_path, fake_coverage_code_manager
):
    """Line 766: aday red olmazsa cleaned_candidate döner."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)

    valid_candidate = (
        "import pytest\n\n"
        "def test_meaningful_value_check():\n"
        "    value = 'x'.upper()\n"
        "    assert value == 'X'\n"
    )

    async def fake_llm(*_args, **_kwargs):
        return f"```python\n{valid_candidate}```"

    agent.call_llm = fake_llm
    out = await agent._tool_generate_missing_tests(
        json.dumps(
            {
                "coverage_finding": {"target_path": "src/m.py", "missing_lines": [1]},
                "coveragerc": {},
            }
        )
    )
    assert "test_meaningful_value_check" in out
    # Deterministic template fallback'in ilk satırını ihtiva etmemeli
    assert "deterministic exception path" not in out


@pytest.mark.asyncio
async def test_tool_generate_missing_tests_skips_source_when_target_missing(
    tmp_path, fake_coverage_code_manager
):
    """Branch 744->750: target_path boşsa source okuma atlanır."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)

    async def fake_llm(*_args, **_kwargs):
        return (
            "import pytest\n\n"
            "def test_no_target():\n"
            "    value = 'a'.upper()\n"
            "    assert value == 'A'\n"
        )

    agent.call_llm = fake_llm
    out = await agent._tool_generate_missing_tests(
        json.dumps(
            {
                "coverage_finding": {"target_path": "", "missing_lines": [1]},
                "coveragerc": {},
            }
        )
    )
    assert "test_no_target" in out


@pytest.mark.asyncio
async def test_tool_generate_missing_tests_skips_source_when_read_fails(
    tmp_path, fake_coverage_code_manager
):
    """Branch 748->750: read_file False döndürdüğünde source_excerpt boş kalır."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    fake_coverage_code_manager.read_file = AsyncMock(return_value=(False, "kaynak okunamadı"))

    async def fake_llm(*_args, **_kwargs):
        return (
            "import pytest\n\n"
            "def test_read_fail_path():\n"
            "    value = 'b'.upper()\n"
            "    assert value == 'B'\n"
        )

    agent.call_llm = fake_llm
    out = await agent._tool_generate_missing_tests(
        json.dumps(
            {
                "coverage_finding": {"target_path": "src/m.py", "missing_lines": [1]},
                "coveragerc": {},
            }
        )
    )
    assert "test_read_fail_path" in out


@pytest.mark.asyncio
async def test_validate_candidate_with_isolated_pytest_handles_outside_base_dir(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    """Lines 830-831: candidate_path base_dir dışında ise relative_to ValueError yakalanır."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)

    other_dir = tmp_path.parent / "outside_validation"
    other_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(agent.cfg, "BASE_DIR", str(tmp_path))

    # base_dir'i değiştir ama tmp_path dışındaki bir validation_dir kullan
    original_path_class = _COVERAGE_MODULE.Path

    class _PathAlias(original_path_class):
        pass

    # candidate_path mutlak ama base_dir dışında olacak şekilde hile
    original_method = _COVERAGE_MODULE.Path.relative_to

    def raising_relative_to(self, *args, **kwargs):
        if "outside" in str(self):
            raise ValueError("not relative")
        return original_method(self, *args, **kwargs)

    monkeypatch.setattr(_COVERAGE_MODULE.Path, "relative_to", raising_relative_to)

    # validation_dir'i base_dir dışına yönlendir
    fake_validation_dir = other_dir / "outside_artifacts"

    original_truediv = _COVERAGE_MODULE.Path.__truediv__
    base_dir_path = original_path_class(str(tmp_path))

    def patched_truediv(self, other):
        result = original_truediv(self, other)
        if str(self) == str(base_dir_path) and other == "artifacts":
            return fake_validation_dir
        return result

    # Daha basit: BASE_DIR'i ayarlama yerine doğrudan relative_to'yu mock'la
    generated = "def test_outside_base():\n    value = 'z'.upper()\n    assert value == 'Z'\n"
    ok, reason, details = await agent._validate_candidate_with_isolated_pytest(
        suggested_test_path="tests/test_outside.py",
        generated_test=generated,
    )
    assert "isolated_pytest_command" in details


@pytest.mark.asyncio
async def test_validate_candidate_with_isolated_pytest_catches_exception(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    """Lines 839-841: write_text/run_pytest sırasında exception fail-closed yakalanır."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    fake_coverage_code_manager.run_pytest_and_collect = AsyncMock(
        side_effect=RuntimeError("pytest crashed")
    )
    ok, reason, details = await agent._validate_candidate_with_isolated_pytest(
        suggested_test_path="tests/test_x.py",
        generated_test="def test_x():\n    value = 'a'.upper()\n    assert value == 'A'\n",
    )
    assert ok is False
    assert reason == "generated_candidate_isolated_pytest_error"
    assert "pytest crashed" in details["error"]


@pytest.mark.asyncio
async def test_validate_candidate_with_isolated_pytest_invalid_result_type(
    tmp_path, fake_coverage_code_manager
):
    """Lines 847-848: run_pytest_and_collect dict dışı dönerse fail-closed."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    fake_coverage_code_manager.run_pytest_and_collect = AsyncMock(return_value="not-a-dict")

    ok, reason, details = await agent._validate_candidate_with_isolated_pytest(
        suggested_test_path="tests/test_y.py",
        generated_test="def test_y():\n    value = 'b'.upper()\n    assert value == 'B'\n",
    )
    assert ok is False
    assert reason == "generated_candidate_isolated_pytest_invalid_result"
    assert details["result_type"] == "str"


@pytest.mark.asyncio
async def test_tool_autonomous_batch_heal_invokes_run_autonomous_coverage_batch(
    tmp_path, fake_coverage_code_manager, monkeypatch
):
    """Lines 1012-1020: _tool_autonomous_batch_heal payload'ı çözüp run_autonomous_coverage_batch çağırır."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    captured: dict = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        return {"success": True, "status": "batch_completed", "results": []}

    monkeypatch.setattr(agent, "run_autonomous_coverage_batch", fake_run)
    payload = json.dumps(
        {
            "coverage_xml": "cov.xml",
            "coveragerc": ".cov",
            "limit": 5,
            "batch_size": 2,
            "append": False,
            "max_missing_lines_per_finding": 12,
            "max_missing_branches_per_finding": 4,
        }
    )
    out = await agent._tool_autonomous_batch_heal(payload)
    data = json.loads(out)
    assert data["status"] == "batch_completed"
    assert captured["coverage_xml"] == "cov.xml"
    assert captured["coveragerc"] == ".cov"
    assert captured["limit"] == 5
    assert captured["batch_size"] == 2
    assert captured["append"] is False
    assert captured["max_missing_lines_per_finding"] == 12
    assert captured["max_missing_branches_per_finding"] == 4


@pytest.mark.asyncio
async def test_run_task_routes_autonomous_batch_heal_prefix(tmp_path, fake_coverage_code_manager):
    """Line 1072: run_task autonomous_batch_heal| prefix'ini call_tool'a yönlendirir."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)
    captured: list = []

    async def fake_tool(name, arg):
        captured.append((name, arg))
        return f"TOOL:{name}:{arg}"

    agent.call_tool = fake_tool
    result = await agent.run_task("autonomous_batch_heal|{}")
    assert result == "TOOL:autonomous_batch_heal:{}"
    assert captured == [("autonomous_batch_heal", "{}")]


async def test_target_import_alias_parser_handles_patch_and_unexpected_shapes():
    """CoverageAgent import parser should tolerate odd AST shapes and patch styles."""
    import ast

    tree = ast.parse(
        """
import importlib
import pkg.mod
from other.mod import unrelated
from pkg.mod import func as imported_func
from pkg.mod import *
module_alias = importlib.import_module("pkg.mod")
(tuple_alias, other_alias) = importlib.import_module("pkg.mod")
patch("pkg.mod.service")
patch.object("pkg.mod.worker")
mock.patch("other.mod.service")
some_obj.method("pkg.mod.not_a_patch")
"""
    )

    empty_aliases, empty_symbols, empty_patches = CoverageAgent._collect_target_import_aliases(
        tree, ""
    )
    assert (empty_aliases, empty_symbols, empty_patches) == (set(), set(), set())

    module_aliases, imported_symbols, patch_targets = CoverageAgent._collect_target_import_aliases(
        tree, "pkg.mod"
    )

    assert module_aliases == {"pkg", "module_alias"}
    assert imported_symbols == {"imported_func"}
    assert patch_targets == {"pkg.mod.service", "pkg.mod.worker"}


async def test_root_name_and_import_only_assertion_edge_cases():
    """AST helper branches should classify subscript/call roots and import-only asserts."""
    import ast

    chained_call = ast.parse("pkg.factory()['client'].method()").body[0].value
    assert CoverageAgent._root_name(chained_call) == "pkg"

    module_aliases = {"module"}
    compare_assert = ast.parse("assert module is not None").body[0]
    getattr_compare_assert = ast.parse("assert getattr(module, '__name__') == 'pkg.mod'").body[0]
    hasattr_assert = ast.parse("assert hasattr(module, 'run')").body[0]
    unrelated_assert = ast.parse("assert value == 1").body[0]

    assert CoverageAgent._is_import_only_assertion(
        compare_assert, module_aliases=module_aliases, target_module="pkg.mod"
    )
    assert CoverageAgent._is_import_only_assertion(
        getattr_compare_assert, module_aliases=module_aliases, target_module="pkg.mod"
    )
    assert CoverageAgent._is_import_only_assertion(
        hasattr_assert, module_aliases=module_aliases, target_module="pkg.mod"
    )
    assert not CoverageAgent._is_import_only_assertion(
        unrelated_assert, module_aliases=module_aliases, target_module="pkg.mod"
    )


async def test_candidate_rejection_accepts_annotated_target_result_assertion():
    """Annotated assignments from target calls should count as target-coupled behavior."""
    candidate = (
        "from src.service import compute\n\n"
        "def test_annotated_target_result():\n"
        "    result: str = compute()\n"
        "    assert result == 'ok'\n"
    )

    assert (
        CoverageAgent._candidate_rejection_reason(
            candidate, finding={"target_path": "src/service.py", "summary": "branch gap"}
        )
        == ""
    )


@pytest.mark.asyncio
async def test_tool_generate_missing_tests_falls_back_for_unexpected_llm_format(
    tmp_path, fake_coverage_code_manager
):
    """Unexpected non-code LLM output should be rejected and replaced by a safe template."""
    agent = make_agent(tmp_path, fake_coverage_code_manager)

    async def fake_llm(*_args, **_kwargs):
        return {"unexpected": ["not", "python", "test", "code"]}

    agent.call_llm = fake_llm
    generated = await agent._tool_generate_missing_tests(
        json.dumps(
            {
                "coverage_finding": {
                    "target_path": "src/service.py",
                    "missing_lines": [10],
                    "summary": "missing edge branch",
                },
                "coveragerc": {},
            }
        )
    )

    assert "CoverageAgent blocked weak generated test" in generated
    assert "LLM idea: {'unexpected': ['not', 'python', 'test', 'code']}" in generated
    assert "def test_" not in generated


async def test_remaining_target_quality_branches_and_safe_name_fragment(
    tmp_path, fake_coverage_code_manager
):
    """Exercise fail-closed quality branches for unusual AST and trivial write candidates."""
    import ast

    weird_call_tree = ast.parse("(factory())('value')")
    aliases, symbols, patches = CoverageAgent._collect_target_import_aliases(
        weird_call_tree, "pkg.mod"
    )
    assert (aliases, symbols, patches) == (set(), set(), set())

    non_import_only_call = ast.parse("assert hasattr(other_module, 'run')").body[0]
    assert not CoverageAgent._is_import_only_assertion(
        non_import_only_call, module_aliases={"module"}, target_module="pkg.mod"
    )

    assert CoverageAgent._safe_test_name_fragment("!!!.py") == "generated"

    agent = make_agent(tmp_path, fake_coverage_code_manager)
    ok, message, details = agent._validate_generated_test_before_write(
        suggested_test_path="tests/test_trivial.py",
        generated_test="def test_trivial():\n    assert True\n",
        append=False,
    )
    assert ok is False
    assert "kalite kapısından geçemedi" in message
    assert details["quality_rejection_reason"] == "generated_candidate_trivial_or_missing_assertion"


async def test_target_behavior_rejects_imported_constant_without_target_call():
    """Imported target symbols without a target call should not count as behavioral coverage."""
    candidate = (
        "from src.service import VALUE\n\n"
        "def test_imported_constant_only():\n"
        "    assert VALUE == 'ok'\n"
    )

    assert (
        CoverageAgent._candidate_rejection_reason(
            candidate, finding={"target_path": "src/service.py", "summary": "line gap"}
        )
        == "generated_candidate_import_only_contract"
    )


async def test_target_behavior_handles_non_name_assignments_and_pytest_raises():
    """Tuple assignments and exception-path tests should exercise target coupling branches."""
    tuple_assignment_candidate = (
        "from src.service import compute\n\n"
        "def test_tuple_assignment_then_direct_target_assert():\n"
        "    result, other = compute()\n"
        "    assert compute() == ('ok', 'extra')\n"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            tuple_assignment_candidate,
            finding={"target_path": "src/service.py", "summary": "branch gap"},
        )
        == ""
    )

    exception_candidate = (
        "import pytest\n"
        "from src.service import explode\n\n"
        "def test_target_exception_path():\n"
        "    with pytest.raises(ValueError):\n"
        "        explode()\n"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            exception_candidate,
            finding={"target_path": "src/service.py", "summary": "missing exception branch"},
        )
        == ""
    )

    non_name_annassign_candidate = (
        "from src.service import compute\n\n"
        "def test_subscript_annotation_direct_assert():\n"
        "    values = [None]\n"
        "    values[0]: str = compute()\n"
        "    assert compute() == 'ok'\n"
    )
    assert (
        CoverageAgent._candidate_rejection_reason(
            non_name_annassign_candidate,
            finding={"target_path": "src/service.py", "summary": "branch gap"},
        )
        == ""
    )
