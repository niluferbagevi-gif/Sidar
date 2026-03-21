import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_coverage_agent_class():
    saved = {
        name: sys.modules.get(name)
        for name in (
            "agent",
            "agent.base_agent",
            "agent.core",
            "agent.core.contracts",
            "config",
            "core",
            "core.llm_client",
            "managers",
            "managers.security",
            "managers.code_manager",
            "agent.roles.coverage_agent",
        )
    }

    agent_pkg = types.ModuleType("agent")
    agent_pkg.__path__ = [str(ROOT / "agent")]
    core_pkg = types.ModuleType("agent.core")
    core_pkg.__path__ = [str(ROOT / "agent" / "core")]
    managers_pkg = types.ModuleType("managers")
    managers_pkg.__path__ = [str(ROOT / "managers")]
    config_mod = types.ModuleType("config")
    llm_client_mod = types.ModuleType("core.llm_client")
    root_core_pkg = types.ModuleType("core")
    security_mod = types.ModuleType("managers.security")
    code_manager_mod = types.ModuleType("managers.code_manager")

    class _Config:
        AI_PROVIDER = "test"
        BASE_DIR = ROOT

    class _LLMClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def chat(self, **_kwargs):
            return "def test_generated():\n    assert True\n"

    class _SecurityManager:
        def __init__(self, *_args, **_kwargs):
            pass

    class _CodeManager:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_pytest_and_collect(self, *_args, **_kwargs):
            return {}

        def analyze_pytest_output(self, *_args, **_kwargs):
            return {}

        def read_file(self, *_args, **_kwargs):
            return True, "def sample():\n    return 1\n"

        def write_generated_test(self, *_args, **_kwargs):
            return True, "Dosya başarıyla kaydedildi: tests/test_generated.py"

    config_mod.Config = _Config
    llm_client_mod.LLMClient = _LLMClient
    security_mod.SecurityManager = _SecurityManager
    code_manager_mod.CodeManager = _CodeManager
    root_core_pkg.llm_client = llm_client_mod

    sys.modules.update(
        {
            "agent": agent_pkg,
            "agent.core": core_pkg,
            "config": config_mod,
            "core": root_core_pkg,
            "core.llm_client": llm_client_mod,
            "managers": managers_pkg,
            "managers.security": security_mod,
            "managers.code_manager": code_manager_mod,
        }
    )

    try:
        for name, rel_path in (
            ("agent.core.contracts", "agent/core/contracts.py"),
            ("agent.base_agent", "agent/base_agent.py"),
            ("agent.roles.coverage_agent", "agent/roles/coverage_agent.py"),
        ):
            spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        return sys.modules["agent.roles.coverage_agent"].CoverageAgent
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


CoverageAgent = _load_coverage_agent_class()


def test_coverage_agent_writes_generated_test_and_records_task(monkeypatch):
    agent = CoverageAgent()

    class _Db:
        async def create_coverage_task(self, **kwargs):
            self.task_kwargs = kwargs
            return types.SimpleNamespace(id=7)

        async def add_coverage_finding(self, **kwargs):
            self.finding_kwargs = kwargs
            return types.SimpleNamespace(id=11)

    fake_db = _Db()

    async def _fake_ensure_db():
        return fake_db

    monkeypatch.setattr(agent, "_ensure_db", _fake_ensure_db)
    monkeypatch.setattr(
        agent.code,
        "run_pytest_and_collect",
        lambda *_args, **_kwargs: {
            "success": False,
            "command": "pytest -q",
            "output": "1 failed",
            "analysis": {
                "summary": "1 failed",
                "findings": [
                    {
                        "finding_type": "missing_coverage",
                        "target_path": "core/sample.py",
                        "summary": "Eksik satırlar: 10-12",
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(agent.code, "read_file", lambda *_args, **_kwargs: (True, "def sample():\n    return 1\n"))
    writes = []
    monkeypatch.setattr(
        agent.code,
        "write_generated_test",
        lambda path, content, append=True: writes.append((path, content, append)) or (True, f"written:{path}"),
    )

    result = asyncio.run(agent.run_task("coverage cycle"))

    assert '"status": "tests_written"' in result
    assert '"suggested_test_path": "tests/test_sample_coverage.py"' in result
    assert fake_db.task_kwargs["target_path"] == "core/sample.py"
    assert fake_db.task_kwargs["status"] == "tests_written"
    assert writes[0][0] == "tests/test_sample_coverage.py"
    assert writes[0][2] is True


def test_coverage_agent_run_pytest_tool(monkeypatch):
    agent = CoverageAgent()
    monkeypatch.setattr(
        agent.code,
        "run_pytest_and_collect",
        lambda *_args, **_kwargs: {"success": True, "command": "pytest -q", "output": "2 passed", "analysis": {"summary": "2 passed"}},
    )

    out = asyncio.run(agent.run_task('run_pytest|{"command":"pytest -q"}'))

    assert '"success": true' in out.lower()
    assert "2 passed" in out


def test_coverage_agent_write_missing_tests_tool(monkeypatch):
    agent = CoverageAgent()
    monkeypatch.setattr(
        agent.code,
        "write_generated_test",
        lambda path, content, append=True: (True, f"write:{path}:{append}:{content.strip()}"),
    )

    out = asyncio.run(
        agent.run_task(
            'write_missing_tests|{"suggested_test_path":"tests/test_gap.py","generated_test":"def test_gap():\\n    assert True\\n"}'
        )
    )

    assert '"success": true' in out.lower()
    assert "tests/test_gap.py" in out


def test_coverage_agent_helper_paths_cover_payload_normalization_and_db_cache():
    agent = CoverageAgent()
    calls = {"db": 0, "connect": 0, "init_schema": 0}

    class _Database:
        def __init__(self, _cfg):
            calls["db"] += 1

        async def connect(self):
            calls["connect"] += 1

        async def init_schema(self):
            calls["init_schema"] += 1

    fake_db_mod = types.SimpleNamespace(Database=_Database)
    with patch.dict(sys.modules, {"core.db": fake_db_mod}):
        db_first = asyncio.run(agent._ensure_db())
        db_second = asyncio.run(agent._ensure_db())

    assert db_first is db_second
    assert calls == {"db": 1, "connect": 1, "init_schema": 1}
    assert agent._parse_payload("") == {}
    assert agent._parse_payload("pytest tests/test_cov.py -q") == {"command": "pytest tests/test_cov.py -q"}
    assert agent._parse_payload('["not-a-dict"]') == {"command": '["not-a-dict"]'}
    assert agent._suggest_test_path("") == "tests/test_generated_coverage_agent.py"
    assert agent._normalize_analysis("unexpected") == {"summary": "", "findings": []}


def test_coverage_agent_analyze_and_generate_tools_use_fallbacks(monkeypatch):
    agent = CoverageAgent()
    seen = {}

    monkeypatch.setattr(
        agent.code,
        "analyze_pytest_output",
        lambda output: {"summary": f"analiz:{output}", "findings": []},
    )
    monkeypatch.setattr(agent.code, "read_file", lambda *_args, **_kwargs: (False, ""))

    async def _fake_call_llm(messages, **kwargs):
        seen["messages"] = messages
        seen["kwargs"] = kwargs
        return "def test_fallback():\n    assert True\n"

    monkeypatch.setattr(agent, "call_llm", _fake_call_llm)

    analyze_out = asyncio.run(agent.run_task("analyze_pytest_output|plain pytest output"))
    generated_out = asyncio.run(
        agent.run_task(
            'generate_missing_tests|{"target_path":"core/demo.py","pytest_output":"FAIL: sample","analysis":"unexpected-format"}'
        )
    )

    assert "analiz:plain pytest output" in analyze_out
    assert "def test_fallback()" in generated_out
    assert "kaynak okunamadı" in seen["messages"][0]["content"]
    assert "Önerilen test yolu: tests/test_demo_coverage.py" in seen["messages"][0]["content"]
    assert seen["kwargs"]["system_prompt"] == agent.TEST_GENERATION_PROMPT


def test_coverage_agent_run_task_handles_no_gaps_unexpected_analysis_and_record_failures(monkeypatch):
    agent = CoverageAgent()
    writes = []

    monkeypatch.setattr(
        agent.code,
        "run_pytest_and_collect",
        lambda *_args, **_kwargs: {
            "success": False,
            "command": "pytest -q",
            "output": "unexpected pytest output",
            "analysis": ["unexpected", "shape"],
        },
    )

    no_gap_out = asyncio.run(agent.run_task('{"command":"pytest -q tests/test_demo.py"}'))
    no_gap_payload = json.loads(no_gap_out)
    assert no_gap_payload["status"] == "no_gaps_detected"
    assert no_gap_payload["command"] == "pytest -q tests/test_demo.py"

    monkeypatch.setattr(
        agent.code,
        "run_pytest_and_collect",
        lambda *_args, **_kwargs: {
            "success": False,
            "command": "pytest -q",
            "output": "1 failed",
            "analysis": {
                "summary": "1 failed",
                "findings": [
                    {"finding_type": "missing_coverage", "target_path": "core/sample.py", "summary": "Eksik satırlar"},
                    "ignored-entry",
                ],
            },
        },
    )
    monkeypatch.setattr(agent.code, "read_file", lambda *_args, **_kwargs: (True, "def sample():\n    return 1\n"))
    monkeypatch.setattr(
        agent.code,
        "write_generated_test",
        lambda path, content, append=True: writes.append((path, content, append)) or (False, f"write-failed:{path}"),
    )
    async def _record_fail(**_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(agent, "_record_task", _record_fail)

    result = asyncio.run(agent.run_task("coverage recovery"))
    payload = json.loads(result)

    assert payload["success"] is False
    assert payload["status"] == "write_failed"
    assert payload["suggested_test_path"] == "tests/test_sample_coverage.py"
    assert payload["analysis"]["findings"] == [
        {"finding_type": "missing_coverage", "target_path": "core/sample.py", "summary": "Eksik satırlar"}
    ]
    assert payload["write_message"] == "write-failed:tests/test_sample_coverage.py"
    assert writes[0][2] is True