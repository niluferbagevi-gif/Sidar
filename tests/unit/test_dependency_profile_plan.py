from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement


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


def test_dependency_inventory_labels_every_main_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    inventory = pyproject["tool"]["sidar"]["dependency_inventory"]
    labels = inventory["labels"]
    allowed_labels = set(inventory["allowed_labels"])
    dependency_names = {
        Requirement(dependency).name for dependency in pyproject["project"]["dependencies"]
    }

    assert set(labels) == dependency_names
    assert set(labels.values()) <= allowed_labels
    for required_label in (
        "runtime",
        "dev",
        "provider",
        "integration",
        "test-double",
        "security-tool",
    ):
        assert required_label in labels.values()
    assert inventory["status"] == "inventory-only"
    assert inventory["owner_doc"] == "docs/DEPENDENCY_PROFILE_PLAN.md"


def test_ci_has_non_blocking_production_profile_dry_run() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert "production-profile-dry-run:" in workflow
    assert "continue-on-error: true" in workflow
    assert "uv sync --frozen --extra production" in workflow
    assert "production-profile-dry-run" in docs
    assert "ana CI gate'ini kırmaz" in docs


def test_dependency_profile_plan_scopes_docker_and_installer_to_separate_pr() -> None:
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert "## Dockerfile / installer geçiş PR kapsamı" in docs
    for target in (
        "Dockerfile",
        "install_sidar.sh",
        "scripts/install_modules/utils/python_env.sh",
        "Runbook / docs",
    ):
        assert target in docs
    assert "Bu doküman Dockerfile veya installer davranışını bu aşamada değiştirmez" in docs
    assert "`--dependency-profile=all|production`" in docs
    assert "varsayılan `all` kalmalı" in docs
    assert "ana `dependencies` listesi daraltılmamalıdır" in docs


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
    # CVE-2025-3000 için upstream fix henüz yok; aktif dated+scoped istisna
    # security/pip-audit-ignores.tsv içinde tutulur ve süresi dolan kayıtlar
    # scripts/pip_audit_ignore_args.py tarafından reddedilir.
    assert "CVE-2025-3000\ttorch\t" in policy
    assert "expires: 2026-09-17" in docs
