from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PYTHON_MAJOR_MINOR = "3.11"
PYTHON_BASE_IMAGE = f"python:{PYTHON_MAJOR_MINOR}-slim"


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
    assert dockerfile.index("shellcheck") < dockerfile.index("rm -rf /var/lib/apt/lists/*")


def test_main_dockerfile_preinstalls_uv_for_sandbox_regression_tests():
    dockerfile = _read("Dockerfile")

    assert "COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/" in dockerfile
    assert "RUN uv --version && uvx --version" in dockerfile


def test_main_dockerfile_validates_pyright_lsp_binary_for_reviewer_semantics():
    dockerfile = _read("Dockerfile")

    assert "shutil.which('pyright-langserver')" in dockerfile
    assert "shutil.which('pyright')" in dockerfile


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

    assert services["prometheus"]["depends_on"] == [
        "redis-exporter",
        "postgres-exporter",
        "cadvisor",
    ]
    assert services["prometheus"]["image"] == "prom/prometheus:v2.54.1"
    assert services["grafana"]["image"] == "grafana/grafana:11.2.0"
    assert services["grafana"]["healthcheck"]["test"][0] == "CMD-SHELL"


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
