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

    assert 'BENCHMARK_ENABLE_COMPARE="${BENCHMARK_ENABLE_COMPARE:-true}"' in script
    assert 'BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-false}"' in script
    assert "resolve_benchmark_compare_target()" in script
    assert 'find .benchmarks -type f -name "*_${requested_name}.json"' in script
    assert 'find .benchmarks -type f -name "*.json"' in script
    assert 'BENCHMARK_COMPARE_FILE="${latest_file}"' in script
    assert 'BENCHMARK_COMPARE_SELECTOR="${latest_file}"' in script
    assert 'BASH_REMATCH' not in script[script.index("resolve_benchmark_compare_target()") :]
    assert 'benchmark_cmd+=(--benchmark-compare="${BENCHMARK_COMPARE_SELECTOR}")' in script
    assert "baseline=${BENCHMARK_COMPARE_FILE}" in script
    assert "İlk benchmark koşusu --benchmark-save=${BENCHMARK_BASELINE_NAME}" in script
    assert "BENCHMARK_COMPARE_REQUIRED=${BENCHMARK_COMPARE_REQUIRED} iken karşılaştırma için baseline bulunamadı" in script


def test_advanced_env_examples_enable_benchmark_compare_without_requiring_existing_baseline() -> None:
    env_advanced_example = Path(".env.advanced.example").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")

    for content in (env_advanced_example, env_test_example):
        assert "BENCHMARK_ENABLE_COMPARE=true" in content
        assert "BENCHMARK_COMPARE_REQUIRED=false" in content
        assert "BENCHMARK_COMPARE_NAME=baseline" in content


def test_dev_and_test_env_examples_keep_database_password_single_source() -> None:
    dev_env = Path(".env.development.example").read_text(encoding="utf-8")
    test_env = Path(".env.test.example").read_text(encoding="utf-8")

    assert "OLLAMA_NUM_PARALLEL=4" in dev_env
    assert "POSTGRES_PASSWORD=replace-with-a-strong-24-plus-character-password" in dev_env
    assert "postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}" not in dev_env
    assert "Bu dosyada tam DSN veya ek parola kopyası tutmayın" in dev_env

    assert "POSTGRES_PASSWORD=sidar_test_secure_pw" in test_env
    assert "POSTGRES_PASSWORD=sidar\n" not in test_env
    assert "postgresql+asyncpg://USER:PASSWORD@HOST:PORT/NAME" not in test_env
    assert "GOOGLE_API_KEY" not in test_env
    assert "OLLAMA_NUM_PARALLEL=4" in test_env


def test_run_tests_uses_secure_test_password_default_and_redacts_dsn_log() -> None:
    script = _script()

    assert 'POSTGRES_PASSWORD:-sidar_test_secure_pw' in script
    assert 'echo "ℹ️ DATABASE_URL test için ayarlandı: ${DATABASE_URL}"' not in script
    assert "Test veritabanı bağlantısı ayarlandı: user=${test_db_user}" in script
