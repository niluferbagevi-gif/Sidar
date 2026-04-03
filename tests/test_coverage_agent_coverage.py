import asyncio
import importlib
import importlib.util
from pathlib import Path
import json
import sys
import types


def _install_coverage_agent_stubs() -> None:
    config_mod = types.ModuleType("config")

    class Config:
        BASE_DIR = "."

    config_mod.Config = Config
    sys.modules["config"] = config_mod

    base_agent_mod = types.ModuleType("agent.base_agent")

    class BaseAgent:
        def __init__(self, cfg=None, role_name="coverage") -> None:
            self.cfg = cfg or Config()
            self.role_name = role_name

        def register_tool(self, *_args, **_kwargs):
            return None

    base_agent_mod.BaseAgent = BaseAgent
    sys.modules["agent.base_agent"] = base_agent_mod

    registry_mod = types.ModuleType("agent.registry")

    class AgentCatalog:
        @staticmethod
        def register(**_kwargs):
            def _decorator(cls):
                return cls

            return _decorator

        @classmethod
        def find_by_capability(cls, capability):
            return []

        @classmethod
        def list_all(cls):
            return []

    class AgentSpec:
        def __init__(self, role_name="", capabilities=None):
            self.role_name = role_name
            self.capabilities = capabilities or []

    registry_mod.AgentCatalog = AgentCatalog
    registry_mod.AgentSpec = AgentSpec
    sys.modules["agent.registry"] = registry_mod


_install_coverage_agent_stubs()
_spec = importlib.util.spec_from_file_location(
    "coverage_agent_direct",
    Path(__file__).resolve().parents[1] / "agent/roles/coverage_agent.py",
)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)
CoverageAgent = _mod.CoverageAgent


def test_parse_coverage_xml_returns_top_findings(tmp_path):
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(
        """<?xml version=\"1.0\" ?>
<coverage>
  <packages>
    <package name=\"agent\">
      <classes>
        <class filename=\"agent/auto_handle.py\" line-rate=\"0.2\" branch-rate=\"0.0\">
          <lines>
            <line number=\"10\" hits=\"0\"/>
            <line number=\"11\" hits=\"0\" branch=\"true\" condition-coverage=\"50% (1/2)\"/>
          </lines>
        </class>
        <class filename=\"agent/sidar_agent.py\" line-rate=\"0.1\" branch-rate=\"0.0\">
          <lines>
            <line number=\"20\" hits=\"0\"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    parsed = CoverageAgent._parse_coverage_xml(str(coverage_xml), limit=1)

    assert parsed["exists"] is True
    assert parsed["total_findings"] == 2
    assert len(parsed["findings"]) == 1
    assert parsed["findings"][0]["target_path"] in {"agent/auto_handle.py", "agent/sidar_agent.py"}


def test_parse_terminal_coverage_output_extracts_missing_hints():
    output = (
        "agent/auto_handle.py 100 20 10 3 80% 12-16, 45\n"
        "agent/sidar_agent.py 200 100 20 10 50% 30-80\n"
    )
    parsed = CoverageAgent._parse_terminal_coverage_output(output, limit=10)

    assert parsed["total_findings"] == 2
    assert parsed["findings"][0]["target_path"] == "agent/sidar_agent.py"
    assert "30-80" in parsed["findings"][0]["missing_lines_hint"]


def test_tool_analyze_coverage_report_uses_terminal_output_when_xml_missing():
    agent = CoverageAgent.__new__(CoverageAgent)
    terminal = "agent/auto_handle.py 100 20 10 2 80% 1-2\n"

    result = asyncio.run(
        agent._tool_analyze_coverage_report(
            json.dumps({"coverage_xml": "does-not-exist.xml", "coverage_output": terminal, "limit": 5})
        )
    )
    payload = json.loads(result)

    assert payload["coverage_xml"]["exists"] is False
    assert payload["findings"][0]["target_path"] == "agent/auto_handle.py"


def test_tool_write_missing_tests_cleans_markdown_fences():
    class DummyCode:
        def write_generated_test(self, suggested_test_path, generated_test, append=True):
            self.path = suggested_test_path
            self.generated = generated_test
            self.append = append
            return True, "ok"

    agent = CoverageAgent.__new__(CoverageAgent)
    agent.code = DummyCode()

    result = asyncio.run(
        agent._tool_write_missing_tests(
            json.dumps(
                {
                    "suggested_test_path": "tests/test_generated_coverage.py",
                    "generated_test": "```python\\ndef test_x():\\n    assert True\\n```",
                    "append": False,
                }
            )
        )
    )
    payload = json.loads(result)

    assert payload["success"] is True
    assert agent.code.path == "tests/test_generated_coverage.py"
    assert "```" not in agent.code.generated
    assert agent.code.append is False


def test_tool_generate_missing_tests_uses_coverage_finding_prompt():
    agent = CoverageAgent.__new__(CoverageAgent)

    async def _fake_call_llm(messages, **_kwargs):
        return messages[0]["content"]

    agent.call_llm = _fake_call_llm

    result = asyncio.run(
        agent._tool_generate_missing_tests(
            json.dumps(
                {
                    "coverage_finding": {
                        "target_path": "agent/auto_handle.py",
                        "missing_lines": [10, 11],
                        "missing_branches": ["11:50% (1/2)"],
                    },
                    "coveragerc": {"run": {"include": "agent/*"}, "report": {"omit": "tests/*"}},
                }
            )
        )
    )

    assert "Hedef dosya: agent/auto_handle.py" in result
    assert "Eksik satırlar: 10, 11" in result

def test_run_task_routes_prefixed_commands_to_tools():
    agent = CoverageAgent.__new__(CoverageAgent)
    seen = {}

    async def _fake_call_tool(name, arg):
        seen["name"] = name
        seen["arg"] = arg
        return "ok"

    agent.call_tool = _fake_call_tool

    result = asyncio.run(agent.run_task('analyze_coverage_report|{"coverage_xml":"coverage.xml"}'))

    assert result == "ok"
    assert seen == {"name": "analyze_coverage_report", "arg": '{"coverage_xml":"coverage.xml"}'}


def test_run_task_no_gaps_detected_returns_success_payload():
    class DummyCode:
        def run_pytest_and_collect(self, command, cwd):
            return {
                "analysis": {"summary": "all good", "findings": []},
                "output": "",
            }

    agent = CoverageAgent.__new__(CoverageAgent)
    agent.cfg = type("Cfg", (), {"BASE_DIR": "."})()
    agent.code = DummyCode()

    raw = asyncio.run(agent.run_task('{"command":"pytest -q"}'))
    payload = json.loads(raw)

    assert payload["status"] == "no_gaps_detected"
    assert payload["command"] == "pytest -q"


def test_analyze_and_generate_missing_tests_flow_from_xml(tmp_path):
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(
        """<?xml version=\"1.0\" ?>
<coverage>
  <packages>
    <package name=\"core\">
      <classes>
        <class filename=\"core/llm_client.py\" line-rate=\"0.22\" branch-rate=\"0.1\">
          <lines>
            <line number=\"10\" hits=\"0\"/>
            <line number=\"11\" hits=\"0\" branch=\"true\" condition-coverage=\"50% (1/2)\"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    agent = CoverageAgent.__new__(CoverageAgent)

    async def _fake_call_llm(messages, **_kwargs):
        return "def test_generated():\n    assert True"

    agent.call_llm = _fake_call_llm

    analyzed_raw = asyncio.run(
        agent._tool_analyze_coverage_report(
            json.dumps({"coverage_xml": str(coverage_xml), "limit": 5})
        )
    )
    analyzed = json.loads(analyzed_raw)

    assert analyzed["findings"][0]["target_path"] == "core/llm_client.py"

    generated = asyncio.run(
        agent._tool_generate_missing_tests(
            json.dumps({"coverage_finding": analyzed["findings"][0]})
        )
    )

    assert "def test_generated" in generated


def test_generate_test_candidate_uses_fallback_when_source_read_fails():
    agent = CoverageAgent.__new__(CoverageAgent)
    agent.TEST_GENERATION_PROMPT = "prompt"

    class _Code:
        def read_file(self, _target):
            return False, "not readable"

    agent.code = _Code()

    captured = {}

    async def _fake_call_llm(messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        captured["kwargs"] = kwargs
        return "generated"

    agent.call_llm = _fake_call_llm
    agent._suggest_test_path = lambda path: f"tests/test_{Path(path).stem}.py"

    result = asyncio.run(
        agent._generate_test_candidate(
            target_path="agent/sidar_agent.py",
            pytest_output="1 failed",
            analysis={"summary": "1 failed", "findings": [{"target_path": "agent/sidar_agent.py"}]},
        )
    )

    assert result == "generated"
    assert "kaynak okunamadı" in captured["prompt"]
    assert "tests/test_sidar_agent.py" in captured["prompt"]
    assert captured["kwargs"]["system_prompt"] == "prompt"


def test_init_registers_tools_and_builds_managers(monkeypatch):
    import types as _types

    registered: list[str] = []

    class _Security:
        def __init__(self, cfg=None):
            self.cfg = cfg

    class _Code:
        def __init__(self, security, base_dir):
            self.security = security
            self.base_dir = base_dir

    monkeypatch.setattr(CoverageAgent, "register_tool", lambda _self, name, _fn: registered.append(name))
    security_mod = _types.ModuleType("managers.security")
    security_mod.SecurityManager = _Security
    code_mod = _types.ModuleType("managers.code_manager")
    code_mod.CodeManager = _Code
    monkeypatch.setitem(sys.modules, "managers.security", security_mod)
    monkeypatch.setitem(sys.modules, "managers.code_manager", code_mod)

    cfg = _types.SimpleNamespace(BASE_DIR="/tmp/project")
    agent = CoverageAgent(cfg=cfg)

    assert agent.code.base_dir == "/tmp/project"
    assert sorted(registered) == sorted(
        [
            "run_pytest",
            "analyze_pytest_output",
            "analyze_coverage_report",
            "generate_missing_tests",
            "write_missing_tests",
        ]
    )


def test_ensure_db_initializes_once(monkeypatch):
    class _Database:
        def __init__(self, _cfg):
            self.connect_calls = 0
            self.schema_calls = 0

        async def connect(self):
            self.connect_calls += 1

        async def init_schema(self):
            self.schema_calls += 1

    db_mod = types.ModuleType("core.db")
    db_mod.Database = _Database
    monkeypatch.setitem(sys.modules, "core.db", db_mod)

    agent = CoverageAgent.__new__(CoverageAgent)
    agent.cfg = object()
    agent._db = None
    agent._db_lock = None

    first = asyncio.run(agent._ensure_db())
    second = asyncio.run(agent._ensure_db())

    assert first is second
    assert first.connect_calls == 1
    assert first.schema_calls == 1


def test_record_task_persists_all_findings():
    agent = CoverageAgent.__new__(CoverageAgent)
    agent.role_name = "coverage"

    class _Db:
        def __init__(self) -> None:
            self.added: list[dict[str, object]] = []
            self.create_calls: list[dict[str, object]] = []

        async def create_coverage_task(self, **kwargs):
            self.create_calls.append(kwargs)
            return type("Task", (), {"id": 99})()

        async def add_coverage_finding(self, **kwargs):
            self.added.append(kwargs)

    db = _Db()

    async def _fake_ensure_db():
        return db

    agent._ensure_db = _fake_ensure_db

    asyncio.run(
        agent._record_task(
            command="pytest -q",
            pytest_output="failed",
            analysis={
                "findings": [
                    {"finding_type": "missing_coverage", "target_path": "agent/sidar_agent.py", "summary": "gap 1"},
                    {"finding_type": "test_failure", "target_path": "agent/roles/poyraz_agent.py", "summary": "gap 2"},
                ]
            },
            generated_test="def test_x(): pass",
            review_payload={"target_path": "agent/sidar_agent.py", "suggested_test_path": "tests/test_sidar.py"},
            status="generated",
        )
    )

    assert len(db.create_calls) == 1
    assert db.create_calls[0]["requester_role"] == "coverage"
    assert len(db.added) == 2
    assert db.added[0]["task_id"] == 99
    assert db.added[1]["finding_type"] == "test_failure"
