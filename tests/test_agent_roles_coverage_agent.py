"""agent/roles/coverage_agent.py için birim testleri."""
from __future__ import annotations

import asyncio
import json
import pathlib as _pl
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

_proj = _pl.Path(__file__).parent.parent


def _stub_coverage_deps():
    if "agent" not in sys.modules:
        pkg = types.ModuleType("agent")
        pkg.__path__ = [str(_proj / "agent")]
        pkg.__package__ = "agent"
        sys.modules["agent"] = pkg

    cfg_mod = types.ModuleType("config")

    class _Config:
        BASE_DIR = "/tmp/sidar_test"

    cfg_mod.Config = _Config
    sys.modules["config"] = cfg_mod

    ba_mod = types.ModuleType("agent.base_agent")

    class _BaseAgent:
        def __init__(self, *a, cfg=None, role_name="base", **kw):
            self.cfg = cfg or sys.modules["config"].Config()
            self.role_name = role_name
            self.tools = {}

        def register_tool(self, name, fn):
            self.tools[name] = fn

        async def call_tool(self, name, arg):
            return await self.tools[name](arg)

        async def call_llm(self, msgs, system_prompt=None, temperature=0.7, **kw):
            return "def test_generated():\n    assert True"

    ba_mod.BaseAgent = _BaseAgent
    sys.modules["agent.base_agent"] = ba_mod

    for mod, cls in [
        ("managers", None),
        ("managers.security", "SecurityManager"),
        ("managers.code_manager", "CodeManager"),
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
        if cls:
            mock_inst = MagicMock()
            mock_inst.run_pytest_and_collect = MagicMock(
                return_value={"output": "FAILED x", "analysis": {"summary": "s", "findings": []}}
            )
            mock_inst.analyze_pytest_output = MagicMock(return_value={"summary": "analiz", "findings": []})
            mock_inst.read_file = MagicMock(return_value=(True, "def foo(): pass"))
            mock_inst.write_generated_test = MagicMock(return_value=(True, "ok"))
            sys.modules[mod].__dict__[cls] = MagicMock(return_value=mock_inst)


def _get_coverage_agent_module():
    _stub_coverage_deps()
    sys.modules.pop("agent.roles.coverage_agent", None)
    if "agent.roles" not in sys.modules:
        roles = types.ModuleType("agent.roles")
        roles.__path__ = [str(_proj / "agent" / "roles")]
        sys.modules["agent.roles"] = roles
    import agent.roles.coverage_agent as m

    return m


class TestCoverageAgentHelpers:
    def test_parse_payload_empty(self):
        m = _get_coverage_agent_module()
        assert m.CoverageAgent._parse_payload("") == {}

    def test_parse_payload_json_dict(self):
        m = _get_coverage_agent_module()
        assert m.CoverageAgent._parse_payload('{"command": "pytest -q"}') == {"command": "pytest -q"}

    def test_suggest_test_path_module(self):
        m = _get_coverage_agent_module()
        assert m.CoverageAgent._suggest_test_path("agent/roles/coverage_agent.py") == "tests/test_coverage_agent_coverage.py"

    def test_normalize_analysis_filters_invalid_findings(self):
        m = _get_coverage_agent_module()
        out = m.CoverageAgent._normalize_analysis({"summary": 123, "findings": [{"a": 1}, "bad", None]})
        assert out["summary"] == "123"
        assert out["findings"] == [{"a": 1}]


class TestCoverageAgentRunTask:
    def test_empty_prompt_warning(self):
        m = _get_coverage_agent_module()
        result = asyncio.run(m.CoverageAgent().run_task(""))
        assert "UYARI" in result

    def test_run_pytest_routing(self):
        m = _get_coverage_agent_module()
        agent = m.CoverageAgent()
        result = asyncio.run(agent.run_task("run_pytest|pytest -q"))
        parsed = json.loads(result)
        assert "analysis" in parsed

    def test_generate_missing_tests_routing(self):
        m = _get_coverage_agent_module()
        agent = m.CoverageAgent()
        result = asyncio.run(agent.run_task("generate_missing_tests|{\"target_path\":\"core/db.py\",\"pytest_output\":\"FAILED\"}"))
        assert "def test_generated" in result

    def test_main_flow_no_findings(self):
        m = _get_coverage_agent_module()
        agent = m.CoverageAgent()
        agent.code.run_pytest_and_collect.return_value = {
            "output": "ok",
            "analysis": {"summary": "temiz", "findings": []},
        }
        raw = asyncio.run(agent.run_task('{"command":"pytest -q"}'))
        parsed = json.loads(raw)
        assert parsed["status"] == "no_gaps_detected"

    def test_main_flow_writes_test_when_findings_exist(self):
        m = _get_coverage_agent_module()
        agent = m.CoverageAgent()
        agent.code.run_pytest_and_collect.return_value = {
            "output": "FAILED test_x",
            "analysis": {
                "summary": "eksik",
                "findings": [{"finding_type": "missing_test", "target_path": "core/memory.py", "summary": "missing"}],
            },
        }
        with patch.object(agent, "_record_task", AsyncMock(return_value=None)):
            raw = asyncio.run(agent.run_task('{"command":"pytest -q"}'))
        parsed = json.loads(raw)
        assert parsed["status"] == "tests_written"
        assert parsed["suggested_test_path"] == "tests/test_memory_coverage.py"
