import asyncio
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_qa_agent_class():
    saved = {name: sys.modules.get(name) for name in (
        "agent", "agent.base_agent", "agent.core", "agent.core.contracts", "config", "core",
        "core.llm_client", "core.ci_remediation", "managers", "managers.code_manager",
        "managers.security", "agent.roles.qa_agent",
    )}

    agent_pkg = types.ModuleType("agent")
    agent_pkg.__path__ = [str(ROOT / "agent")]
    core_pkg = types.ModuleType("agent.core")
    core_pkg.__path__ = [str(ROOT / "agent" / "core")]
    root_core_pkg = types.ModuleType("core")
    managers_pkg = types.ModuleType("managers")
    managers_pkg.__path__ = [str(ROOT / "managers")]
    config_mod = types.ModuleType("config")
    llm_client_mod = types.ModuleType("core.llm_client")
    ci_mod = types.ModuleType("core.ci_remediation")
    code_manager_mod = types.ModuleType("managers.code_manager")
    security_mod = types.ModuleType("managers.security")

    class _Config:
        AI_PROVIDER = "test"
        BASE_DIR = ROOT

    class _LLMClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def chat(self, **_kwargs):
            return "stub"

    class _SecurityManager:
        def __init__(self, *_args, **_kwargs):
            pass

    class _CodeManager:
        def __init__(self, *_args, **_kwargs):
            pass

        def read_file(self, path):
            return True, f"read:{path}"

        def list_directory(self, path):
            return True, f"list:{path}"

        def grep_files(self, pattern, path, file_glob, context_lines):
            return True, f"grep:{pattern}:{path}:{file_glob}:{context_lines}"

    def _build_ci_remediation_payload(context, diagnosis):
        return {
            "suspected_targets": list(context.get("suspected_targets") or []),
            "root_cause_summary": diagnosis,
            "remediation_loop": {"status": "planned", "validation_commands": ["python -m pytest"]},
        }

    config_mod.Config = _Config
    llm_client_mod.LLMClient = _LLMClient
    ci_mod.build_ci_remediation_payload = _build_ci_remediation_payload
    code_manager_mod.CodeManager = _CodeManager
    security_mod.SecurityManager = _SecurityManager
    root_core_pkg.llm_client = llm_client_mod
    root_core_pkg.ci_remediation = ci_mod

    sys.modules.update({
        "agent": agent_pkg,
        "agent.core": core_pkg,
        "config": config_mod,
        "core": root_core_pkg,
        "core.llm_client": llm_client_mod,
        "core.ci_remediation": ci_mod,
        "managers": managers_pkg,
        "managers.code_manager": code_manager_mod,
        "managers.security": security_mod,
    })

    try:
        for name, rel_path in (
            ("agent.core.contracts", "agent/core/contracts.py"),
            ("agent.base_agent", "agent/base_agent.py"),
            ("agent.roles.qa_agent", "agent/roles/qa_agent.py"),
        ):
            spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        return sys.modules["agent.roles.qa_agent"].QAAgent
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


QAAgent = _load_qa_agent_class()


def test_qa_agent_exposes_coverage_tools():
    agent = QAAgent()
    assert set(agent.tools.keys()) == {"read_file", "list_directory", "grep_search", "coverage_config", "ci_remediation"}


def test_qa_agent_returns_coveragerc_summary():
    agent = QAAgent()
    payload = asyncio.run(agent.run_task("coverage_config"))
    assert '"fail_under": 100' in payload
    assert '.coveragerc' in payload


def test_qa_agent_builds_coverage_plan_with_suggested_tests():
    agent = QAAgent()
    out = asyncio.run(agent.run_task('coverage_plan|{"suspected_targets": ["core/ci_remediation.py"], "diagnosis": "Eksik test var."}'))
    assert 'tests/test_ci_remediation.py' in out
    assert '"fail_under": 100' in out


def test_qa_agent_routes_missing_test_generation(monkeypatch):
    agent = QAAgent()
    seen = {}

    async def _fake_generate(target_path: str, context: str) -> str:
        seen["target_path"] = target_path
        seen["context"] = context
        return "def test_generated():\n    assert True\n"

    monkeypatch.setattr(agent, "_generate_test_code", _fake_generate)

    out = asyncio.run(agent.run_task("write_missing_tests|core/ci_remediation.py|critical branches"))

    assert "def test_generated" in out
    assert seen == {
        "target_path": "core/ci_remediation.py",
        "context": "critical branches",
    }
