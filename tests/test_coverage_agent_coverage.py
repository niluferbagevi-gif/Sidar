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

    registry_mod.AgentCatalog = AgentCatalog
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


def test_run_task_handles_empty_prompt() -> None:
    agent = CoverageAgent.__new__(CoverageAgent)

    result = asyncio.run(agent.run_task("   "))

    assert "Boş coverage görevi" in result


def test_run_task_delegates_prefixed_command() -> None:
    agent = CoverageAgent.__new__(CoverageAgent)

    async def _fake_call_tool(name: str, arg: str) -> str:
        return f"{name}:{arg}"

    agent.call_tool = _fake_call_tool

    result = asyncio.run(agent.run_task("analyze_coverage_report|{}"))

    assert result == "analyze_coverage_report:{}"
