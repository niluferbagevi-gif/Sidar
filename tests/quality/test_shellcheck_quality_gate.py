from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.quality_gate, pytest.mark.shellcheck]

SHELLCHECK_PATTERNS = (
    "install_sidar.sh",
    "autonomous_loop.sh",
    "run_tests.sh",
    "scripts/*.sh",
    "scripts/**/*.sh",
    "tests/shell/*.bats",
)


def _tracked_shell_targets() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", *SHELLCHECK_PATTERNS],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def test_shellcheck_quality_gate_covers_tracked_shell_scripts() -> None:
    targets = _tracked_shell_targets()

    assert "install_sidar.sh" in targets
    assert "autonomous_loop.sh" in targets
    assert "run_tests.sh" in targets
    assert any(Path(target).parts[:1] == ("scripts",) for target in targets)
    assert any(target.endswith(".bats") for target in targets)


def test_shellcheck_quality_gate_passes_for_tracked_shell_scripts() -> None:
    shellcheck = shutil.which("shellcheck")
    assert shellcheck is not None, "shellcheck-py must expose the shellcheck executable via uv"

    targets = _tracked_shell_targets()
    assert targets, "ShellCheck quality gate must have at least one tracked target"

    result = subprocess.run(
        [shellcheck, "--severity=warning", "-x", *targets],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
