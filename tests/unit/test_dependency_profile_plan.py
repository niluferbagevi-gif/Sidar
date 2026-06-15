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


def test_dependency_profile_plan_documents_inventory_phase_table() -> None:
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert "## Envanter taslağı" in docs
    for inventory_class in (
        "runtime-core",
        "runtime-web",
        "runtime-db",
        "runtime-rag-content",
        "runtime-ops-telemetry",
        "optional-provider",
        "optional-integration",
        "dev-quality",
    ):
        assert inventory_class in docs
    for representative_package in (
        "fastapi",
        "SQLAlchemy",
        "opentelemetry-*",
        "pytest-*",
        "bandit",
        "safety",
    ):
        assert representative_package in docs
    assert "install/lock davranışını" in docs
    assert "ana `dependencies` listesinden paket taşımaz" in docs


def test_dependency_profile_plan_does_not_prematurely_remove_dev_tools_from_current_deps() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])

    for package_prefix in ("pytest", "ruff", "mypy", "bandit", "safety"):
        assert any(dep.startswith(package_prefix) for dep in dependencies)


def test_rag_torch_dependency_is_bounded_below_current_audit_failure() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    rag_deps = pyproject["project"]["optional-dependencies"]["rag"]
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")
    policy = Path("security/pip-audit-ignores.tsv").read_text(encoding="utf-8")

    assert "torch>=2.4.1,<2.12" in rag_deps
    assert "torchvision>=0.19,<0.27" in rag_deps
    assert "uv lock --upgrade-package torch --upgrade-package torchvision" in docs
    assert "CVE-2025-3000" in docs
    assert "Mevcut `uv.lock` çözümü `torch 2.11.0`" in docs
    assert "CVE-2025-3000" not in policy
    assert "No active pip-audit vulnerability exceptions." in policy
