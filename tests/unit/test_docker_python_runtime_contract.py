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


def test_observability_compose_pins_tracing_and_exports_infra_metrics():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    assert services["redis"]["image"] == "redis:7.4-alpine"
    assert services["postgres"]["image"] == "pgvector/pgvector:0.8.1-pg16"

    assert services["jaeger"]["image"] == "jaegertracing/all-in-one:1.63.0"
    assert ":latest" not in services["jaeger"]["image"]

    assert services["redis-exporter"]["image"] == "oliver006/redis_exporter:v1.67.0"
    assert services["redis-exporter"]["environment"] == ["REDIS_ADDR=redis://redis:6379"]

    postgres_exporter = services["postgres-exporter"]
    assert postgres_exporter["image"] == "prometheuscommunity/postgres-exporter:v0.15.0"
    assert any(
        item.startswith("DATA_SOURCE_NAME=postgresql://")
        for item in postgres_exporter["environment"]
    )
    assert postgres_exporter["depends_on"]["postgres"]["condition"] == "service_healthy"

    cadvisor = services["cadvisor"]
    assert cadvisor["profiles"] == ["monitoring-full"]
    assert cadvisor["image"] == "gcr.io/cadvisor/cadvisor:v0.49.1"
    assert cadvisor["privileged"] is True
    assert "/var/lib/docker:/var/lib/docker:ro" in cadvisor["volumes"]

    assert services["prometheus"]["depends_on"] == {
        "redis-exporter": {"condition": "service_started"},
        "postgres-exporter": {"condition": "service_started"},
    }
    cadvisor_override = yaml.safe_load(
        (ROOT / "docker-compose.cadvisor.override.yml").read_text()
    )
    assert cadvisor_override["services"]["prometheus"]["depends_on"]["cadvisor"] == {
        "condition": "service_started"
    }
    assert services["prometheus"]["image"] == "prom/prometheus:v2.54.1"
    assert services["grafana"]["image"] == "grafana/grafana:11.2.0"
    assert services["grafana"]["healthcheck"]["test"][0] == "CMD-SHELL"


def test_prometheus_scrapes_sidar_and_infra_exporters():
    prometheus = yaml.safe_load((ROOT / "docker_setup/prometheus/prometheus.yml").read_text())
    scrape_targets = {
        config["job_name"]: config["static_configs"][0]["targets"]
        for config in prometheus["scrape_configs"]
    }

    assert scrape_targets == {
        "sidar-web": ["sidar-web:7860"],
        "redis-exporter": ["redis-exporter:9121"],
        "postgres-exporter": ["postgres-exporter:9187"],
        "cadvisor": ["cadvisor:8080"],
    }
    assert prometheus["scrape_configs"][0]["metrics_path"] == "/metrics/llm/prometheus"
