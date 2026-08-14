"""Contracts for the release-blocking Production Compose evidence gate."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def test_production_compose_gate_covers_runtime_release_evidence() -> None:
    script = Path("scripts/ci/validate_production_compose.sh").read_text(encoding="utf-8")

    for evidence in (
        "up --detach --build --wait sidar-web",
        "postgres redis sidar-web",
        "/healthz",
        "/readyz",
        "alembic heads",
        "alembic current",
        "restart sidar-web",
        ".production-compose-marker",
        "stop --timeout 20 sidar-web",
        ".State.ExitCode",
    ):
        assert evidence in script


def test_generated_gate_env_satisfies_required_compose_interpolation() -> None:
    """Disposable gate secrets must cover every fail-closed Compose variable."""
    script = Path("scripts/ci/validate_production_compose.sh").read_text(encoding="utf-8")
    compose = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("docker-compose.yml", "docker-compose.production.yml")
    )
    generated_env = script.split('cat >"$env_file" <<EOF', maxsplit=1)[1].split(
        "\nEOF", maxsplit=1
    )[0]

    required_variables = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):\?", compose))
    generated_variables = {
        match.group(1)
        for line in generated_env.splitlines()
        if (match := re.match(r"^([A-Z][A-Z0-9_]*)=", line))
    }

    assert required_variables <= generated_variables
    assert "GRAFANA_ADMIN_PASSWORD=compose-gate-grafana-admin-password-32" in generated_env
    assert "compose-gate-grafana-admin-password-32" not in Path(
        ".github/workflows/ci.yml"
    ).read_text(encoding="utf-8")


@pytest.mark.integration
def test_generated_gate_env_passes_real_compose_config(tmp_path: Path) -> None:
    """Run Compose interpolation against the gate-generated disposable environment."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")

    compose_version = subprocess.run(
        [docker, "compose", "version"],
        check=False,
        capture_output=True,
        text=True,
    )
    if compose_version.returncode != 0:
        pytest.skip("Docker Compose plugin is not installed")

    for relative_path in (
        "docker-compose.yml",
        "docker-compose.production.yml",
        "scripts/ci/validate_production_compose.sh",
    ):
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(relative_path, destination)

    clean_env = {
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
        "PRODUCTION_COMPOSE_CONFIG_ONLY": "1",
        "PRODUCTION_COMPOSE_PROJECT_NAME": f"sidar-compose-config-{tmp_path.name}",
    }
    completed = subprocess.run(
        ["bash", "scripts/ci/validate_production_compose.sh"],
        cwd=tmp_path,
        env=clean_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / ".env.production.compose-gate").exists()
    assert not (tmp_path / ".env").exists()


def test_production_readiness_aggregate_requires_compose_and_minimal_profiles() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    aggregate = workflow[
        workflow.index("  production-readiness:") : workflow.index("  production-profile-dry-run:")
    ]

    assert "production-compose-validation" in aggregate
    assert "production-profile-dry-run" in aggregate
    assert "Production Compose runtime gates passed" in aggregate


def test_production_override_requires_healthcheck_restart_and_named_volumes() -> None:
    override = Path("docker-compose.production.yml").read_text(encoding="utf-8")

    assert "restart: always" in override
    assert "http://localhost:7860/healthz" in override
    assert "sidar_data_prod:/app/data" in override
    assert "sidar_logs_prod:/app/logs" in override
    assert "sidar_temp_prod:/app/temp" in override
