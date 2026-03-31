"""
agent/roles/coverage_agent.py için birim testleri.
Tüm ağır bağımlılıklar stub'lanır; deterministik davranışlar test edilir.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
import pathlib as _pl
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_proj = _pl.Path(__file__).parent.parent


def _stub_coverage_deps():
    """CoverageAgent'ın tüm import bağımlılıklarını stub'lar."""
    # agent package stub
    if "agent" not in sys.modules:
        pkg = types.ModuleType("agent")
        pkg.__path__ = [str(_proj / "agent")]
        pkg.__package__ = "agent"
        sys.modules["agent"] = pkg

    # agent.core stub
    if "agent.core" not in sys.modules:
        core = types.ModuleType("agent.core")
        core.__path__ = [str(_proj / "agent" / "core")]
        core.__package__ = "agent.core"
        sys.modules["agent.core"] = core
    else:
        c = sys.modules["agent.core"]
        if not hasattr(c, "__path__"):
            c.__path__ = [str(_proj / "agent" / "core")]

    # agent.core.contracts stub
    if "agent.core.contracts" not in sys.modules:
        contracts = types.ModuleType("agent.core.contracts")
        contracts.is_delegation_request = lambda v: False
        sys.modules["agent.core.contracts"] = contracts

    # config stub
    if "config" not in sys.modules:
        cfg_mod = types.ModuleType("config")
        class _Config:
            AI_PROVIDER = "ollama"
            OLLAMA_MODEL = "qwen2.5-coder:7b"
            BASE_DIR = "/tmp/sidar_test"
            USE_GPU = False
            GPU_DEVICE = 0
            GPU_MIXED_PRECISION = False
            RAG_DIR = "/tmp/sidar_test/rag"
            RAG_TOP_K = 3
            RAG_CHUNK_SIZE = 1000
            RAG_CHUNK_OVERLAP = 200
        cfg_mod.Config = _Config
        sys.modules["config"] = cfg_mod

    # core / core.llm_client stubs
    for mod in ("core", "core.llm_client"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
    if not hasattr(sys.modules["core.llm_client"], "LLMClient"):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="llm yanıtı")
        sys.modules["core.llm_client"].LLMClient = MagicMock(return_value=mock_llm)

    # core.db stub
    if "core.db" not in sys.modules:
        db_mod = types.ModuleType("core.db")
        mock_task = MagicMock(); mock_task.id = 1
        mock_db = MagicMock()
        mock_db.connect = AsyncMock()
        mock_db.init_schema = AsyncMock()
        mock_db.create_coverage_task = AsyncMock(return_value=mock_task)
        mock_db.add_coverage_finding = AsyncMock()
        db_mod.Database = MagicMock(return_value=mock_db)
        sys.modules["core.db"] = db_mod

    # managers stubs
    for mod, cls in [
        ("managers", None),
        ("managers.code_manager", "CodeManager"),
        ("managers.security", "SecurityManager"),
    ]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)
        if cls:
            mock_inst = MagicMock()
            mock_inst.read_file = MagicMock(return_value=(True, "dosya içeriği"))
            mock_inst.run_pytest_and_collect = MagicMock(return_value={
                "output": "1 passed",
                "analysis": {"summary": "tüm testler geçti", "findings": []},
            })
            mock_inst.analyze_pytest_output = MagicMock(return_value={
                "summary": "analiz tamamlandı",
                "findings": [],
            })
            mock_inst.write_generated_test = MagicMock(return_value=(True, "yazıldı"))
            sys.modules[mod].__dict__[cls] = MagicMock(return_value=mock_inst)

    # agent.base_agent stub
    if "agent.base_agent" not in sys.modules:
        ba_mod = types.ModuleType("agent.base_agent")
        class _BaseAgent:
            def __init__(self, *a, cfg=None, role_name="base", **kw):
                self.cfg = cfg or sys.modules["config"].Config()
                self.role_name = role_name
                self.llm = MagicMock()
                self.llm.chat = AsyncMock(return_value="llm yanıtı")
                self.tools = {}
            def register_tool(self, name, fn):
                self.tools[name] = fn
            async def call_tool(self, name, arg):
                if name not in self.tools:
                    return f"HATA: {name} bulunamadı"
                return await self.tools[name](arg)
            async def call_llm(self, msgs, system_prompt=None, temperature=0.7, **kw):
                return "def test_generated(): pass"
        ba_mod.BaseAgent = _BaseAgent
        sys.modules["agent.base_agent"] = ba_mod


def _get_coverage():
    _stub_coverage_deps()
    sys.modules.pop("agent.roles.coverage_agent", None)
    if "agent.roles" not in sys.modules:
        roles = types.ModuleType("agent.roles")
        roles.__path__ = [str(_proj / "agent" / "roles")]
        sys.modules["agent.roles"] = roles
    import agent.roles.coverage_agent as m
    return m


# ─────────────────────────────────────────────────────────
# Başlatma testleri
# ─────────────────────────────────────────────────────────

class TestCoverageAgentInit:
    def test_instantiation(self):
        m = _get_coverage()
        assert m.CoverageAgent() is not None

    def test_role_name(self):
        m = _get_coverage()
        assert m.CoverageAgent().role_name == "coverage"

    def test_tools_registered(self):
        m = _get_coverage()
        agent = m.CoverageAgent()
        for tool in ("run_pytest", "analyze_pytest_output",
                     "analyze_coverage_report", "generate_missing_tests", "write_missing_tests"):
            assert tool in agent.tools, f"{tool} kayıtlı değil"

    def test_custom_cfg(self):
        m = _get_coverage()
        cfg = sys.modules["config"].Config()
        agent = m.CoverageAgent(cfg=cfg)
        assert agent.cfg is cfg


# ─────────────────────────────────────────────────────────
# _parse_payload statik metot testleri
# ─────────────────────────────────────────────────────────

class TestParsePayload:
    def test_empty_string_returns_empty_dict(self):
        m = _get_coverage()
        assert m.CoverageAgent._parse_payload("") == {}

    def test_whitespace_only_returns_empty_dict(self):
        m = _get_coverage()
        assert m.CoverageAgent._parse_payload("   ") == {}

    def test_valid_json_object(self):
        m = _get_coverage()
        result = m.CoverageAgent._parse_payload('{"command": "pytest -v"}')
        assert result["command"] == "pytest -v"

    def test_invalid_json_returns_command_key(self):
        m = _get_coverage()
        result = m.CoverageAgent._parse_payload("{bozuk json}")
        assert "command" in result

    def test_plain_text_returns_command_key(self):
        m = _get_coverage()
        result = m.CoverageAgent._parse_payload("pytest --tb=short")
        assert result.get("command") == "pytest --tb=short"

    def test_json_array_falls_back_to_command_key(self):
        m = _get_coverage()
        result = m.CoverageAgent._parse_payload('["a","b"]')
        assert "command" in result

    def test_nested_payload_preserved(self):
        m = _get_coverage()
        result = m.CoverageAgent._parse_payload('{"command": "pytest", "cwd": "/app"}')
        assert result["cwd"] == "/app"


# ─────────────────────────────────────────────────────────
# _suggest_test_path statik metot testleri
# ─────────────────────────────────────────────────────────

class TestSuggestTestPath:
    def test_empty_path_returns_default(self):
        m = _get_coverage()
        result = m.CoverageAgent._suggest_test_path("")
        assert result == "tests/test_generated_coverage_agent.py"

    def test_simple_module_path(self):
        m = _get_coverage()
        result = m.CoverageAgent._suggest_test_path("core/memory.py")
        assert result == "tests/test_memory_coverage.py"

    def test_nested_role_path(self):
        m = _get_coverage()
        result = m.CoverageAgent._suggest_test_path("agent/roles/coder_agent.py")
        assert result == "tests/test_coder_agent_coverage.py"

    def test_relative_path_with_dot_prefix(self):
        m = _get_coverage()
        result = m.CoverageAgent._suggest_test_path("./managers/security.py")
        assert "security" in result

    def test_no_extension(self):
        m = _get_coverage()
        result = m.CoverageAgent._suggest_test_path("core/db")
        assert "db" in result
        assert result.startswith("tests/")


# ─────────────────────────────────────────────────────────
# _normalize_analysis statik metot testleri
# ─────────────────────────────────────────────────────────

class TestNormalizeAnalysis:
    def test_none_returns_defaults(self):
        m = _get_coverage()
        result = m.CoverageAgent._normalize_analysis(None)
        assert result["summary"] == ""
        assert result["findings"] == []

    def test_non_dict_returns_defaults(self):
        m = _get_coverage()
        result = m.CoverageAgent._normalize_analysis(["a", "b"])
        assert result["summary"] == ""
        assert result["findings"] == []

    def test_valid_dict_preserved(self):
        m = _get_coverage()
        raw = {"summary": "kapsam %70", "findings": [{"finding_type": "missing", "target_path": "core/db.py", "summary": "test yok"}]}
        result = m.CoverageAgent._normalize_analysis(raw)
        assert result["summary"] == "kapsam %70"
        assert len(result["findings"]) == 1

    def test_non_dict_findings_filtered(self):
        m = _get_coverage()
        raw = {"summary": "ok", "findings": [{"a": 1}, "geçersiz", 42, {"b": 2}]}
        result = m.CoverageAgent._normalize_analysis(raw)
        assert all(isinstance(f, dict) for f in result["findings"])
        assert len(result["findings"]) == 2

    def test_missing_findings_key_defaults_to_empty(self):
        m = _get_coverage()
        result = m.CoverageAgent._normalize_analysis({"summary": "ok"})
        assert result["findings"] == []

    def test_none_summary_coerced_to_string(self):
        m = _get_coverage()
        result = m.CoverageAgent._normalize_analysis({"summary": None, "findings": []})
        assert result["summary"] == ""


class TestCoverageXmlParsing:
    def test_parse_coverage_xml_when_file_missing_returns_exists_false(self, tmp_path):
        m = _get_coverage()
        missing = tmp_path / "not-found.xml"

        parsed = m.CoverageAgent._parse_coverage_xml(str(missing))

        assert parsed["exists"] is False
        assert parsed["files"] == []
        assert parsed["findings"] == []

    def test_parse_coverage_xml_extracts_missing_lines_and_branches(self, tmp_path):
        m = _get_coverage()
        xml_path = tmp_path / "coverage.xml"
        xml_path.write_text(
            """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="core">
      <classes>
        <class filename="core/sample.py" line-rate="0.5" branch-rate="0.5">
          <lines>
            <line number="10" hits="0" branch="true" condition-coverage="50% (1/2)"/>
            <line number="11" hits="1"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
            encoding="utf-8",
        )
        parsed = m.CoverageAgent._parse_coverage_xml(str(xml_path), limit=10)
        assert parsed["exists"] is True
        assert parsed["total_findings"] == 1
        finding = parsed["findings"][0]
        assert finding["target_path"] == "core/sample.py"
        assert 10 in finding["missing_lines"]
        assert any(str(branch).startswith("10:") for branch in finding["missing_branches"])

    def test_read_coveragerc_returns_run_and_report(self, tmp_path):
        m = _get_coverage()
        rc = tmp_path / ".coveragerc"
        rc.write_text(
            "[run]\ninclude = core/*\n[report]\nomit = tests/*\n",
            encoding="utf-8",
        )
        parsed = m.CoverageAgent._read_coveragerc(str(rc))
        assert parsed["exists"] is True
        assert parsed["run"]["include"] == "core/*"
        assert parsed["report"]["omit"] == "tests/*"

    def test_read_coveragerc_when_missing_returns_empty_sections(self, tmp_path):
        m = _get_coverage()
        parsed = m.CoverageAgent._read_coveragerc(str(tmp_path / ".coveragerc"))

        assert parsed["exists"] is False
        assert parsed["run"] == {}
        assert parsed["report"] == {}

    def test_parse_coverage_xml_skips_entries_without_filename_and_respects_limit(self, tmp_path):
        m = _get_coverage()
        xml_path = tmp_path / "coverage.xml"
        xml_path.write_text(
            """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="core">
      <classes>
        <class filename="" line-rate="0.0" branch-rate="0.0">
          <lines><line number="1" hits="0"/></lines>
        </class>
        <class filename="core/a.py" line-rate="0.1" branch-rate="0.9">
          <lines><line number="10" hits="0"/></lines>
        </class>
        <class filename="core/b.py" line-rate="0.2" branch-rate="0.8">
          <lines><line number="20" hits="0"/></lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
            encoding="utf-8",
        )

        parsed = m.CoverageAgent._parse_coverage_xml(str(xml_path), limit=0)

        assert parsed["exists"] is True
        assert parsed["total_findings"] == 2
        assert len(parsed["findings"]) == 1
        assert all(item["path"] for item in parsed["files"])

    def test_build_dynamic_pytest_prompt_contains_coverage_hints(self):
        m = _get_coverage()
        prompt = m.CoverageAgent._build_dynamic_pytest_prompt(
            finding={
                "target_path": "core/llm_client.py",
                "missing_lines": [100, 101],
                "missing_branches": ["120:50% (1/2)"],
            },
            coveragerc={"run": {"include": "core/*"}, "report": {"omit": "tests/*"}},
        )
        assert "core/llm_client.py" in prompt
        assert "200" in prompt
        assert "404/500" in prompt

    def test_parse_coverage_xml_ignores_fully_covered_branch_conditions(self, tmp_path):
        m = _get_coverage()
        xml_path = tmp_path / "coverage.xml"
        xml_path.write_text(
            """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package name="core">
      <classes>
        <class filename="core/full_branch.py" line-rate="1.0" branch-rate="1.0">
          <lines>
            <line number="15" hits="1" branch="true" condition-coverage="100% (2/2)"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
""",
            encoding="utf-8",
        )

        parsed = m.CoverageAgent._parse_coverage_xml(str(xml_path), limit=5)
        assert parsed["exists"] is True
        assert parsed["total_findings"] == 0
        assert parsed["findings"] == []


class TestTerminalCoverageParsing:
    def test_parse_terminal_coverage_output_extracts_files_and_findings(self):
        m = _get_coverage()
        terminal_output = """
Name                      Stmts   Miss Branch BrPart  Cover   Missing
----------------------------------------------------------------------
web_server.py              3090   1310    750    230    42%   10-12, 40-58
core/multimodal.py          411    150     88     24    55%   22, 44, 48-60
tests/test_sample.py         20      0      0      0   100%
"""
        parsed = m.CoverageAgent._parse_terminal_coverage_output(terminal_output, limit=10)

        assert parsed["total_findings"] == 2
        assert parsed["files"][0]["path"] == "web_server.py"
        assert parsed["files"][0]["missing_lines_count"] == 1310
        assert parsed["findings"][0]["target_path"] == "web_server.py"
        assert parsed["findings"][0]["suggested_test_path"] == "tests/test_web_server_coverage.py"

    def test_parse_terminal_coverage_output_returns_parse_error_for_unmatched_rows(self):
        m = _get_coverage()
        parsed = m.CoverageAgent._parse_terminal_coverage_output("no coverage table here")

        assert parsed["files"] == []
        assert parsed["findings"] == []
        assert "ayrıştırılamadı" in parsed["summary"]

    def test_parse_terminal_coverage_output_skips_row_when_path_is_empty_after_strip(self):
        m = _get_coverage()

        fake_match = MagicMock()
        fake_match.groupdict.return_value = {
            "path": "   ",
            "stmts": "10",
            "miss": "1",
            "branch": "2",
            "brpart": "1",
            "cover": "90",
            "missing": "10",
        }
        fake_pattern = MagicMock()
        fake_pattern.match.return_value = fake_match

        with patch.object(m.re, "compile", return_value=fake_pattern):
            parsed = m.CoverageAgent._parse_terminal_coverage_output("dummy coverage row")

        assert parsed["files"] == []
        assert parsed["findings"] == []
        assert "ayrıştırılamadı" in parsed["summary"]


# ─────────────────────────────────────────────────────────
# run_task yönlendirme testleri
# ─────────────────────────────────────────────────────────

class TestCoverageAgentRunTask:
    def test_empty_prompt_returns_warning(self):
        async def _run():
            m = _get_coverage()
            result = await m.CoverageAgent().run_task("")
            assert "UYARI" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_whitespace_prompt_returns_warning(self):
        async def _run():
            m = _get_coverage()
            result = await m.CoverageAgent().run_task("   ")
            assert "UYARI" in result
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_pytest_routing(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            result = await agent.run_task('run_pytest|{"command": "pytest -q"}')
            assert result is not None
            parsed = json.loads(result)
            assert isinstance(parsed, dict)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_analyze_pytest_output_routing(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            result = await agent.run_task('analyze_pytest_output|{"output": "1 failed"}')
            assert result is not None
            parsed = json.loads(result)
            assert isinstance(parsed, dict)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_analyze_coverage_report_routing(self, tmp_path):
        async def _run():
            m = _get_coverage()
            xml_path = tmp_path / "coverage.xml"
            xml_path.write_text(
                """<?xml version="1.0" ?>
    <coverage><packages><package name="x"><classes>
    <class filename="core/x.py" line-rate="0.0" branch-rate="1.0"><lines><line number="1" hits="0"/></lines></class>
    </classes></package></packages></coverage>
    """,
                encoding="utf-8",
            )
            agent = m.CoverageAgent()
            payload = json.dumps({"coverage_xml": str(xml_path), "limit": 5})
            result = await agent.run_task(f"analyze_coverage_report|{payload}")
            parsed = json.loads(result)
            assert isinstance(parsed, dict)
            assert parsed["coverage_xml"]["exists"] is True
            assert parsed["findings"]
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_analyze_coverage_report_uses_terminal_findings_when_xml_missing(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            payload = json.dumps(
                {
                    "coverage_xml": "/tmp/does-not-exist.xml",
                    "coverage_output": "web_server.py 3090 1310 750 230 42% 10-12, 40-58",
                }
            )
            result = await agent.run_task(f"analyze_coverage_report|{payload}")
            parsed = json.loads(result)
    
            assert parsed["coverage_xml"]["exists"] is False
            assert parsed["coverage_terminal"]["total_findings"] == 1
            assert parsed["findings"][0]["target_path"] == "web_server.py"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_generate_missing_tests_routing(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            result = await agent.run_task('generate_missing_tests|{"target_path": "core/db.py", "pytest_output": "1 failed"}')
            assert result is not None
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_write_missing_tests_routing(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            payload = json.dumps({
                "suggested_test_path": "tests/test_db_coverage.py",
                "generated_test": "def test_foo(): pass",
            })
            result = await agent.run_task(f"write_missing_tests|{payload}")
            parsed = json.loads(result)
            assert "success" in parsed
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_no_findings_returns_no_gaps_status(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            # code.run_pytest_and_collect analiz findings'i boş döndürüyor (mock zaten böyle ayarlı)
            result = await agent.run_task('{"command": "pytest -q"}')
            parsed = json.loads(result)
            assert parsed.get("status") == "no_gaps_detected"
            assert parsed.get("success") is True
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_findings_present_triggers_test_generation(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            finding = {
                "finding_type": "missing_tests",
                "target_path": "core/memory.py",
                "summary": "hiç test yok",
            }
            agent.code.run_pytest_and_collect = MagicMock(return_value={
                "output": "FAILED core/memory.py",
                "analysis": {"summary": "eksik", "findings": [finding]},
            })
            result = await agent.run_task('{"command": "pytest -q"}')
            parsed = json.loads(result)
            assert parsed.get("target_path") == "core/memory.py"
            assert "suggested_test_path" in parsed
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_findings_write_success(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            finding = {"finding_type": "missing", "target_path": "core/db.py", "summary": "test yok"}
            agent.code.run_pytest_and_collect = MagicMock(return_value={
                "output": "1 failed",
                "analysis": {"summary": "eksik", "findings": [finding]},
            })
            agent.code.write_generated_test = MagicMock(return_value=(True, "yazıldı"))
            result = await agent.run_task("{}")
            parsed = json.loads(result)
            assert parsed.get("success") is True
            assert parsed.get("status") == "tests_written"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_findings_write_failure(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            finding = {"finding_type": "missing", "target_path": "core/db.py", "summary": "test yok"}
            agent.code.run_pytest_and_collect = MagicMock(return_value={
                "output": "1 failed",
                "analysis": {"summary": "eksik", "findings": [finding]},
            })
            agent.code.write_generated_test = MagicMock(return_value=(False, "izin hatası"))
            result = await agent.run_task("{}")
            parsed = json.loads(result)
            assert parsed.get("success") is False
            assert parsed.get("status") == "write_failed"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_run_task_returns_json_string(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            result = await agent.run_task("{}")
            # Boş olmayan JSON string dönmeli
            assert isinstance(result, str)
            json.loads(result)  # parse edilebilmeli
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_db_record_exception_does_not_propagate(self):
        async def _run():
            """_record_task içindeki istisnanın run_task'ı patlatmaması gerekir."""
            m = _get_coverage()
            agent = m.CoverageAgent()
            finding = {"finding_type": "missing", "target_path": "core/db.py", "summary": "test yok"}
            agent.code.run_pytest_and_collect = MagicMock(return_value={
                "output": "1 failed",
                "analysis": {"summary": "eksik", "findings": [finding]},
            })
            with patch.object(agent, "_record_task", AsyncMock(side_effect=RuntimeError("db hatası"))):
                result = await agent.run_task("{}")
            # İstisna yutulmuş olmalı, hâlâ JSON sonuç dönmeli
            parsed = json.loads(result)
            assert "success" in parsed
        import asyncio as _asyncio
        _asyncio.run(_run())


# ─────────────────────────────────────────────────────────
# Tool metodları doğrudan testler
# ─────────────────────────────────────────────────────────

class TestCoverageAgentTools:
    def test_ensure_db_returns_cached_instance_immediately(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            cached = object()
            agent._db = cached
    
            result = await agent._ensure_db()
    
            assert result is cached
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_ensure_db_returns_cached_instance_inside_lock(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            marker = object()
    
            class _LockThatSeedsDb:
                async def __aenter__(self_inner):
                    agent._db = marker
    
                async def __aexit__(self_inner, exc_type, exc, tb):
                    return False
    
            agent._db_lock = _LockThatSeedsDb()
    
            result = await agent._ensure_db()
    
            assert result is marker
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_tool_run_pytest_default_command(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            result = await agent._tool_run_pytest("{}")
            parsed = json.loads(result)
            assert isinstance(parsed, dict)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_tool_run_pytest_custom_command(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            result = await agent._tool_run_pytest('{"command": "pytest tests/ -v"}')
            parsed = json.loads(result)
            assert isinstance(parsed, dict)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_tool_analyze_pytest_output(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            result = await agent._tool_analyze_pytest_output('{"output": "1 passed, 2 failed"}')
            parsed = json.loads(result)
            assert isinstance(parsed, dict)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_tool_generate_missing_tests(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            payload = json.dumps({
                "target_path": "core/memory.py",
                "pytest_output": "1 failed",
            })
            result = await agent._tool_generate_missing_tests(payload)
            assert isinstance(result, str)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_tool_generate_missing_tests_with_coverage_finding_without_target_path(self):
        m = _get_coverage()
        agent = m.CoverageAgent()
        payload = json.dumps(
            {
                "pytest_output": "FAILED core/service.py::test_x",
                "coverage_finding": {
                    "target_path": "core/service.py",
                    "missing_lines": [257, 258, 260],
                    "missing_branches": ["148:50% (1/2)"],
                },
                "coveragerc": {"run": {"include": "core/*"}, "report": {"omit": "tests/*"}},
            }
        )

        with patch.object(agent, "call_llm", AsyncMock(return_value="def test_dynamic(): pass")):
            result = asyncio.run(agent._tool_generate_missing_tests(payload))
        assert isinstance(result, str)
        assert "def test_dynamic" in result

    def test_tool_generate_missing_tests_with_coverage_finding_uses_dynamic_prompt(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            payload = json.dumps(
                {
                    "coverage_finding": {
                        "target_path": "agent/roles/coverage_agent.py",
                        "missing_lines": [260, 261],
                        "missing_branches": ["320:50% (1/2)"],
                    },
                    "coveragerc": {"run": {"include": "agent/*"}, "report": {"omit": "tests/*"}},
                }
            )
            with patch.object(agent, "call_llm", AsyncMock(return_value="def test_dynamic(): pass")) as llm_mock:
                result = await agent._tool_generate_missing_tests(payload)
            assert "test_dynamic" in result
            prompt = llm_mock.await_args.args[0][0]["content"]
            assert "Hedef dosya: agent/roles/coverage_agent.py" in prompt
            assert ".coveragerc include: agent/*" in prompt
            assert ".coveragerc omit: tests/*" in prompt
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_tool_generate_missing_tests_uses_given_analysis_without_reanalyze(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            analysis = {"summary": "hazır", "findings": [{"target_path": "core/db.py"}]}
            agent.code.analyze_pytest_output = MagicMock(side_effect=AssertionError("reanalyze edilmemeli"))
            payload = json.dumps({
                "target_path": "core/db.py",
                "pytest_output": "FAILED core/db.py",
                "analysis": analysis,
            })
    
            result = await agent._tool_generate_missing_tests(payload)
    
            assert isinstance(result, str)
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_tool_write_missing_tests_success(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            payload = json.dumps({
                "suggested_test_path": "tests/test_memory_coverage.py",
                "generated_test": "def test_x(): pass",
            })
            result = await agent._tool_write_missing_tests(payload)
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["suggested_test_path"] == "tests/test_memory_coverage.py"
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_tool_write_missing_tests_failure(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            agent.code.write_generated_test = MagicMock(return_value=(False, "yazma hatası"))
            payload = json.dumps({
                "suggested_test_path": "tests/test_fail_coverage.py",
                "generated_test": "def test_y(): pass",
            })
            result = await agent._tool_write_missing_tests(payload)
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert "message" in parsed
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_tool_write_missing_tests_append_flag(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            payload = json.dumps({
                "suggested_test_path": "tests/test_append_coverage.py",
                "generated_test": "def test_append(): pass",
                "append": False,
            })
            result = await agent._tool_write_missing_tests(payload)
            parsed = json.loads(result)
            assert "success" in parsed
            # append=False ile çağrıldığında write_generated_test doğru argümanla çağrılmış olmalı
            agent.code.write_generated_test.assert_called_once_with(
                "tests/test_append_coverage.py",
                "def test_append(): pass",
                append=False,
            )
        import asyncio as _asyncio
        _asyncio.run(_run())

    def test_record_task_persists_findings_with_fallback_defaults(self):
        async def _run():
            m = _get_coverage()
            agent = m.CoverageAgent()
            fake_db = MagicMock()
            fake_db.create_coverage_task = AsyncMock(return_value=types.SimpleNamespace(id=99))
            fake_db.add_coverage_finding = AsyncMock()
            with patch.object(agent, "_ensure_db", AsyncMock(return_value=fake_db)):
                await agent._record_task(
                    command="pytest -q",
                    pytest_output="FAILED ...",
                    analysis={"findings": [{"summary": "eksik test"}]},
                    generated_test="def test_x(): pass",
                    review_payload={"target_path": "core/x.py", "suggested_test_path": "tests/test_x.py"},
                    status="tests_written",
                )
            fake_db.create_coverage_task.assert_awaited_once()
            fake_db.add_coverage_finding.assert_awaited_once()
            call_kwargs = fake_db.add_coverage_finding.await_args.kwargs
            assert call_kwargs["finding_type"] == "unknown"
            assert call_kwargs["target_path"] == ""
        import asyncio as _asyncio
        _asyncio.run(_run())


class TestCoverageAgentRunTaskExtraBranches:
    def test_run_task_returns_write_failed_when_test_file_cannot_be_written(self):
        m = _get_coverage()
        agent = m.CoverageAgent()
        agent.code.run_pytest_and_collect = MagicMock(
            return_value={
                "output": "FAILED tests/test_x.py::test_a",
                "analysis": {"summary": "gap", "findings": [{"target_path": "core/x.py"}]},
            }
        )
        agent.code.write_generated_test = MagicMock(return_value=(False, "disk dolu"))
        agent._generate_test_candidate = AsyncMock(return_value="def test_auto(): pass")
        agent._record_task = AsyncMock(side_effect=RuntimeError("db unavailable"))

        result = asyncio.run(agent.run_task('{"command":"pytest -q","cwd":"/tmp"}'))
        parsed = json.loads(result)
        assert parsed["status"] == "write_failed"
        assert parsed["success"] is False
        assert parsed["target_path"] == "core/x.py"

    def test_run_task_plain_text_prompt_uses_command_fallback(self):
        m = _get_coverage()
        agent = m.CoverageAgent()
        agent.code.run_pytest_and_collect = MagicMock(
            return_value={"output": "", "analysis": {"summary": "ok", "findings": []}}
        )

        result = asyncio.run(agent.run_task("pytest -q tests/test_core_db.py"))
        parsed = json.loads(result)
        assert parsed["status"] == "no_gaps_detected"
        assert parsed["command"] == "pytest -q tests/test_core_db.py"
