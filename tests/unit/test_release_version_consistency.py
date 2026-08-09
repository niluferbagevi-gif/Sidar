from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _pyproject_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as file_obj:
        return tomllib.load(file_obj)["project"]["version"]


def test_release_version_consistency_smoke_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_release_version_consistency.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"Release version consistency OK: {_pyproject_version()}" in result.stdout


def test_ci_runs_release_version_consistency_smoke() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Check release version consistency" in workflow
    assert "uv run python scripts/check_release_version_consistency.py" in workflow
