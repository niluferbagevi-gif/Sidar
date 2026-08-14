"""Contracts for the release-blocking Production Compose evidence gate."""

from __future__ import annotations

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


def test_production_readiness_aggregate_requires_compose_and_minimal_profiles() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    aggregate = workflow[
        workflow.index("  production-readiness:") : workflow.index(
            "  production-profile-dry-run:"
        )
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
