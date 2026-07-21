"""End-to-end self-heal patch execution and rollback coverage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.self_heal.executor import execute_mechanical_autofix, execute_self_heal_plan
from managers.code_manager import CodeManager
from managers.security import SecurityManager


class _LocalSandboxCodeManager(CodeManager):
    def __init__(self, *args, validation_success: bool, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.validation_success = validation_success
        self.validation_commands: list[str] = []

    def run_shell_in_sandbox(self, command: str, workdir: str) -> tuple[bool, str]:
        self.validation_commands.append(command)
        if self.validation_success:
            return True, "validation passed"
        return False, "validation failed"


class _MechanicalAutofixCodeManager(CodeManager):
    """Simulates `ruff check --fix` mutating a file, then a validation command."""

    def __init__(
        self, *args, autofix_ok: bool, validation_ok: bool, target: str, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self.autofix_ok = autofix_ok
        self.validation_ok = validation_ok
        self.target = target
        self.commands_run: list[str] = []

    def run_shell_in_sandbox(self, command: str, workdir: str) -> tuple[bool, str]:
        self.commands_run.append(command)
        if "--fix" in command:
            if self.autofix_ok:
                with open(self.target, "a", encoding="utf-8") as handle:
                    handle.write("FIXED = True\n")
                return True, "ruff fixed it"
            return False, "ruff crashed"
        if self.validation_ok:
            return True, "validation passed"
        return False, "validation failed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_self_heal_patch_apply_then_rollback_with_real_file_io(tmp_path) -> None:
    target = tmp_path / "module.py"
    target.write_text("VALUE = 'old'\n", encoding="utf-8")
    cfg = SimpleNamespace(BASE_DIR=str(tmp_path), DOCKER_IMAGE="python:3.11-slim")
    security = SecurityManager(access_level="full", base_dir=tmp_path, cfg=cfg)

    apply_manager = _LocalSandboxCodeManager(
        security=security,
        base_dir=tmp_path,
        cfg=cfg,
        validation_success=True,
    )
    rollback_manager = _LocalSandboxCodeManager(
        security=security,
        base_dir=tmp_path,
        cfg=cfg,
        validation_success=False,
    )

    target_path = str(target)
    plan = {
        "summary": "Update value",
        "operations": [
            {"path": target_path, "target": "VALUE = 'old'", "replacement": "VALUE = 'new'"}
        ],
        "validation_commands": ["uv run pytest tests/unit/agent -q"],
    }
    remediation_loop = {"scope_paths": [target_path]}

    applied = await execute_self_heal_plan(
        code=apply_manager,
        base_dir=str(tmp_path),
        remediation_loop=remediation_loop,
        plan=plan,
    )
    assert applied["status"] == "applied"
    assert target.read_text(encoding="utf-8") == 'VALUE = "new"\n'

    reverted = await execute_self_heal_plan(
        code=rollback_manager,
        base_dir=str(tmp_path),
        remediation_loop=remediation_loop,
        plan={
            "summary": "Broken update",
            "operations": [
                {"path": target_path, "target": 'VALUE = "new"', "replacement": "VALUE = 'broken'"}
            ],
            "validation_commands": ["uv run pytest tests/unit/agent -q"],
        },
    )

    assert reverted["status"] == "reverted"
    assert reverted["reverted"] is True
    assert target.read_text(encoding="utf-8") == 'VALUE = "new"\n'
    assert rollback_manager.validation_commands == ["uv run pytest tests/unit/agent -q"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mechanical_autofix_applies_without_llm_when_validation_passes(tmp_path) -> None:
    target = tmp_path / "module.py"
    target.write_text("VALUE = 'old'\n", encoding="utf-8")
    cfg = SimpleNamespace(BASE_DIR=str(tmp_path), DOCKER_IMAGE="python:3.11-slim")
    security = SecurityManager(access_level="full", base_dir=tmp_path, cfg=cfg)
    target_path = str(target)

    manager = _MechanicalAutofixCodeManager(
        security=security,
        base_dir=tmp_path,
        cfg=cfg,
        autofix_ok=True,
        validation_ok=True,
        target=target_path,
    )
    remediation_loop = {
        "scope_paths": [target_path],
        "autofix_commands": [f"uv run ruff check --fix {target_path}"],
        "validation_commands": ["uv run ruff check --select D415 ."],
    }

    result = await execute_mechanical_autofix(
        code=manager, base_dir=str(tmp_path), remediation_loop=remediation_loop
    )

    assert result["status"] == "applied"
    assert "FIXED = True" in target.read_text(encoding="utf-8")
    assert manager.commands_run == [
        f"uv run ruff check --fix {target_path}",
        "uv run ruff check --select D415 .",
    ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mechanical_autofix_reverts_when_validation_still_fails(tmp_path) -> None:
    target = tmp_path / "module.py"
    original_content = 'VALUE = "old"\n'
    target.write_text(original_content, encoding="utf-8")
    cfg = SimpleNamespace(BASE_DIR=str(tmp_path), DOCKER_IMAGE="python:3.11-slim")
    security = SecurityManager(access_level="full", base_dir=tmp_path, cfg=cfg)
    target_path = str(target)

    manager = _MechanicalAutofixCodeManager(
        security=security,
        base_dir=tmp_path,
        cfg=cfg,
        autofix_ok=True,
        validation_ok=False,
        target=target_path,
    )
    remediation_loop = {
        "scope_paths": [target_path],
        "autofix_commands": [f"uv run ruff check --fix {target_path}"],
        "validation_commands": ["uv run ruff check --select D415 ."],
    }

    result = await execute_mechanical_autofix(
        code=manager, base_dir=str(tmp_path), remediation_loop=remediation_loop
    )

    assert result["status"] == "reverted"
    assert result["reverted"] is True
    assert target.read_text(encoding="utf-8") == original_content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mechanical_autofix_skipped_without_autofix_commands(tmp_path) -> None:
    cfg = SimpleNamespace(BASE_DIR=str(tmp_path), DOCKER_IMAGE="python:3.11-slim")
    security = SecurityManager(access_level="full", base_dir=tmp_path, cfg=cfg)
    manager = _MechanicalAutofixCodeManager(
        security=security,
        base_dir=tmp_path,
        cfg=cfg,
        autofix_ok=True,
        validation_ok=True,
        target=str(tmp_path / "unused.py"),
    )

    result = await execute_mechanical_autofix(
        code=manager, base_dir=str(tmp_path), remediation_loop={"scope_paths": []}
    )

    assert result["status"] == "skipped"
    assert manager.commands_run == []
