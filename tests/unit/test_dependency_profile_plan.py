from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement


def test_dependency_profile_plan_preserves_current_install_standard() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    plan = pyproject["tool"]["sidar"]["dependency_profile_plan"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]
    docs = Path(plan["owner_doc"]).read_text(encoding="utf-8")

    assert plan["current_install_standard"] == (
        "installer default developer-full; uv sync --all-extras"
    )
    assert plan["installer_default_profile"] == "dev-full"
    assert plan["developer_full_sync"] == "uv sync --all-extras"
    assert plan["ci_full_sync"] == "uv sync --all-extras"
    assert plan["production_profile"] == "production"
    assert plan["production_minimal_profile"] == "production-minimal"
    assert plan["status"] == "phase-1-dev-split"
    assert {"dev-light", "production", "production-minimal"} <= set(optional_dependencies)
    assert optional_dependencies["production"] == ["sidar[runtime-postgres,telemetry]"]
    assert optional_dependencies["production-minimal"] == ["sidar[runtime-postgres]"]
    assert "uv sync --all-extras" in docs
    assert "Docker/installer" in docs
    for tool_name in ("pytest", "ruff", "mypy", "bandit", "safety"):
        assert tool_name in docs


def test_installer_dependency_profile_contract_matches_plan_metadata() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    optional_dependencies = pyproject["project"]["optional-dependencies"]
    plan = pyproject["tool"]["sidar"]["dependency_profile_plan"]
    python_env = Path("scripts/install_modules/utils/python_env.sh").read_text(encoding="utf-8")

    assert plan["installer_default_profile"] == "dev-full"
    assert 'requested="dev-full"' in python_env
    assert "uv sync --frozen --extra dev-light" in python_env
    assert 'requested="dev-full"' in python_env
    assert "uv sync --frozen --all-extras" in python_env
    assert plan["developer_full_sync"] == "uv sync --all-extras"
    assert plan["ci_full_sync"] == "uv sync --all-extras"
    assert "Tam CI/production-readiness doğrulaması seçildi" in python_env
    assert "uv sync --frozen --extra production-minimal --no-dev" in python_env
    assert optional_dependencies["production"] != optional_dependencies["production-minimal"]

    heavy_extras = {"rag", "gpu", "voice", "browser"}
    production_minimal = optional_dependencies["production-minimal"]
    for dependency in production_minimal:
        requirement = Requirement(dependency)
        assert heavy_extras.isdisjoint(requirement.extras)


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


def test_ci_has_blocking_production_profile_runtime_validation() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    validation = pyproject["tool"]["sidar"]["dependency_profile_plan"][
        "production_minimal_runtime_validation"
    ]
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow_words = " ".join(workflow.split())
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")
    job_slice = workflow[
        workflow.index("production-profile-dry-run:") : workflow.index("pg-stress:")
    ]

    assert validation["status"] == "release-blocking"
    assert validation["review_by"] == "2026-08-15"
    assert validation["blocking_transition_pr_required"] is False
    assert validation["release_artifact"] == "production-minimal-runtime-evidence"
    assert validation["release_artifact_path"] == (
        "artifacts/production-minimal/runtime-evidence.json"
    )
    assert "production-profile-dry-run:" in workflow
    assert "continue-on-error" not in job_slice
    assert "./install_sidar.sh sync-deps --skip-models --skip-smoke-test --ci --no-interaction" in (
        workflow_words
    )
    assert "web.app_factory import create_app" in workflow
    assert "uv run --no-sync alembic upgrade head" in workflow
    assert "actions/upload-artifact@v4" in job_slice
    assert "production-minimal-runtime-evidence" in workflow
    assert "artifacts/production-minimal/runtime-evidence.json" in workflow
    assert "production-profile-dry-run" in docs
    assert "`sidar[postgres]`" in docs
    assert "ana CI kalite kapısının parçası" in docs
    assert "continue-on-error` kullanılmamalıdır" in docs
    assert "release-blocking runtime" in docs
    assert "runtime-evidence.json" in docs


def test_torch_upgrade_reminder_records_resolved_advisory_and_validation_plan() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    reminder = pyproject["tool"]["sidar"]["dependency_profile_plan"]["torch_upgrade_reminder"]
    runbook = Path(reminder["runbook_file"])
    runbook_text = runbook.read_text(encoding="utf-8")
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert reminder["status"] == "resolved"
    assert reminder["current_lock"] == "torch 2.13.0"
    assert reminder["tracked_policy_exception"] == "CVE-2025-3000"
    assert reminder["advisory_checked_on"] == "2026-08-09"
    assert reminder["upstream_patched_versions"] == "2.13.0"
    assert reminder["upgrade_command"] == (
        "uv lock --upgrade-package torch --upgrade-package torchvision"
    )
    assert "uv sync --all-extras" in reminder["validation_commands"]
    assert runbook.exists()
    assert str(runbook) in docs
    for required in (
        "Review completed:** 2026-08-09",
        "first patched version `2.13.0`",
        "Exception status:** removed",
        "uv lock --upgrade-package torch --upgrade-package torchvision",
        "uv run python scripts/ci/check_policy_dates.py --warn-within-days 45",
        "uv run --with pip-audit pip-audit --skip-editable --timeout 30",
        "security/pip-audit-ignores.tsv",
        "Do not move `torch` / `torchvision` into `production-minimal`",
    ):
        assert required in runbook_text


def test_zero_ruff_debt_is_enforced_after_global_ignores_are_removed() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    ruff = pyproject["tool"]["ruff"]
    lint = pyproject["tool"]["ruff"]["lint"]
    debt = pyproject["tool"]["sidar"]["ruff_debt"]

    assert ruff["line-length"] == 100
    directly_enforced = {
        "E501",
        "D200",
        "D202",
        "D205",
        "D209",
        "D212",
        "D403",
        "D415",
        "D417",
        "ASYNC240",
    }
    assert directly_enforced.isdisjoint(lint["ignore"])
    assert debt["line_length"] == 100
    assert debt["e501_global_ignore_review_by"] == "2026-09-30"
    assert isinstance(debt["e501_debt_baseline"], int)
    assert debt["e501_debt_baseline"] >= 0
    assert debt["async240_global_ignore_review_by"] == "2026-09-30"
    assert debt["global_ignores_removed_on"] == "2026-08-02"
    assert {"web_server.py", "main.py"} <= set(debt["legacy_hotspots"])
    assert (
        "uv run python scripts/ci/check_ruff_debt_baseline.py"
        in debt["planned_validation_commands"]
    )
    assert "--update" in Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")
    assert debt["docstring_async_debt_baseline"] == {
        "D200": 0,
        "D202": 0,
        "D205": 0,
        "D209": 0,
        "D212": 0,
        "D403": 0,
        "D415": 0,
        "D417": 0,
        "ASYNC240": 0,
    }


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
    assert (
        "dev-light`, `dev-full`, `dev-gpu`, `gpu-runtime`, `production`, "
        "`production-minimal` ve `custom`" in docs
    )
    assert "normal kurulum varsayılanı ve önerisi `developer-full` / `dev-full`" in docs
    assert "varsayılan production install akışı değiştirilmez" in docs


def test_dependency_profile_plan_moves_dev_tools_to_dev_extra_not_runtime_deps() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])
    dev_dependencies = set(pyproject["project"]["optional-dependencies"]["dev"])

    for package_prefix in ("pytest", "ruff", "mypy", "pyright", "bandit", "safety"):
        assert not any(dep.startswith(package_prefix) for dep in dependencies)
        assert any(dep.startswith(package_prefix) for dep in dev_dependencies)


def test_production_minimal_excludes_heavy_optional_extras() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    optional_dependencies = pyproject["project"]["optional-dependencies"]
    production_minimal = optional_dependencies["production-minimal"]
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert production_minimal == ["sidar[runtime-postgres]"]
    heavy_extras = {"rag", "gpu", "voice", "browser"}
    for dependency in production_minimal:
        requirement = Requirement(dependency)
        assert heavy_extras.isdisjoint(requirement.extras)

    heavy_packages = {
        Requirement(dependency).name
        for extra_name in heavy_extras
        for dependency in optional_dependencies[extra_name]
        if not dependency.startswith("sidar[")
    }
    production_minimal_packages = {
        Requirement(dependency).name
        for dependency in production_minimal
        if not dependency.startswith("sidar[")
    }
    assert production_minimal_packages.isdisjoint(heavy_packages)
    assert "RAG/GPU/voice/browser" in docs
    assert "test_dependency_profile_plan.py" in docs


def test_rag_torch_dependency_uses_patched_release_without_audit_exception() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    rag_deps = pyproject["project"]["optional-dependencies"]["rag"]
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")
    policy = Path("security/pip-audit-ignores.tsv").read_text(encoding="utf-8")

    assert "torch>=2.13,<2.14" in rag_deps
    assert "torchvision>=0.28,<0.29" in rag_deps
    assert "uv lock --upgrade-package torch --upgrade-package torchvision" in docs
    assert "CVE-2025-3000" in docs
    assert "Mevcut `uv.lock` çözümü `torch 2.13.0`" in docs
    assert "security/pip-audit-ignores.tsv" in Path("pyproject.toml").read_text(encoding="utf-8")
    assert "scripts/pip_audit_ignore_args.py" in docs
    reminder = pyproject["tool"]["sidar"]["dependency_profile_plan"]["torch_upgrade_reminder"]
    assert reminder["status"] == "resolved"
    assert reminder["advisory_checked_on"] == "2026-08-09"
    assert reminder["upstream_last_affected"] == "2.12.1"
    assert reminder["upstream_patched_versions"] == "2.13.0"
    assert "Çözüldü (2026-08-09)" in docs
    assert "fail-closed" in docs
    active_policy_lines = [
        line for line in policy.splitlines() if line and not line.startswith("#")
    ]
    assert not any("GHSA-rrmf-rvhw-rf47" in line for line in active_policy_lines)


def test_production_profile_excludes_dev_quality_tools() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    production_dependencies = set(pyproject["project"]["optional-dependencies"]["production"])
    docs = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")

    assert production_dependencies == {"sidar[runtime-postgres,telemetry]"}
    assert (
        "production profili `sidar[runtime-postgres,telemetry]`, production-minimal profili ise "
        "`sidar[runtime-postgres]` ile dev araçlarını ve Pyright LSP yükünü dışarıda tutar"
        in docs
    )
    assert "P2 structural hardening" in docs
    for package_prefix in ("pytest", "ruff", "mypy", "pyright", "bandit", "safety"):
        assert not any(dep.startswith(package_prefix) for dep in production_dependencies)
