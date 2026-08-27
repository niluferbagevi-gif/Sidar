from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PYTHON_MAJOR_MINOR = "3.11.15"
PYTHON_BASE_IMAGE = f"python:{PYTHON_MAJOR_MINOR}-slim"
UV_IMAGE = (
    "ghcr.io/astral-sh/uv:0.12.0@"
    "sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105"
)
PRODUCTION_PYTHON_IMAGE = (
    "python:3.11.15-slim-bookworm@"
    "sha256:d29f48a31a8b408ed19272ca1e7b10ebae13b240a27e862d3d4217c528e2e0c3"
)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def test_main_dockerfile_defaults_to_python_311_runtime():
    dockerfile = _read("Dockerfile")

    assert f"ARG PYTHON_VERSION={PYTHON_MAJOR_MINOR}" in dockerfile
    assert "ARG BASE_IMAGE=python:${PYTHON_VERSION}-slim" in dockerfile
    assert "FROM ${BASE_IMAGE}" in dockerfile
    assert "UV_PYTHON=${PYTHON_VERSION}" in dockerfile
    assert "python:3.12" not in dockerfile


def test_main_dockerfile_installs_shellcheck_os_package():
    dockerfile = _read("Dockerfile")

    assert "shellcheck \\" in dockerfile
    assert dockerfile.index("pkg-config") < dockerfile.index("shellcheck")
    # System apt layer uses a BuildKit cache mount (no baked-in
    # `rm -rf /var/lib/apt/lists/*`), so anchor on the ENV block that
    # follows it to confirm shellcheck still lands in that same layer.
    assert dockerfile.index("shellcheck") < dockerfile.index("ENV UV_INDEX_STRATEGY=first-index")


def test_main_dockerfile_uses_cache_mount_for_apt_not_baked_in_lists_cleanup():
    """Regression: GPU builds previously re-downloaded the same .deb archives every time.

    A BuildKit cache mount keeps them across builds instead. Cache mounts
    never persist into the image layer, so the old
    `rm -rf /var/lib/apt/lists/*` cleanup would only defeat the cache.
    """
    dockerfile = _read("Dockerfile")

    assert "--mount=type=cache,target=/var/cache/apt" in dockerfile
    assert "--mount=type=cache,target=/var/lib/apt/lists" in dockerfile


def test_main_dockerfile_installs_gpu_python_via_uv_not_deadsnakes_ppa():
    """Regression: a GPU (Ubuntu-based nvidia/cuda) build previously added the deadsnakes PPA.

    That dragged in ~60 unrelated packages (software-properties-common,
    dbus, PackageKit, PolicyKit, ...) and could trip tzdata's interactive
    prompt. `uv python install` provisions the same pinned version without
    apt/PPA at all.
    """
    dockerfile = _read("Dockerfile")

    assert "uv python install ${PYTHON_VERSION}" in dockerfile
    assert "deadsnakes" not in dockerfile
    assert "add-apt-repository" not in dockerfile
    assert "software-properties-common" not in dockerfile


def test_main_dockerfile_disables_interactive_apt_prompts():
    """Regression: without DEBIAN_FRONTEND=noninteractive, tzdata drops apt into a prompt.

    tzdata is pulled in transitively by packages like
    docker.io/ffmpeg/alsa-utils on an Ubuntu-based GPU base image, and the
    interactive timezone prompt it triggers hangs forever in a TTY-less CI
    build.
    """
    dockerfile = _read("Dockerfile")

    assert "DEBIAN_FRONTEND=noninteractive" in dockerfile
    assert "TZ=Etc/UTC" in dockerfile
    # Anchor on the actual apt RUN instruction (not just any "apt-get
    # install" substring — the file's GPU usage comment near the top also
    # mentions one) to confirm the ENV lands before that layer runs.
    assert dockerfile.index("DEBIAN_FRONTEND=noninteractive") < dockerfile.index(
        "RUN --mount=type=cache,target=/var/cache/apt"
    )


def test_main_dockerfile_preinstalls_uv_for_sandbox_regression_tests():
    dockerfile = _read("Dockerfile")

    assert f"COPY --from={UV_IMAGE} /uv /uvx /bin/" in dockerfile
    assert "ghcr.io/astral-sh/uv:latest" not in dockerfile
    assert "RUN uv --version && uvx --version" in dockerfile


def test_production_dockerfile_pins_build_inputs_by_version_and_digest():
    dockerfile = _read("Dockerfile.production")

    assert f"ARG BASE_IMAGE={PRODUCTION_PYTHON_IMAGE}" in dockerfile
    assert f"COPY --from={UV_IMAGE} /uv /uvx /bin/" in dockerfile
    assert "ghcr.io/astral-sh/uv:latest" not in dockerfile


def test_production_dockerfile_keeps_build_toolchain_out_of_runtime_stage():
    """The deploy image must copy artifacts, not compilers or package managers."""
    dockerfile = _read("Dockerfile.production")
    builder, runtime = dockerfile.split("FROM ${BASE_IMAGE} AS runtime", maxsplit=1)

    assert "FROM ${BASE_IMAGE} AS builder" in builder
    assert "build-essential git" in builder
    assert "COPY --from=builder /app /app" in runtime
    runtime_apt = runtime.split("apt-get install -y --no-install-recommends", maxsplit=1)[1].split(
        "rm -rf /var/lib/apt/lists/*", maxsplit=1
    )[0]
    for build_only in ("build-essential", " git", "/uv /uvx", "python3-pip", "python3-venv"):
        assert build_only not in runtime_apt
    assert "ca-certificates curl ffmpeg" in runtime_apt


def test_main_dockerfile_documents_current_cuda_13_example_consistently():
    dockerfile = _read("Dockerfile")

    assert "nvidia/cuda:13.0.0-runtime-ubuntu22.04" in dockerfile
    assert "nvidia/cuda:12.6" not in dockerfile


def test_main_dockerfile_validates_pyright_lsp_binary_for_reviewer_semantics():
    dockerfile = _read("Dockerfile")

    assert "shutil.which('pyright-langserver')" in dockerfile
    assert "shutil.which('pyright')" in dockerfile


def test_dockerfiles_only_grant_runtime_user_ownership_to_writable_directories():
    """Keep application sources and the virtualenv root-owned in runtime images."""
    writable_directories = (
        "/app/logs",
        "/app/data",
        "/app/temp",
        "/app/sessions",
        "/app/chroma_db",
    )

    for relative_path in ("Dockerfile", "Dockerfile.production"):
        dockerfile = _read(relative_path)
        ownership_instruction = dockerfile.split("&& chown -R sidaruser:sidaruser", maxsplit=1)[
            1
        ].split("USER sidaruser", maxsplit=1)[0]

        assert ownership_instruction.replace("\\\n", " ").split() == [*writable_directories]
        assert "/app/.venv" not in ownership_instruction


def test_compose_cpu_builds_use_python_311_base_image():
    compose = _read("docker-compose.yml")

    assert compose.count(f"BASE_IMAGE: {PYTHON_BASE_IMAGE}") >= 2
    assert "BASE_IMAGE: python:3.12" not in compose
    assert "python:3.12-slim" not in compose


def test_compose_postgres_volume_uses_predictable_name():
    compose = _read("docker-compose.yml")

    assert "- postgres_data:/var/lib/postgresql/data" in compose
    assert "  postgres_data:\n    name: sidar_postgres_data" in compose


def test_compose_ollama_service_keeps_model_warm_for_gpu_benchmark_stability():
    compose = _read("docker-compose.yml")

    assert "OLLAMA_NUM_PARALLEL=${OLLAMA_NUM_PARALLEL:-4}" in compose
    assert "OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE:-30m}" in compose


def test_prod_staging_helm_values_do_not_pin_python_312_images():
    helm_files = [
        *ROOT.glob("helm/sidar/values*.yaml"),
        *ROOT.glob("sidar_assets/helm/sidar/values*.yaml"),
    ]
    assert helm_files

    for path in helm_files:
        text = path.read_text()
        assert "python:3.12" not in text, path
        assert "python:3.12-slim" not in text, path


def test_helm_values_use_external_postgresql_secrets_only():
    value_paths = (
        "helm/sidar/values.yaml",
        "helm/sidar/values-prod.yaml",
        "helm/sidar/values-staging.yaml",
        "sidar_assets/helm/sidar/values.yaml",
        "sidar_assets/helm/sidar/values-prod.yaml",
        "sidar_assets/helm/sidar/values-staging.yaml",
    )

    values = _read("helm/sidar/values.yaml")
    assert 'command: ["python", "main.py", "--quick", "web"]' in values
    assert "sidar.py" not in values

    for rel_path in value_paths:
        document = yaml.safe_load((ROOT / rel_path).read_text())
        postgresql = document["postgresql"]
        assert "password" not in postgresql
        assert "existingSecret" in postgresql

    base_values = yaml.safe_load((ROOT / "helm/sidar/values.yaml").read_text())
    assert base_values["postgresql"]["existingSecret"] == {
        "name": "",
        "databaseUrlKey": "DATABASE_URL",
        "databaseKey": "POSTGRES_DB",
        "usernameKey": "POSTGRES_USER",
        "passwordKey": "POSTGRES_PASSWORD",
    }


def test_helm_deployments_read_database_url_from_secret():
    for rel_path in (
        "helm/sidar/templates/deployment-web.yaml",
        "helm/sidar/templates/deployment-ai-worker.yaml",
        "sidar_assets/helm/sidar/templates/deployment-web.yaml",
        "sidar_assets/helm/sidar/templates/deployment-ai-worker.yaml",
    ):
        template = _read(rel_path)
        assert "valueFrom:" in template
        assert "secretKeyRef:" in template
        assert "key: {{ .Values.postgresql.existingSecret.databaseUrlKey | quote }}" in template
        assert ".Values.postgresql.password" not in template


def test_helm_deployments_share_hardened_security_context():
    # ai-worker runs more capable tooling (docker CLI for sandboxed code
    # execution, git for project ops) than web, so it must be at least as
    # hardened, not less — a reviewer previously found ai-worker shipped
    # with no securityContext at all while web had one.
    expected_container_security_context = (
        "securityContext:\n"
        "            allowPrivilegeEscalation: false\n"
        "            readOnlyRootFilesystem: false\n"
        "            runAsNonRoot: true\n"
        "            runAsUser: 1000\n"
        "            capabilities:\n"
        '              drop: ["ALL"]'
    )
    for rel_path in (
        "helm/sidar/templates/deployment-web.yaml",
        "helm/sidar/templates/deployment-ai-worker.yaml",
        "sidar_assets/helm/sidar/templates/deployment-web.yaml",
        "sidar_assets/helm/sidar/templates/deployment-ai-worker.yaml",
    ):
        template = _read(rel_path)
        assert expected_container_security_context in template, rel_path
        assert "fsGroup: 1000" in template, rel_path


def test_helm_chart_rejects_inline_postgresql_password_generation():
    for rel_path in (
        "helm/sidar/templates/secret-postgresql.yaml",
        "sidar_assets/helm/sidar/templates/secret-postgresql.yaml",
    ):
        template = _read(rel_path)
        assert "kind: Secret" not in template
        assert "fail " in template
        assert "postgresql.existingSecret.name" in template
        assert ".Values.postgresql.password" not in template


def test_observability_compose_pins_tracing_and_exports_infra_metrics():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    assert services["redis"]["image"] == "redis:7.4-alpine"
    assert services["postgres"]["image"] == "pgvector/pgvector:0.8.1-pg16"

    assert services["jaeger"]["image"] == "jaegertracing/all-in-one:1.63.0"
    assert ":latest" not in services["jaeger"]["image"]

    assert services["redis-exporter"]["image"] == "oliver006/redis_exporter:v1.67.0"
    redis_exporter_env = services["redis-exporter"]["environment"]
    assert "REDIS_ADDR=redis://redis:6379" in redis_exporter_env
    assert any(str(item).startswith("REDIS_PASSWORD=") for item in redis_exporter_env)

    assert services["redis"]["ports"] == ["127.0.0.1:${REDIS_PORT:-6379}:6379"]
    assert "--requirepass" in services["redis"]["command"]

    postgres_exporter = services["postgres-exporter"]
    assert postgres_exporter["image"] == "prometheuscommunity/postgres-exporter:v0.15.0"
    assert any(
        item.startswith("DATA_SOURCE_NAME=postgresql://")
        for item in postgres_exporter["environment"]
    )
    assert postgres_exporter["depends_on"]["postgres"]["condition"] == "service_healthy"

    cadvisor = services["cadvisor"]
    assert cadvisor["image"] == "gcr.io/cadvisor/cadvisor:v0.49.1"
    assert cadvisor["privileged"] is True
    assert "/var/lib/docker:/var/lib/docker:ro" in cadvisor["volumes"]

    assert set(services["prometheus"]["depends_on"]) == {
        "redis-exporter",
        "postgres-exporter",
        "cadvisor",
        "prometheus-token-init",
    }
    assert (
        services["prometheus"]["depends_on"]["prometheus-token-init"]["condition"]
        == "service_completed_successfully"
    )
    assert services["prometheus"]["image"] == "prom/prometheus:v2.54.1"
    assert services["grafana"]["image"] == "grafana/grafana:11.2.0"
    assert services["grafana"]["healthcheck"]["test"][0] == "CMD-SHELL"


def test_observability_profile_services_have_resource_limits():
    """Ensure the observability sidecars can't starve the host of CPU/memory.

    A code review flagged that jaeger/the exporters/cadvisor (and, by the
    same standard already applied to sidar-web/sidar-ai, prometheus/grafana
    too) had no resource limits at all, unlike sidar-web/sidar-ai which set
    both the top-level `cpus`/`mem_limit` shorthand and the
    `deploy.resources.limits` block. Healthchecks for these services were
    deliberately NOT added in the same change — see the comment above the
    jaeger service in docker-compose.yml for why (this sandbox has no live
    Docker daemon to verify wget/curl/shell exist in each third-party image,
    and a wrong guess produces a permanently-misleading "unhealthy" status).
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    for service_name in (
        "jaeger",
        "redis-exporter",
        "postgres-exporter",
        "cadvisor",
        "prometheus",
        "grafana",
    ):
        service = services[service_name]
        assert "cpus" in service, f"{service_name} is missing a top-level cpus limit"
        assert "mem_limit" in service, f"{service_name} is missing a top-level mem_limit"
        limits = service["deploy"]["resources"]["limits"]
        assert limits["cpus"]
        assert limits["memory"]


def test_prometheus_scrape_of_authenticated_sidar_endpoints_carries_a_bearer_token():
    """Fail-closed regression for a review comment.

    prometheus.yml never sent any Authorization header for the sidar-web/
    sidar-gpu jobs, but web_server.py's global auth middleware 401s *every*
    request lacking `Authorization: Bearer ...` - independent of whether
    METRICS_TOKEN is configured. Scraping those two jobs was therefore
    always broken, not just when the documented METRICS_TOKEN hardening
    step was turned on. docker-compose.yml's prometheus-token-init writes
    METRICS_TOKEN into the file prometheus.yml now points both jobs at
    (fail-closed via a required env var if METRICS_TOKEN is unset); the
    exporter jobs (redis/postgres/cadvisor) are untouched since they are
    unauthenticated third-party processes outside Sidar's own auth guard.
    """
    prometheus_yml = yaml.safe_load(
        (ROOT / "docker_setup" / "prometheus" / "prometheus.yml").read_text()
    )
    jobs = {job["job_name"]: job for job in prometheus_yml["scrape_configs"]}

    for job_name in ("sidar-web", "sidar-gpu"):
        assert jobs[job_name]["bearer_token_file"] == "/etc/prometheus-secrets/metrics_token"
    for job_name in ("redis-exporter", "postgres-exporter", "cadvisor"):
        assert "bearer_token_file" not in jobs[job_name]
        assert "bearer_token" not in jobs[job_name]

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    init_service = services["prometheus-token-init"]
    assert init_service["profiles"] == ["observability"]
    assert "${METRICS_TOKEN:?" in " ".join(init_service["command"])
    assert {"prometheus_secrets:/etc/prometheus-secrets"} <= set(init_service["volumes"])

    assert "prometheus_secrets:/etc/prometheus-secrets:ro" in services["prometheus"]["volumes"]
    assert "prometheus_secrets" in compose["volumes"]


def test_postgres_and_ollama_ports_bind_to_loopback_like_redis():
    """Ensure Postgres/Ollama host ports never bind wider than Redis's loopback-only policy.

    Fail-closed regression: a review comment flagged that redis's port was
    scoped to `127.0.0.1` while postgres/ollama/ollama-gpu published to all
    interfaces (`"5432:5432"` / `"11434:11434"`) with no host_ip prefix —
    reachable from the LAN/WSL even with a strong POSTGRES_PASSWORD, and
    Ollama's API has no authentication of its own at all.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    assert services["postgres"]["ports"] == ["127.0.0.1:${POSTGRES_PORT:-5432}:5432"]
    assert services["ollama"]["ports"] == ["127.0.0.1:${OLLAMA_PORT:-11434}:11434"]
    assert services["ollama-gpu"]["ports"] == ["127.0.0.1:${OLLAMA_PORT:-11434}:11434"]


def test_ollama_services_have_a_healthcheck_and_dependents_wait_for_it():
    """Ensure Ollama's startup can't race the first request against it.

    A review comment flagged that redis/postgres both have a healthcheck and
    are waited on via `condition: service_healthy`, but ollama/ollama-gpu had
    neither: they only defined `condition: service_started`, which is
    satisfied the instant the container process starts — not when Ollama's
    HTTP API is actually ready to serve requests. Ollama's official image
    has no curl/wget in its runtime stage (verified against its Dockerfile),
    so the healthcheck uses the `ollama` binary already in the image
    (`ollama list`, which itself talks to the local API and fails until the
    server is up) instead of redis/postgres's curl/pg_isready style.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    for service_name in ("ollama", "ollama-gpu"):
        healthcheck = services[service_name]["healthcheck"]
        assert healthcheck["test"] == ["CMD", "ollama", "list"]
        assert healthcheck["retries"] >= 1

    for service_name in ("sidar-ai", "sidar-web", "sidar-gpu", "sidar-web-gpu"):
        depends_on = services[service_name]["depends_on"]
        for ollama_dep in ("ollama", "ollama-gpu"):
            if ollama_dep in depends_on:
                assert depends_on[ollama_dep]["condition"] == "service_healthy"


def test_ollama_image_is_pinned_not_latest():
    """Ollama was the only unpinned image in docker-compose.yml.

    A code review flagged that every other image (redis, postgres, jaeger,
    the exporters) is pinned to a specific version, but ollama/ollama-gpu
    used `ollama/ollama:latest` — an upstream release can silently change
    behavior/API surface on the next `docker compose pull` with no diff in
    this repo to review.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    for service_name in ("ollama", "ollama-gpu"):
        image = services[service_name]["image"]
        assert image.startswith("ollama/ollama:")
        assert ":latest" not in image


def test_helm_redis_and_postgresql_images_match_docker_compose_pins():
    """Helm's redis/postgresql images must not drift from docker-compose.yml.

    A code review found docker-compose.yml pins `redis:7.4-alpine` /
    `pgvector/pgvector:0.8.1-pg16`, while the Helm chart's values.yaml used
    unversioned `redis:alpine` / `pgvector/pgvector:pg16` — a real
    Compose-vs-Helm version mismatch, not just a cosmetic one, since neither
    values-prod.yaml nor values-staging.yaml override these image fields
    (verified: only `image.tag`, the app's own image, is CI-overridden).
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    redis_image = compose["services"]["redis"]["image"]
    postgres_image = compose["services"]["postgres"]["image"]

    for rel_path in ("helm/sidar/values.yaml", "sidar_assets/helm/sidar/values.yaml"):
        document = yaml.safe_load((ROOT / rel_path).read_text())
        assert document["redis"]["image"] == redis_image
        assert document["postgresql"]["image"] == postgres_image
        # values-prod.yaml/values-staging.yaml must not silently reintroduce
        # an unpinned override on top of the base file's pinned image.
        for overlay in (
            rel_path.replace("values.yaml", "values-prod.yaml"),
            rel_path.replace("values.yaml", "values-staging.yaml"),
        ):
            overlay_doc = yaml.safe_load((ROOT / overlay).read_text())
            assert "image" not in overlay_doc.get("redis", {})
            assert "image" not in overlay_doc.get("postgresql", {})


def test_cli_sandbox_services_use_docker_socket_proxy_not_raw_host_socket():
    """Ensure sandbox services never mount the raw host Docker socket.

    Fail-closed regression: sidar-ai/sidar-gpu must never mount the raw host
    Docker socket directly. Doing so grants host-root-equivalent access
    (container escape via `docker run --privileged -v /:/host`), contradicting
    their `ACCESS_LEVEL=sandbox` label. They must instead reach the daemon
    through docker-socket-proxy, which only exposes the container
    create/start/stop/logs operations CodeManager actually needs.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    proxy = services["docker-socket-proxy"]
    assert proxy["volumes"] == ["/var/run/docker.sock:/var/run/docker.sock:ro"]
    assert "ports" not in proxy
    proxy_env = set(proxy["environment"])
    assert "EXEC=0" in proxy_env
    assert "VOLUMES=0" in proxy_env
    assert "NETWORKS=0" in proxy_env
    assert "SYSTEM=0" in proxy_env
    assert "CONTAINERS=1" in proxy_env
    assert "POST=1" in proxy_env

    for name in ("sidar-ai", "sidar-gpu"):
        service = services[name]
        volume_sources = [str(v) for v in service.get("volumes") or []]
        assert not any("docker.sock" in v for v in volume_sources), name
        env = service.get("environment") or []
        assert any(str(item).startswith("DOCKER_HOST=") for item in env), name
        assert "docker-socket-proxy" in service["depends_on"], name


def test_dockerignore_exists_and_excludes_secrets_from_build_context():
    """Regression: `.env`/`.env.production`/`.env.test` must never reach the Docker build context.

    `Dockerfile`/`Dockerfile.production` both use `COPY . .`. `.gitignore`
    only affects git, not the Docker build context, so without a root
    `.dockerignore` any secret env file left at the repo root by
    `install_sidar.sh` (including the 8 secrets covered by
    `runbooks/production-cutover-playbook.md` §1.5 production secret
    rotation) would be sent to the daemon and baked into image layers by
    `docker build .`.
    """
    dockerignore = _read(".dockerignore")

    # Secret-bearing env files must be excluded, but documented examples
    # (which hold no real secrets) stay available for onboarding.
    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "!.env.example" in dockerignore
    assert "!.env.production.example" in dockerignore
    assert "!.env.test.example" in dockerignore
    assert "/secrets/" in dockerignore
    assert "/credentials/" in dockerignore
    assert ".sidar_keys.env" in dockerignore

    # VCS metadata and local dependency/cache trees never need to reach the
    # image and bloat the build context.
    assert ".git" in dockerignore
    assert "web_ui_react/node_modules/" in dockerignore
    assert ".venv/" in dockerignore


def test_dockerignore_preserves_react_spa_build_output():
    """Regression: a blanket `dist/`/`build/` exclusion must not swallow `web_ui_react/dist`.

    `web_server.py` serves the SPA from `web_ui_react/dist` (see
    `web_dist_path()`), which `release-quality.yml` builds via
    `npm run build` *before* `docker build`, not inside the Dockerfile. A
    generic `dist/`/`build/` rule would therefore also match
    `web_ui_react/dist` and silently ship an image with no frontend.
    """
    dockerignore = _read(".dockerignore")
    ignored_lines = {
        line.strip()
        for line in dockerignore.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "dist/" not in ignored_lines
    assert "build/" not in ignored_lines
    assert "/dist/" not in ignored_lines
    assert "/build/" not in ignored_lines


def test_prometheus_scrapes_sidar_and_infra_exporters():
    prometheus = yaml.safe_load((ROOT / "docker_setup/prometheus/prometheus.yml").read_text())
    scrape_targets = {
        config["job_name"]: config["static_configs"][0]["targets"]
        for config in prometheus["scrape_configs"]
    }

    assert scrape_targets == {
        "sidar-web": ["sidar-web:7860"],
        "sidar-gpu": ["sidar-web:7860"],
        "redis-exporter": ["redis-exporter:9121"],
        "postgres-exporter": ["postgres-exporter:9187"],
        "cadvisor": ["cadvisor:8080"],
    }
    metrics_paths = {
        config["job_name"]: config["metrics_path"]
        for config in prometheus["scrape_configs"]
        if "metrics_path" in config
    }
    assert metrics_paths == {
        "sidar-web": "/metrics/llm/prometheus",
        "sidar-gpu": "/metrics",
    }
