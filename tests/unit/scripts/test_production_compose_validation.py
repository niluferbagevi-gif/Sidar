"""Contracts for the release-blocking Production Compose evidence gate."""

from __future__ import annotations

import re
from pathlib import Path


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
