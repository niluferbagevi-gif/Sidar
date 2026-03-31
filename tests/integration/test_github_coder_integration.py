"""GitHubManager + CodeManager + CoderAgent entegrasyon simülasyonu."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.roles.coder_agent import CoderAgent
from managers.github_manager import GitHubManager


def _build_cfg(tmp_path: Path):
    cfg = SimpleNamespace()
    cfg.AI_PROVIDER = "ollama"
    cfg.BASE_DIR = Path(tmp_path)
    cfg.DOCKER_RUNTIME = ""
    cfg.DOCKER_ALLOWED_RUNTIMES = [""]
    cfg.DOCKER_MICROVM_MODE = "off"
    cfg.DOCKER_MEM_LIMIT = "128m"
    cfg.DOCKER_NETWORK_DISABLED = True
    cfg.DOCKER_NANO_CPUS = 500_000_000
    cfg.DOCKER_PYTHON_IMAGE = "python:3.11-alpine"
    cfg.DOCKER_EXEC_TIMEOUT = 5
    cfg.ENABLE_LSP = False
    cfg.LSP_TIMEOUT_SECONDS = 5
    cfg.LSP_MAX_REFERENCES = 20
    cfg.PYTHON_LSP_SERVER = "pyright-langserver"
    cfg.TYPESCRIPT_LSP_SERVER = "typescript-language-server"
    return cfg


def test_github_content_can_be_written_locally_and_read_via_coder_agent(tmp_path):
    cfg = _build_cfg(tmp_path)

    async def _run_case() -> None:
        coder = CoderAgent(cfg=cfg)

        github = MagicMock(spec=GitHubManager)
        github.read_remote_file.return_value = (
            True,
            "def greet(name):\n    return f'hello {name}'\n",
        )

        ok_remote, remote_content = github.read_remote_file("src/sample.py", ref="main")
        assert ok_remote is True

        ok_write, _ = coder.code.write_file("src/sample.py", remote_content)
        assert ok_write is True

        read_result = await asyncio.wait_for(coder.run_task("read_file|src/sample.py"), timeout=30)
        assert "def greet(name)" in read_result
        assert "hello" in read_result
        github.read_remote_file.assert_called_once_with("src/sample.py", ref="main")

    asyncio.run(_run_case())
