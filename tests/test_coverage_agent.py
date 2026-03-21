import asyncio
import importlib.util
import sys
import types
from pathlib import Path


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


def test_coverage_agent_generates_reviewer_delegation(monkeypatch):
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

    result = asyncio.run(agent.run_task("coverage cycle"))

    assert agent.is_delegation_message(result) is True
    assert result.target_agent == "reviewer"
    assert "generated_test_candidate" in result.payload
    assert fake_db.task_kwargs["target_path"] == "core/sample.py"


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
