"""End-to-end self-heal patch execution and rollback coverage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.self_heal.executor import execute_self_heal_plan
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
