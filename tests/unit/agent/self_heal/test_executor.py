"""Unit coverage for execute_mechanical_autofix()'s blocked/reverted branches.

tests/integration/workflow/test_self_heal_e2e.py already covers the happy path
(applied) and the "validation still fails after autofix" revert path with a real
CodeManager/SecurityManager stack. These tests use a lightweight stub instead to
target the remaining early-exit branches without spinning up the sandbox stack.
"""

from __future__ import annotations

from agent.self_heal.executor import execute_mechanical_autofix


class _StubCodeManager:
    """Minimal stand-in satisfying executor.py's ``_CodeManagerLike`` protocol."""

    def __init__(
        self,
        *,
        read_results: dict[str, tuple[bool, str]] | None = None,
        command_results: dict[str, tuple[bool, str]] | None = None,
    ) -> None:
        self._read_results = read_results or {}
        self._command_results = command_results or {}
        self.read_attempts: list[str] = []
        self.commands_run: list[str] = []
        self.written: dict[str, str] = {}

    def read_file(self, path: str, include_line_numbers: bool = False) -> tuple[bool, str]:
        self.read_attempts.append(path)
        return self._read_results.get(path, (True, f"original:{path}"))

    def write_file(
        self, path: str, content: str, include_line_numbers: bool = False
    ) -> tuple[bool, str]:
        self.written[path] = content
        return True, "written"

    def patch_file(self, path: str, target: str, replacement: str) -> tuple[bool, str]:
        raise NotImplementedError("execute_mechanical_autofix does not patch files directly")

    def run_shell_in_sandbox(self, command: str, workdir: str) -> tuple[bool, str]:
        self.commands_run.append(command)
        return self._command_results.get(command, (True, "ok"))


async def test_blocked_when_autofix_commands_but_no_validation_commands() -> None:
    manager = _StubCodeManager()
    remediation_loop = {
        "autofix_commands": ["uv run ruff check --fix ."],
        "validation_commands": [],
    }

    result = await execute_mechanical_autofix(
        code=manager, base_dir="/repo", remediation_loop=remediation_loop
    )

    assert result["status"] == "blocked"
    assert "doğrulama komutu olmadan engellendi" in result["summary"]
    assert result["reverted"] is False
    assert manager.commands_run == []


async def test_backup_loop_skips_unreadable_scope_path_and_continues() -> None:
    manager = _StubCodeManager(
        read_results={"a.py": (False, "permission denied"), "b.py": (True, "content-b")},
        command_results={"autofix": (True, "fixed"), "validate": (True, "passed")},
    )
    remediation_loop = {
        "scope_paths": ["a.py", "b.py"],
        "autofix_commands": ["autofix"],
        "validation_commands": ["validate"],
    }

    result = await execute_mechanical_autofix(
        code=manager, base_dir="/repo", remediation_loop=remediation_loop
    )

    # Both paths were attempted despite the first failing to read — the loop did
    # not stop early on the unreadable file.
    assert manager.read_attempts == ["a.py", "b.py"]
    assert result["status"] == "applied"


async def test_blocked_when_all_scope_path_backups_fail_to_read() -> None:
    manager = _StubCodeManager(
        read_results={
            "a.py": (False, "permission denied"),
            "b.py": (False, "not found"),
        }
    )
    remediation_loop = {
        "scope_paths": ["a.py", "b.py"],
        "autofix_commands": ["uv run ruff check --fix ."],
        "validation_commands": ["uv run ruff check ."],
    }

    result = await execute_mechanical_autofix(
        code=manager, base_dir="/repo", remediation_loop=remediation_loop
    )

    assert result["status"] == "blocked"
    assert "güvenli bir rollback noktası oluşturulamadı" in result["summary"]
    assert result["reverted"] is False
    # Backups could not be established, so no autofix command should have run.
    assert manager.commands_run == []


async def test_reverted_when_validation_fails_after_successful_autofix() -> None:
    manager = _StubCodeManager(
        read_results={"a.py": (True, "original-a")},
        command_results={
            "autofix": (True, "fixed"),
            "validate-1": (True, "passed"),
            "validate-2": (False, "still red"),
        },
    )
    remediation_loop = {
        "scope_paths": ["a.py"],
        "autofix_commands": ["autofix"],
        "validation_commands": ["validate-1", "validate-2", "validate-3"],
    }

    result = await execute_mechanical_autofix(
        code=manager, base_dir="/repo", remediation_loop=remediation_loop
    )

    assert result["status"] == "reverted"
    assert result["reverted"] is True
    assert "doğrulama başarısız" in result["summary"]
    # The autofix ran once; validation stopped at the failing command, so the
    # third validation command must never run.
    assert manager.commands_run == ["autofix", "validate-1", "validate-2"]
    # Rollback restored the backed-up file even though the autofix itself succeeded.
    assert manager.written == {"a.py": "original-a"}


async def test_reverted_when_autofix_command_itself_fails_mid_loop() -> None:
    manager = _StubCodeManager(
        read_results={"a.py": (True, "original-a")},
        command_results={
            "autofix-1": (True, "fixed step 1"),
            "autofix-2": (False, "ruff crashed"),
        },
    )
    remediation_loop = {
        "scope_paths": ["a.py"],
        "autofix_commands": ["autofix-1", "autofix-2", "autofix-3"],
        "validation_commands": ["validate"],
    }

    result = await execute_mechanical_autofix(
        code=manager, base_dir="/repo", remediation_loop=remediation_loop
    )

    assert result["status"] == "reverted"
    assert result["reverted"] is True
    assert "Mekanik autofix komutu başarısız oldu ve geri alındı: autofix-2" in result["summary"]
    # The loop stopped at the failing command; the third autofix command and any
    # validation command must never run.
    assert manager.commands_run == ["autofix-1", "autofix-2"]
    # Rollback restored the backed-up file.
    assert manager.written == {"a.py": "original-a"}
