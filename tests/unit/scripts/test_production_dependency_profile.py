from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_production_minimal_profile_and_artifacts_are_declared() -> None:
    """Production-minimal dependency profile should map to concrete build artifacts."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional_deps = pyproject["project"]["optional-dependencies"]
    plan = pyproject["tool"]["sidar"]["dependency_profile_plan"]

    assert optional_deps["production"] == ["sidar[runtime-postgres,telemetry]"]
    assert optional_deps["production-minimal"] == ["sidar[runtime-postgres]"]
    assert optional_deps["production-minimal"] != optional_deps["production"]
    assert plan["requirements_exporter"] == "scripts/export_production_requirements.sh"
    assert plan["production_dockerfile"] == "Dockerfile.production"
    assert {profile["name"] for profile in plan["profiles"]} >= {
        "production",
        "production-minimal",
    }


def test_canonical_dependency_profiles_are_explicit_and_composable() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional_deps = pyproject["project"]["optional-dependencies"]

    assert optional_deps["runtime-core"] == []
    assert optional_deps["runtime-postgres"] == ["sidar[postgres]"]
    assert optional_deps["runtime-gpu"] == ["sidar[rag,gpu]"]
    assert optional_deps["provider-ollama"] == []
    assert optional_deps["provider-openai"] == ["sidar[openai]"]
    assert optional_deps["provider-gemini"] == ["sidar[gemini]"]
    assert optional_deps["ci-cpu"] == ["sidar[dev,browser,sandbox]"]
    assert optional_deps["ci-gpu"] == ["sidar[ci-cpu,runtime-gpu]"]


def test_requirements_exporter_uses_uv_production_no_dev() -> None:
    """The generated requirements flow must be owned by uv and exclude dev extras."""
    exporter = (REPO_ROOT / "scripts/export_production_requirements.sh").read_text(encoding="utf-8")

    assert "uv export" in exporter
    assert "--extra production" in exporter
    assert "--no-dev" in exporter
    assert "--no-emit-project" in exporter
    assert "requirements-production.txt" in exporter


def test_production_dockerfile_uses_no_dev_profile() -> None:
    """Production image should not inherit the all-extras developer install surface."""
    dockerfile = (REPO_ROOT / "Dockerfile.production").read_text(encoding="utf-8")

    assert "# Sidar production image." in dockerfile
    assert 'LABEL description="Sidar production Web/API image"' in dockerfile
    assert "production-minimal image" not in dockerfile
    assert "uv sync --frozen --extra production --no-dev --no-install-project" in dockerfile
    assert "uv sync --frozen --extra production --no-dev" in dockerfile
    assert "--all-extras" not in dockerfile
    assert "--extra dev" not in dockerfile
    assert "FROM ${BASE_IMAGE} AS builder" in dockerfile
    assert "FROM ${BASE_IMAGE} AS runtime" in dockerfile
    assert "COPY --from=builder /app /app" in dockerfile
