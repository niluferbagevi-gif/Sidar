from __future__ import annotations

import tomllib
from pathlib import Path


def test_dependency_profile_plan_preserves_current_install_standard() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    plan = pyproject["tool"]["sidar"]["dependency_profile_plan"]
    docs = Path(plan["owner_doc"]).read_text(encoding="utf-8")

    assert plan["current_install_standard"] == "uv sync --all-extras"
    assert plan["status"] == "planned"
    profile_names = {item["name"] for item in plan["profiles"]}
    assert {"runtime", "dev", "all", "production"} <= profile_names
    assert "uv sync --all-extras" in docs
    assert "Docker/installer" in docs
    for tool_name in ("pytest", "ruff", "mypy", "bandit", "safety"):
        assert tool_name in docs


def test_dependency_profile_plan_does_not_prematurely_remove_dev_tools_from_current_deps() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])

    for package_prefix in ("pytest", "ruff", "mypy", "bandit", "safety"):
        assert any(dep.startswith(package_prefix) for dep in dependencies)
