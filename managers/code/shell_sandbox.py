"""Shell sandbox adapter for CodeManager."""

from __future__ import annotations

from typing import Any, cast

from managers.code import test_runner_orchestrator
from managers.code.pytest_parser import command_invokes_pytest, command_requires_uv_tooling


class ShellSandboxAdapter:
    """Select sandbox images and execute shell commands in Docker sandbox."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def select_shell_sandbox_image(self, command: str, image: str | None) -> str:
        """Use the project test image for test/uv commands, otherwise the REPL image."""

        if image:
            return image
        if command_requires_uv_tooling(command):
            return cast(str, self.owner.docker_test_image)
        return cast(str, self.owner.docker_image)

    def build_shell_preflight_command(self, command: str) -> str:
        """Build PATH/uv/pytest preflight for sandbox shell commands."""

        return test_runner_orchestrator.build_shell_preflight_command(self.owner, command)

    def run_shell_in_sandbox(
        self,
        command: str,
        cwd: str | None = None,
        image: str | None = None,
    ) -> tuple[bool, str]:
        """Run a shell command in the owner's Docker sandbox."""

        owner = self.owner
        if owner.code_execution_backend in {
            "disabled",
            "none",
            "off",
        }:  # pragma: no cover - deployment-mode branch
            return (
                False,
                "Sandbox komutu çalıştırma backend'i devre dışı (CODE_EXECUTION_BACKEND=disabled).",
            )
        owner.ensure_docker_initialized()
        return test_runner_orchestrator.run_shell_in_sandbox(owner, command, cwd=cwd, image=image)

    @staticmethod
    def command_invokes_pytest(command: str) -> bool:
        """Return whether the command directly invokes pytest."""

        return command_invokes_pytest(command)
