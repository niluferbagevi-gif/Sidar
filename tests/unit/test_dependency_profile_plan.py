from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

from packaging.requirements import Requirement


def test_dependency_profile_plan_preserves_current_install_standard() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    plan = pyproject["tool"]["sidar"]["dependency_profile_plan"]
    docs = Path(plan["owner_doc"]).read_text(encoding="utf-8")

    assert plan["current_install_standard"] == "uv sync --all-extras"
    assert plan["status"] == "phase-1-dev-split"
    profile_names = {item["name"] for item in plan["profiles"]}
    assert {"runtime", "dev", "all", "production"} <= profile_names
    assert (
        "sidar[postgres,telemetry]" in pyproject["project"]["optional-dependencies"]["production"]
    )
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
    assert "runtime/dev install davranışını" in docs
    assert "Ana runtime dependencies ve `dev` extra adayları" in docs.replace("\n", " ")


def test_dependency_inventory_labels_main_and_dev_extra_dependencies() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    inventory = pyproject["tool"]["sidar"]["dependency_inventory"]
    labels = inventory["labels"]
    allowed_labels = set(inventory["allowed_labels"])
    dependency_names = {
        Requirement(dependency).name for dependency in pyproject["project"]["dependencies"]
    }
    dev_dependency_names = {
        Requirement(dependency).name
        for dependency in pyproject["project"]["optional-dependencies"]["dev"]
        if not dependency.startswith("sidar[")
    }

    assert dependency_names <= set(labels)
    assert dev_dependency_names <= set(labels)
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
    # Migration candidates are allowed by policy metadata, but none should be
    # required after the httpx2 cleanup unless a new adapter RFC reopens one.
    assert "migration-candidate" in allowed_labels
    assert inventory["status"] == "inventory-only"
    assert inventory["owner_doc"] == "docs/DEPENDENCY_PROFILE_PLAN.md"
    assert pyproject["tool"]["uv"]["environments"] == ["sys_platform == 'linux'"]


def test_httpx2_migration_candidate_is_retired_to_keep_single_http_client() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    labels = pyproject["tool"]["sidar"]["dependency_inventory"]["labels"]
    deps = pyproject["project"]["dependencies"]
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert labels["httpx"] == "runtime"
    assert "httpx2" not in labels
    assert all(not dep.startswith("httpx2") for dep in deps)
    assert "HTTP client standardization policy (`httpx` only)" in docs
    assert "Production modüllerinde `import httpx2` yapılmaz" in docs
    assert "SIDAR_HTTP_CLIENT_BACKEND=httpx|candidate" in docs
    assert "Final cleanup" in docs


def test_posthog_major_cap_is_documented_as_chromadb_telemetry_constraint() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert "posthog<6.0.0" in deps
    assert "## PostHog major cap policy" in docs
    assert "ChromaDB 0.5.x" in docs
    assert "PostHog v6" in docs


def test_ci_has_non_blocking_production_profile_dry_run() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert "production-profile-dry-run:" in workflow
    assert "continue-on-error: true" in workflow
    assert "uv sync --frozen --extra production-minimal --no-dev" in workflow
    assert "production-minimal imports ok" in workflow
    assert "production-profile-dry-run" in docs
    assert "ana CI gate'ini kırmaz" in docs


def test_torch_upgrade_reminder_has_calendar_artifact_and_validation_plan() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    reminder = pyproject["tool"]["sidar"]["dependency_profile_plan"][
        "torch_upgrade_reminder"
    ]
    calendar = Path(reminder["calendar_file"])
    calendar_text = calendar.read_text(encoding="utf-8")
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert reminder["current_lock"] == "torch 2.11.0"
    assert reminder["tracked_policy_exception"] == "CVE-2025-3000"
    assert reminder["review_by"] == "2026-08-15"
    assert reminder["expires"] == "2026-09-15"
    assert reminder["upgrade_command"] == (
        "uv lock --upgrade-package torch --upgrade-package torchvision"
    )
    assert "uv sync --all-extras" in reminder["validation_commands"]
    assert calendar.exists()
    assert "DTSTART;VALUE=DATE:20260815" in calendar_text
    assert "Review Sidar torch 2.11.0 pin" in calendar_text
    assert str(calendar) in docs


def test_ruff_line_length_debt_is_tracked_until_docstring_campaign_close() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    ruff = pyproject["tool"]["ruff"]
    lint = pyproject["tool"]["ruff"]["lint"]
    debt = pyproject["tool"]["sidar"]["ruff_debt"]

    assert ruff["line-length"] == 100
    assert "E501" in lint["ignore"]
    assert debt["line_length"] == 100
    assert debt["e501_global_ignore_review_by"] == "2026-09-30"
    assert {"web_server.py", "main.py"} <= set(debt["legacy_hotspots"])


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
    assert "varsayılan production install akışı değiştirilmez" in docs


def test_dependency_profile_plan_moves_dev_tools_to_dev_extra_not_runtime_deps() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])
    dev_dependencies = set(pyproject["project"]["optional-dependencies"]["dev"])

    for package_prefix in ("pytest", "ruff", "mypy", "pyright", "bandit", "safety"):
        assert not any(dep.startswith(package_prefix) for dep in dependencies)
        assert any(dep.startswith(package_prefix) for dep in dev_dependencies)


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
    assert "sys_platform == 'linux'" in docs
    assert "security/pip-audit-ignores.tsv" in Path("pyproject.toml").read_text(encoding="utf-8")
    assert "scripts/pip_audit_ignore_args.py" in docs
    assert "2026-09-15" in docs
    assert "2026-08-15" in docs
    assert "status=watch" in docs
    assert "fail-closed" in docs
    assert "CVE-2025-3000" in policy
    assert "GHSA-rrmf-rvhw-rf47" in policy
    assert "torch" in policy
    assert "status=watch" in policy
    assert "installed=torch 2.11.0" in policy
    assert "next_review=2026-08-15" in policy
    assert "upstream fix unavailable" in policy
    assert date.fromisoformat("2026-09-15") > date(2026, 6, 17)


def test_production_profile_excludes_dev_quality_tools() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    production_dependencies = set(pyproject["project"]["optional-dependencies"]["production"])
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert production_dependencies == {"sidar[postgres,telemetry]"}
    assert (
        "production profili `sidar[postgres,telemetry]` ile dev araçlarını ve Pyright LSP yükünü dışarıda tutar"
        in docs
    )
    assert "P2 structural hardening" in docs
    for package_prefix in ("pytest", "ruff", "mypy", "pyright", "bandit", "safety"):
        assert not any(dep.startswith(package_prefix) for dep in production_dependencies)
