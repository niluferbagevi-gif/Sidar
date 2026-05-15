from __future__ import annotations

from pathlib import Path

RUN_TESTS = Path("run_tests.sh")


def _script() -> str:
    return RUN_TESTS.read_text(encoding="utf-8")


def test_run_tests_defers_coverage_fail_under_until_combined_report() -> None:
    script = _script()

    assert "--cov-fail-under=0" in script
    assert 'coverage report --fail-under="${COVERAGE_FAIL_UNDER}"' in script
    assert "final coverage report --fail-under" in script


def test_run_tests_enforces_combined_gate_before_ratchet() -> None:
    script = _script()

    gate_call = script.index("  enforce_combined_coverage_gate\n")
    ratchet_function = script.index("update_progressive_coverage_gate()")
    ratchet_call = script.index("  update_progressive_coverage_gate", ratchet_function)

    assert gate_call < ratchet_function < ratchet_call


def test_run_tests_regenerates_machine_readable_coverage_before_gate() -> None:
    script = _script()
    gate_function = script[script.index("enforce_combined_coverage_gate()") :]

    assert "uv run python -m coverage html -d htmlcov" in gate_function
    assert "uv run python -m coverage xml -o coverage.xml" in gate_function
    assert "uv run python -m coverage json -o coverage.json" in gate_function


def test_run_tests_enables_benchmark_compare_but_allows_first_run_baseline_creation() -> None:
    script = _script()

    assert 'BENCHMARK_ENABLE_COMPARE="${BENCHMARK_ENABLE_COMPARE:-1}"' in script
    assert 'BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-0}"' in script
    assert "resolve_benchmark_compare_target()" in script
    assert 'find .benchmarks -type f -name "*_${requested_name}.json"' in script
    assert 'find .benchmarks -type f -name "*.json"' in script
    assert 'BENCHMARK_COMPARE_FILE="${latest_file}"' in script
    assert 'BENCHMARK_COMPARE_SELECTOR="${latest_file}"' in script
    assert "BASH_REMATCH" not in script[script.index("resolve_benchmark_compare_target()") :]
    assert 'benchmark_cmd+=(--benchmark-compare="${BENCHMARK_COMPARE_SELECTOR}")' in script
    assert "baseline=${BENCHMARK_COMPARE_FILE}" in script
    assert "İlk benchmark koşusu --benchmark-save=${BENCHMARK_BASELINE_NAME}" in script
    assert "BENCHMARK_COMPARE_REQUIRED=1 iken karşılaştırma için baseline bulunamadı" in script


PRODUCTION_REQUIRED_SECRETS = (
    "JWT_SECRET_KEY",
    "MEMORY_ENCRYPTION_KEY",
    "API_KEY",
    "METRICS_TOKEN",
    "AUTONOMY_WEBHOOK_SECRET",
    "SWARM_FEDERATION_SHARED_SECRET",
    "GRAFANA_ADMIN_PASSWORD",
    "GITHUB_WEBHOOK_SECRET",
)


def test_env_example_has_production_required_secret_checklist() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    checklist = env_example.split("PRODUCTION_REQUIRED CHECKLIST", maxsplit=1)[1].split(
        "# ─── AI Sağlayıcısı", maxsplit=1
    )[0]

    assert "secret manager / CI secret store" in checklist
    assert "secrets.token_urlsafe(32)" in checklist
    for secret_name in PRODUCTION_REQUIRED_SECRETS:
        assert f"# - {secret_name}" in checklist
        assert f"{secret_name}=" in env_example


def test_env_examples_document_postgres_host_consistently() -> None:
    for env_path in (".env.example", ".env.development.example", ".env.test.example"):
        content = Path(env_path).read_text(encoding="utf-8")

        assert "POSTGRES_HOST=localhost" in content


def test_test_postgres_password_is_test_only_not_default_project_name() -> None:
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")
    run_tests = Path("run_tests.sh").read_text(encoding="utf-8")
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "POSTGRES_PASSWORD=sidar_test_only" in env_test_example
    assert "POSTGRES_PASSWORD=sidar\n" not in env_test_example
    assert "POSTGRES_PASSWORD:-sidar_test_only" in run_tests
    assert "POSTGRES_PASSWORD: sidar_test_only" in ci_workflow
    assert "TEST_DATABASE_PASSWORD: sidar_test_only" in ci_workflow
    assert "sidar:sidar@localhost" not in ci_workflow


def test_development_env_keeps_postgres_password_single_source() -> None:
    content = Path(".env.development.example").read_text(encoding="utf-8")

    assert content.count("replace-with-a-strong-24-plus-character-password") == 1
    assert "DATABASE_URL=postgresql" not in content
    assert "SIDAR_CONTAINER_DATABASE_URL=postgresql" not in content
    assert "SELF_HEAL_DATABASE_URL=postgresql" not in content
    assert "POSTGRES_* bileşenlerinden otomatik türetir" in content


def test_docker_compose_derives_database_url_from_postgres_components() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "SIDAR_CONTAINER_DATABASE_URL" not in compose
    assert compose.count("POSTGRES_HOST=postgres") == 4
    assert compose.count("DATABASE_URL=") == 4


def test_env_examples_do_not_use_legacy_google_api_key_for_gemini() -> None:
    for env_path in (".env.example", ".env.development.example", ".env.test.example"):
        content = Path(env_path).read_text(encoding="utf-8")

        assert "GOOGLE_API_KEY=" not in content

    assert "GEMINI_API_KEY=" in Path(".env.example").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=" in Path(".env.test.example").read_text(encoding="utf-8")


def test_env_examples_document_redis_connection_pool_limits() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")

    assert "REDIS_URL=redis://localhost:6379/0" in env_example
    assert "REDIS_MAX_CONNECTIONS=50" in env_example
    assert "REDIS_MAX_CONNECTIONS=5" in env_test_example


def test_env_examples_document_ollama_parallelism_consistently() -> None:
    for env_path in (".env.example", ".env.development.example", ".env.test.example"):
        content = Path(env_path).read_text(encoding="utf-8")

        assert "OLLAMA_NUM_PARALLEL=4" in content


def test_env_example_uses_loopback_web_host_by_default() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "WEB_HOST=127.0.0.1" in env_example
    assert "WEB_HOST=0.0.0.0" not in env_example
    assert "production/container için bilinçli override" in env_example


def test_env_example_uses_single_web_scrape_character_limit_name() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "WEB_SCRAPE_MAX_CHARS=12000" in env_example
    assert "WEB_FETCH_MAX_CHARS=" not in env_example
    assert "deprecation fallback" in env_example


def test_env_example_docker_allowed_runtimes_has_no_empty_entry() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime" in env_example
    assert "DOCKER_ALLOWED_RUNTIMES=,runc" not in env_example


def test_env_examples_enable_benchmark_compare_without_requiring_existing_baseline() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")

    for content in (env_example, env_test_example):
        assert "BENCHMARK_ENABLE_COMPARE=1" in content
        assert "BENCHMARK_COMPARE_REQUIRED=0" in content
        assert "BENCHMARK_COMPARE_NAME=baseline" in content
