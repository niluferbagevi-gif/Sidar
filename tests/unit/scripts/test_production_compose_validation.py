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


def test_container_name_fields_are_namespaced_by_compose_project_name() -> None:
    """Regression test: container_name must never be a bare literal again.

    A literal ``container_name: sidar_ollama`` (etc.) is unique per Docker
    daemon regardless of ``--project-name``/``-p``: two independent Compose
    stacks sharing the same daemon (a developer's already-running dev stack
    and scripts/ci/validate_production_compose.sh's isolated
    "sidar-production-gate" project, or two CI jobs on a self-hosted runner)
    collide with "Conflict. The container name ... is already in use" the
    moment both try to create e.g. "sidar_ollama". Every container_name must
    interpolate ``${COMPOSE_PROJECT_NAME:-sidar}`` so a distinct project name
    produces distinct container names, while the default (unset
    COMPOSE_PROJECT_NAME) still resolves to today's plain "sidar_*" names --
    see test_compose_project_name_isolates_container_names_between_stacks for
    the real-Compose-interpolation half of this contract.
    """
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    container_name_lines = [
        line for line in compose.splitlines() if line.strip().startswith("container_name:")
    ]
    assert container_name_lines, "expected at least one container_name field"
    for line in container_name_lines:
        assert "${COMPOSE_PROJECT_NAME:-sidar}_" in line, (
            f"container_name must be namespaced by COMPOSE_PROJECT_NAME: {line.strip()}"
        )


def test_validate_production_compose_exports_compose_project_name() -> None:
    """The gate must export COMPOSE_PROJECT_NAME, not just pass --project-name.

    docker-compose.yml's container_name fields interpolate
    ``${COMPOSE_PROJECT_NAME}``, which reads the environment variable --
    relying solely on the ``--project-name``/``-p`` CLI flag to populate that
    interpolation is an undocumented, Compose-version-dependent assumption.
    """
    script = Path("scripts/ci/validate_production_compose.sh").read_text(encoding="utf-8")
    assert 'export COMPOSE_PROJECT_NAME="$project_name"' in script
    assert script.index('export COMPOSE_PROJECT_NAME="$project_name"') < script.index(
        'compose=(docker compose --project-name "$project_name"'
    )


def test_validate_production_compose_isolates_postgres_volume() -> None:
    """The disposable gate must never mount or remove the development database."""
    script = Path("scripts/ci/validate_production_compose.sh").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "name: ${SIDAR_POSTGRES_VOLUME_NAME:-sidar_postgres_data}" in compose
    expected_volume_name_export = (
        "export SIDAR_POSTGRES_VOLUME_NAME="
        '"${SIDAR_POSTGRES_VOLUME_NAME:-${project_name}_postgres_data}"'
    )
    assert expected_volume_name_export in script
    assert "SIDAR_POSTGRES_VOLUME_NAME=$SIDAR_POSTGRES_VOLUME_NAME" in script
    assert script.index("export SIDAR_POSTGRES_VOLUME_NAME=") < script.index(
        'compose=(docker compose --project-name "$project_name"'
    )


@pytest.mark.integration
def test_compose_project_name_isolates_container_names_between_stacks(tmp_path: Path) -> None:
    """Real Compose interpolation: distinct project names -> distinct container names.

    Reproduces the reported "Conflict. The container name '/sidar_ollama' is
    already in use" failure mode directly: two ``docker compose config`` runs
    against the *same* docker-compose.yml, with different project names
    (mirroring a developer's plain dev stack vs.
    validate_production_compose.sh's "sidar-production-gate" project running
    concurrently on the same Docker daemon), must produce non-colliding
    container names. Also pins the required backward-compat guarantee: the
    default project name (no ``--project-name`` at all, matching every
    existing plain ``docker compose up`` invocation) still resolves to
    today's unprefixed "sidar_*" names, so scripts that hardcode e.g.
    "sidar_postgres" as their default (06_services.sh's
    ``SIDAR_POSTGRES_CONTAINER``, scripts/sync_postgres_password.py) stay
    correct.
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
                "POSTGRES_PASSWORD=compose-name-gate-postgres-password-32",
                "REDIS_PASSWORD=compose-name-gate-redis-password-32",
                "GRAFANA_ADMIN_PASSWORD=compose-name-gate-grafana-admin-password-32",
                "METRICS_TOKEN=compose-name-gate-metrics-token-32-characters",
                "API_KEY=compose-name-gate-api-key-32-characters",
                "JWT_SECRET_KEY=compose-name-gate-jwt-secret-key-32-characters",
                "MEMORY_ENCRYPTION_KEY=MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # See test_production_override_actually_closes_datastore_ports for why a
    # clean, minimal env (not the full ambient os.environ) is used here.
    # SIDAR_RUNTIME_ENV_FILE points sidar-migrate's env_file at the same
    # disposable secrets (the repo has no top-level .env of its own).
    clean_env = {
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
        "SIDAR_RUNTIME_ENV_FILE": str(env_file),
    }

    def compose_container_names(*, project_name: str | None) -> set[str]:
        command = [docker, "compose"]
        if project_name is not None:
            command += ["--project-name", project_name]
        command += [
            "--env-file",
            str(env_file),
            "-f",
            "docker-compose.yml",
            "--profile",
            "cpu",
            "config",
        ]
        completed = subprocess.run(
            command, check=False, capture_output=True, text=True, env=clean_env
        )
        assert completed.returncode == 0, completed.stderr
        merged = yaml.safe_load(completed.stdout)
        return {service["container_name"] for service in merged["services"].values()}

    dev_stack_names = compose_container_names(project_name=None)
    gate_names = compose_container_names(project_name="sidar-production-gate")

    assert "sidar_ollama" in dev_stack_names
    assert "sidar_postgres" in dev_stack_names
    assert "sidar_redis" in dev_stack_names
    assert dev_stack_names.isdisjoint(gate_names), (
        "distinct --project-name values must produce non-colliding container names",
        dev_stack_names,
        gate_names,
    )
    assert all(name.startswith("sidar-production-gate_") for name in gate_names)


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


def test_validate_production_compose_sanitizes_inherited_secret_env_vars() -> None:
    """The gate must scrub every name it generates before writing $env_file.

    Regression for a real fail-closed false positive: run_tests.sh's
    ``load_test_database_password_env`` exports ``POSTGRES_PASSWORD`` (the
    sidar_test DB password) into its own process so psql/ALTER ROLE can reach
    it, and never unsets it before later invoking this script as a child
    ``bash`` process that inherits the export. Docker Compose gives a real
    shell environment variable precedence over ``--env-file``, so that stale
    value used to get silently baked into interpolated fields like
    DATABASE_URL at ``compose config`` time, while the container's own
    POSTGRES_PASSWORD (injected via ``env_file:``, not subject to that
    precedence) kept the fresh, correct value -- tripping
    core/config_postgres.py's fail-closed drift check
    ("DATABASE_URL parolası POSTGRES_PASSWORD ile senkron değil") for a
    reason that had nothing to do with the actual run. See
    test_ambient_postgres_password_does_not_leak_into_resolved_database_url
    for the real-Compose-interpolation reproduction of this exact failure.
    """
    script = Path("scripts/ci/validate_production_compose.sh").read_text(encoding="utf-8")
    sanitize_block = script.split('project_name="${PRODUCTION_COMPOSE_PROJECT_NAME', 1)[1].split(
        'export SIDAR_RUNTIME_ENV_FILE="${SIDAR_RUNTIME_ENV_FILE', 1
    )[0]

    assert "unset -v" in sanitize_block, "gate script must unset inherited secret/config env vars"
    # The unset statement continues across multiple `\`-newline-joined lines;
    # collapse those to search it as one line for each variable name.
    unset_statement = sanitize_block.split("unset -v", maxsplit=1)[1].replace("\\\n", " ")
    generated_env = script.split('cat >"$env_file" <<EOF', maxsplit=1)[1].split(
        "\nEOF", maxsplit=1
    )[0]
    generated_variables = {
        match.group(1)
        for line in generated_env.splitlines()
        if (match := re.match(r"^([A-Z][A-Z0-9_]*)=", line))
    }
    # SIDAR_RUNTIME_ENV_FILE/SIDAR_POSTGRES_VOLUME_NAME are deliberate
    # override knobs (read via `${VAR:-default}` right after the sanitize
    # block) and must stay inheritable, not scrubbed.
    exempt_override_knobs = {"SIDAR_RUNTIME_ENV_FILE", "SIDAR_POSTGRES_VOLUME_NAME"}
    must_be_sanitized = generated_variables - exempt_override_knobs
    must_be_sanitized |= {"DATABASE_URL", "SIDAR_CONTAINER_DATABASE_URL"}
    for variable in sorted(must_be_sanitized):
        assert re.search(rf"(?:^|\s){variable}(?:\s|$)", unset_statement), (
            f"{variable} is generated by this gate but not sanitized from the inherited "
            "environment before generation"
        )


@pytest.mark.integration
def test_ambient_postgres_password_does_not_leak_into_resolved_database_url(
    tmp_path: Path,
) -> None:
    """Real-Compose reproduction of the run_tests.sh POSTGRES_PASSWORD leak.

    Fail-closed regression: without the sanitize block this asserts, an
    inherited ambient ``POSTGRES_PASSWORD`` (as run_tests.sh leaves exported
    after ``load_test_database_password_env``) silently overrides this gate's
    own freshly generated secret in every interpolated ``DATABASE_URL``,
    while ``env_file:``-injected container POSTGRES_PASSWORD stays correct --
    the exact drift core/config_postgres.py's boot-time check rejects.
    """
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")

    compose_version = subprocess.run(
        [docker, "compose", "version"], check=False, capture_output=True, text=True
    )
    if compose_version.returncode != 0:
        pytest.skip("Docker Compose plugin is not installed")

    for relative_path in (
        "docker-compose.yml",
        "docker-compose.production.yml",
        "scripts/ci/validate_production_compose.sh",
        "scripts/secret_strength.py",
        "scripts/__init__.py",
    ):
        source = Path(relative_path)
        if not source.exists():
            continue
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    # Run everything the real script runs up to (but not including) its
    # `config --quiet` sanity check, then request the *full* resolved config
    # ourselves so DATABASE_URL's interpolated password is observable.
    script = (tmp_path / "scripts/ci/validate_production_compose.sh").read_text(encoding="utf-8")
    setup, _rest = script.split('"${compose[@]}" config --quiet', maxsplit=1)
    harness = setup + '"${compose[@]}" config >"${RESOLVED_CONFIG_PATH}" 2>&1\n'
    harness_path = tmp_path / "scripts/ci/_resolve_config_harness.sh"
    harness_path.write_text(harness, encoding="utf-8")

    resolved_config_path = tmp_path / "resolved-config.yaml"
    poisoned_env = {
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
        "PRODUCTION_COMPOSE_PROJECT_NAME": f"sidar-leak-gate-{tmp_path.name}",
        "RESOLVED_CONFIG_PATH": str(resolved_config_path),
        # Exactly what run_tests.sh's load_test_database_password_env leaves
        # exported in its process (and never unsets) before invoking this
        # script as a child `bash` process.
        "POSTGRES_PASSWORD": "leaked-test-db-password-not-the-gate-secret",
    }
    completed = subprocess.run(
        ["bash", str(harness_path)],
        cwd=tmp_path,
        env=poisoned_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr

    resolved = resolved_config_path.read_text(encoding="utf-8")
    assert "leaked-test-db-password-not-the-gate-secret" not in resolved, (
        "the ambient POSTGRES_PASSWORD leaked into the resolved Compose config"
    )
    database_urls = {
        line.strip().split("DATABASE_URL: ", 1)[1]
        for line in resolved.splitlines()
        if "DATABASE_URL:" in line
    }
    assert database_urls, "expected at least one resolved DATABASE_URL in the Compose config"
    postgres_passwords = {
        line.strip().split("POSTGRES_PASSWORD: ", 1)[1]
        for line in resolved.splitlines()
        if line.strip().startswith("POSTGRES_PASSWORD:")
    }
    assert len(postgres_passwords) == 1, (
        "every service's container POSTGRES_PASSWORD must be the one shared gate secret",
        postgres_passwords,
    )
    (gate_secret,) = postgres_passwords
    assert all(gate_secret in url for url in database_urls), (
        "DATABASE_URL must be built from the gate's own generated POSTGRES_PASSWORD, "
        "not an inherited/ambient value",
        database_urls,
        gate_secret,
    )


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


@pytest.mark.integration
def test_enable_tracing_defaults_to_false_without_the_observability_profile(
    tmp_path: Path,
) -> None:
    """Regression: sidar-web/-gpu must not enable tracing by default.

    A friend's log review of the Production Compose gate found sidar-web
    retrying OTLP span exports against `jaeger:4317` and failing with
    DEADLINE_EXCEEDED -- functionally harmless but noisy boot-log spam that
    burns a few seconds on every boot. Root cause: docker-compose.yml hardcoded
    `ENABLE_TRACING=${ENABLE_TRACING:-true}` for sidar-web/-gpu, silently
    overriding config.py's own Python-level default (`ENABLE_TRACING: bool =
    False`, see core/config_observability.py) and the documented default in
    docs/project-report/04-teknik-borc-ve-yapilandirma.md ("`ENABLE_TRACING` |
    `false`"). `jaeger` only starts under `profiles: ["observability"]`, so
    any compose run with just `--profile cpu`/`gpu` (including
    scripts/ci/validate_production_compose.sh, and any plain `docker compose
    up` without also requesting the observability profile) got tracing
    silently turned on against a collector that was never started.
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
                "POSTGRES_PASSWORD=compose-tracing-gate-postgres-password-32",
                "REDIS_PASSWORD=compose-tracing-gate-redis-password-32-c",
                "GRAFANA_ADMIN_PASSWORD=compose-tracing-gate-grafana-admin-pw-32",
                "METRICS_TOKEN=compose-tracing-gate-metrics-token-32-chars",
                "API_KEY=compose-tracing-gate-api-key-32-characters",
                "JWT_SECRET_KEY=compose-tracing-gate-jwt-secret-key-32-chars",
                "MEMORY_ENCRYPTION_KEY=MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # A clean, minimal env -- see test_generated_gate_env_passes_real_compose_config
    # for why the full ambient os.environ is not inherited here.
    clean_env = {
        "HOME": str(tmp_path),
        "PATH": os.environ["PATH"],
        "SIDAR_RUNTIME_ENV_FILE": str(env_file),
    }

    for profile, services in (("cpu", ["sidar-web"]), ("gpu", ["sidar-web-gpu"])):
        completed = subprocess.run(
            [
                docker,
                "compose",
                "--project-name",
                f"sidar-tracing-default-gate-{profile}-{tmp_path.name}",
                "--env-file",
                str(env_file),
                "-f",
                "docker-compose.yml",
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
        assert "jaeger" not in merged["services"], (
            f"jaeger must stay opt-in via the observability profile, "
            f"not run under --profile {profile}"
        )
        for service_name in services:
            assert merged["services"][service_name]["environment"]["ENABLE_TRACING"] == "false", (
                f"{service_name} must not enable tracing by default when jaeger isn't running"
            )


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
    default to the dev-tooling ``Dockerfile`` (build-essential, git,
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
