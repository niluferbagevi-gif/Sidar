from pathlib import Path

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
