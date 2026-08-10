"""Validate externally supplied quality-gate environment variable names."""

from __future__ import annotations

import difflib
import os
import sys
from collections.abc import Mapping

# Declarative public configuration surface for run_tests.sh and test_gates helpers.
# Values are intentionally not modeled here: their owning helper remains responsible
# for type/range validation. This schema catches misspelled *names* before defaults
# silently mask them.
TEST_GATE_ENV_NAMES = frozenset(
    """
    AUTO_BUILD_DOCKER_TEST_IMAGE AUTO_DOCKER_TEST_SERVICES AUTO_HEAL_BATCH_RETRIES
    AUTO_HEAL_LOG_PATH AUTO_HEAL_MAX_ATTEMPTS AUTO_HEAL_ON_FAILURE AUTO_HEAL_RESULT_PATH
    AUTO_INSTALL_CI_SYSTEM_DEPS AUTO_OPEN_ARTIFACTS AUTO_PREPARE_TEST_DB
    AUTONOMOUS_LOOP_OPERATION_PROFILE BATS_REPORT_DIR BENCHMARK_BASELINE_FILE
    BENCHMARK_BASELINE_MAX_AGE_DAYS BENCHMARK_BASELINE_NAME BENCHMARK_CPU_AFFINITY
    BENCHMARK_COMPARE_FAIL BENCHMARK_COMPARE_NAME BENCHMARK_COMPARE_REQUIRED
    BENCHMARK_DISABLE_GC BENCHMARK_ENABLE_COMPARE BENCHMARK_ENFORCE_COMPARE
    BENCHMARK_ENFORCE_RESULT BENCHMARK_GPU_JSON_OUTPUT BENCHMARK_GPU_TEST_FILE
    BENCHMARK_FILTER BENCHMARK_IO_COMPARE_FAIL BENCHMARK_IO_JSON_OUTPUT BENCHMARK_JSON_OUTPUT
    BENCHMARK_TREND_COMPARE BENCHMARK_TREND_HISTORY BENCHMARK_TREND_MAX_REGRESSION_PCT
    BENCHMARK_TREND_WINDOW BENCHMARK_WARMUP BENCHMARK_WARMUP_ITERATIONS
    CLEAN_ZONE_IDENTIFIER_ARTIFACTS CODING_MODEL COVERAGE_CAMPAIGN
    COVERAGE_FAIL_UNDER COVERAGE_FAIL_UNDER_CAMPAIGN COVERAGE_FAIL_UNDER_CI
    COVERAGE_FAIL_UNDER_LOCAL COVERAGE_RATCHET_ENABLED COVERAGE_RATCHET_MAX_GATE
    COVERAGE_RATCHET_MIN_EXISTING_GATE COVERAGE_RATCHET_MIN_GATE
    COVERAGE_RATCHET_STATE_FILE COVERAGE_RATCHET_STEP
    DOCKER_TEST_IMAGE DOCKER_TEST_IMAGE_BUILD_CONTEXT ENABLE_GPU_TESTS
    ENFORCE_FRONTEND_E2E FRONTEND_BUNDLE_BUDGET FRONTEND_BUNDLE_BUDGET_LOCAL_FULL
    FRONTEND_COVERAGE_REPORT_PATH FRONTEND_E2E_ENFORCE_RESULT FRONTEND_E2E_NPM_SCRIPT
    FRONTEND_E2E_RETRY_ON_FAIL FRONTEND_PLAYWRIGHT_PACKAGE_LOCK
    FRONTEND_NPM_AUDIT_ALLOW_NETWORK_FAILURE FRONTEND_NPM_AUDIT_LEVEL
    FRONTEND_PLAYWRIGHT_REPORT_PATH FRONTEND_PLAYWRIGHT_SENTINEL
    INTEGRATION_PYTEST_WORKERS MIN_UNIT_COVERAGE_FAIL_UNDER OLLAMA_AUTO_PULL_MISSING
    OLLAMA_MODEL_SYNC OLLAMA_REQUIRED_MODELS PERFORMANCE_TEST_DIR
    PIP_AUDIT_ALLOW_NETWORK_FAILURE PIP_AUDIT_ARTIFACT_DIR PIP_AUDIT_MAX_RETRIES
    PIP_AUDIT_RETRY_WAIT_SECONDS PIP_AUDIT_TIMEOUT PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
    PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT POSTGRES_ADMIN_USER PROJECT_VENV_ENV
    PYTEST_DIST_MODE PYTEST_WORKERS QUALITY_GATE_EXIT_AFTER_FIRST_FAIL
    RESET_TEST_DATABASE RETRY_ON_FAIL RUFF_AUTOFIX RUFF_AUTOFIX_UNSAFE
    RUFF_AUTOFIX_UNSAFE_RULES RUN_ALEMBIC_DOWNGRADE_CHECK RUN_BATS_TESTS
    RUN_BENCHMARKS RUN_FRONTEND_E2E RUN_FRONTEND_E2E_AUTO_INSTALL RUN_GPU_BENCHMARKS RUN_GPU_STRESS
    RUN_SECURITY_ANALYSIS RUN_STATIC_ANALYSIS RUN_TESTS_STAGE SIDAR_PRODUCTION_READINESS
    SIDAR_PROMPT_LOCAL_BATS_INSTALL SMOKE_SKIP_EXTERNAL_INFRA TEST_DATABASE_NAME
    TEST_DATABASE_PASSWORD TEST_DATABASE_USER TEST_ENV_SCHEMA_MODE TEST_PROFILE
    TEST_SERVICES_READY_MAX_ATTEMPTS TEST_SERVICES_READY_SLEEP_SECONDS TEST_SUMMARY_JSON
    TEST_SUMMARY_JUNIT_DIR UV_LINK_MODE
    """.split()
)

_OWNED_PREFIXES = (
    "AUTO_",
    "BENCHMARK_",
    "COVERAGE_",
    "FRONTEND_",
    "PIP_AUDIT_",
    "RUFF_",
    "RUN_",
    "TEST_",
)


def unknown_test_gate_env(environ: Mapping[str, str]) -> list[tuple[str, str | None]]:
    """Return suspicious unknown names and their nearest supported spelling."""
    findings: list[tuple[str, str | None]] = []
    supported = sorted(TEST_GATE_ENV_NAMES)
    for name in sorted(environ):
        if name in TEST_GATE_ENV_NAMES or not name.isupper() or "_" not in name:
            continue
        matches = difflib.get_close_matches(name, supported, n=1, cutoff=0.82)
        if name.startswith(_OWNED_PREFIXES) or matches:
            findings.append((name, matches[0] if matches else None))
    return findings


def main() -> int:
    """Fail or warn when quality-gate-looking environment names are unknown."""
    mode = os.getenv("TEST_ENV_SCHEMA_MODE", "error").strip().lower()
    if mode == "off":
        return 0
    if mode not in {"error", "warn"}:
        print("❌ TEST_ENV_SCHEMA_MODE yalnız error|warn|off olabilir.", file=sys.stderr)
        return 2

    findings = unknown_test_gate_env(os.environ)
    if not findings:
        return 0
    for name, suggestion in findings:
        hint = f"; şunu mu demek istediniz: {suggestion}?" if suggestion else ""
        print(f"⚠️ Bilinmeyen test kalite-gate env değişkeni: {name}{hint}", file=sys.stderr)
    if mode == "error":
        print(
            "❌ Env schema doğrulaması başarısız. Geçici inceleme için "
            "TEST_ENV_SCHEMA_MODE=warn kullanabilirsiniz.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
