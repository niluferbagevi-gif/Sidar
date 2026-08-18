"""Contracts for the release-blocking Production Compose evidence gate."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


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
    assert "GRAFANA_ADMIN_PASSWORD=$(random_secret)" in generated_env
    assert "compose-gate-grafana-admin-password-32" not in Path(
        ".github/workflows/ci.yml"
    ).read_text(encoding="utf-8")
    assert "SIDAR_RUNTIME_ENV_FILE=$env_file" in generated_env


def test_generated_gate_env_secrets_satisfy_production_entropy_policy() -> None:
    """Fail-closed regression for the gate's own disposable secrets.

    They used to be human-readable placeholders (e.g. "compose-gate-jwt-secret-key-32-characters")
    that fail Sidar's production entropy policy. That made
    `docker compose up --wait sidar-web` crash-loop on ValueError from
    config.py's Config.__init__ (JWT_SECRET_KEY/API_KEY/POSTGRES_PASSWORD
    "boş bırakılamaz") before this gate's own healthz/readyz/migration
    assertions ever ran, breaking the release-blocking evidence job it exists
    to produce. Every value produced by the script's `random_secret` helper
    must pass the app's real `is_weak_secret` check.
    """
    from core.config_secrets import is_weak_secret

    script = Path("scripts/ci/validate_production_compose.sh").read_text(encoding="utf-8")
    assert "random_secret()" in script, "gate script must generate secrets via random_secret()"

    function_source = script.split("random_secret() {", maxsplit=1)[1].split("\n}", maxsplit=1)[0]
    completed = subprocess.run(
        [
            "bash",
            "-c",
            f"random_secret() {{{function_source}\n}}\nfor _ in 1 2 3; do random_secret; done",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    generated_values = [line for line in completed.stdout.splitlines() if line]
    assert len(generated_values) == 3
    for value in generated_values:
        assert not is_weak_secret(value), f"random_secret() produced a weak value: {value!r}"

    for key in (
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "GRAFANA_ADMIN_PASSWORD",
        "METRICS_TOKEN",
        "API_KEY",
        "JWT_SECRET_KEY",
        "AUTONOMY_WEBHOOK_SECRET",
        "SWARM_FEDERATION_SHARED_SECRET",
        "GITHUB_WEBHOOK_SECRET",
    ):
        assert f"{key}=$(random_secret)" in script, f"{key} must use random_secret()"


def test_production_profile_is_the_compose_service_env_contract() -> None:
    """CLI interpolation and container injection must use one production file."""
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    production_env = Path(".env.production.example").read_text(encoding="utf-8")

    assert compose.count("- ${SIDAR_RUNTIME_ENV_FILE:-.env}") == 5
    assert "SIDAR_RUNTIME_ENV_FILE=.env.production" in production_env


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


@pytest.mark.integration
def test_production_override_actually_closes_datastore_ports(tmp_path: Path) -> None:
    """`ports: []` in the override does NOT close a base file's published port.

    Fail-closed regression: Compose merges list fields like `ports` by
    replacing them only when the override's list is non-empty; an empty
    list contributes nothing, so the override's `ports: []` silently left
    redis/postgres/ollama/ollama-gpu published exactly as the base file
    defined them. Verified in isolation with a minimal two-file repro
    (`ports: []` left `8080:80` untouched) before fixing this file to use
    the compose-spec `!reset` merge tag, which actually clears the list.
    This test runs the *real* `docker compose config` (not a text/substring
    check) so a future edit that reintroduces plain `ports: []` fails here.
    """
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")

    compose_version = subprocess.run(
        [docker, "compose", "version"], check=False, capture_output=True, text=True
    )
    if compose_version.returncode != 0:
        pytest.skip("Docker Compose plugin is not installed")

    env_file = tmp_path / "gate.env"
    env_file.write_text(
        "\n".join(
            [
                "SIDAR_ENV=production",
                "POSTGRES_DB=sidar",
                "POSTGRES_USER=sidar",
                "POSTGRES_PASSWORD=compose-gate-postgres-password-32",
                "REDIS_PASSWORD=compose-gate-redis-password-32",
                "GRAFANA_ADMIN_PASSWORD=compose-gate-grafana-admin-password-32",
                "METRICS_TOKEN=compose-gate-metrics-token-32-characters",
                "API_KEY=compose-gate-api-key-32-characters",
                "JWT_SECRET_KEY=compose-gate-jwt-secret-key-32-characters",
                "MEMORY_ENCRYPTION_KEY=MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                "SIDAR_DATA_MOUNT=sidar_data_prod",
                "SIDAR_LOGS_MOUNT=sidar_logs_prod",
                "SIDAR_TEMP_MOUNT=sidar_temp_prod",
                "WEB_PORT=7860",
                "WEB_GPU_PORT=7861",
                "",
            ]
        ),
        encoding="utf-8",
    )

    # Docker Compose gives real shell environment variables precedence over
    # --env-file, so inheriting the full ambient os.environ here would let an
    # unrelated WEB_PORT/WEB_GPU_PORT set by some other step in the same CI
    # job silently override the gate.env values above and make the published
    # port assertions below flaky/host-dependent. Pass a clean, minimal env
    # instead (same approach as test_generated_gate_env_passes_real_compose_config).
    clean_env = {
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
        "SIDAR_RUNTIME_ENV_FILE": str(env_file),
    }

    for profile, closed_services, published_services in (
        ("cpu", ("redis", "postgres", "ollama"), {"sidar-web": "7860"}),
        ("gpu", ("redis", "postgres", "ollama-gpu"), {"sidar-web-gpu": "7861"}),
    ):
        completed = subprocess.run(
            [
                docker,
                "compose",
                "--project-name",
                f"sidar-port-gate-{profile}-{tmp_path.name}",
                "--env-file",
                str(env_file),
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.production.yml",
                "--profile",
                profile,
                "config",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=clean_env,
        )
        assert completed.returncode == 0, completed.stderr
        merged = yaml.safe_load(completed.stdout)
        services = merged["services"]

        for name in closed_services:
            assert not services[name].get("ports"), (
                f"{name} ({profile} profile) is still published in production: "
                f"{services[name].get('ports')!r}"
            )

        for name, expected_published_port in published_services.items():
            ports = services[name]["ports"]
            assert any(str(p.get("published")) == expected_published_port for p in ports), (
                name,
                ports,
            )
            assert services[name]["restart"] == "always"
            assert services[name]["healthcheck"]["test"][0] == "CMD-SHELL"
            assert {v["source"] for v in services[name]["volumes"]} == {
                "sidar_data_prod",
                "sidar_logs_prod",
                "sidar_temp_prod",
            }


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


def test_production_override_builds_the_hardened_production_dockerfile() -> None:
    """Regression guard: the production gate must never fall back to the dev Dockerfile.

    ``docker-compose.yml``'s ``build:`` blocks never set ``dockerfile:``, so they
    default to the dev-tooling ``Dockerfile`` (build-essential, cargo, git,
    pyright, shellcheck, ...). Without an explicit override here, the
    "production" Compose gate silently ships that dev image instead of the
    minimal, no-dev ``Dockerfile.production``.
    """
    base = Path("docker-compose.yml").read_text(encoding="utf-8")
    override = Path("docker-compose.production.yml").read_text(encoding="utf-8")

    assert "dockerfile:" not in base, (
        "docker-compose.yml now pins a dockerfile: for a build service; "
        "re-check whether docker-compose.production.yml's override is still needed/correct."
    )
    assert "dockerfile: Dockerfile.production" in override
    # The dev command syntax (main.py's `--quick web ...` CLI) is invalid against
    # Dockerfile.production's `uvicorn web_server:app` ENTRYPOINT and must be reset.
    assert 'command: ["--host", "0.0.0.0", "--port", "7860"]' in override
