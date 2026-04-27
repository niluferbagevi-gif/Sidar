import subprocess
import sys


def _run_cli_with_stubbed_agent(*args: str) -> subprocess.CompletedProcess[str]:
    """Run cli.main() in a subprocess with lightweight stub modules."""
    script = r"""
import asyncio
import sys
import types

fake_config = types.ModuleType("config")

class Config:
    ACCESS_LEVEL = "full"
    AI_PROVIDER = "ollama"
    CODING_MODEL = "stub-model"
    LOG_LEVEL = "INFO"

    def initialize_directories(self):
        return True

    def validate_critical_settings(self):
        return True

fake_config.Config = Config
sys.modules["config"] = fake_config

fake_agent_module = types.ModuleType("agent.sidar_agent")

class SidarAgent:
    VERSION = "e2e"

    def __init__(self, cfg):
        self.cfg = cfg

    async def initialize(self):
        return None

    def status(self):
        return "AGENT_STATUS_OK"

fake_agent_module.SidarAgent = SidarAgent
sys.modules["agent.sidar_agent"] = fake_agent_module

import cli
sys.argv = ["cli.py"] + ARGS
cli.main()
""".replace("ARGS", repr(list(args)))

    return subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_status_mode_runs_end_to_end() -> None:
    result = _run_cli_with_stubbed_agent("--status")

    assert result.returncode == 0
    assert "AGENT_STATUS_OK" in result.stdout
    assert result.stderr == ""


def test_cli_help_output_is_printed_by_real_argument_parser() -> None:
    result = _run_cli_with_stubbed_agent("--help")

    assert result.returncode == 0
    assert "Sidar — Yazılım Mühendisi AI Asistanı (CLI)" in result.stdout
    assert "--status" in result.stdout
