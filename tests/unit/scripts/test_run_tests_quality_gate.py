from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import textwrap
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from tests._helpers.source_contracts import expanded_bash_source, shell_function_body

RUN_TESTS = Path("run_tests.sh")


def _script() -> str:
    """Return run_tests.sh with sourced test gate modules expanded in-place."""
    return expanded_bash_source(RUN_TESTS)


def _run_tests_block_between(start_marker: str, end_marker: str, *, start_offset: int = 0) -> str:
    """Return a run_tests.sh block for structure-oriented shell assertions."""
    script = _script()
    start = script.index(start_marker, start_offset)
    return script[start : script.index(end_marker, start)]


def installer_contract_sources() -> str:
    """Return the modular installer contract surface as one searchable string."""
    paths = [Path("install_sidar.sh"), *sorted(Path("scripts/install_modules").rglob("*.sh"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def _run_tests_frontend_playwright_helpers() -> str:
    """Return frontend Playwright helper definitions with required run_tests defaults."""
    run_tests = RUN_TESTS.read_text(encoding="utf-8")
    defaults = run_tests[
        run_tests.index("FRONTEND_PLAYWRIGHT_SENTINEL=") : run_tests.index(
            "# 3) Frontend React testleri"
        )
    ]
    helpers = Path("scripts/test_gates/frontend_helpers.sh").read_text(encoding="utf-8")
    return defaults + "\n" + helpers


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_run_tests_function(name: str) -> str:
    """Return a shell function body from run_tests.sh or its test gate modules."""
    return shell_function_body(_script(), name)


def test_run_tests_omits_set_e_but_centralizes_exit_code_checks_via_run_checked() -> None:
    """Regression test: exit codes feeding the aggregate must use run_checked().

    run_tests.sh intentionally runs without `set -e` (it must keep running
    later test phases/quality gates even after an earlier one fails, then
    aggregate a combined exit code), but every command whose exit code feeds
    into that aggregate must go through the shared run_checked() helper
    instead of ad hoc, inconsistent `cmd; x=$?` / `cmd || true` patterns.
    """
    script = _script()

    assert script.splitlines()[1] == "set -uo pipefail"

    run_checked_block = script[script.index("run_checked() {") : script.index("RUN_TESTS_STAGE=")]
    assert run_checked_block.strip().splitlines()[1:] == ['  "$@"', "  return $?", "}"]

    for consequential_call in (
        'run_checked "${DOCKER_COMPOSE_CMD[@]}" stop redis postgres',
        'run_checked "${phase1_cmd[@]}"\n    phase1_exit=$?',
        'run_checked "${phase2_cmd[@]}"\n    phase2_exit=$?',
        'run_checked "${benchmark_cmd[@]}"\n    BENCHMARK_EXIT_CODE=$?',
        "run_checked npm ci",
        "run_checked npm install",
        "run_checked npm run audit:high",
        "run_checked npm run lint",
        "run_checked npm run typecheck",
        "run_checked npm run test:coverage",
        "run_checked run_frontend_e2e_with_retry",
    ):
        assert consequential_call in script, consequential_call


def test_run_checked_propagates_exit_code_and_passes_through_stdio(tmp_path) -> None:
    script = _script()
    helper = tmp_path / "run_checked_probe.sh"
    helper.write_text(
        "#!/usr/bin/env bash\nset -uo pipefail\n"
        + script[script.index("run_checked() {") : script.index("RUN_TESTS_STAGE=")]
        + '\necho "before"\n'
        + 'run_checked bash -c "echo mid; exit 7"\n'
        + 'echo "captured=$?"\n'
        + 'echo "after"\n',
        encoding="utf-8",
    )
    helper.chmod(0o755)

    result = subprocess.run([str(helper)], capture_output=True, text=True)

    assert result.returncode == 0
    assert result.stdout == "before\nmid\ncaptured=7\nafter\n"


def test_frontend_coverage_dark_mode_links_are_injected_without_late_css_imports(tmp_path) -> None:
    coverage_dir = tmp_path / "coverage"
    nested_dir = coverage_dir / "components" / "button"
    nested_dir.mkdir(parents=True)
    (coverage_dir / "base.css").write_text("body { color: #111; }\n", encoding="utf-8")
    (coverage_dir / "index.html").write_text(
        '<html><head><link rel="stylesheet" href="base.css" /></head><body></body></html>',
        encoding="utf-8",
    )
    (nested_dir / "index.html").write_text(
        '<html><head><link rel="stylesheet" href="../../base.css" /></head><body></body></html>',
        encoding="utf-8",
    )
    runner = tmp_path / "run_dark_mode.sh"
    runner.write_text(
        "#!/bin/bash\nset -euo pipefail\n"
        + _extract_run_tests_function("apply_dark_mode_to_frontend_coverage_report")
        + f'\napply_dark_mode_to_frontend_coverage_report "{coverage_dir}"\n',
        encoding="utf-8",
    )

    subprocess.run(["bash", str(runner)], check=True)

    assert '@import url("./sidar_dark_mode.css");' not in (coverage_dir / "base.css").read_text(
        encoding="utf-8"
    )
    assert (coverage_dir / "sidar_dark_mode.css").exists()
    root_html = (coverage_dir / "index.html").read_text(encoding="utf-8")
    nested_html = (nested_dir / "index.html").read_text(encoding="utf-8")
    assert 'href="base.css" />\n<link rel="stylesheet" href="sidar_dark_mode.css" />' in root_html
    assert (
        'href="../../base.css" />\n<link rel="stylesheet" href="../../sidar_dark_mode.css" />'
        in nested_html
    )


def test_frontend_coverage_dark_mode_failure_sets_frontend_exit_code() -> None:
    script = _script()
    late_import_append = 'printf \'\\n@import url("./sidar_dark_mode.css");\\n\' >> "${base_css}"'
    assert late_import_append not in script
    assert 'if ! apply_dark_mode_to_frontend_coverage_report "$PWD/coverage"; then' in script
    assert "FRONTEND_EXIT_CODE=1" in script


def test_mypy_is_strict_python_311() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    mypy = config["tool"]["mypy"]

    assert mypy["python_version"] == "3.11"
    assert mypy["strict"] is True


def test_coverage_ratchet_state_is_committed_and_guarded() -> None:
    script = _script()
    pyproject_path = Path("pyproject.toml")

    assert pyproject_path.exists()
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    # pyproject.toml is the single coverage config source: branch behavior,
    # omit/exclude patterns, HTML config, and the local ratchet baseline live together.
    assert pyproject["tool"]["coverage"]["run"]["branch"] is True
    coverage_fail_under = pyproject["tool"]["coverage"]["report"]["fail_under"]
    assert coverage_fail_under == 100

    coverage_agent_docs = Path("docs/COVERAGE_AGENT_KULLANIMI.md").read_text(encoding="utf-8")
    test_plan_docs = Path("docs/TEST_OPTIMIZATION_PLAN.md").read_text(encoding="utf-8")
    project_report = Path("docs/PROJE_RAPORU.md").read_text(encoding="utf-8")

    assert f"güncel repo gate: `%{coverage_fail_under:g}`" in coverage_agent_docs
    assert "Branch coverage ölçümü `[tool.coverage.run] branch = true`" in test_plan_docs
    assert "Coverage Quality Gate" in project_report
    assert (
        f"fail_under={coverage_fail_under:g}" in project_report
        or f"fail_under = {coverage_fail_under:g}" in project_report
    )
    assert not any(
        line.strip() == "pyproject.toml"
        for line in Path(".gitignore").read_text(encoding="utf-8").splitlines()
    )
    assert 'COVERAGE_RATCHET_STATE_FILE="${COVERAGE_RATCHET_STATE_FILE:-pyproject.toml}"' in script
    assert "validate_coverage_ratchet_state()" in script
    assert 'if [ ! -f "${COVERAGE_RATCHET_STATE_FILE}" ]; then' in script
    assert "Coverage ratchet state dosyası bulunamadı" in script
    assert "Coverage ratchet baseline sıfırlanmış olabilir" in script
    assert "[tool.coverage.report] fail_under" in script
    assert "coverage debug config" in script
    assert 'DEFAULT_COVERAGE_FAIL_UNDER="$(validate_coverage_ratchet_state)" || exit 1' in script
    testing_docs = Path("docs/TESTING.md").read_text(encoding="utf-8")
    tests_module_notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")
    assert ".coveragerc" not in testing_docs
    assert ".coveragerc" not in tests_module_notes
    assert "[tool.coverage.report] fail_under" in tests_module_notes


def test_run_tests_enforces_required_static_security_and_coverage_gates() -> None:
    script = _script()

    assert "uv run mypy --strict core/ agent/ web/ managers/" in script
    assert "uv run bandit -r . -c pyproject.toml" in script
    assert 'MIN_UNIT_COVERAGE_FAIL_UNDER="${MIN_UNIT_COVERAGE_FAIL_UNDER:-5}"' in script
    assert "minimum unit floor=${MIN_UNIT_COVERAGE_FAIL_UNDER}" in script
    assert 'coverage report --fail-under="${COVERAGE_FAIL_UNDER}"' in script


def test_run_tests_ruff_autofix_is_explicit_opt_in() -> None:
    script = _script()
    precommit_block = _extract_run_tests_function("run_precommit_autofix")

    assert 'if [ "${RUFF_AUTOFIX:-0}" != "1" ]; then' in precommit_block
    assert "uv run ruff check ." in precommit_block
    assert "uv run ruff format --check ." in precommit_block
    assert "RUFF_AUTOFIX=1 bash run_tests.sh --stage all" in precommit_block
    assert "uv run ruff check --fix" in precommit_block
    assert "uv run ruff format ." in precommit_block
    assert 'report_git_diff_state "RUFF_AUTOFIX başlangıç durumu"' in precommit_block
    assert 'report_git_diff_state "RUFF_AUTOFIX bitiş durumu"' in precommit_block
    assert script.index('if [ "${RUFF_AUTOFIX:-0}" != "1" ]; then') < script.index(
        "uv run ruff check --fix"
    )


def test_ci_exposes_security_and_mutation_quality_gates() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    mutation = Path(".github/workflows/weekly-mutation-and-critical-tests.yml").read_text(
        encoding="utf-8"
    )

    assert "uv run bandit -r . -c pyproject.toml" in ci
    assert "make production-readiness" in ci
    assert "uv run python scripts/ci/check_policy_dates.py" in ci
    assert "POSTGRES_PASSWORD: sidar" in ci
    assert "Test-only CI service credentials" in ci
    assert "SIDAR_ENV: test" in ci
    assert "CI production-readiness is a quality gate, not an app production runtime." in ci
    assert "cannot satisfy or mask production-secret tests" in ci
    assert "Verify committed coverage ratchet baseline" in ci
    assert "git diff --exit-code -- pyproject.toml" in ci
    assert "pyproject.toml coverage fail_under changed during run_tests.sh" in ci
    # CI no longer hardcodes a stricter override; it inherits the
    # ratchet-managed pyproject.toml baseline like the local profile.
    assert 'COVERAGE_FAIL_UNDER_CI: "95"' not in ci
    assert "uv run --with mutmut mutmut run --max-children 4" in mutation


def test_run_tests_defers_coverage_fail_under_until_combined_report() -> None:
    script = _script()

    assert "--cov-fail-under=0" in script
    assert 'coverage report --fail-under="${COVERAGE_FAIL_UNDER}"' in script
    # The user-facing echo surfaces both the baseline source and the resolved
    # profile so a developer can tell which gate they are running against.
    assert "pyproject.toml baseline=" in script
    assert "profile=${COVERAGE_FAIL_UNDER_SOURCE}" in script


def test_run_tests_verifies_alembic_downgrade_upgrade_chain() -> None:
    script = _script()

    assert "RUN_ALEMBIC_DOWNGRADE_CHECK:-1" in script
    assert "uv run alembic downgrade base" in script
    assert "uv run alembic upgrade head" in script
    assert "downgrade/upgrade zinciri doğrulanıyor" in script


def test_run_tests_uses_loadgroup_distribution_for_xdist_state_isolation() -> None:
    script = _script()
    notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")

    assert 'PYTEST_DIST_MODE="${PYTEST_DIST_MODE:-loadgroup}"' in script
    assert 'base_pytest_cmd+=(-n "${PYTEST_WORKERS}" --dist "${PYTEST_DIST_MODE}")' in script
    assert 'TEST_SUMMARY_JUNIT_DIR="${TEST_SUMMARY_JUNIT_DIR:-artifacts/pytest}"' in script

    phase1_block = _run_tests_block_between(
        "local phase1_cmd=(",
        'echo "➡️ Aşama 1 (Unit) komutu',
    )
    assert '"${base_pytest_cmd[@]}"' in phase1_block
    assert '"--junitxml=${TEST_SUMMARY_JUNIT_DIR}/backend-unit.xml"' in phase1_block
    assert "tests/unit" in phase1_block

    assert "Aşama 1 unit fazı artık pytest-xdist mevcutsa" in notes
    assert "Unit ağırlığı" in notes


def test_run_tests_enforces_combined_gate_before_ratchet() -> None:
    script = _script()

    gate_call = script.index("  enforce_combined_coverage_gate\n")
    ratchet_function = script.index("update_progressive_coverage_gate()")
    ratchet_call = script.index("  update_progressive_coverage_gate", ratchet_function)

    assert gate_call < ratchet_function < ratchet_call


def test_run_tests_regenerates_machine_readable_coverage_before_gate() -> None:
    script = _script()
    gate_function = script[script.index("enforce_combined_coverage_gate()") :]

    assert "uv run python -m coverage html -d htmlcov --fail-under=0" in gate_function
    assert "uv run python -m coverage xml -o coverage.xml --fail-under=0" in gate_function
    assert "uv run python -m coverage json -o coverage.json --fail-under=0" in gate_function


def test_run_tests_coverage_artifact_generation_is_not_gated_by_fail_under() -> None:
    # coverage.py'nin html/xml/json alt komutları [tool.coverage.report] fail_under
    # eşiğini miras alır; --fail-under=0 olmadan eşiğin altındaki bir kısmi
    # çalıştırmada rapor başarıyla yazılsa bile komut non-zero döner ve script
    # bunu yanlışlıkla "rapor üretilemedi" olarak kaydeder.
    script = _script()
    gate_start = script.index("\nenforce_combined_coverage_gate() {") + 1
    gate_function = script[gate_start : script.index("update_progressive_coverage_gate()")]

    assert "coverage_html_report_failed" in gate_function
    assert "coverage_xml_report_failed" in gate_function
    assert "coverage_json_report_failed" in gate_function


def test_run_tests_skips_global_coverage_gate_for_partial_stage_runs() -> None:
    # --stage integration (veya smoke/e2e) yalnızca kısmi bir kapsam üretir;
    # repo genelindeki fail_under eşiğini bu kapsamla uygulamak, integration
    # testlerinin kendisi geçmişken sahte bir coverage başarısızlığı üretir.
    script = _script()

    assert "should_enforce_combined_coverage_gate() {" in script
    should_enforce_start = script.index("should_enforce_combined_coverage_gate() {")
    should_enforce_end = script.index("\nenforce_combined_coverage_gate() {", should_enforce_start)
    should_enforce_fn = script[should_enforce_start:should_enforce_end]
    assert (
        "stage_all_selected || stage_selected backend || stage_selected unit" in should_enforce_fn
    )

    gate_start = script.index("\nenforce_combined_coverage_gate() {") + 1
    gate_function = script[gate_start : script.index("update_progressive_coverage_gate()")]
    assert "if ! should_enforce_combined_coverage_gate; then" in gate_function
    assert "global coverage fail-under kalite kapısı atlandı" in gate_function

    # Kapsam kararı, rapor üretiminden (html/xml/json) SONRA ama asıl
    # `coverage report --fail-under` çağrısından ÖNCE devreye girmeli.
    skip_check_pos = gate_function.index("if ! should_enforce_combined_coverage_gate; then")
    json_report_pos = gate_function.index("coverage json -o coverage.json --fail-under=0")
    final_gate_pos = gate_function.index('coverage report --fail-under="${COVERAGE_FAIL_UNDER}"')
    assert json_report_pos < skip_check_pos < final_gate_pos


def test_gpu_defaults_are_cpu_friendly_and_auto_detect_runtime_hardware() -> None:
    script = _script()
    installer_contract = installer_contract_sources()
    env_example = Path(".env.example").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")
    env_prod_example = Path(".env.production.example").read_text(encoding="utf-8")
    env_development_example = Path(".env.development.example").read_text(encoding="utf-8")
    env_utils = Path("scripts/install_modules/utils/env_utils.sh").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert 'local enable_gpu_tests="${ENABLE_GPU_TESTS:-auto}"' in script
    assert "gpu_hardware_available()" in script
    assert "ENABLE_GPU_TESTS=auto -> 1" in script
    assert "ENABLE_GPU_TESTS=auto -> 0" in script
    assert "if ! gpu_hardware_available; then" in script

    assert "USE_GPU=false" in env_example
    assert "REQUIRE_GPU=false" in env_example
    assert "USE_GPU=false" in env_test_example
    assert "REQUIRE_GPU=false" in env_test_example
    assert "USE_GPU=false" in env_prod_example
    assert "REQUIRE_GPU=false" in env_prod_example
    assert "GPU_MIXED_PRECISION=true" in env_prod_example
    assert "USE_GPU=false" in env_development_example
    assert "REQUIRE_GPU=false" in env_development_example

    assert "REQUIRE_GPU=true" in installer_contract
    assert "REQUIRE_GPU=false" in installer_contract
    assert "USE_GPU=true, REQUIRE_GPU=true, GPU_MIXED_PRECISION=true" in installer_contract
    assert "USE_GPU=false, REQUIRE_GPU=false, GPU_MIXED_PRECISION=false" in installer_contract
    assert "USE_GPU=true, REQUIRE_GPU=true, GPU_MIXED_PRECISION=true" in env_utils
    assert "USE_GPU=false, REQUIRE_GPU=false, GPU_MIXED_PRECISION=false" in env_utils
    assert "install_sidar.sh` GPU tespit ederse" in readme
    assert "varsayılan `REQUIRE_GPU=false`" in readme


def test_run_tests_syncs_effective_dotenv_postgres_password_without_logging_secret() -> None:
    script = _script()

    assert "load_test_database_password_env()" in script
    assert 'DOTENV_FILE="${test_dotenv_file}" uv run python - "${password_file}"' in script
    assert "_effective_postgres_password(discover_env_chain())" in script
    assert "export POSTGRES_PASSWORD" in script
    assert (
        'sync_postgres_login_role "${admin_db_user}" "${POSTGRES_USER:-sidar}" '
        '"${POSTGRES_PASSWORD}"' in script
    )
    assert (
        'sync_postgres_login_role "${admin_db_user}" "${test_db_user}" "${test_db_password}"'
        in script
    )
    assert "CREATE ROLE %I LOGIN PASSWORD %L" in script
    assert "ALTER ROLE %I WITH LOGIN PASSWORD %L" in script
    assert "is_safe_postgres_identifier()" in script
    assert "^[A-Za-z_][A-Za-z0-9_]*$" in script
    assert "Geçersiz TEST_DATABASE_NAME" in script
    assert "Geçersiz TEST_DATABASE_USER" in script
    assert "postgres_identifiers_equal()" in script
    assert "ana POSTGRES_DB" in script
    assert script.index(
        'postgres_identifiers_equal "${test_db_name}" "${primary_db_name}"'
    ) < script.index("DROP DATABASE IF EXISTS ${test_db_name}")
    assert script.index('is_safe_postgres_identifier "${test_db_name}"') < script.index(
        "DROP DATABASE IF EXISTS ${test_db_name}"
    )
    assert script.index('is_safe_postgres_identifier "${test_db_user}"') < script.index(
        "GRANT ALL PRIVILEGES ON DATABASE ${test_db_name} TO ${test_db_user}"
    )
    assert (
        "TEST_DATABASE_PASSWORD ana PostgreSQL parolasından farklıysa ayrı bir TEST_DATABASE_USER"
        in script
    )
    assert "DATABASE_URL test için ayarlandı: ${DATABASE_URL}" not in script
    assert script.index("load_test_database_password_env && ensure_test_services") < script.index(
        "&& prepare_test_database; then"
    )


def test_prepare_test_database_rejects_case_folded_primary_database_collision(
    tmp_path: Path,
) -> None:
    """The destructive reset must stop before Docker when test and primary DB collide."""
    harness = tmp_path / "database-collision.sh"
    harness.write_text(
        "\n".join(
            (
                "#!/usr/bin/env bash",
                "set -uo pipefail",
                "BACKEND_EXIT_CODE=0",
                "DOCKER_COMPOSE_CMD=()",
                _extract_run_tests_function("is_safe_postgres_identifier"),
                _extract_run_tests_function("postgres_identifiers_equal"),
                _extract_run_tests_function("prepare_test_database"),
                "resolve_docker_compose_cmd() { echo docker-must-not-run >&2; return 99; }",
                "POSTGRES_DB=sidar TEST_DATABASE_NAME=SIDAR prepare_test_database",
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True)

    assert result.returncode == 1
    assert "ana POSTGRES_DB (sidar) ile aynı olamaz" in result.stdout
    assert "docker-must-not-run" not in result.stderr


def test_service_readiness_timeout_fails_without_enabling_smoke_skip(tmp_path: Path) -> None:
    """An automatic-infra timeout must remain a blocking backend failure."""
    harness = tmp_path / "service-timeout.sh"
    harness.write_text(
        "\n".join(
            (
                "#!/usr/bin/env bash",
                "set -uo pipefail",
                "BACKEND_EXIT_CODE=0",
                "DOCKER_COMPOSE_CMD=(fake-compose)",
                "fake-compose() { return 1; }",
                "sleep() { :; }",
                _extract_run_tests_function("wait_for_test_services_ready"),
                "TEST_SERVICES_READY_MAX_ATTEMPTS=1",
                "TEST_SERVICES_READY_SLEEP_SECONDS=0",
                "if wait_for_test_services_ready; then exit 90; fi",
                '[ "${BACKEND_EXIT_CODE}" -eq 1 ]',
                '[ -z "${SMOKE_SKIP_EXTERNAL_INFRA:-}" ]',
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "smoke testleri skip'e çevrilmeyecek" in result.stdout


def test_automatic_test_infrastructure_failures_are_blocking() -> None:
    """Missing Compose and failed service startup must not become successful skips."""
    body = _extract_run_tests_function("ensure_test_services")

    assert "zorunlu Redis/PostgreSQL test altyapısı başlatılamadı" in body
    assert "BACKEND_EXIT_CODE=1" in body
    assert body.count("return 1") >= 2
    assert "SMOKE_SKIP_EXTERNAL_INFRA=1 ayarlandı" not in body
    assert "if ! wait_for_test_services_ready; then\n    return 1\n  fi" in body


def test_benchmark_tooling_bootstrap_prepares_system_deps_before_pytest_benchmark() -> None:
    """Missing pytest/pytest-benchmark should not surface as python -m pytest import errors."""
    script = _script()
    body = _extract_run_tests_function("ensure_benchmark_tool_dependencies")
    benchmark_block = script[script.index("# 2) Kritik yol performans baseline testleri") :]

    assert "import pytest" in body
    assert "import pytest_benchmark" in body
    assert "bash scripts/install_ci_system_deps.sh" in body
    assert "pyaudio/portaudio.h" in body
    assert "uv sync --frozen --all-extras" in body
    assert "make benchmark-seed && make production-readiness" in body
    assert body.index("bash scripts/install_ci_system_deps.sh") < body.index(
        "uv sync --frozen --all-extras"
    )
    assert "ensure_benchmark_tool_dependencies" in benchmark_block
    assert "Benchmark önkoşulları hazırlanamadı" in benchmark_block
    assert benchmark_block.index("ensure_benchmark_tool_dependencies") < benchmark_block.index(
        "uv run python -m pytest"
    )


def test_run_tests_uses_profile_aware_benchmark_compare_defaults() -> None:
    script = _script()

    assert 'BENCHMARK_ENABLE_COMPARE="${BENCHMARK_ENABLE_COMPARE:-1}"' in script
    assert 'BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-1}"' in script
    assert 'BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-0}"' in script
    assert script.index('if [ "${TEST_PROFILE}" = "ci" ]; then') < script.index(
        'BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-1}"'
    )
    assert script.index(
        "else", script.index('BENCHMARK_COMPARE_FAIL="${BENCHMARK_COMPARE_FAIL:-mean:10%}"')
    ) < script.index('BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-0}"')
    assert script.count('BENCHMARK_ENFORCE_COMPARE="${BENCHMARK_ENFORCE_COMPARE:-1}"') >= 2
    assert 'if [ "${TEST_PROFILE}" = "ci" ]; then' in script
    assert 'BENCHMARK_COMPARE_FAIL="${BENCHMARK_COMPARE_FAIL:-mean:10%}"' in script
    assert 'BENCHMARK_COMPARE_FAIL="${BENCHMARK_COMPARE_FAIL:-mean:15%}"' in script
    assert "resolve_benchmark_compare_target()" in script
    assert 'find .benchmarks -type f -name "*_${requested_name}.json"' in script
    assert 'find .benchmarks -type f -name "*.json"' in script
    assert 'BENCHMARK_COMPARE_FILE="${latest_file}"' in script
    assert 'BENCHMARK_COMPARE_SELECTOR="${latest_file}"' in script
    assert "BASH_REMATCH" not in script[script.index("resolve_benchmark_compare_target()") :]
    assert 'benchmark_cmd+=(--benchmark-compare="${BENCHMARK_COMPARE_SELECTOR}")' in script
    assert 'if [ "${BENCHMARK_ENFORCE_COMPARE}" = "1" ]; then' in script
    assert 'benchmark_cmd+=(--benchmark-compare-fail="${BENCHMARK_COMPARE_FAIL}")' in script
    assert '--benchmark-warmup="${BENCHMARK_WARMUP}"' in script
    assert '--benchmark-warmup-iterations="${BENCHMARK_WARMUP_ITERATIONS}"' in script
    assert "benchmark_cmd+=(--benchmark-disable-gc)" in script
    assert "baseline=${BENCHMARK_COMPARE_FILE}" in script
    assert "İlk benchmark koşusu --benchmark-save=${BENCHMARK_BASELINE_NAME}" in script
    assert "BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh" in script
    assert (
        "BENCHMARK_COMPARE_REQUIRED=1 BENCHMARK_ENFORCE_COMPARE=1 RUN_BENCHMARKS=required "
        "./run_tests.sh" in script
    )
    assert "GitHub Actions cache/artifact üzerinden seed/restore eder" in script
    assert "BENCHMARK_COMPARE_REQUIRED=1 iken karşılaştırma için baseline bulunamadı" in script
    assert 'if [ "${IS_CI_ENV}" -eq 1 ]; then' in script
    assert "Local production-readiness için benchmark baseline bulunamadı" in script
    assert "Önerilen tek aksiyon: make benchmark-seed && make production-readiness" in script
    assert (
        script.index('if [ "${IS_CI_ENV}" -eq 1 ]; then')
        < script.index("elif production_readiness_gate_active; then")
        < script.index(
            "Yerel bootstrap: BENCHMARK_COMPARE_REQUIRED=1 olsa da baseline bulunamadığı için ilk "
            "benchmark koşusu karşılaştırmasız çalıştırılacak"
        )
    )
    assert (
        "Yerel bootstrap: BENCHMARK_COMPARE_REQUIRED=1 olsa da baseline bulunamadığı için ilk "
        "benchmark koşusu karşılaştırmasız çalıştırılacak" in script
    )
    assert "benchmark_compare_target_found=0" in script
    assert "benchmark_compare_target_found=1" in script
    assert "Benchmark baseline kaydı hazır: ${BENCHMARK_COMPARE_FILE}" in script
    assert "Sonraki benchmark koşusunda --benchmark-compare=${BENCHMARK_COMPARE_SELECTOR}" in script
    assert (
        "Benchmark JSON üretildi ancak .benchmarks altında '${BENCHMARK_COMPARE_NAME}' baseline "
        "kaydı doğrulanamadı" in script
    )


def test_benchmark_compare_fails_when_enforced_baseline_is_stale() -> None:
    script = _script()

    assert 'BENCHMARK_BASELINE_MAX_AGE_DAYS="${BENCHMARK_BASELINE_MAX_AGE_DAYS:-14}"' in script
    assert "benchmark_baseline_age_days()" in script
    assert 'stat -c %Y "${baseline_file}"' in script
    assert 'stat -f %m "${baseline_file}"' in script

    compare_block = script[
        script.index(
            'if resolve_benchmark_compare_target "${BENCHMARK_COMPARE_NAME}"; then'
        ) : script.index('BENCHMARK_COMPARE_STATUS="missing_baseline"')
    ]
    assert "benchmark_baseline_age_days_value=" in compare_block
    assert 'benchmark_baseline_age_days "${BENCHMARK_COMPARE_FILE}"' in compare_block
    assert (
        '[ "${benchmark_baseline_age_days_value}" -ge "${BENCHMARK_BASELINE_MAX_AGE_DAYS}" ]'
        in compare_block
    )
    assert "gündür yenilenmedi" in compare_block
    assert "make benchmark-seed" in compare_block
    assert 'if [ "${BENCHMARK_ENFORCE_COMPARE}" = "1" ]; then' in compare_block
    assert 'BENCHMARK_COMPARE_STATUS="stale_required"' in compare_block
    assert "BENCHMARK_EXIT_CODE=1" in compare_block
    assert 'if [ "${BENCHMARK_COMPARE_STATUS}" != "stale_required" ]; then' in compare_block
    # Freshness check must run before the enforce/report-only branch, not after.
    assert compare_block.index("gündür yenilenmedi") < compare_block.rindex(
        'if [ "${BENCHMARK_ENFORCE_COMPARE}" = "1" ]; then'
    )


def test_release_scope_warning_flags_gpu_quality_gate_as_out_of_scope() -> None:
    warning_fn = _extract_run_tests_function("print_release_scope_warning_once")
    assert "GPU Inference Quality Gate" in warning_fn
    assert "ENABLE_GPU_BENCH_GATE=true" in warning_fn
    assert "self-hosted" in warning_fn
    assert "Lokal production_ready=true" in warning_fn
    assert "GPU Inference Required Evidence Gate" in warning_fn
    assert "production-readiness aggregate buna bağlıdır" in warning_fn
    # The GPU-gate note must be unconditional (printed regardless of which
    # release-scope branch is taken), so it has to precede the branching.
    assert warning_fn.index("GPU Inference Quality Gate") < warning_fn.index(
        "production_readiness_gate_active"
    )


def test_ci_production_readiness_requires_gpu_inference_evidence_policy() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    production_job = ci[
        ci.index("  production-readiness:") : ci.index("  production-profile-dry-run:")
    ]
    policy_job = ci[
        ci.index("  gpu-inference-policy-gate:") : ci.index("  publish-standalone-installer:")
    ]

    assert "needs: [test, benchmark-compare, gpu-inference-policy-gate]" in production_job
    assert "needs: [test, gpu-inference-quality-gate]" in policy_job
    assert 'if [[ "${GPU_GATE_ENABLED}" != "true" ]]' in policy_job
    assert 'if [[ "${GPU_GATE_RESULT}" != "success" ]]' in policy_job
    assert "production readiness must not pass without TTFT/latency evidence" in policy_job


def test_postgresql_multi_user_benchmark_warms_pool_and_uses_stable_pedantic_rounds() -> None:
    benchmark_test = Path("tests/performance/test_benchmark.py").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")

    assert 'os.getenv("SIDAR_FORMAT_TABLE_MAX_MEAN_MS", "5.0")' in benchmark_test
    assert "format_table_mean_ms" in benchmark_test
    assert "async def _warm_postgresql_connection_pool(db: Database) -> None:" in benchmark_test
    assert 'await conn.execute("SELECT 1")' in benchmark_test
    assert "loop.run_until_complete(_warm_postgresql_connection_pool(db))" in benchmark_test
    assert "warmup_rounds=5" in benchmark_test
    assert "rounds=25" in benchmark_test
    assert "SIDAR_BENCHMARK_POSTGRES_URL=postgresql+asyncpg://" in env_test_example
    assert "yalnız SQLite varyantını koşturur" in env_test_example


def test_benchmark_docs_require_uv_and_review_before_promoting_latest_baseline() -> None:
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    env_advanced = Path(".env.advanced.example").read_text(encoding="utf-8")

    assert "uv run pytest tests/performance/ --benchmark-save=baseline" in notes
    assert "commit_info.dirty" in notes
    assert "version-sort" in notes
    assert "2026-06-22 performans değerlendirmesinde 13 benchmark" in notes
    assert "test_format_table_handles_large_dataset_quickly` yaklaşık `3.7 ms" in notes
    assert "SIDAR_FORMAT_TABLE_MAX_MEAN_MS=5.0" in notes
    assert "test_gpu_vram_peak_under_load` için yaklaşık `2249 ms` mean" in notes
    assert "BENCHMARK_COMPARE_REQUIRED=1" in notes
    assert "BENCHMARK_ENFORCE_COMPARE=1" in notes
    assert "commit_info.dirty" in readme
    assert "version-sort" in readme
    assert "### İlk yerel kurulum: benchmark baseline bootstrap" in readme
    assert "yerel profil varsayılanı `BENCHMARK_COMPARE_REQUIRED=0`" in readme
    assert "make benchmark-seed" in readme
    assert (
        "BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required bash run_tests.sh --stage all"
        in readme
    )
    assert "İlk yerel benchmark koşusunda `.benchmarks` baseline yoksa" in agents
    assert "BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh" in agents
    assert "BENCHMARK_COMPARE_REQUIRED=1" in readme
    assert "BENCHMARK_ENFORCE_COMPARE=1" in readme
    assert (
        "restore/seed edilmiş *_baseline.json kayıtları içinden en güncel eşleşmeyi seçer"
        in env_advanced
    )
    assert (
        "Yerel boş cache ilk koşusunda RUN_BENCHMARKS=required ./run_tests.sh baseline seed eder"
        in env_advanced
    )
    assert "yerel profil varsayılanı BENCHMARK_COMPARE_REQUIRED=0" in env_advanced
    assert "SIDAR_FORMAT_TABLE_MAX_MEAN_MS=5.0" in env_advanced
    assert "mevcut 0004_baseline.json" not in env_advanced


def test_advanced_env_examples_enable_benchmark_compare_without_requiring_existing_baseline() -> (
    None
):
    env_advanced = Path(".env.advanced.example").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")
    install_script = Path("scripts/install_modules/phases/08_env.sh").read_text(encoding="utf-8")

    variants_start = install_script.index(
        "local -a variants=(",
        install_script.index("propagate_shared_secrets_to_env_variants()"),
    )
    variants_block = install_script[variants_start : install_script.index(")", variants_start)]
    development_variant = '".env.development:.env.development.example"'
    test_variant = '".env.test:.env.test.example"'
    advanced_variant = '".env.advanced:.env.advanced.example"'
    assert development_variant in variants_block
    assert test_variant in variants_block
    assert advanced_variant in variants_block
    assert variants_block.index(development_variant) < variants_block.index(test_variant)
    assert variants_block.index(test_variant) < variants_block.index(advanced_variant)
    assert 'ADVANCED_ENV_FILE="$SCRIPT_DIR/.env.advanced"' in install_script
    assert 'ADVANCED_EXAMPLE_FILE="$SCRIPT_DIR/.env.advanced.example"' in install_script
    assert 'cp "$ADVANCED_EXAMPLE_FILE" "$ADVANCED_ENV_FILE"' in install_script

    for content in (env_advanced, env_test_example):
        assert "BENCHMARK_ENABLE_COMPARE=1" in content
        assert "BENCHMARK_COMPARE_REQUIRED=" in content
        assert "BENCHMARK_COMPARE_FAIL=" in content
        assert "yerelde mean:15%, CI profilinde mean:10%" in content
        assert "BENCHMARK_COMPARE_NAME=baseline" in content

    assert "Override hiyerarşisi" in env_advanced
    assert "override=False ile yüklenir" in env_advanced
    assert "boş" in env_advanced and ".env içindeki dolu değerleri ezmez" in env_advanced
    assert "docker-compose env_file:" in env_advanced
    assert "AUTONOMOUS_LOOP_COVERAGE_XML=coverage.xml" in env_advanced
    assert "SIDAR_EVENT_BUS_BACKEND=redis" in env_advanced
    assert "SIDAR_RABBITMQ_URL=" in env_advanced
    assert "SIDAR_KAFKA_BOOTSTRAP_SERVERS=" in env_advanced
    assert "SIDAR_JUDGE_AUTO_FEEDBACK_ENABLED=true" in env_advanced
    assert "AUTONOMOUS_LOOP_MUTATION_ENABLED=true" in env_advanced
    assert "ENABLE_LORA_TRAINING=false" in env_advanced
    assert "DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime" in env_advanced


def test_env_documentation_clarifies_loading_chain_and_api_key_policy() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    technical_reference = Path("docs/TEKNIK_REFERANS.md").read_text(encoding="utf-8")
    project_report = Path("docs/PROJE_RAPORU.md").read_text(encoding="utf-8")
    environment_configuration = Path("docs/ENVIRONMENT_CONFIGURATION.md").read_text(
        encoding="utf-8"
    )

    for content in (readme, technical_reference, project_report):
        assert ".env.advanced" in content
        assert "SIDAR_KEYS_FILE" in content
        assert "~/.sidar_keys.env" in content

    assert "Runtime yükleme zinciri" in readme
    assert "`.env.advanced` (`override=False`)" in readme
    assert "API anahtarı politikası" in readme
    assert "kalıcı kaynak olarak yalnız `.env`" in readme
    assert "Docker Compose `env_file:` kaynağı yapılmamalıdır" in readme

    assert "Kod içi güvenli varsayılanlar" in technical_reference
    assert "API anahtarı saklama politikası" in technical_reference
    assert "yalnız `.env` ve repo dışındaki `~/.sidar_keys.env`" in technical_reference
    assert "Compose" in technical_reference and "`env_file:` kaynağı" in technical_reference

    assert "Yükleme zinciri `config.py` varsayılanları" in project_report
    assert "kalıcı kaynak politikası yalnız `.env`" in project_report

    assert "`.env` report `0/18` filled service API keys" in environment_configuration
    assert "not a failure when" in environment_configuration
    assert "runtime loader still reads the final" in environment_configuration
    assert "`600` or stricter" in environment_configuration
    assert "explicit materialization opt-in" in environment_configuration


def test_pytest_conftest_checks_env_test_postgres_password_parity() -> None:
    conftest = Path("tests/conftest.py").read_text(encoding="utf-8")

    assert "_assert_test_dotenv_postgres_parity()" in conftest
    assert ".env.test içindeki POSTGRES_PASSWORD" in conftest
    assert "scripts/sync_database_passwords.py --all-envs" in conftest
    assert "InvalidPasswordError" in conftest
    assert conftest.index("_load_pytest_dotenv_chain()") < conftest.index(
        "_assert_test_dotenv_postgres_parity()"
    )


def test_pytest_conftest_keeps_installer_collection_lightweight() -> None:
    conftest = Path("tests/conftest.py").read_text(encoding="utf-8")

    assert 'os.environ.setdefault("SIDAR_ENV", "test")' in conftest
    assert 'os.environ["SIDAR_KEYS_FILE"] = ""' in conftest
    assert "SIDAR_TEST_LOAD_REAL_KEYS" in conftest
    assert 'importlib.import_module("agent.sidar_agent")' not in conftest
    assert 'importlib.import_module("agent.core.event_stream")' not in conftest
    assert 'importlib.import_module("core.db")' not in conftest
    assert "def _test_needs_web_server_runtime" in conftest


def test_pytest_conftest_parity_guard_fails_on_password_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import tests.conftest as conftest

    (tmp_path / ".env").write_text(
        "POSTGRES_PASSWORD=base_secure_password_123456\n"
        "DATABASE_URL=postgresql://sidar:base_secure_password_123456@localhost:5432/sidar\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.test").write_text(
        "POSTGRES_PASSWORD=stale_test_password_123456\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(conftest, "PROJECT_ROOT", tmp_path)

    with pytest.raises(pytest.fail.Exception, match="InvalidPasswordError"):
        conftest._assert_test_dotenv_postgres_parity()


def test_pytest_conftest_parity_guard_accepts_matching_passwords(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import tests.conftest as conftest

    (tmp_path / ".env").write_text(
        "POSTGRES_PASSWORD=base_secure_password_123456\n"
        "DATABASE_URL=postgresql://sidar:base_secure_password_123456@localhost:5432/sidar\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.test").write_text(
        "POSTGRES_PASSWORD=base_secure_password_123456\n"
        "DATABASE_URL=postgresql://sidar:base_secure_password_123456@localhost:5432/sidar\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(conftest, "PROJECT_ROOT", tmp_path)

    conftest._assert_test_dotenv_postgres_parity()


def test_install_sidar_production_readiness_requires_full_ci_gate() -> None:
    install_script = installer_contract_sources()
    validation_phase = Path("scripts/install_modules/phases/10_validation.sh").read_text(
        encoding="utf-8"
    )

    assert "--production-readiness" in install_script
    assert (
        "--production-readiness) RUN_CI_FULL_VALIDATION=true; NO_INTERACTION=true ;;"
    ) in install_script
    assert (
        'if [[ "$AUTO_ENV_TYPE" == "production" && "$RUN_CI_FULL_VALIDATION" != true ]]; then'
    ) in install_script
    assert (
        "RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all" in install_script
    )
    run_tests_script = Path("run_tests.sh").read_text(encoding="utf-8")
    assert (
        'PRODUCTION_READINESS_COMMAND="TEST_PROFILE=ci RUN_BENCHMARKS=required '
        'RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"'
    ) in run_tests_script
    assert "Development full validation başarıyla tamamlandı" in run_tests_script
    assert "RELEASE / MERGE ONAYI VERMEYİN [summary-code=10]" in run_tests_script
    assert "RELEASE / MERGE ONAYI VERMEYİN [summary-code=20]" in run_tests_script
    assert "print_release_scope_warning_once()" in run_tests_script
    assert "RELEASE_SCOPE_WARNING_PRINTED=1" in run_tests_script
    assert "artifacts/test-summary.json içinde production_ready=false kalır" in run_tests_script
    assert "Production readiness için kanonik komut" in run_tests_script
    assert "Production readiness profili çalıştırılmadı" not in run_tests_script
    assert "Tam doğrulama durumu: ÇALIŞTIRILMADI" not in run_tests_script
    assert "assert_production_readiness_request" in run_tests_script
    assert "check_production_readiness_system_dependencies" in run_tests_script
    assert "scripts/install_ci_system_deps.sh --check" in run_tests_script
    assert "production_readiness_gate_active" in run_tests_script
    assert "SIDAR_PRODUCTION_READINESS=1" in validation_phase
    assert "scripts/install_ci_system_deps.sh --check" in validation_phase
    assert "sistem_bagimliligi_eksik" in validation_phase
    assert "run_install_frontend_quality_validation()" in validation_phase
    assert "run_tests.sh --stage frontend" in validation_phase
    assert "lint, typecheck, test:coverage, test:e2e:smoke" in validation_phase
    assert "SIDAR_PRODUCTION_READINESS" in install_script
    assert "sidar_install_production_gate_required()" in validation_phase
    env_phase = Path("scripts/install_modules/phases/08_env.sh").read_text(encoding="utf-8")
    finish_phase = Path("scripts/install_modules/phases/07_finish.sh").read_text(encoding="utf-8")
    database_url_utils = Path("scripts/install_modules/utils/database_url.sh").read_text(
        encoding="utf-8"
    )
    alembic_phase = Path("scripts/install_modules/phases/12_alembic.sh").read_text(encoding="utf-8")
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert 'SIDAR_SELECTED_ENV_TYPE="$selected_env"' in env_phase
    assert (
        "production-readiness gate geçmeden SIDAR_ENV=production kalıcılaştırılmayacak" in env_phase
    )
    assert (
        'production_ready="$(sidar_install_summary_field_or_empty production_ready)"' in env_phase
    )
    assert (
        "production-readiness, secret rotasyon ve migration doğrulamaları tamamlandı" in env_phase
    )
    assert 'production_secret_rotation_gate_passes "$env_file"' in env_phase
    assert "secret rotasyon kapısı geçmeden SIDAR_ENV=production kalıcılaştırılmayacak" in env_phase
    assert (
        'local env_choice="${SIDAR_SELECTED_ENV_TYPE:-${AUTO_ENV_TYPE:-ask}}"' in validation_phase
    )
    assert finish_phase.index("prompt_post_install_sidar_env_mode") < finish_phase.index(
        "run_install_ci_full_validation"
    )
    assert 'if [[ "${SIDAR_SELECTED_ENV_TYPE:-}" == "production" ]]; then' in finish_phase
    assert "resolve_runtime_database_url()" in database_url_utils
    assert "resolve_runtime_database_url_from_file()" in database_url_utils
    assert "POSTGRES_HOST" in database_url_utils
    assert "resolve_runtime_database_url" in alembic_phase
    assert "current --check-heads" in alembic_phase
    assert "alembic_revision_sets_match" in alembic_phase
    assert "Production readiness gate başarısız" in validation_phase
    assert "Development tam doğrulaması başarısız oldu" in validation_phase
    assert 'local optional_command="make dev-full"' in validation_phase
    assert "AUTO_OPEN_ARTIFACTS=0 make dev-full" in validation_phase
    for checksum_var in (
        "OLLAMA_INSTALL_SHA256",
        "UV_INSTALL_SHA256",
        "VOLTA_INSTALL_SHA256",
        "NVM_INSTALL_SHA256",
    ):
        assert f"-u {checksum_var}" in validation_phase
    assert "make production-readiness" in validation_phase
    assert "SIDAR_TOTAL_JS_BUDGET_KB" in makefile
    assert "SIDAR_TOTAL_GZIP_BUDGET_KB" in makefile
    assert (
        "production-ready/merge kabulü için tam doğrulama başarıyla geçmelidir" in validation_phase
    )
    assert "Tam doğrulama sonucu: HATA" in validation_phase
    assert "uygulama geliştirme amacıyla çalışabilir" in validation_phase
    assert "production-ready sayılmaz" in validation_phase
    assert "PRODUCTION GATE: Tam CI/e2e/benchmark doğrulaması zorunludur" in validation_phase
    assert "DEVELOPMENT UYARISI" in validation_phase
    assert "production_readiness_status_reported=false" in validation_phase
    assert "Development full validation geçti = geliştirici ortamı sağlıklı" in validation_phase
    assert "Profil farkı:" in finish_phase
    assert "dev-light: hızlı lokal geliştirme" in finish_phase
    assert "dev-full / uv sync --frozen --all-extras: tam geliştirici/CI paritesi" in finish_phase
    assert (
        "production-readiness: release/merge kapısı; sistem bağımlılıkları + Playwright browser + "
        "benchmark baseline gerektirebilir" in finish_phase
    )
    assert "print_install_dependency_profile_readiness_legend" in validation_phase
    assert "Profil farkı:" in validation_phase
    assert "dev-light: hızlı lokal geliştirme" in validation_phase
    assert (
        "dev-full / uv sync --frozen --all-extras: tam geliştirici/CI paritesi" in validation_phase
    )
    assert (
        "production-readiness: release/merge kapısı; sistem bağımlılıkları + Playwright browser + "
        "benchmark baseline gerektirebilir" in validation_phase
    )
    assert "Development validation ≠ release/merge onayı" in validation_phase
    assert "Release/merge için tek zorunlu komut" in validation_phase
    assert "DEVELOPMENT VALIDATION ≠ PRODUCTION READINESS" in validation_phase
    assert "AUTO_OPEN_ARTIFACTS=0 make production-readiness" in validation_phase
    assert (
        "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
        "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
    ) in validation_phase


def test_install_docs_explain_frontend_gate_is_opt_in() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    testing = Path("docs/TESTING.md").read_text(encoding="utf-8")
    install_options = Path("docs/install-script-options.md").read_text(encoding="utf-8")

    for doc in (readme, testing, install_options):
        assert "--stage all" in doc
        assert "RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend" in doc

    assert "Varsayılan development/local kurulumda `--stage all` otomatik çalıştırılmaz" in readme
    assert "smoke = hızlı sağlık kontrolü" in readme
    assert "dev-full = local tam doğrulama" in readme
    assert "production-readiness = merge/release kapısı" in readme
    assert "**“dev-full geçti” / “Development full validation geçti”**" in readme
    assert "**“production-readiness çalıştırılmadı”**" in readme
    assert "smoke = hızlı sağlık kontrolü" in testing
    assert "dev-full = local tam doğrulama" in testing
    assert "production-readiness = merge/release kapısı" in testing
    assert (
        "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
        "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
    ) in readme
    assert "frontend stage'in atlandığını görmek normaldir" in testing
    assert "`installer` nesnesi installer bootstrap" in testing
    assert "HTTP 429 retry sayısı" in testing
    assert "Coverage yüzdesi yalnız tüm ilgili test fazları geçtiğinde" in testing
    assert "frontend kalite kapısı ise bilinçli opt-in gerektirir" in install_options
    assert "--with-integration verilmediği için frontend stage çalıştırılmadı" in install_options


def test_ci_workflow_documents_and_seeds_benchmark_baseline() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    testing = Path("docs/TESTING.md").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in ci
    assert "seed_benchmark_baseline:" in ci
    assert "seed-benchmark-baseline:" in ci
    assert "Seed benchmark baseline cache" in ci
    assert "uses: actions/cache/restore@v4" in ci
    assert "uses: actions/cache/save@v4" in ci
    assert '--benchmark-save="${BENCHMARK_BASELINE_NAME}"' in ci
    assert "baseline-seed-manifest.json" in ci
    assert '"schema_version": 1' in ci
    assert "retention-days: 90" in ci
    assert "benchmark-baseline-seed" in ci
    assert "Next step: rerun the normal CI / production-readiness gate" in ci
    assert "GitHub Actions → CI → Run workflow" in ci
    assert "seed_benchmark_baseline=true" in ci
    assert (
        "if: ${{ github.event_name != 'workflow_dispatch' || !inputs.seed_benchmark_baseline }}"
        in ci
    )
    assert "Benchmark baseline missing" in ci
    assert "Run canonical production-readiness gate" in ci
    assert "Validate production-readiness test summary" in ci
    assert "--mode release --summary artifacts/test-summary.json" in ci
    assert "--mode development --summary artifacts/test-summary.json" not in ci
    assert "CI benchmark baseline cache boşsa ne yapılır?" in testing
    assert "seed_benchmark_baseline" in testing
    assert "benchmark-baseline-seed" in testing
    assert "production readiness gate'ini tekrar koşun" in testing
    assert "make benchmark-seed\nmake production-readiness" in testing
    assert "Local `make production-readiness` ilk kez çalışırken `.benchmarks` boşsa" in testing
    assert "Benchmark karşılaştırması atlandı ... baseline ile eşleşen kayıt" in testing
    assert "bulunamadı” uyarısı temiz checkout" in testing
    assert ".benchmarks/.../0001_baseline.json" in testing
    assert "CI'ın cache/artifact üzerinden" in testing
    assert "seed edilen baseline'ıyla karıştırılmamalıdır" in testing
    assert "yerelde oluşan ilk baseline'ı normal kabul edin" in readme
    assert "cache/artifact" in readme
    assert "cp -a /tmp/sidar-benchmark-baseline/.benchmarks/. .benchmarks/" in testing


def test_run_tests_summary_uses_phase_specific_backend_statuses(tmp_path: Path) -> None:
    script = _script()
    summary_json = tmp_path / "test-summary.json"
    summary_block = script[
        script.index("quality_summary_status() {") : script.index("MIN_UNIT_COVERAGE_FAIL_UNDER=")
    ]
    runner = tmp_path / "summary_probe.sh"
    runner.write_text(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        + summary_block
        + f"""
TEST_SUMMARY_JSON={summary_json}
TEST_SUMMARY_JUNIT_DIR={tmp_path / "pytest"}
TEST_PROFILE=local
SIDAR_INSTALLER_MODE=development_local
BACKEND_UNIT_RAN=1
BACKEND_UNIT_EXIT_CODE=1
BACKEND_INTEGRATION_RAN=1
BACKEND_INTEGRATION_EXIT_CODE=0
BACKEND_SMOKE_RAN=1
BACKEND_SMOKE_EXIT_CODE=0
BACKEND_E2E_RAN=1
BACKEND_E2E_EXIT_CODE=0
FRONTEND_LINT_RAN=1
FRONTEND_LINT_EXIT_CODE=0
FRONTEND_TYPECHECK_RAN=1
FRONTEND_TYPECHECK_EXIT_CODE=0
FRONTEND_COVERAGE_RAN=1
FRONTEND_COVERAGE_EXIT_CODE=0
FRONTEND_E2E_RAN=1
FRONTEND_E2E_EXIT_CODE=0
RUN_BENCHMARKS=required
BENCHMARK_EXIT_CODE=0
BENCHMARK_COMPARE_STATUS=seeded_not_compared
SIDAR_INSTALLER_BOOTSTRAP_MODE=raw-module-fallback
SIDAR_INSTALL_MODULES_DOWNLOADED_COUNT=7
SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS=9
SIDAR_INSTALL_MODULE_HTTP_429_RETRIES=2
SIDAR_INSTALL_MODULE_CACHE_HITS=3
SIDAR_INSTALL_MODULE_BASE_URL=https://mirror.example/install_modules
write_test_summary_json false
""",
        encoding="utf-8",
    )
    runner.chmod(0o755)

    subprocess.run([str(runner)], check=True)

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["integration"] == "passed"
    assert summary["smoke"] == "passed"
    assert summary["e2e"] == "passed"
    assert summary["benchmark"] == "passed"
    assert summary["production_readiness"] == "not_run"
    assert summary["benchmark_compare"] == "seeded_not_compared"
    assert summary["frontend_e2e_scope"] == "smoke"
    assert summary["installer_mode"] == "development_local"
    assert summary["production_readiness_detail"]["status"] == "partial_stage"
    assert summary["production_readiness_detail"]["required_command"] == "make production-readiness"
    assert (
        summary["production_readiness_detail"]["equivalent_direct_command"]
        == "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
        "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
    )
    assert summary["benchmark_baseline"] == {
        "name": "baseline",
        "compare_required": False,
        "compare_enforced": False,
        "compare_enabled": True,
        "compare_fail": None,
        "file": None,
        "selector": None,
        "json_output": "artifacts/benchmark/benchmark.json",
        "local_seed_command": (
            "BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required bash run_tests.sh --stage all"
        ),
        "ci_seed_workflow": "GitHub Actions → CI → Run workflow → seed_benchmark_baseline=true",
        "ci_fail_closed": True,
    }
    assert summary["production_ready"] is False
    assert summary["backend_failed_tests"] == []
    assert summary["installer"] == {
        "bootstrap_mode": "raw-module-fallback",
        "raw_fallback_modules_downloaded": 7,
        "remote_module_download_attempts": 9,
        "http_429_retries": 2,
        "remote_module_cache_hits": 3,
        "remote_module_base_url": "https://mirror.example/install_modules",
    }


def test_run_tests_help_lists_make_and_direct_production_readiness_commands() -> None:
    result = subprocess.run(
        ["bash", "run_tests.sh", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Production readiness gate:" in result.stdout
    assert "make production-readiness" in result.stdout
    assert (
        "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
        "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all" in result.stdout
    )


def test_production_readiness_checks_system_deps_before_quality_gates() -> None:
    script = _script()
    body = _extract_run_tests_function("check_production_readiness_system_dependencies")
    testing_doc = Path("docs/TESTING.md").read_text(encoding="utf-8")

    assert "production_readiness_gate_active" in body
    assert "bash scripts/install_ci_system_deps.sh --check" in body
    assert "pyaudio derleme hatasının bandit/pytest" in body
    assert "make production-readiness" in body
    assert script.index("assert_production_readiness_request") < script.index(
        "check_production_readiness_system_dependencies"
    )
    assert script.index("check_production_readiness_system_dependencies") < script.index(
        "ensure_runtime_dependencies()"
    )
    assert "scripts/install_ci_system_deps.sh --check" in testing_doc
    assert "`uv sync`, Bandit veya pytest aşamasına geçmeden durur" in testing_doc


def test_security_gate_runs_ruff_debt_baseline_before_bandit() -> None:
    """Local security gate mirrors CI's Ruff debt ratchet before SAST scans."""
    body = _extract_run_tests_function("run_security_analysis_gates")

    tooling_check = "ensure_security_tool_dependencies"
    debt_check = "uv run python scripts/ci/check_ruff_debt_baseline.py"
    bandit_check = "uv run bandit -r . -c pyproject.toml"
    assert tooling_check in body
    assert debt_check in body
    assert bandit_check in body
    assert body.index(tooling_check) < body.index(debt_check) < body.index(bandit_check)
    assert "Güvenlik analizi önkoşulları hazırlanamadı" in body
    assert "Ruff docstring/E501/ASYNC240 borç baseline kontrolü başarısız" in body


def test_security_tooling_bootstrap_prepares_system_deps_before_full_uv_sync() -> None:
    """Missing Bandit should trigger the same PortAudio-safe full-sync preparation."""
    body = _extract_run_tests_function("ensure_security_tool_dependencies")

    assert "import bandit" in body
    assert "bash scripts/install_ci_system_deps.sh" in body
    assert "pyaudio/portaudio.h" in body
    assert "uv sync --frozen --all-extras" in body
    assert body.index("bash scripts/install_ci_system_deps.sh") < body.index(
        "uv sync --frozen --all-extras"
    )


def test_linter_docs_route_python_to_ruff_and_shell_to_shellcheck() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    testing_doc = Path("docs/TESTING.md").read_text(encoding="utf-8")
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "ruff` Python dosyaları içindir" in readme
    assert "`ruff` yalnız Python dosyaları için kullanılmalıdır" in testing_doc
    assert "uv run ruff check tests/unit/scripts/test_run_tests_quality_gate.py" in readme
    assert "uv run ruff check tests/unit/scripts/test_run_tests_quality_gate.py" in testing_doc
    assert "uv run shellcheck --severity=warning -x run_tests.sh" in readme
    assert "uv run shellcheck --severity=warning -x run_tests.sh" in testing_doc
    assert "make lint-shell" in readme
    assert "make lint-shell" in testing_doc
    assert "installer-shellcheck:" in makefile
    assert "lint-shell:" in makefile
    assert "$(SHELLCHECK) --severity=warning -x $(SHELLCHECK_FILES)" in makefile


def test_run_tests_summary_includes_backend_failed_tests_from_junit(tmp_path: Path) -> None:
    script = _script()
    summary_json = tmp_path / "test-summary.json"
    junit_dir = tmp_path / "pytest"
    junit_dir.mkdir()
    (junit_dir / "backend-unit.xml").write_text(
        textwrap.dedent(
            """\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuites>
              <testsuite name="pytest">
                <testcase
                  classname="tests.unit.root.test_config"
                  name="test_production_requires_explicit_jwt_secret_and_api_key"
                  file="tests/unit/root/test_config.py"
                >
                  <failure message="assertion failed">details</failure>
                </testcase>
                <testcase classname="tests.unit.root.test_config" name="test_passing" />
              </testsuite>
            </testsuites>
            """
        ),
        encoding="utf-8",
    )
    summary_block = script[
        script.index("quality_summary_status() {") : script.index("MIN_UNIT_COVERAGE_FAIL_UNDER=")
    ]
    runner = tmp_path / "summary_failed_tests_probe.sh"
    runner.write_text(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        + summary_block
        + f"""
TEST_SUMMARY_JSON={summary_json}
TEST_SUMMARY_JUNIT_DIR={junit_dir}
BACKEND_UNIT_RAN=1
BACKEND_UNIT_EXIT_CODE=1
BACKEND_INTEGRATION_RAN=0
BACKEND_INTEGRATION_EXIT_CODE=0
BACKEND_SMOKE_RAN=0
BACKEND_SMOKE_EXIT_CODE=0
BACKEND_E2E_RAN=0
BACKEND_E2E_EXIT_CODE=0
FRONTEND_LINT_RAN=0
FRONTEND_LINT_EXIT_CODE=0
FRONTEND_TYPECHECK_RAN=0
FRONTEND_TYPECHECK_EXIT_CODE=0
FRONTEND_COVERAGE_RAN=0
FRONTEND_COVERAGE_EXIT_CODE=0
FRONTEND_E2E_RAN=0
FRONTEND_E2E_EXIT_CODE=0
RUN_BENCHMARKS=0
BENCHMARK_EXIT_CODE=0
write_test_summary_json false
""",
        encoding="utf-8",
    )
    runner.chmod(0o755)

    subprocess.run([str(runner)], check=True)

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["backend_failed_tests"] == [
        "tests/unit/root/test_config.py::test_production_requires_explicit_jwt_secret_and_api_key"
    ]


def test_install_validation_summary_reads_run_tests_json_for_partial_full_failures(
    tmp_path: Path,
) -> None:
    validation_phase = Path("scripts/install_modules/phases/10_validation.sh").resolve()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    summary_json = artifacts_dir / "test-summary.json"
    summary_json.write_text(
        json.dumps(
            {
                "smoke": "passed",
                "integration": "passed",
                "e2e": "passed",
                "frontend_lint": "passed",
                "frontend_typecheck": "passed",
                "frontend_coverage": "passed",
                "frontend_e2e": "passed",
                "benchmark": "passed",
                "production_ready": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            """set -Eeuo pipefail
source "$1"
BOLD=
GREEN=
YELLOW=
RED=
NC=
SCRIPT_DIR="$2"
TEST_SUMMARY_JSON="$3"
CI_FULL_VALIDATION_STATUS=hata
SMOKE_TEST_STATUS=atlandi_bayrak
INTEGRATION_TEST_STATUS=atlandi_bayrak
FRONTEND_QUALITY_STATUS=atlandi_bayrak
RUN_INSTALL_INTEGRATION_TESTS=false
GPU_AVAILABLE=false
sidar_install_production_gate_required() { return 1; }
print_install_coverage_gate_note() { :; }
print_install_ci_parity_summary() { :; }
print_install_validation_coverage""",
            "bash",
            str(validation_phase),
            str(tmp_path),
            str(summary_json),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Integration : tests/integration GEÇTİ" in result.stdout
    assert "E2E         : tests/e2e/{agents,cli,web} GEÇTİ" in result.stdout
    assert "Benchmark   : tests/performance GEÇTİ" in result.stdout
    assert "Production readiness:" in result.stdout
    assert "GEÇMEDİ" in result.stdout
    assert "Tam doğrulama sonucu: HATA" in result.stdout
    assert "Integration:  ATLANDI" not in result.stdout
    assert "Benchmark:    ATLANDI" not in result.stdout


def test_optional_full_validation_syncs_frontend_status_from_run_tests_summary(
    tmp_path: Path,
) -> None:
    validation_phase = Path("scripts/install_modules/phases/10_validation.sh").resolve()
    summary_json = tmp_path / "test-summary.json"
    summary_json.write_text(
        json.dumps(
            {
                "frontend_lint": "passed",
                "frontend_typecheck": "passed",
                "frontend_coverage": "passed",
                "frontend_e2e": "passed",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            """set -Eeuo pipefail
source "$1"
SCRIPT_DIR="$2"
TEST_SUMMARY_JSON="$3"
FRONTEND_QUALITY_STATUS=atlandi_bayrak
info() { printf 'INFO:%s\n' "$*"; }
sync_frontend_quality_status_from_test_summary
printf 'FRONTEND_QUALITY_STATUS=%s\n' ${FRONTEND_QUALITY_STATUS}""",
            "bash",
            str(validation_phase),
            str(tmp_path),
            str(summary_json),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "FRONTEND_QUALITY_STATUS=tamamlandi" in result.stdout
    assert "artifacts/test-summary.json üzerinden tamamlandı" in result.stdout


def test_full_validation_failure_syncs_frontend_status_from_summary(tmp_path: Path) -> None:
    validation_phase = Path("scripts/install_modules/phases/10_validation.sh").resolve()
    summary_json = tmp_path / "test-summary.json"
    summary_json.write_text(
        json.dumps(
            {
                "frontend_lint": "passed",
                "frontend_typecheck": "passed",
                "frontend_coverage": "passed",
                "frontend_e2e": "passed",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    makefile = tmp_path / "Makefile"
    makefile.write_text("production-readiness:\n\t@exit 1\n", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            "-c",
            """set -Eeuo pipefail
source "$1"
SCRIPT_DIR="$2"
TEST_SUMMARY_JSON="$3"
RUN_CI_FULL_VALIDATION=true
CI_FULL_VALIDATION_FAILURE_POLICY=warn
FRONTEND_QUALITY_STATUS=atlandi_bayrak
step() { :; }
info() { :; }
warn() { :; }
ok() { :; }
fail() { printf 'FAIL:%s\n' "$*"; exit 1; }
sidar_install_production_gate_required() { return 1; }
run_install_ci_full_validation
printf 'CI_FULL_VALIDATION_STATUS=%s\n' "$CI_FULL_VALIDATION_STATUS"
printf 'FRONTEND_QUALITY_STATUS=%s\n' "$FRONTEND_QUALITY_STATUS"
""",
            "bash",
            str(validation_phase),
            str(tmp_path),
            str(summary_json),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "CI_FULL_VALIDATION_STATUS=hata" in result.stdout
    assert "FRONTEND_QUALITY_STATUS=tamamlandi" in result.stdout


def test_optional_dev_full_validation_failure_syncs_frontend_status_from_summary(
    tmp_path: Path,
) -> None:
    validation_phase = Path("scripts/install_modules/phases/10_validation.sh").resolve()
    summary_json = tmp_path / "test-summary.json"
    summary_json.write_text(
        json.dumps(
            {
                "frontend_lint": "passed",
                "frontend_typecheck": "passed",
                "frontend_coverage": "passed",
                "frontend_e2e": "passed",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    run_tests = tmp_path / "run_tests.sh"
    run_tests.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    run_tests.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            """set -Eeuo pipefail
source "$1"
SCRIPT_DIR="$2"
TEST_SUMMARY_JSON="$3"
GPU_AVAILABLE=true
SMOKE_TEST_STATUS=tamamlandi
NO_INTERACTION=false
AUTO_INSTALL=false
SILENT_MODE=false
FRONTEND_QUALITY_STATUS=atlandi_bayrak
info() { :; }
warn() { :; }
ok() { :; }
prompt_yes_no_with_timeout_default_no() { printf 'e'; }
run_optional_dev_full_validation_prompt
printf 'CI_FULL_VALIDATION_STATUS=%s\n' "$CI_FULL_VALIDATION_STATUS"
printf 'FRONTEND_QUALITY_STATUS=%s\n' "$FRONTEND_QUALITY_STATUS"
""",
            "bash",
            str(validation_phase),
            str(tmp_path),
            str(summary_json),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "CI_FULL_VALIDATION_STATUS=hata" in result.stdout
    assert "FRONTEND_QUALITY_STATUS=tamamlandi" in result.stdout


def test_optional_dev_full_validation_does_not_leak_tofu_checksum_state(
    tmp_path: Path,
) -> None:
    validation_phase = Path("scripts/install_modules/phases/10_validation.sh").resolve()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make = bin_dir / "make"
    make.write_text(
        "#!/usr/bin/env bash\n"
        "for name in OLLAMA_INSTALL_SHA256 UV_INSTALL_SHA256 "
        "VOLTA_INSTALL_SHA256 NVM_INSTALL_SHA256; do\n"
        "  [[ -z ${!name+x} ]] || exit 42\n"
        "done\n",
        encoding="utf-8",
    )
    make.chmod(0o755)
    (tmp_path / "run_tests.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    for checksum_var in (
        "OLLAMA_INSTALL_SHA256",
        "UV_INSTALL_SHA256",
        "VOLTA_INSTALL_SHA256",
        "NVM_INSTALL_SHA256",
    ):
        env[checksum_var] = f"tofu-{checksum_var.lower()}"

    result = subprocess.run(
        [
            "bash",
            "-c",
            """set -Eeuo pipefail
source "$1"
SCRIPT_DIR="$2"
GPU_AVAILABLE=true
SMOKE_TEST_STATUS=tamamlandi
NO_INTERACTION=false
AUTO_INSTALL=false
SILENT_MODE=false
info() { :; }
warn() { :; }
ok() { :; }
prompt_yes_no_with_timeout_default_no() { printf 'e'; }
run_optional_dev_full_validation_prompt
printf 'status=%s\n' "$CI_FULL_VALIDATION_STATUS"
""",
            "bash",
            str(validation_phase),
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "status=tamamlandi" in result.stdout


def test_finish_frontend_qa_block_refreshes_summary_before_printing(tmp_path: Path) -> None:
    finish_phase = Path("scripts/install_modules/phases/07_finish.sh").resolve()

    result = subprocess.run(
        [
            "bash",
            "-c",
            """set -Eeuo pipefail
source "$1"
GREEN=
YELLOW=
RED=
BOLD=
NC=
FRONTEND_QUALITY_STATUS=atlandi_bayrak
sync_frontend_quality_status_from_test_summary() { FRONTEND_QUALITY_STATUS=tamamlandi; }
print_react_frontend_qa_status_block""",
            "bash",
            str(finish_phase),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "✅ Frontend QA: lint/typecheck/coverage/e2e smoke tamamlandı." in result.stdout
    assert "FRONTEND QA ÇALIŞTIRILMADI" not in result.stdout


def test_install_validation_summary_separates_development_full_validation_from_production_gate(
    tmp_path: Path,
) -> None:
    validation_phase = Path("scripts/install_modules/phases/10_validation.sh").resolve()
    summary_json = tmp_path / "test-summary.json"
    summary_json.write_text(
        json.dumps(
            {
                "smoke": "passed",
                "integration": "passed",
                "e2e": "passed",
                "frontend_lint": "passed",
                "frontend_typecheck": "passed",
                "frontend_coverage": "passed",
                "frontend_e2e": "passed",
                "benchmark": "passed",
                "production_ready": False,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            """set -Eeuo pipefail
source "$1"
BOLD=
GREEN=
YELLOW=
RED=
NC=
SCRIPT_DIR="$2"
TEST_SUMMARY_JSON="$3"
CI_FULL_VALIDATION_STATUS=tamamlandi
SMOKE_TEST_STATUS=tamamlandi
INTEGRATION_TEST_STATUS=atlandi_bayrak
FRONTEND_QUALITY_STATUS=atlandi_bayrak
RUN_INSTALL_INTEGRATION_TESTS=false
GPU_AVAILABLE=false
sidar_install_production_gate_required() { return 1; }
print_install_coverage_gate_note() { :; }
print_install_ci_parity_summary() { :; }
print_install_validation_coverage""",
            "bash",
            str(validation_phase),
            str(tmp_path),
            str(summary_json),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Production readiness: ÇALIŞTIRILMADI / TALEP EDİLMEDİ" in result.stdout
    assert "Development full validation geçti = geliştirici ortamı sağlıklı" in result.stdout
    assert "Development validation ≠ release/merge onayı" in result.stdout
    assert "Release/merge için tek zorunlu komut" in result.stdout
    assert "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all" in result.stdout
    assert result.stdout.count("Production readiness:") == 1
    assert "Production readiness: GEÇMEDİ" not in result.stdout


def test_install_alembic_logs_revision_and_db_source_observability() -> None:
    alembic_phase = Path("scripts/install_modules/phases/12_alembic.sh").read_text(encoding="utf-8")

    assert "mask_alembic_db_url()" in alembic_phase
    assert "log_alembic_revision_observation()" in alembic_phase
    assert "Alembic DB URL kaynağı:" in alembic_phase
    assert "Alembic DB URL (maskeli):" in alembic_phase
    assert "Alembic current revizyon:" in alembic_phase
    assert "Alembic head revizyon:" in alembic_phase
    assert "resolve_runtime_database_url" in alembic_phase
    assert "RUNTIME_DATABASE_URL_SOURCE" in alembic_phase
    assert 'DB_URL_SOURCE="$RUNTIME_DATABASE_URL_SOURCE"' in alembic_phase
    assert "if resolve_runtime_database_url >/dev/null; then" in alembic_phase
    assert "post_current_output=" in alembic_phase
    assert "post_heads_output=" in alembic_phase
    assert 'log_alembic_revision_observation "$current_rev" "$head_rev"' in alembic_phase


def test_install_summary_prints_masked_runtime_key_source_report() -> None:
    env_phase = Path("scripts/install_modules/phases/08_env.sh").read_text(encoding="utf-8")
    finish_phase = Path("scripts/install_modules/phases/07_finish.sh").read_text(encoding="utf-8")

    assert "print_runtime_key_source_summary()" in env_phase
    assert "config.get_dotenv_key_source_report()" in env_phase
    assert 'os.environ.setdefault("SIDAR_CONFIG_QUIET", "true")' in env_phase
    assert "Kritik key kaynak özeti (değerler maskeli)" in env_phase
    assert 'return "process-env"' in env_phase
    assert 'print(f"  {display_key:<26}  ***        {source_display}")' in env_phase
    assert 'print(f"  {display_key:<26}  eksik      -")' in env_phase
    for key in (
        "API_KEY",
        "JWT_SECRET_KEY",
        "MEMORY_ENCRYPTION_KEY",
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "TEAMS_WEBHOOK_URL",
    ):
        assert key in env_phase

    assert "declare -F print_runtime_key_source_summary" in finish_phase
    assert "print_runtime_key_source_summary" in finish_phase


def test_install_sidar_does_not_sync_real_api_keys_to_test_env_by_default() -> None:
    env_phase = Path("scripts/install_modules/phases/08_env.sh").read_text(encoding="utf-8")
    collect_start = env_phase.index("collect_api_keys_interactive()")
    collect_block = env_phase[
        collect_start : env_phase.index("report_env_api_key_status()", collect_start)
    ]

    assert "SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV:-0" in collect_block
    assert "_sync_real_keys_to_test_env_enabled()" in collect_block
    test_start = collect_block.index('optional_env_file="$SCRIPT_DIR/.env.test"')
    test_target_block = collect_block[test_start : collect_block.index("printf '%s", test_start)]
    assert "if _sync_real_keys_to_test_env_enabled; then" in test_target_block
    assert 'targets+=("$optional_env_file")' in test_target_block
    assert "varsayılan güvenli davranış" not in test_target_block
    assert "SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=1" in collect_block
    assert "api_key_target_env_files" in collect_block
    assert "mapfile -t api_key_target_env_files" in collect_block


def test_install_sidar_propagates_api_keys_to_env_variants_after_collection() -> None:
    install_script = Path("scripts/install_modules/phases/08_env.sh").read_text(encoding="utf-8")
    installer_root = Path("install_sidar.sh").read_text(encoding="utf-8")

    # sidar_user_api_key_names() must delegate to the single-source-of-truth array
    # in install_sidar.sh (shared with mask_install_log_stream()'s masking pattern)
    # instead of keeping its own separately-maintained hardcoded key list; see
    # test_install_sidar_shares_one_secret_key_list_between_masking_and_api_keys.
    api_keys_start = install_script.index("sidar_user_api_key_names()")
    api_keys_block = install_script[api_keys_start : install_script.index("\n}\n", api_keys_start)]
    assert "printf '%s\\n' \"${SIDAR_USER_SECRET_ENV_KEYS[@]}\"" in api_keys_block

    keys_array_start = installer_root.index("SIDAR_USER_SECRET_ENV_KEYS=(")
    keys_array_block = installer_root[
        keys_array_start : installer_root.index(")", keys_array_start)
    ]
    for key in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "JIRA_TOKEN",
        "TEAMS_WEBHOOK_URL",
    ):
        assert key in keys_array_block

    collect_start = install_script.index("collect_api_keys_interactive()")
    collect_block = install_script[
        collect_start : install_script.index("report_env_api_key_status()", collect_start)
    ]
    assert "mapfile -t KEY_ORDER < <(sidar_user_api_key_names)" in collect_block
    assert "_api_key_env_targets_without_warning()" in collect_block
    assert "SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV:-0" in collect_block
    assert "_materialize_real_keys_to_env_enabled()" in collect_block
    assert "local -a targets=()" in collect_block
    assert 'targets+=("$sidar_keys_file")' in collect_block
    assert 'targets+=("$env_file")' in collect_block
    assert 'local advanced_env_file="$SCRIPT_DIR/.env.advanced"' in collect_block
    assert 'optional_env_file="$SCRIPT_DIR/.env.development"' in collect_block
    assert 'optional_env_file="$SCRIPT_DIR/.env.test"' in collect_block
    assert "SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV:-0" in collect_block
    assert "_sync_real_keys_to_test_env_enabled" in collect_block
    assert "Gerçek servis anahtarları env dosyalarına kopyalanmayacak" in collect_block
    assert 'targets+=("$optional_env_file")' in collect_block
    assert "varsayılan güvenli davranış" in collect_block
    assert (
        "mapfile -t api_key_target_env_files < <(_api_key_env_targets_without_warning)"
        in collect_block
    )
    assert 'for target in "${api_key_target_env_files[@]}"' in collect_block
    assert "_sync_existing_api_keys_to_env_targets" in collect_block
    assert collect_block.count("_sync_existing_api_keys_to_env_targets") >= 6
    no_interaction_pos = collect_block.index('if [[ "$NO_INTERACTION" == true ]]')
    import_pos = collect_block.index("_import_api_keys_from_file()")
    assert no_interaction_pos < import_pos
    assert (
        "_sync_existing_api_keys_to_env_targets\n        return"
        in collect_block[no_interaction_pos:import_pos]
    )

    propagate_start = install_script.index("propagate_shared_secrets_to_env_variants()")
    propagate_block = install_script[
        propagate_start : install_script.index("local -a variants=", propagate_start)
    ]
    assert "mapfile -t api_keys < <(sidar_user_api_key_names)" not in propagate_block
    assert 'shared_keys+=("${api_keys[@]}")' not in propagate_block

    report_start = install_script.index("report_env_api_key_status()")
    report_block = install_script[
        report_start : install_script.index("validate_runtime_env_loading()", report_start)
    ]
    assert "mapfile -t key_order < <(sidar_user_api_key_names)" in report_block


def test_install_sidar_shares_one_secret_key_list_between_masking_and_api_keys() -> None:
    """Regression test: masking and API-key allowlists must share one source.

    mask_install_log_stream() and sidar_user_api_key_names() used to keep two
    independently-maintained allowlists, so GITHUB_TOKEN/SLACK_TOKEN/TAVILY_API_KEY/
    HF_TOKEN/JIRA_TOKEN were collected as user API keys but never masked in
    install logs. Both must now read from the same SIDAR_USER_SECRET_ENV_KEYS array.
    """
    installer_root = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "SIDAR_INTERNAL_SECRET_ENV_KEYS=(" in installer_root
    assert "SIDAR_USER_SECRET_ENV_KEYS=(" in installer_root
    assert installer_root.index("SIDAR_USER_SECRET_ENV_KEYS=(") < installer_root.index(
        "mask_install_log_stream() {"
    )

    mask_fn_start = installer_root.index("mask_install_log_stream() {")
    mask_fn = installer_root[mask_fn_start : installer_root.index("\n}\n", mask_fn_start)]
    assert "SIDAR_INTERNAL_SECRET_ENV_KEYS[*]" in mask_fn
    assert "SIDAR_USER_SECRET_ENV_KEYS[*]" in mask_fn
    assert 'masked_keys_pattern="$(' in mask_fn
    assert '"s#((${masked_keys_pattern})=)[^[:space:]\\";]+#\\1****#g"' in mask_fn
    assert (
        '"s#(\\"(${masked_keys_pattern})\\"[[:space:]]*:[[:space:]]*\\")[^\\"]*\\"#\\1****\\"#g"'
        in mask_fn
    )


def test_install_summary_explains_sidarkeys_when_materialization_disabled() -> None:
    finish_phase = Path("scripts/install_modules/phases/07_finish.sh").read_text(encoding="utf-8")
    summary_start = finish_phase.index("print_summary()")
    summary_block = finish_phase[
        summary_start : finish_phase.index("verify_sidar_keys_file_permissions", summary_start)
    ]

    assert "sidar_summary_materialize_real_keys_to_env_enabled" in finish_phase
    assert "SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV:-0" in finish_phase
    assert "ℹ️  .env dosyasında" in summary_block
    assert "beklenen güvenli kurulum davranışıdır" in summary_block
    assert "SIDAR_KEYS_FILE" in summary_block
    assert "Kritik key kaynak özeti" in summary_block
    assert "SIDAR_MATERIALIZE_REAL_KEYS_TO_ENV=1" in summary_block
    assert summary_block.index(
        "elif ! sidar_summary_materialize_real_keys_to_env_enabled"
    ) < summary_block.index("⚠️  Dolu anahtar")


def test_install_sidar_reports_api_key_write_failures_without_missing_err_function() -> None:
    env_phase = Path("scripts/install_modules/phases/08_env.sh").read_text(encoding="utf-8")
    collect_start = env_phase.index("collect_api_keys_interactive()")
    collect_block = env_phase[
        collect_start : env_phase.index("report_env_api_key_status()", collect_start)
    ]

    assert "err " not in collect_block
    assert "api_key_write_success_count" in collect_block
    assert "api_key_write_failure_count" in collect_block
    assert "api_key_write_failures" in collect_block
    assert "bkz. yukarıdaki update_dotenv_value hatası" in collect_block
    assert "Başarısız API anahtarı hedefleri" in collect_block
    assert "API anahtarı yazma denemesinden" in collect_block
    assert '_write_key "$key" "$raw_val"' in collect_block
    assert "_validate_api_key_value" in collect_block
    assert 'value_bytes="$(LC_ALL=C printf' in collect_block
    assert "değer ${value_bytes} bayt (sınır: ${max_value_bytes})" in collect_block
    assert '_write_key "${grp_missing[$i]}" "${_vals[$i]:-}" || true' in collect_block


def test_primary_env_example_stays_minimal_for_new_users() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert len(env_example.splitlines()) <= 50
    assert "DATABASE_URL=" not in env_example
    assert "SIDAR_CONTAINER_DATABASE_URL=" not in env_example
    assert "GOOGLE_API_KEY" not in env_example
    assert "GOOGLE_SEARCH_API_KEY" not in env_example
    assert "BENCHMARK_ENABLE_COMPARE" not in env_example


def test_development_env_derives_database_urls_from_single_postgres_password() -> None:
    env_development = Path(".env.development.example").read_text(encoding="utf-8")

    assert "POSTGRES_PASSWORD=replace-with-a-strong-24-plus-character-password" in env_development
    assert env_development.count("replace-with-a-strong-24-plus-character-password") == 1
    assert "DATABASE_URL=postgresql" not in env_development
    assert "SIDAR_CONTAINER_DATABASE_URL=postgresql" not in env_development
    assert "SELF_HEAL_DATABASE_URL=postgresql" not in env_development
    assert "POSTGRES_CONTAINER_HOST=postgres" in env_development
    assert "POSTGRES_DB=sidar_development" in env_development
    assert "OLLAMA_NUM_PARALLEL=4" in env_development
    assert "USE_GPU=false" in env_development
    assert "REQUIRE_GPU=false" in env_development
    assert "GPU_MEMORY_FRACTION=0.8" in env_development
    assert "LLM_GPU_MEMORY_FRACTION=0.6" in env_development
    assert "RAG_GPU_MEMORY_FRACTION=0.3" in env_development
    assert (
        "JWT_SECRET_KEY=replace-with-a-local-development-jwt-secret-32-plus-chars"
        in env_development
    )


def test_test_env_uses_stronger_postgres_password_and_runtime_database_url() -> None:
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")

    assert "POSTGRES_PASSWORD=__GENERATE__" in env_test_example
    assert "POSTGRES_PASSWORD=sidar_test_secure_pw" not in env_test_example
    assert "POSTGRES_PASSWORD=sidar\n" not in env_test_example
    assert "DATABASE_URL=postgresql" not in env_test_example
    assert "TEST_DATABASE_URL=" not in env_test_example
    assert "izole test DATABASE_URL değerini çalışma zamanında üretir" in env_test_example
    assert "güçlü, lokal" in env_test_example


def test_run_tests_renders_generate_sentinel_when_creating_env_test() -> None:
    script = RUN_TESTS.read_text(encoding="utf-8")

    assert "render_generated_secret_sentinels" in script
    assert "POSTGRES_PASSWORD=__GENERATE__" in script
    assert "secrets.token_urlsafe(32)" in script


def test_install_sidar_bootstraps_env_secrets_after_uv_sync() -> None:
    contract = installer_contract_sources()
    python_env = Path("scripts/install_modules/utils/python_env.sh").read_text(encoding="utf-8")
    env_phase = Path("scripts/install_modules/phases/08_env.sh").read_text(encoding="utf-8")

    assert "ensure_env_file_secrets_after_uv_sync" in contract
    assert 'ok "Python bağımlılıkları kilitli uv.lock üzerinden senkronlandı."' in python_env
    assert (
        "ensure_env_file_secrets_after_uv_sync"
        in python_env[
            python_env.index("install_python_deps()") : python_env.index(
                "install_pyright_lsp_tool()"
            )
        ]
    )
    assert "Boş .env dosyası uv sync sonrası .env.example ile dolduruldu." in env_phase
    assert "POSTGRES_PASSWORD otomatik ve güvenli bir değerle oluşturuldu" in env_phase


def test_install_sidar_treats_change_me_placeholders_as_weak_secrets() -> None:
    script = installer_contract_sources()

    assert "change-me*|replace-with-*" in script
    assert 'is_weak_secret_value "$val" && return 0' in script


def test_install_sidar_uses_central_known_weak_secret_list() -> None:
    script = installer_contract_sources()
    known_weak = Path("scripts/known_weak_secrets.txt").read_text(encoding="utf-8")

    assert "is_known_weak_secret_value" in script
    assert "is_env_example_secret_value" in script
    assert "known_weak_secrets.txt" in script
    assert 'is_weak_secret_value "$val" && return 0' in script
    assert 'is_known_weak_secret_value "$key" "$val" && return 0' in script
    assert 'is_env_example_secret_value "$key" "$val" && return 0' in script

    for line in known_weak.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        _, weak_value = line.split("=", 1)
        assert weak_value not in script


def test_known_weak_secret_list_captures_legacy_install_examples() -> None:
    known_weak = Path("scripts/known_weak_secrets.txt").read_text(encoding="utf-8")

    for weak_postgres_password in (
        "change-me-to-a-strong-password",
        "replace-with-a-strong-24-plus-character-password",
        "__GENERATE__",
        "sidar_test_secure_pw",
        "sidar_dev_secure_pw",
        "sidar_development_secure_pw",
        "sidar_prod_secure_pw",
        "sidar_production_secure_pw",
    ):
        assert f"POSTGRES_PASSWORD={weak_postgres_password}" in known_weak

    for env_example in Path(".").glob(".env*.example"):
        for line in env_example.read_text(encoding="utf-8").splitlines():
            if line.startswith("POSTGRES_PASSWORD=") and line.strip() != "POSTGRES_PASSWORD=":
                assert line in known_weak

    for key in (
        "API_KEY",
        "JWT_SECRET_KEY",
        "MEMORY_ENCRYPTION_KEY",
        "AUTONOMY_WEBHOOK_SECRET",
        "SWARM_FEDERATION_SHARED_SECRET",
        "GITHUB_WEBHOOK_SECRET",
        "METRICS_TOKEN",
    ):
        assert f"{key}=" in known_weak


def test_install_sidar_uses_entropy_checker_for_database_password_hardening() -> None:
    script = installer_contract_sources()

    assert 'if is_weak_secret_value "$db_password"; then' in script
    assert 'case "$db_password" in' not in script
    assert "secret_strength.py" in script
    assert "Password1" not in script


def test_install_sidar_never_runs_destructive_git_cleanup_without_stash_guard() -> None:
    script = installer_contract_sources()
    recovery_start = script.index('warn "Stash apply sırasında çakışma oluştu')
    recovery_block = script[
        recovery_start : script.index('SCRIPT_DIR="$TARGET_DIR"', recovery_start)
    ]

    assert 'git stash apply "$INSTALL_STASH_REF"' in script
    assert "git stash pop" not in script
    assert 'git rev-parse -q --verify "${INSTALL_STASH_REF}^{commit}"' in recovery_block
    assert recovery_block.index("git rev-parse -q --verify") < recovery_block.index(
        "git clean -fd ||"
    )
    assert "Yedek stash korunuyor" in recovery_block
    assert "git stash apply ${INSTALL_STASH_REF}" in recovery_block
    assert (
        "Manuel çözün veya '$TARGET_DIR' içinde 'git reset --hard origin/main && git clean -fd' "
        "çalıştırın" not in script
    )


def test_install_sidar_has_locale_switch_for_english_messages() -> None:
    script = installer_contract_sources()

    assert "resolve_sidar_locale()" in script
    assert "SIDAR_LOCALE" in script
    assert "${LANG:-${LC_ALL:-${LC_MESSAGES:-tr}}}" in script
    assert "sidar_t()" in script
    assert "Usage:" in script
    assert "Unknown argument:" in script
    assert "Select installer message language" in script


def test_developer_prerequisite_docs_call_system_deps_before_uv_sync() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    testing_doc = Path("docs/TESTING.md").read_text(encoding="utf-8")
    prerequisite = (
        "bash scripts/install_ci_system_deps.sh   # portaudio, shellcheck, bats\n"
        "uv sync --frozen --all-extras"
    )

    assert "#### Geliştirici ön koşulu" in readme
    assert "### Geliştirici ön koşulu" in testing_doc
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert prerequisite in readme
    assert prerequisite in testing_doc
    assert "platform marker eklenmedi" in readme
    assert "platform marker ile gizlenmez" in testing_doc
    assert '"pyaudio~=0.2.14"' in pyproject
    assert '"pyaudio~=0.2.14";' not in pyproject
    assert "PyAudio is intentionally not hidden behind a platform marker" in pyproject
    assert "dev-light = [" in pyproject
    assert '"sidar[postgres,dev]"' in pyproject
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "uv sync --frozen --extra dev-light" in readme
    assert "uv sync --frozen --extra dev-light" in testing_doc
    assert "make deps-full" in readme
    assert "make deps-full" in testing_doc
    assert "make deps-dev-light" in readme
    assert "make deps-dev-light" in testing_doc
    deps_full_block = makefile[makefile.index("deps-full:") : makefile.index("deps-dev-light:")]
    deps_dev_light_block = makefile[
        makefile.index("deps-dev-light:") : makefile.index("test-shell:")
    ]
    assert "bash scripts/install_ci_system_deps.sh" in deps_full_block
    assert "uv sync --frozen --all-extras" in deps_full_block
    assert deps_full_block.index("bash scripts/install_ci_system_deps.sh") < deps_full_block.index(
        "uv sync --frozen --all-extras"
    )
    assert "uv sync --frozen --extra dev-light" in deps_dev_light_block
    readme_prereq_start = readme.index("#### Geliştirici ön koşulu")
    testing_prereq_start = testing_doc.index("### Geliştirici ön koşulu")
    assert readme.index(
        "bash scripts/install_ci_system_deps.sh   # portaudio, shellcheck, bats",
        readme_prereq_start,
    ) < readme.index("uv sync --frozen --all-extras", readme_prereq_start)
    assert testing_doc.index(
        "bash scripts/install_ci_system_deps.sh   # portaudio, shellcheck, bats",
        testing_prereq_start,
    ) < testing_doc.index("uv sync --frozen --all-extras", testing_prereq_start)


def test_installer_prompts_dependency_profile_after_runtime_mode() -> None:
    install_cli = Path("scripts/install_modules/install_cli.sh").read_text(encoding="utf-8")
    install_contract = installer_contract_sources()
    runtime_phase = Path("scripts/install_modules/phases/03_runtime.sh").read_text(encoding="utf-8")
    python_env = Path("scripts/install_modules/utils/python_env.sh").read_text(encoding="utf-8")
    plan = Path("docs/DEPENDENCY_PROFILE_PLAN.md").read_text(encoding="utf-8")
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'DEPENDENCY_PROFILE="${SIDAR_DEPENDENCY_PROFILE:-ask}"' in install_cli
    assert (
        "--dependency-profile=dev-light|dev-full|dev-gpu|gpu-runtime|production-minimal|production|custom"
        in install_contract
    )
    assert 'sidar_source_install_utils "gpu_utils.sh" "python_env.sh"' in runtime_phase
    assert runtime_phase.index("select_runtime_mode") < runtime_phase.index(
        "select_dependency_profile"
    )
    assert "select_dependency_profile()" in python_env
    assert "1) dev-light" in python_env
    assert "2) developer-full" in python_env
    assert "3) dev-gpu" in python_env
    assert "4) production-minimal" in python_env
    assert "5) production" in python_env
    assert "6) gpu-runtime" in python_env
    assert "7) özel provider seçimi" in python_env
    assert "RUN_CI_FULL_VALIDATION" in python_env
    assert 'requested="dev-full"' in python_env
    assert 'requested="dev-light"' in python_env
    assert "build_custom_dependency_sync_args()" in python_env
    assert "SIDAR_DEPENDENCY_EXTRAS" in python_env
    assert "normal kurulum varsayılanı ve önerisi `developer-full` / `dev-full`" in plan
    assert "custom` — `SIDAR_DEPENDENCY_EXTRAS=dev,openai,postgres`" in plan
    assert (
        'current_install_standard = "installer default developer-full; uv sync --all-extras"'
        in pyproject
    )
    assert 'default_profile = "dev-full"' in pyproject
    assert 'default_command = "./install_sidar.sh --dev-full"' in pyproject


def test_pytest_warning_filters_do_not_import_runtime_only_modules_during_config() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "ignore::pydantic.warnings.PydanticDeprecatedSince20" not in pyproject
    assert "ignore::DeprecationWarning:pydantic.*" in pyproject
    assert "pytest should reach tests/conftest.py" in pyproject


def test_ci_system_dependency_installer_provisions_shell_test_tools() -> None:
    installer = Path("scripts/install_ci_system_deps.sh").read_text(encoding="utf-8")
    sidar_installer_contract = installer_contract_sources()

    assert "PACKAGES=(portaudio19-dev shellcheck bats)" in installer
    assert (
        "curl wget git build-essential shellcheck bats software-properties-common"
        in sidar_installer_contract
    )
    assert (
        "AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=sidar:latest bash run_tests.sh"
        in installer
    )
    assert "MISSING_PACKAGES=()" in installer
    assert "CHECK_ONLY=false" in installer
    assert 'if [[ "${1:-}" == "--check" ]]; then' in installer
    assert (
        "Supported package manager not found (apt-get, dnf, zypper, pacman, or brew required)."
        in installer
    )
    assert "PACKAGES=(portaudio-devel ShellCheck bats)" in installer
    assert "PACKAGES=(portaudio shellcheck bats)" in installer
    assert "PACKAGES=(portaudio shellcheck bats-core)" in installer
    assert "Missing system dependencies for ${MANAGER}: ${MISSING_PACKAGES[*]}" in installer
    assert "brew install" in installer
    assert "pacman -Sy --needed --noconfirm" in installer
    assert "zypper --non-interactive install --no-recommends" in installer
    assert "dnf install -y" in installer
    assert "SUDO=(sudo -n)" in installer
    assert "if ! sudo -n true >/dev/null 2>&1; then" in installer
    assert "Passwordless or cached sudo is required for non-interactive installation." in installer
    assert "Run 'sudo -v' first" in installer
    assert (
        '"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y '
        '--no-install-recommends "${MISSING_PACKAGES[@]}"' in installer
    )


def test_ci_system_dependency_installer_check_mode_reports_apt_missing(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    apt_log = tmp_path / "apt.log"
    (fake_bin / "apt-get").write_text(
        f"""#!/usr/bin/env bash
printf 'unexpected apt-get call: %s\n' "$*" >> {apt_log!s}
exit 99
""",
        encoding="utf-8",
    )
    (fake_bin / "dpkg-query").write_text(
        """#!/usr/bin/env bash
if [[ "$*" == *shellcheck* ]]; then printf 'Status: install ok installed\n'; exit 0; fi
exit 1
""",
        encoding="utf-8",
    )
    (fake_bin / "apt-get").chmod(0o755)
    (fake_bin / "dpkg-query").chmod(0o755)

    result = subprocess.run(
        ["/usr/bin/bash", "scripts/install_ci_system_deps.sh", "--check"],
        check=False,
        capture_output=True,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin"},
        text=True,
    )

    assert result.returncode == 1
    assert "Missing system dependencies for apt: portaudio19-dev bats" in result.stderr
    assert not apt_log.exists()


def test_ci_system_dependency_installer_check_mode_supports_brew(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    brew_log = tmp_path / "brew.log"
    (fake_bin / "brew").write_text(
        f"""#!/usr/bin/bash
printf '%s\n' "$*" >> {brew_log!s}
if [[ "$1" == "list" && "$2" == "--versions" ]]; then
  [[ "$3" == "shellcheck" ]] && exit 0
  exit 1
fi
exit 99
""",
        encoding="utf-8",
    )
    (fake_bin / "brew").chmod(0o755)

    result = subprocess.run(
        ["/usr/bin/bash", "scripts/install_ci_system_deps.sh", "--check"],
        check=False,
        capture_output=True,
        env={**os.environ, "PATH": str(fake_bin)},
        text=True,
    )

    assert result.returncode == 1
    assert "Missing system dependencies for brew: portaudio bats-core" in result.stderr
    brew_output = brew_log.read_text(encoding="utf-8")
    assert "list --versions portaudio" in brew_output
    assert "install" not in brew_output


def test_doctor_production_readiness_target_checks_environment_prerequisites() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    doctor = Path("scripts/doctor_production_readiness.py").read_text(encoding="utf-8")
    testing = Path("docs/TESTING.md").read_text(encoding="utf-8")

    assert "doctor-production-readiness:" in makefile
    assert "uv run python scripts/doctor_production_readiness.py" in makefile
    assert "check_uv_available" in doctor
    assert "check_python_version" in doctor
    assert "check_portaudio_header" in doctor
    assert "scripts/install_ci_system_deps.sh" in doctor
    assert "sync" in doctor
    assert "--frozen" in doctor
    assert "--all-extras" in doctor
    assert "--dry-run" in doctor
    assert "bandit" in doctor
    assert "pytest_benchmark" in doctor
    assert "web_ui_react/node_modules" in doctor
    assert "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH" in doctor
    assert "PLAYWRIGHT_BROWSERS_PATH" in doctor
    assert "make benchmark-seed && make production-readiness" in doctor
    assert "make doctor-production-readiness" in testing
    assert "Release gate öncesi ortam doctor/preflight raporu" in testing


def test_makefile_benchmark_seed_is_local_only_and_production_readiness_is_release_gate() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    testing = Path("docs/TESTING.md").read_text(encoding="utf-8")
    pr_template = Path(".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")

    benchmark_seed_block = makefile[
        makefile.index("benchmark-seed:") : makefile.index("frontend-gate:")
    ]
    base_quality_block = makefile[
        makefile.index("base-quality-gates:") : makefile.index("production-readiness:")
    ]
    production_readiness_block = makefile[
        makefile.index("production-readiness:") : makefile.index("# Lokal benchmark baseline")
    ]

    assert "Lokal benchmark baseline bootstrap içindir" in makefile
    assert "seed_benchmark_baseline=true" in makefile
    assert "BENCHMARK_COMPARE_REQUIRED=$(BENCHMARK_COMPARE_REQUIRED)" in benchmark_seed_block
    assert "RUN_BENCHMARKS=required bash run_tests.sh --stage all" in benchmark_seed_block
    assert "SIDAR_PRODUCTION_READINESS=1" not in benchmark_seed_block
    assert "TEST_PROFILE=ci" not in benchmark_seed_block

    assert (
        "TEST_PROFILE=ci RUN_BENCHMARKS=$(CI_RUN_BENCHMARKS) RUN_FRONTEND_E2E=1"
        in base_quality_block
    )
    assert "SIDAR_PRODUCTION_READINESS=$(CI_PRODUCTION_READINESS)" in base_quality_block
    assert "bash run_tests.sh --stage all" in base_quality_block
    assert (
        "$(MAKE) base-quality-gates CI_RUN_BENCHMARKS=required CI_PRODUCTION_READINESS=1"
        in production_readiness_block
    )

    assert "make benchmark-seed" in testing
    assert "make production-readiness" in testing
    assert "seed_benchmark_baseline=true" in pr_template
    assert "docs/TESTING.md#ci-benchmark-baseline-cache-boşsa-ne-yapılır" in pr_template


def test_make_lint_requires_installer_shellcheck_gate() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "lint: lint-shell" in makefile
    assert "install_sidar.sh" in makefile
    assert "scripts/**/*.sh" in makefile
    assert "autonomous_loop.sh" in makefile
    assert "run_tests.sh" in makefile
    assert "uv run shellcheck" in makefile
    assert "--severity=warning -x" in makefile
    assert "dev-full:" in makefile
    assert "dev-full-gpu:" in makefile
    assert "RUN_GPU_STRESS=1 $(MAKE) dev-full" in makefile
    assert "RUN_BENCHMARKS=required" in makefile
    assert "RUN_FRONTEND_E2E=1" in makefile
    assert "FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=$(FRONTEND_BUNDLE_BUDGET_LOCAL_FULL)" in makefile
    assert "bash run_tests.sh --stage all" in makefile
    assert "production-readiness:" in makefile
    assert "TEST_PROFILE=ci RUN_BENCHMARKS=$(CI_RUN_BENCHMARKS) RUN_FRONTEND_E2E=1" in makefile
    assert "CI_PRODUCTION_READINESS=1" in makefile
    assert "SIDAR_TOTAL_JS_BUDGET_KB=$(SIDAR_TOTAL_JS_BUDGET_KB)" in makefile
    assert "SIDAR_TOTAL_GZIP_BUDGET_KB=$(SIDAR_TOTAL_GZIP_BUDGET_KB)" in makefile
    assert "frontend-gate:" in makefile
    assert (
        "RUN_FRONTEND_E2E=1 FRONTEND_E2E_ENFORCE_RESULT=1 bash run_tests.sh --stage frontend"
        in makefile
    )
    assert "backend-integration:" in makefile
    assert "bash run_tests.sh --stage integration" in makefile
    assert "sudo apt-get install -y bats shellcheck" not in ci_workflow
    assert "Install shell test tools" not in ci_workflow
    assert "run: bash scripts/install_ci_system_deps.sh" in ci_workflow
    assert ci_workflow.index("run: bash scripts/install_ci_system_deps.sh") < ci_workflow.index(
        "uv sync --frozen --all-extras"
    )
    assert ci_workflow.index("uv sync --frozen --all-extras") < ci_workflow.index("make lint")
    assert "make lint" in ci_workflow
    assert "make test-shell" in ci_workflow


def test_direct_local_stage_all_enables_frontend_bundle_budget_by_default() -> None:
    """The canonical shell command must enforce the same bundle gate as make dev-full."""
    script = _script()
    local_profile = script[
        script.index('if [ "${TEST_PROFILE}" = "ci" ]; then') : script.index(
            'RUN_FRONTEND_E2E_AUTO_INSTALL="${RUN_FRONTEND_E2E_AUTO_INSTALL:-1}"'
        )
    ]
    testing_docs = Path("docs/TESTING.md").read_text(encoding="utf-8")

    assert "if stage_all_selected; then" in local_profile
    assert "FRONTEND_BUNDLE_BUDGET_LOCAL_FULL:-1" in local_profile
    assert 'FRONTEND_BUNDLE_BUDGET="${FRONTEND_BUNDLE_BUDGET:-0}"' in local_profile
    assert "bundle budget dahil local ortam sağlığını doğrular" in testing_docs
    assert "bash run_tests.sh --stage all` hem" in testing_docs


def test_pre_commit_config_runs_uv_managed_static_gates() -> None:
    config = Path(".pre-commit-config.yaml").read_text(encoding="utf-8")
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert '"pre-commit>=4.0.0,<5.0.0"' in pyproject
    assert "id: ruff-check" in config
    assert "entry: uv run ruff check --force-exclude" in config
    assert "id: ruff-format-check" in config
    assert "entry: uv run ruff format --check --force-exclude" in config
    assert "id: mypy" in config
    assert "entry: uv run mypy ." in config
    assert "pass_filenames: false" in config
    assert "id: pytest-meta-contracts" in config
    assert (
        "entry: uv run pytest -q --no-cov -x tests/unit/scripts "
        "tests/unit/test_dependency_profile_plan.py" in config
    )
    assert "always_run: true" in config
    assert "stages: [pre-push]" in config
    assert "id: check-core-install-manifest" in config
    assert "entry: uv run python scripts/tools/update_core_install_manifest.py --check" in config
    assert "id: check-install-module-hashes" in config
    assert (
        "entry: uv run python scripts/tools/update_install_module_hash_manifest.py "
        "--target install_sidar.sh --check-manifest-only"
    ) in config
    assert "id: check-install-module-pin" in config
    assert (
        "entry: uv run python scripts/tools/update_install_module_hash_manifest.py "
        "--target install_sidar.sh --check"
    ) in config
    assert "stages: [pre-commit]" in config
    assert "stages: [pre-push]" in config
    assert ".sidar_manifest" in config
    assert "core/(memory|multimodal)" in config
    assert "scripts/install_modules/.*\\.(sh|ps1)" in config
    python_env_utils = Path("scripts/install_modules/utils/python_env.sh").read_text(
        encoding="utf-8"
    )
    workspace_phase = Path("scripts/install_modules/phases/04_workspace.sh").read_text(
        encoding="utf-8"
    )

    assert "uv run pre-commit install --hook-type pre-commit --hook-type pre-push" in readme
    assert "install_pre_commit_hooks()" in python_env_utils
    assert (
        "uv run pre-commit install --hook-type pre-commit --hook-type pre-push" in python_env_utils
    )
    assert workspace_phase.index("install_python_deps") < workspace_phase.index(
        "install_pre_commit_hooks"
    )
    assert workspace_phase.index("install_pre_commit_hooks") < workspace_phase.index(
        "install_pyright_lsp_tool"
    )
    assert "check-core-install-manifest" in readme
    assert "check-install-module-hashes" in readme
    assert "check-install-module-pin" in readme
    assert "manifest drift'ini" in readme
    assert "id: shellcheck" in config
    assert "entry: uv run shellcheck --severity=warning -x" in config
    assert "autonomous_loop" in config
    assert "scripts/.*\\.(sh|bash)" in config


def test_install_sidar_core_manifest_hashes_match_current_security_files() -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")
    sidar_manifest = Path(".sidar_manifest.txt").read_text(encoding="utf-8")
    protected_files = ("core/memory.py", "core/multimodal.py")

    for rel_path in protected_files:
        expected_line = f"{_sha256_file(Path(rel_path))}  {rel_path}"
        assert expected_line in sidar_manifest
        assert expected_line in install_script

    for required_marker in (
        "verify_core_install_manifest()",
        "SIDAR_INSTALL_MANIFEST_EOF",
        "Güvenlik ihlali: çekirdek kurulum dosyaları hash doğrulamasını geçemedi",
        "kurulum modül manifestinden (scripts/install_modules) değil",
        "scripts/sync_install_manifest.sh",
        "ALLOW_UNVERIFIED_REMOTE_SCRIPTS yalnız kurulum modülleri için",
        "çekirdek dosya manifesti için bypass uygulanmaz",
    ):
        assert required_marker in install_script


def test_sync_install_manifest_updates_core_manifest_contract() -> None:
    sync_script = Path("scripts/sync_install_manifest.sh").read_text(encoding="utf-8")
    update_tool = Path("scripts/tools/update_core_install_manifest.py").read_text(encoding="utf-8")

    assert "uv run python scripts/tools/update_core_install_manifest.py" in sync_script
    assert 'Path("core/memory.py")' in update_tool
    assert 'Path("core/multimodal.py")' in update_tool
    assert ".sidar_manifest.txt" in update_tool
    assert "SIDAR_INSTALL_MANIFEST_EOF" in update_tool
    assert "Düzeltmek için: scripts/sync_install_manifest.sh" in update_tool


def test_web_framework_dependencies_exclude_vulnerable_starlette_release() -> None:
    with Path("pyproject.toml").open("rb") as pyproject_file:
        dependencies = tomllib.load(pyproject_file)["project"]["dependencies"]
    with Path("uv.lock").open("rb") as lock_file:
        locked_packages = {
            package["name"]: package["version"] for package in tomllib.load(lock_file)["package"]
        }

    dependency_specifiers = {
        requirement.name: requirement.specifier
        for dependency in dependencies
        if (requirement := Requirement(dependency)).name in {"fastapi", "starlette"}
    }

    assert "0.136.1" in dependency_specifiers["fastapi"]
    assert "0.129.2" not in dependency_specifiers["fastapi"]
    assert "1.3.1" in dependency_specifiers["starlette"]
    assert "1.1.0" not in dependency_specifiers["starlette"]
    assert Version(locked_packages["fastapi"]) in dependency_specifiers["fastapi"]
    assert Version(locked_packages["starlette"]) in dependency_specifiers["starlette"]
    assert Version("1.1.0") not in dependency_specifiers["starlette"]


def test_pytest_shellcheck_quality_gate_is_registered() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    shellcheck_gate = Path("tests/quality/test_shellcheck_quality_gate.py").read_text(
        encoding="utf-8"
    )

    assert '"shellcheck: shell betikleri için ShellCheck kalite kapısı"' in pyproject
    assert "pytest.mark.shellcheck" in shellcheck_gate
    assert "pytest.mark.quality_gate" in shellcheck_gate
    assert "uv run pytest -q --no-cov -m quality_gate" in ci_workflow
    assert "tests/quality/test_shellcheck_quality_gate.py" in ci_workflow
    assert "shellcheck-py must expose the shellcheck executable via uv" in shellcheck_gate


def test_ci_publishes_standalone_installer_bundle() -> None:
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    bundle_script = Path("scripts/tools/bundle_install_sidar.sh").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    modularization_note = Path("docs/module-notes/install_sidar_modularization.md").read_text(
        encoding="utf-8"
    )

    assert "tags:" in ci_workflow
    assert '"v*"' in ci_workflow
    assert "bash scripts/tools/bundle_install_sidar.sh" in ci_workflow
    assert "bash -n dist/install_sidar.sh" in ci_workflow
    assert (
        "SIDAR_INSTALL_TEST_MODE=1 SIDAR_INSTALL_VERSION_PROBE_ONLY=1 bash dist/install_sidar.sh"
        in ci_workflow
    )
    assert "name: standalone-install-sidar" in ci_workflow
    assert "path: |" in ci_workflow
    assert "dist/install_sidar.sh" in ci_workflow
    assert "dist/MODULE_HASHES.txt" in ci_workflow
    assert "dist/INSTALLER_USAGE.md" in ci_workflow
    assert "softprops/action-gh-release@v2" in ci_workflow
    assert "github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v')" in ci_workflow
    assert (
        "tag_name: ${{ startsWith(github.ref, 'refs/tags/v') && github.ref_name || "
        "'installer-main' }}" in ci_workflow
    )
    assert "`main` pushes update this prerelease snapshot" in ci_workflow
    assert "overwrite_files: true" in ci_workflow
    assert "files: |" in ci_workflow

    dynamic_url = "https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/main/install_sidar.sh"
    release_url = (
        "https://github.com/niluferbagevi-gif/Sidar/releases/latest/download/install_sidar.sh"
    )
    assert "OUTPUT_USAGE=" in bundle_script
    assert "RELEASE_INSTALLER_URL=" in bundle_script
    assert "RAW_INSTALLER_URL=" in bundle_script
    assert (
        r"export SIDAR_INSTALLER_BOOTSTRAP_MODE=\"${SIDAR_INSTALLER_BOOTSTRAP_MODE:-bundle}\""
        in bundle_script
    )
    assert (
        r"export SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS="
        r"\"${SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS:-0}\"" in bundle_script
    )
    assert "Preferred release/bundle install" in bundle_script
    assert "Last-resort raw fallback" in bundle_script
    assert (
        "raw main/install_sidar.sh yalnız release bundle mevcut değilse son çare" in bundle_script
    )
    assert release_url in readme
    assert release_url in modularization_note
    for content in (readme, modularization_note):
        assert dynamic_url in content
        assert "git clone https://github.com/niluferbagevi-gif/Sidar.git" in content
        assert "uv sync --all-extras" in content
        assert "dinamik modül" in content
        assert content.index(release_url) < content.index(dynamic_url)
        assert "raw fallback" in content
        assert "GitHub raw 429/5xx" in content
        if content == readme:
            assert "pin-drift" in content
            assert "--check-pin" in content
    assert "curl -fL --retry 5 --retry-all-errors --retry-delay 2" in readme
    assert "wget --tries=5 --waitretry=2" in readme
    assert "Retry-After" in readme
    assert "Release bundle (önerilen)" in readme
    assert "varsayılan Release bundle, raw fallback son çare" in modularization_note
    assert "Normal kullanıcı, temiz kurulum, kurumsal/offline veya interneti kısıtlı" in readme
    assert "Raw fallback notu" in readme
    assert "raw.githubusercontent.com" in readme
    assert "Raw fallback modül indirme: 30 modül indirildi" in readme
    assert "kusur değildir" in readme
    assert "monolitik Release bundle" in modularization_note


def test_install_sidar_root_guard_allows_explicit_test_mode_only() -> None:
    script = installer_contract_sources()

    assert '"${EUID:-$(id -u)}" -eq 0 && "${SIDAR_INSTALL_TEST_MODE:-0}" != "1"' in script


def test_install_sidar_prefers_existing_repo_module_tree_before_download_or_clone() -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "use_existing_install_module_tree_if_available()" in install_script
    assert '"${PWD}/scripts/install_modules"' in install_script
    assert 'candidates+=("${TARGET_DIR}/scripts/install_modules")' in install_script
    assert '"${HOME}/Sidar/scripts/install_modules"' in install_script
    assert "Mevcut repo kurulum modülleri doğrudan kullanılacak" in install_script
    module_resolution_flow = install_script[
        install_script.index(
            "use_existing_install_module_tree_if_available || true"
        ) : install_script.index('if [[ "${INSTALL_MODULES_DOWNLOADED:-0}" != "1" ]]; then')
    ]
    assert module_resolution_flow.index(
        "use_existing_install_module_tree_if_available || true"
    ) < module_resolution_flow.index("download_install_modules_to_temp")
    missing_module_flow = install_script[
        install_script.index("use_existing_install_module_tree_if_available || true") :
    ]
    assert missing_module_flow.index(
        'download_install_modules_to_temp "$REMOTE_MODULE_BASE"'
    ) < missing_module_flow.index("bootstrap_clone_and_reexec")


def test_install_sidar_detects_offline_mode_before_bootstrap_downloads() -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "sidar_detect_early_offline_mode()" in install_script
    assert 'sidar_detect_early_offline_mode "$@" || true' in install_script
    assert "--offline|--air-gapped" in install_script
    assert "${OFFLINE_INSTALL:-}" in install_script
    assert "${AIR_GAPPED_INSTALL:-}" in install_script

    early_detector = install_script.index('sidar_detect_early_offline_mode "$@" || true')
    missing_module_guard = install_script.index('if [[ "${OFFLINE_MODE:-false}" == "true" ]]; then')
    skip_direct_guard = install_script.index(
        'if [[ "${SIDAR_INSTALL_SKIP_DIRECT_MODULE_DOWNLOAD:-0}" == "1" ]]; then'
    )
    remote_resolution = install_script.index('REMOTE_MODULE_BASE="$(resolve_remote_module_base)"')
    trust_validation = install_script.index(
        'validate_remote_module_trust_root "$REMOTE_MODULE_BASE"'
    )
    direct_download = install_script.index('download_install_modules_to_temp "$REMOTE_MODULE_BASE"')
    bootstrap_clone = install_script.index("bootstrap_clone_and_reexec", direct_download)
    cli_parse = install_script.index('sidar_parse_install_cli "$@"')

    assert early_detector < missing_module_guard < skip_direct_guard < remote_resolution
    assert skip_direct_guard < remote_resolution < trust_validation < direct_download
    assert missing_module_guard < bootstrap_clone < cli_parse
    offline_guard_block = install_script[missing_module_guard:skip_direct_guard]
    assert "raw fallback modül indirme veya bootstrap clone yapılmayacak" in offline_guard_block
    assert "release bundle install_sidar.sh" in offline_guard_block


def test_install_sidar_sources_existing_cwd_module_tree_before_remote_fallback(
    tmp_path: Path,
) -> None:
    runner_dir = tmp_path / "runner"
    runner_dir.mkdir()
    shutil.copy2("install_sidar.sh", runner_dir / "install_sidar.sh")

    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -Eeuo pipefail; script_path="$1"; set --; source "$script_path"; printf "%s\n" '
            '"$INSTALL_MODULE_DIR"',
            "bash",
            str(runner_dir / "install_sidar.sh"),
        ],
        check=True,
        capture_output=True,
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "SIDAR_INSTALL_TEST_MODE": "1",
            "SIDAR_INSTALL_MODULE_BASE_URL": (tmp_path / "missing-remote").as_uri(),
        },
        text=True,
    )

    expected_module_dir = str((Path.cwd() / "scripts/install_modules").resolve())
    assert result.stdout.strip() == expected_module_dir
    assert "Mevcut repo kurulum modülleri doğrudan kullanılacak" in result.stderr
    assert "Fallback modül indirildi" not in result.stderr


def test_install_sidar_keeps_plural_module_dir_alias_synced(tmp_path: Path) -> None:
    runner_dir = tmp_path / "runner"
    runner_dir.mkdir()
    shutil.copy2("install_sidar.sh", runner_dir / "install_sidar.sh")

    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                'set -Eeuo pipefail; script_path="$1"; set --; '
                'source "$script_path"; '
                'printf "%s\\n%s\\n%s\\n" '
                '"$INSTALL_MODULE_DIR" "$INSTALL_MODULES_DIR" "$INSTALL_HELPERS_MODULE"'
            ),
            "bash",
            str(runner_dir / "install_sidar.sh"),
        ],
        check=True,
        capture_output=True,
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "SIDAR_INSTALL_TEST_MODE": "1",
            "SIDAR_INSTALL_MODULE_BASE_URL": (tmp_path / "missing-remote").as_uri(),
        },
        text=True,
    )

    module_dir, plural_alias, helpers_module = result.stdout.strip().splitlines()
    expected_module_dir = str((Path.cwd() / "scripts/install_modules").resolve())
    assert module_dir == expected_module_dir
    assert plural_alias == expected_module_dir
    assert helpers_module == f"{expected_module_dir}/install_helpers.sh"


def test_install_sidar_single_file_fallback_downloads_all_modules(tmp_path: Path) -> None:
    remote_modules = tmp_path / "remote"
    runner_dir = tmp_path / "runner"
    shutil.copytree("scripts/install_modules", remote_modules)
    runner_dir.mkdir()
    shutil.copy2("install_sidar.sh", runner_dir / "install_sidar.sh")

    expected_modules = (
        "install_helpers.sh",
        "utils/install_remediation.sh",
        "utils/wsl_integration_autofix.ps1",
        "utils/wsl_gpu_preflight.sh",
        "utils/wsl_host.sh",
        "utils/gpu_utils.sh",
        "utils/python_env.sh",
        "utils/db_credentials.sh",
        "utils/env_utils.sh",
        "utils/ollama_models.sh",
        "utils/playwright_ubuntu_override.sh",
        "phases/01_context.sh",
        "phases/02_repo.sh",
        "phases/03_runtime.sh",
        "phases/04_workspace.sh",
        "phases/05_frontend.sh",
        "phases/06_services.sh",
        "phases/07_finish.sh",
    )
    module_checks = "; ".join(
        f'test -f "$INSTALL_MODULE_DIR/{module}"' for module in expected_modules
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            f'set -Eeuo pipefail; script_path="$1"; set --; source "$script_path"; '
            f"{module_checks}; "
            'case "$INSTALL_MODULE_DIR" in /tmp/sidar_install_modules.*/*) ;; *) exit 1 ;; esac; '
            'printf "%s\n" "$INSTALL_MODULE_DIR"',
            "bash",
            str(runner_dir / "install_sidar.sh"),
        ],
        check=True,
        capture_output=True,
        cwd=runner_dir,
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "SIDAR_INSTALL_TEST_MODE": "1",
            "SIDAR_INSTALL_MODULE_BASE_URL": remote_modules.resolve().as_uri(),
        },
        text=True,
    )

    assert "Kurulum modülleri indirildi" in result.stderr
    assert "Fallback modül indirildi: install_helpers.sh ->" in result.stderr
    assert "install_modules" in result.stdout


def test_install_sidar_remote_module_download_has_retry_backoff_and_resume_cache() -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert (
        'SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES="${SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES:-5}"'
        in install_script
    )
    assert "--retry-all-errors" in install_script
    assert "--connect-timeout" in install_script
    assert "--max-time" in install_script
    assert "remote_install_module_status_is_retryable()" in install_script
    assert "000|403|408|409|425|429|5??" in install_script
    assert "remote_install_module_retry_sleep" in install_script
    assert "Retry-After:" in install_script
    assert "SIDAR_INSTALL_MODULE_CACHE_ROOT" in install_script
    assert "SIDAR_INSTALLER_BOOTSTRAP_MODE" in install_script
    assert "SIDAR_INSTALL_MODULES_DOWNLOADED_COUNT" in install_script
    assert "SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS" in install_script
    assert "SIDAR_INSTALL_MODULE_HTTP_429_RETRIES" in install_script
    assert "SIDAR_INSTALL_MODULE_CACHE_HITS" in install_script
    assert 'cache_sentinel="${cache_path}.ok"' in install_script
    assert "Fallback modül cache'den kullanıldı" in install_script
    assert (
        "Cache korunur; aynı komut tekrar çalıştırıldığında başarılı modüller yeniden "
        "kullanılacaktır." in install_script
    )
    assert "Fallback modül indirme başarısız (${module_rel})" in install_script


def test_wsl_integration_autofix_ps1_uses_utf8_bom_for_windows_powershell_51() -> None:
    raw_script = Path("scripts/install_modules/utils/wsl_integration_autofix.ps1").read_bytes()

    assert raw_script.startswith(b"\xef\xbb\xbf")
    script = raw_script.decode("utf-8-sig")
    assert "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()" in script
    # Verify the durable contract of the WSL-side socket validation instead of the
    # exact user-facing sentence, which may evolve as diagnostics are clarified.
    assert 'Write-Error "docker-desktop görünmüyor' in script
    assert "WSL dağıtımı içinden Docker socket doğrulanamıyor" in script


def test_install_sidar_main_uses_phase_modules_as_orchestrator() -> None:
    script = installer_contract_sources()
    main_body = shell_function_body(script, "sidar_dispatch_install_phases")

    expected_modules = (
        "phases/01_context.sh",
        "phases/02_repo.sh",
        "phases/03_runtime.sh",
        "phases/04_workspace.sh",
        "phases/05_frontend.sh",
        "phases/06_services.sh",
        "phases/07_finish.sh",
        "utils/install_remediation.sh",
        "utils/wsl_gpu_preflight.sh",
        "utils/wsl_host.sh",
        "utils/gpu_utils.sh",
        "utils/python_env.sh",
        "utils/db_credentials.sh",
        "utils/env_utils.sh",
        "utils/ollama_models.sh",
        "utils/playwright_ubuntu_override.sh",
    )
    for module in expected_modules:
        assert module in script
        assert Path("scripts/install_modules", module).is_file()

    for phase_call in (
        "sidar_phase_initialize_context",
        "sidar_phase_handle_early_exit",
        "sidar_phase_bootstrap_repo_system",
        "sidar_phase_runtime_prerequisites",
        "sidar_phase_workspace_config",
        "sidar_phase_frontend_assets",
        "sidar_phase_local_migrations_and_models",
        "sidar_phase_services_and_validation",
        "sidar_phase_finish",
    ):
        assert phase_call in main_body

    for legacy_inline_call in (
        "install_system_dependencies",
        "sync_repo",
        "create_uv_venv",
        "setup_env_file",
        "run_migrations",
        "launch_docker_services",
        "print_summary",
    ):
        assert legacy_inline_call not in main_body

    assert 'if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]' in script
    assert 'main "$@"' in script


def test_install_sidar_phases_delegate_functional_install_utils() -> None:
    helper = Path("scripts/install_modules/install_helpers.sh").read_text(encoding="utf-8")
    context_phase = Path("scripts/install_modules/phases/01_context.sh").read_text(encoding="utf-8")
    system_phase = Path("scripts/install_modules/phases/03_system.sh").read_text(encoding="utf-8")
    runtime_phase = Path("scripts/install_modules/phases/03_runtime.sh").read_text(encoding="utf-8")
    workspace_phase = Path("scripts/install_modules/phases/04_workspace.sh").read_text(
        encoding="utf-8"
    )
    services_phase = Path("scripts/install_modules/phases/06_services.sh").read_text(
        encoding="utf-8"
    )
    alembic_phase = Path("scripts/install_modules/phases/12_alembic.sh").read_text(encoding="utf-8")
    remediation_utils = Path("scripts/install_modules/utils/install_remediation.sh").read_text(
        encoding="utf-8"
    )
    preflight_utils = Path("scripts/install_modules/utils/wsl_gpu_preflight.sh").read_text(
        encoding="utf-8"
    )
    gpu_utils = Path("scripts/install_modules/utils/gpu_utils.sh").read_text(encoding="utf-8")
    python_env_utils = Path("scripts/install_modules/utils/python_env.sh").read_text(
        encoding="utf-8"
    )
    db_url_utils = Path("scripts/install_modules/utils/database_url.sh").read_text(encoding="utf-8")
    db_utils = Path("scripts/install_modules/utils/db_credentials.sh").read_text(encoding="utf-8")
    env_secret_utils = Path("scripts/install_modules/utils/env_secrets.sh").read_text(
        encoding="utf-8"
    )
    env_utils = Path("scripts/install_modules/utils/env_utils.sh").read_text(encoding="utf-8")
    ollama_utils = Path("scripts/install_modules/utils/ollama_models.sh").read_text(
        encoding="utf-8"
    )
    bundler = Path("scripts/tools/bundle_install_sidar.sh").read_text(encoding="utf-8")
    install_script = installer_contract_sources()
    ux_utils = Path("scripts/install_modules/utils/ux.sh").read_text(encoding="utf-8")

    assert "sidar_source_install_utils()" in helper
    assert 'sidar_source_install_utils "install_remediation.sh" "ux.sh"' in install_script
    assert "print_install_help()" in ux_utils
    assert "print_install_help() {" not in Path("install_sidar.sh").read_text(encoding="utf-8")
    assert "sidar_run_install_phase()" in remediation_utils
    assert "sidar_handle_install_failure()" in remediation_utils
    assert "sidar_remediate_uv_sync_failure()" in remediation_utils
    assert "SIDAR_INSTALL_RESUME_FROM_PHASE" in remediation_utils
    assert "uv lock --check" in remediation_utils
    assert "uv cache prune" in remediation_utils
    assert 'sidar_source_install_utils "wsl_gpu_preflight.sh"' in context_phase
    assert "run_wsl2_gpu_preflight" in context_phase
    assert context_phase.index("detect_environment") < context_phase.index("run_wsl2_gpu_preflight")
    assert 'sidar_source_install_utils "gpu_utils.sh"' in runtime_phase
    assert (
        'sidar_source_install_utils "python_env.sh" "database_url.sh" "db_credentials.sh" '
        '"env_utils.sh"' in workspace_phase
    )
    assert 'sidar_source_install_utils "ollama_models.sh"' in services_phase
    assert "sync_database_passwords_before_smoke_tests" in services_phase
    assert "ensure_env_test_postgres_password_matches_base_before_smoke" in services_phase
    assert "ensure_postgres_volume_reset_before_smoke_tests" in services_phase
    assert "sidar_phase06_preserve_pre_service_smoke_log" in services_phase
    assert "artifacts/install/remediation" in services_phase
    assert "Smoke gate kalıcı log kopyası" in services_phase
    assert "uv run python scripts/sync_database_passwords.py --all-envs" in services_phase
    assert "uv run python scripts/sync_postgres_password.py" in services_phase
    assert "POSTGRES_PASSWORD değeri .env ile uyuşmuyor" in services_phase
    assert "docker compose down --volumes --remove-orphans" in services_phase
    assert "PostgreSQL volume reset doğrulanamadı" in services_phase
    assert services_phase.index(
        "sync_database_passwords_before_smoke_tests"
    ) < services_phase.index("run_smoke_tests")
    assert "Servis öncesi installer smoke gate Python bağımlılıkları doğrulanıyor" in services_phase
    assert 'for module in ("pytest", "pydantic", "pydantic_settings")' in services_phase
    assert "uv sync --frozen --extra dev-light" in services_phase
    assert "Manuel doğrulama: uv sync --frozen --extra dev-light" in services_phase
    assert "SIDAR_ENV=test" in services_phase
    assert 'SIDAR_KEYS_FILE=""' in services_phase
    assert "SIDAR_TEST_LOAD_REAL_KEYS=0" in services_phase
    assert '--confcutdir="$SCRIPT_DIR/tests/smoke"' in services_phase
    assert "tests/smoke/test_install_verification.py" in services_phase
    assert services_phase.index(
        "Servis öncesi installer smoke gate Python bağımlılıkları doğrulanıyor"
    ) < services_phase.index(
        "Servis öncesi installer smoke gate başlamadan PostgreSQL dotenv profilleri eşitleniyor"
    )
    assert services_phase.index(
        "Servis öncesi installer smoke gate başlamadan PostgreSQL dotenv profilleri eşitleniyor"
    ) < services_phase.index("uv run pytest")
    assert services_phase.index(
        "scripts/sync_database_passwords.py --all-envs"
    ) < services_phase.index("ensure_env_test_postgres_password_matches_base_before_smoke")
    assert services_phase.index(
        "ensure_env_test_postgres_password_matches_base_before_smoke"
    ) < services_phase.index("ensure_postgres_volume_reset_before_smoke_tests")
    assert services_phase.index(
        "ensure_postgres_volume_reset_before_smoke_tests"
    ) < services_phase.index("scripts/sync_postgres_password.py")

    assert "run_wsl2_gpu_preflight()" in preflight_utils
    assert "SIDAR_WSL_GPU_PREFLIGHT" in preflight_utils
    assert "nvidia-smi" in preflight_utils
    assert "GPU adı RTX/NVIDIA LLM hızlandırma profiline benzemiyor" not in preflight_utils
    assert '"$gpu_name" =~ (RTX|Blackwell|Ada|Ampere|NVIDIA)' not in preflight_utils
    assert "GPU product names are informational only" in preflight_utils
    assert "/dev/dxg" in preflight_utils
    assert "libcuda" in preflight_utils
    assert "Ollama API" in preflight_utils
    assert "detect_gpu()" in gpu_utils
    assert "setup_nvidia_docker()" in gpu_utils
    assert "install_nvidia_container_repository()" in gpu_utils
    assert "sudo install -m 0644" in gpu_utils
    assert "sudo install -d -m 0755 /usr/share/keyrings" in gpu_utils
    assert "--retry-all-errors" in gpu_utils
    assert "curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |" not in gpu_utils
    assert "setup_nvidia_docker()" not in system_phase
    assert "docker_nvidia_runtime_registered()" in gpu_utils
    assert "wait_for_docker_nvidia_runtime()" in gpu_utils
    assert "SIDAR_DOCKER_NVIDIA_RUNTIME_WAIT_SECONDS" in gpu_utils
    assert "docker info --format '{{json .Runtimes}}'" in gpu_utils
    assert "wait_for_docker_nvidia_runtime()" in install_script
    assert "create_uv_venv()" in python_env_utils
    assert "ensure_python_311()" not in python_env_utils
    assert "install_python_deps()" in python_env_utils
    assert "uv sync" in python_env_utils
    assert "uv pip" not in python_env_utils
    assert "uv tool install" not in python_env_utils
    assert "harden_database_credentials()" in db_utils
    assert "harden_database_credentials()" not in env_secret_utils
    assert "generate_secure_token()" in env_secret_utils
    assert "sync_postgres_env_with_database_url()" in db_url_utils
    assert "ensure_database_url_defaults()" in db_url_utils
    assert "setup_env_file()" in env_utils
    assert 'ADVANCED_ENV_FILE="$SCRIPT_DIR/.env.advanced"' in env_utils
    assert 'ADVANCED_EXAMPLE_FILE="$SCRIPT_DIR/.env.advanced.example"' in env_utils
    assert 'install -m 600 "$ADVANCED_EXAMPLE_FILE" "$ADVANCED_ENV_FILE"' in env_utils
    assert "propagate_shared_secrets_to_env_variants" in env_utils
    assert "sync_database_env_chain_after_setup()" in env_utils
    assert "uv run python -m scripts.sync_database_passwords --all-envs" in env_utils
    assert "uv run python -m scripts.sync_database_passwords --remove-explicit-urls" in env_utils
    assert "sync_database_env_chain_after_setup()" in install_script
    assert "uv run python -m scripts.sync_database_passwords --all-envs" in install_script
    assert (
        "uv run python -m scripts.sync_database_passwords --remove-explicit-urls" in install_script
    )
    propagate_body = install_script[
        install_script.index("propagate_shared_secrets_to_env_variants()") : install_script.index(
            "ensure_local_service_host_defaults()"
        )
    ]
    assert "POSTGRES_PASSWORD" not in propagate_body
    assert "DATABASE_URL" not in propagate_body
    assert "SIDAR_DATABASE_ENV_CHAIN_SYNCED" not in env_utils
    assert "SIDAR_DATABASE_ENV_CHAIN_SYNCED" not in install_script
    assert "migrasyon DSN'i POSTGRES_* parçalarından üretildi" in alembic_phase
    recovery_guard = alembic_phase[
        alembic_phase.index(
            'if sidar_weak_password_recovery_allowed "$migration_sidar_env"'
        ) : alembic_phase.index(
            'if [[ "$auth_check_rc" -eq 10 ]]', alembic_phase.index("recovery_password_candidates")
        )
    ]
    assert 'recovery_password_candidates+=("sidar" "postgres"' in recovery_guard
    assert "production ortamında devre dışıdır" in recovery_guard
    assert "collect_api_keys_interactive kendi içinde .env + runtime env varyantlarına" in env_utils
    existing_env_branch = env_utils[
        env_utils.index('if [[ -f "$ENV_FILE" ]]') : env_utils.index(
            "return", env_utils.index('if [[ -f "$ENV_FILE" ]]')
        )
    ]
    assert existing_env_branch.index(
        "propagate_shared_secrets_to_env_variants"
    ) < existing_env_branch.index("collect_api_keys_interactive")
    assert existing_env_branch.index("report_env_api_key_status") < existing_env_branch.index(
        "sync_database_env_chain_after_setup"
    )
    assert existing_env_branch.index(
        "sync_database_env_chain_after_setup"
    ) < existing_env_branch.index("validate_runtime_env_loading")
    assert "ikinci bir generic propagate gerekmez" in existing_env_branch
    assert "harden_database_credentials" in env_utils
    assert "download_ollama_models()" in ollama_utils
    assert "qwen2.5-coder:7b" in ollama_utils
    assert "_is_playwright_os_mismatch_error" not in install_script
    assert "Çıktı metninden bağımsız fallback" in install_script

    assert 'module_dir "/utils' in bundler
    assert 'module_dir "/phases' in bundler


def test_playwright_install_fallback_does_not_depend_on_cli_error_text(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    python_log = tmp_path / "python.log"
    os_release = tmp_path / "os-release"
    os_release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    python = fake_bin / "python"
    python.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$PYTHON_LOG"\n'
        'case "$*" in\n'
        '  "-c import playwright") exit 0 ;;\n'
        '  "-m playwright install --with-deps chromium") '
        "printf 'upstream-metni-artik-farkli\\n' >&2; exit 23 ;;\n"
        '  "-m playwright install chromium") exit 0 ;;\n'
        "esac\n"
        "exit 1\n",
        encoding="utf-8",
    )
    python.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            "source ./install_sidar.sh >/dev/null 2>&1; install_playwright_browsers",
        ],
        capture_output=True,
        env={
            **os.environ,
            "OS_RELEASE_PATH": str(os_release),
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "PLAYWRIGHT_BROWSERS_MODE": "always",
            "PYTHON_LOG": str(python_log),
            "SIDAR_INSTALL_TEST_MODE": "1",
        },
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    calls = python_log.read_text(encoding="utf-8").splitlines()
    output = result.stdout + result.stderr
    assert "-m playwright install --with-deps chromium" in calls
    assert "-m playwright install chromium" in calls
    assert "Çıktı metninden bağımsız fallback" in output
    assert "fallback ile tamamlandı" in output


def test_alembic_weak_password_recovery_is_disabled_in_production() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/install_modules/phases/12_alembic.sh; "
            "sidar_weak_password_recovery_allowed development; "
            "sidar_weak_password_recovery_allowed test; "
            "! sidar_weak_password_recovery_allowed production; "
            "! sidar_weak_password_recovery_allowed PROD",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_react_frontend_phase_suppresses_npm_update_notice_with_opt_in_upgrade() -> None:
    react_phase = Path("scripts/install_modules/phases/14_react.sh").read_text(encoding="utf-8")

    assert "maybe_upgrade_npm_latest()" in react_phase
    assert "SIDAR_UPGRADE_NPM_LATEST" in react_phase
    assert "UPGRADE_NPM_LATEST" in react_phase
    assert "install -g npm@latest --no-audit --no-fund" in react_phase
    assert "npm_config_update_notifier=false" in react_phase
    assert "NPM_CONFIG_UPDATE_NOTIFIER=false" in react_phase
    assert react_phase.index("maybe_upgrade_npm_latest") < react_phase.index("npm ci")


def test_install_sidar_ollama_install_keeps_sudo_alive_and_tolerates_post_install_rc() -> None:
    script = installer_contract_sources()
    ollama_block = script[
        script.index("# Ollama (varsayılan AI provider)") : script.index(
            "# Servisin anlık olarak yanıt verip vermediğini kontrol et"
        )
    ]

    assert "sudo -n -v 2>/dev/null || exit 0" in ollama_block
    assert 'sleep "${SUDO_KEEPALIVE_INTERVAL_SECONDS:-30}"' in ollama_block
    assert 'kill "$sudo_keepalive_pid" 2>/dev/null || true' in ollama_block
    assert 'if sh "$ollama_install_script"; then' in ollama_block
    assert "_ollama_rc=$?" in ollama_block
    assert "if (( _ollama_rc != 0 )); then" in ollama_block
    assert "command -v ollama &>/dev/null && ollama -v &>/dev/null" in ollama_block
    assert "büyük olasılıkla sudo timestamp expire" in ollama_block
    assert "/var/log/syslog veya logs/install_*.log" in ollama_block


def test_install_sidar_defaults_gpu_available_for_resume_mode() -> None:
    script = installer_contract_sources()

    strict_mode_pos = script.index("set -Eeuo pipefail")
    default_pos = script.index('export GPU_AVAILABLE="${GPU_AVAILABLE:-false}"')
    phase_runner_pos = script.index('sidar_run_install_phase "01_context"')

    assert strict_mode_pos < default_pos < phase_runner_pos


def test_install_remediation_treats_timeout_exit_codes_as_non_retryable() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            source ./scripts/install_modules/utils/install_remediation.sh
            for rc in -9 124; do
                if sidar_is_non_retryable_failure_code "$rc"; then
                    echo "non-retryable:$rc"
                else
                    echo "retryable:$rc"
                fi
            done
            if sidar_is_non_retryable_failure_code 1; then
                echo retryable-code-marked-non-retryable
            else
                echo retryable:1
            fi
            """,
        ],
        check=True,
        capture_output=True,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        text=True,
    )

    assert result.stdout.splitlines() == ["non-retryable:-9", "non-retryable:124", "retryable:1"]


def test_install_sidar_runtime_phase_uses_transient_retry_budget() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            source ./scripts/install_modules/utils/install_remediation.sh
            sidar_retry_budget_for_failure 03_runtime 'sh /tmp/ollama_install_script' \
              'sudo: timed out'
            SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS_TRANSIENT=2 \
                sidar_retry_budget_for_failure 03_runtime 'network fetch' 'temporary failure'
            sidar_retry_budget_for_failure 03_runtime 'pytest' 'deterministic failure'
            sidar_retry_budget_for_failure 04_workspace 'unknown' 'unknown'
            if sidar_is_deterministic_failure_signal 'sh /tmp/ollama_install_script' \
              'sudo: timed out deterministic'; then
                echo deterministic
            else
                echo transient
            fi
            """,
        ],
        check=True,
        capture_output=True,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        text=True,
    )

    assert result.stdout.splitlines() == ["3", "2", "1", "1", "transient"]


def test_install_sidar_auto_heal_wraps_phases_and_resumes() -> None:
    script = installer_contract_sources()
    main_body = shell_function_body(script, "sidar_dispatch_install_phases")
    remediation_utils = Path("scripts/install_modules/utils/install_remediation.sh").read_text(
        encoding="utf-8"
    )

    assert '"utils/install_remediation.sh"' in script
    assert 'sidar_source_install_utils "install_remediation.sh"' in script
    assert "sidar_handle_install_failure" in script
    assert "SIDAR_INSTALL_ORIGINAL_ARGS" in script

    for phase_name in (
        "01_context",
        "02_repo",
        "03_runtime",
        "04_workspace",
        "05_frontend",
        "06_models",
        "06_services",
        "07_finish",
    ):
        assert f'sidar_run_install_phase "{phase_name}"' in main_body

    assert "SIDAR_INSTALL_AUTO_HEAL" in remediation_utils
    assert "SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS" in remediation_utils
    assert "02_repo|03_runtime|05_frontend|06_models|06_services" in remediation_utils
    assert '*"sudo: timed out"*|*"ollama_install"*)' in remediation_utils
    assert "sidar_phase_remediation_strategy()" in remediation_utils
    assert "03_runtime)" in remediation_utils
    assert "ollama-installed-despite-rc" in remediation_utils
    assert "treat-as-success;resume-phase" in remediation_utils
    assert "ollama-install-retry" in remediation_utils
    assert "rerun-install-script;refresh-sudo" in remediation_utils
    assert "sidar_resume_after_remediation()" in remediation_utils
    assert "uv.lock" in remediation_utils
    assert "uv lock" in remediation_utils
    assert "exec env" in remediation_utils
    assert "artifacts/install/remediation" in remediation_utils


def test_install_sidar_runtime_ollama_remediation_writes_action_reports(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ollama = bin_dir / "ollama"
    ollama.write_text("#!/usr/bin/env bash\necho 'ollama version 0.0-test'\n", encoding="utf-8")
    ollama.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            info() { printf '%s\n' "$*" >&2; }
            warn() { printf '%s\n' "$*" >&2; }
            SCRIPT_DIR="$1"
            PATH="$2:$PATH"
            source ./scripts/install_modules/utils/install_remediation.sh
            sidar_phase_remediation_strategy 03_runtime 'sh /tmp/ollama_install_script' \
              'sudo: timed out'
            report="$(find "$SCRIPT_DIR/artifacts/install/remediation" -type f \
              -name '*_03_runtime.log' | sort | tail -n 1)"
            cat "$report"
            """,
            "bash",
            str(tmp_path),
            str(bin_dir),
        ],
        check=True,
        capture_output=True,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        text=True,
    )

    assert "reason=ollama-installed-despite-rc" in result.stdout
    assert "action=treat-as-success;resume-phase" in result.stdout

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            info() { printf '%s\n' "$*" >&2; }
            warn() { printf '%s\n' "$*" >&2; }
            SCRIPT_DIR="$1"
            source ./scripts/install_modules/utils/install_remediation.sh
            ollama() { return 1; }
            export -f ollama
            sidar_phase_remediation_strategy 03_runtime 'sh /tmp/ollama_install_script' \
              'sudo: timed out'
            report="$(find "$SCRIPT_DIR/artifacts/install/remediation" -type f \
              -name '*_03_runtime.log' | sort | tail -n 1)"
            cat "$report"
            """,
            "bash",
            str(tmp_path / "retry"),
        ],
        check=True,
        capture_output=True,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        text=True,
    )

    assert "reason=ollama-install-retry" in result.stdout
    assert "action=rerun-install-script;refresh-sudo" in result.stdout


def _extract_services_phase_function(name: str, next_marker: str) -> str:
    services_phase = Path("scripts/install_modules/phases/06_services.sh").read_text(
        encoding="utf-8"
    )
    start = services_phase.index(f"{name}() {{")
    end = services_phase.index(next_marker, start)
    return services_phase[start:end]


def test_postgres_volume_reset_env_gate_rejects_missing_or_unrecognized_sidar_env(
    tmp_path: Path,
) -> None:
    """Regression test: SIDAR_ENV unset/empty/unrecognized must fail closed.

    Reject the volume reset instead of silently defaulting to "development"
    and allowing a destructive `docker volume rm -f` to proceed.
    """
    gate_fn = _extract_services_phase_function(
        "sidar_postgres_volume_reset_allowed_for_env",
        "\nmaybe_reset_postgres_volume_after_password_hardening() {",
    )
    env_utils = Path("scripts/install_modules/utils/env_utils.sh").read_text(encoding="utf-8")

    harness = tmp_path / "gate_probe.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -uo pipefail\n"
        'warn() { printf "WARN\\n" >&2; }\n'
        + env_utils
        + gate_fn
        + textwrap.dedent(
            """
            probe() {
                local label="$1"
                local env_file="$2"
                if sidar_postgres_volume_reset_allowed_for_env "$env_file"; then
                    echo "${label}=allowed"
                else
                    echo "${label}=rejected"
                fi
            }

            probe no_env_file "$1/nonexistent.env"

            printf 'SOME_OTHER_VAR=x\\n' > "$1/.env"
            probe sidar_env_missing_key "$1/.env"

            printf 'SIDAR_ENV=""\\n' > "$1/.env"
            probe sidar_env_empty_quoted "$1/.env"

            printf 'SIDAR_ENV=development\\n' > "$1/.env"
            probe development "$1/.env"

            printf 'SIDAR_ENV=production\\n' > "$1/.env"
            unset ALLOW_PRODUCTION_DB_VOLUME_RESET
            probe production_no_bypass "$1/.env"

            export ALLOW_PRODUCTION_DB_VOLUME_RESET=1
            probe production_with_bypass "$1/.env"
            unset ALLOW_PRODUCTION_DB_VOLUME_RESET

            printf 'SIDAR_ENV=garbage\\n' > "$1/.env"
            probe unrecognized "$1/.env"
            """
        ),
        encoding="utf-8",
    )
    harness.chmod(0o755)
    env_dir = tmp_path / "envs"
    env_dir.mkdir()

    result = subprocess.run(
        ["bash", str(harness), str(env_dir)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "no_env_file=rejected",
        "sidar_env_missing_key=rejected",
        "sidar_env_empty_quoted=rejected",
        "development=allowed",
        "production_no_bypass=rejected",
        "production_with_bypass=allowed",
        "unrecognized=rejected",
    ]


def test_both_postgres_volume_reset_callers_share_the_same_env_gate() -> None:
    """Regression test: both volume-reset callers must share the same env gate.

    Both the password-hardening reset path and the smoke-test-forced reset
    path must go through the same SIDAR_ENV safety gate, so the smoke-test
    path can't bypass a brake the other one enforced.
    """
    services_phase = Path("scripts/install_modules/phases/06_services.sh").read_text(
        encoding="utf-8"
    )

    assert "sidar_postgres_volume_reset_allowed_for_env() {" in services_phase
    assert 'sidar_postgres_volume_reset_allowed_for_env "$env_file" || return 0' in services_phase
    assert 'sidar_postgres_volume_reset_allowed_for_env "$SCRIPT_DIR/.env"' in services_phase
    assert services_phase.count("sidar_postgres_volume_reset_allowed_for_env") == 3


def test_create_directories_permission_steps_no_longer_swallow_errors_silently() -> None:
    """Regression test: create_directories() failures must surface a warning.

    chmod/chown/setfacl failures in create_directories() must surface a
    diagnostic warning instead of being fully swallowed via
    `2>/dev/null || true`, so permission issues can actually be diagnosed.
    """
    workspace_phase = Path("scripts/install_modules/phases/04_workspace.sh").read_text(
        encoding="utf-8"
    )

    create_directories_block = workspace_phase[
        workspace_phase.index("create_directories() {") : workspace_phase.index(
            "setup_vscode_workspace() {"
        )
    ]

    assert "2>/dev/null || true" not in create_directories_block
    assert "sidar_run_or_warn() {" in workspace_phase
    for expected_call in (
        'sidar_run_or_warn "chmod 755 \\"$SCRIPT_DIR/$dir\\"" chmod 755 "$SCRIPT_DIR/$dir"',
        'sidar_run_or_warn "chown 10001:10001 \\"$SCRIPT_DIR/$bind_dir\\"" chown 10001:10001'
        ' "$SCRIPT_DIR/$bind_dir"',
        'sidar_run_or_warn "chmod u+rwx,g+rx,o+rx \\"$SCRIPT_DIR/$bind_dir\\"" chmod'
        ' u+rwx,g+rx,o+rx "$SCRIPT_DIR/$bind_dir"',
        'sidar_run_or_warn "setfacl -m u:10001:rwx \\"$SCRIPT_DIR/$bind_dir\\"" setfacl -m'
        ' u:10001:rwx "$SCRIPT_DIR/$bind_dir"',
        'sidar_run_or_warn "chown 10001:10001 \\"$log_file\\"" chown 10001:10001 "$log_file"',
        'sidar_run_or_warn "setfacl -m u:10001:rw \\"$log_file\\"" setfacl -m u:10001:rw'
        ' "$log_file"',
        'sidar_run_or_warn "chmod u+rw \\"$log_file\\"" chmod u+rw "$log_file"',
    ):
        assert expected_call in create_directories_block, expected_call


def test_sidar_run_or_warn_surfaces_error_and_stays_non_fatal(tmp_path: Path) -> None:
    workspace_phase = Path("scripts/install_modules/phases/04_workspace.sh").read_text(
        encoding="utf-8"
    )
    helper_fn = workspace_phase[
        workspace_phase.index("sidar_run_or_warn() {") : workspace_phase.index(
            "sidar_precheck_workspace_ownership() {"
        )
    ]

    harness = tmp_path / "run_or_warn_probe.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
        'warn() { printf "WARN: %s\\n" "$*" >&2; }\n'
        + helper_fn
        + textwrap.dedent(
            """
            tmp_file="$(mktemp)"
            sidar_run_or_warn "chmod ok" chmod 644 "$tmp_file"
            echo "after-success"

            sidar_run_or_warn "chmod missing" chmod 644 "/nonexistent/path/xyz" || true
            echo "after-failure-with-or-true"
            """
        ),
        encoding="utf-8",
    )
    harness.chmod(0o755)

    result = subprocess.run(["bash", str(harness)], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "after-success" in result.stdout
    assert "after-failure-with-or-true" in result.stdout
    assert "chmod missing başarısız oldu:" in result.stderr
    assert "No such file or directory" in result.stderr


def _extract_ini_set_key_once() -> str:
    frontend_phase = Path("scripts/install_modules/phases/05_frontend.sh").read_text(
        encoding="utf-8"
    )
    start = frontend_phase.index("ini_set_key_once() {")
    end = frontend_phase.index('if [[ -n "$wslconfig_path" ]]; then', start)
    return frontend_phase[start:end]


def test_wslconfig_ini_helpers_consolidated_into_one_function() -> None:
    """Regression test: the .wslconfig awk helpers must be consolidated into one.

    The three near-duplicate awk-based .wslconfig helpers
    (_ensure_wsl2_key_once, _ensure_ini_key_once, _set_wsl2_key_value) must be
    consolidated into a single parameterized ini_set_key_once, with every call
    site migrated to it.
    """
    frontend_phase = Path("scripts/install_modules/phases/05_frontend.sh").read_text(
        encoding="utf-8"
    )

    assert "_ensure_wsl2_key_once" not in frontend_phase
    assert "_ensure_ini_key_once" not in frontend_phase
    assert "_set_wsl2_key_value" not in frontend_phase
    assert "ini_set_key_once() {" in frontend_phase
    assert frontend_phase.count("ini_set_key_once ") == 7


def test_ini_set_key_once_ensure_mode_preserves_existing_value(tmp_path: Path) -> None:
    harness = tmp_path / "ini_probe.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -uo pipefail\n" + _extract_ini_set_key_once(),
        encoding="utf-8",
    )
    harness.chmod(0o755)
    cfg = tmp_path / ".wslconfig"

    cfg.write_text("[wsl2]\nmemory=16GB\nmemory=99GB\nswap=4GB\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", f'source {harness}; ini_set_key_once "{cfg}" wsl2 memory 32GB'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    content = cfg.read_text(encoding="utf-8")
    assert content.count("memory=") == 1
    assert "memory=16GB" in content

    cfg.write_text("[wsl2]\nswap=4GB\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", f'source {harness}; ini_set_key_once "{cfg}" wsl2 memory 16GB'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "memory=16GB" in cfg.read_text(encoding="utf-8")


def test_ini_set_key_once_force_mode_overwrites_and_dedups(tmp_path: Path) -> None:
    harness = tmp_path / "ini_probe.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -uo pipefail\n" + _extract_ini_set_key_once(),
        encoding="utf-8",
    )
    harness.chmod(0o755)
    cfg = tmp_path / ".wslconfig"

    cfg.write_text("[wsl2]\nmemory=16GB\nmemory=99GB\nswap=4GB\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", f'source {harness}; ini_set_key_once "{cfg}" wsl2 memory 32GB force'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    content = cfg.read_text(encoding="utf-8")
    assert content.count("memory=") == 1
    assert "memory=32GB" in content

    result = subprocess.run(
        ["bash", "-c", f'source {harness}; ini_set_key_once "{cfg}" wsl2 memory 32GB force'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr


def test_ini_set_key_once_creates_missing_section(tmp_path: Path) -> None:
    harness = tmp_path / "ini_probe.sh"
    harness.write_text(
        "#!/usr/bin/env bash\nset -uo pipefail\n" + _extract_ini_set_key_once(),
        encoding="utf-8",
    )
    harness.chmod(0o755)
    cfg = tmp_path / ".wslconfig"
    cfg.write_text("[wsl2]\nmemory=16GB\n", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source {harness}; ini_set_key_once "{cfg}" experimental sparseVhd true',
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    content = cfg.read_text(encoding="utf-8")
    assert "[experimental]" in content
    assert "sparseVhd=true" in content


def test_install_sidar_download_verified_script_fails_after_http_200_when_checksum_missing(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl_log = tmp_path / "curl.log"
    downloaded_body = "#!/usr/bin/env bash\necho downloaded-ok\n"
    curl_script = fake_bin / "curl"
    curl_script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf '%s\\n' \"$*\" >> {curl_log!s}\n"
        "out=''\n"
        "while [[ $# -gt 0 ]]; do\n"
        '  if [[ "$1" == \'-o\' ]]; then shift; out="$1"; fi\n'
        "  shift || true\n"
        "done\n"
        '[[ -n "$out" ]]\n'
        f"cat > \"$out\" <<'REMOTE_SCRIPT'\n{downloaded_body}REMOTE_SCRIPT\n"
        "exit 0\n",
        encoding="utf-8",
    )
    curl_script.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            export SIDAR_INSTALL_TEST_MODE=1
            set --
            source ./install_sidar.sh
            OFFLINE_MODE=false
            NO_INTERACTION=true
            unset ALLOW_UNVERIFIED_REMOTE_SCRIPTS
            download_verified_script 'https://example.invalid/install.sh' '' 'uv_install'
            """,
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        text=True,
    )

    assert result.returncode == 1
    assert curl_log.exists(), "HTTP 200 mock curl path should be exercised before checksum gate"
    assert "https://example.invalid/install.sh" in curl_log.read_text(encoding="utf-8")
    assert "UV_INSTALL_SHA256" in result.stderr
    assert "./install_sidar.sh" in result.stderr
    assert "<hash>" in result.stderr
    assert "no-retry;manual-fix-required" in result.stderr
    assert "uv_install indirilemedi" not in result.stderr


def test_install_sidar_remote_script_checksum_missing_is_classified_deterministic() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            source ./scripts/install_modules/utils/install_remediation.sh
            ollama_reason='missing OLLAMA_INSTALL_SHA256'
            uv_reason='missing UV_INSTALL_SHA256'
            sidar_retry_budget_for_failure 03_runtime 'fail' "$ollama_reason"
            sidar_retry_budget_for_failure 04_workspace 'fail' "$uv_reason"
            if sidar_is_deterministic_failure_signal 'fail' "$ollama_reason"; then
                echo deterministic
            else
                echo transient
            fi
            if sidar_is_deterministic_failure_signal 'fail' "$uv_reason"; then
                echo deterministic
            else
                echo transient
            fi
            if sidar_is_remote_script_checksum_missing 'fail' "$ollama_reason"; then
                echo missing
            else
                echo present
            fi
            sidar_detect_missing_checksum_var 'fail' "$ollama_reason"
            sidar_detect_missing_checksum_var 'fail' "$uv_reason"
            """,
        ],
        check=True,
        capture_output=True,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        text=True,
    )

    assert result.stdout.splitlines() == [
        "1",
        "1",
        "deterministic",
        "deterministic",
        "missing",
        "OLLAMA_INSTALL_SHA256",
        "UV_INSTALL_SHA256",
    ]


def test_install_sidar_smoke_gate_version_failure_is_classified_deterministic(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            info() { printf '%s\n' "$*" >&2; }
            warn() { printf '%s\n' "$*" >&2; }
            SCRIPT_DIR="$1"
            source ./scripts/install_modules/utils/install_remediation.sh
            reason='Servis öncesi installer smoke gate başarısız: INSTALL_SIDAR_VERSION=<boş>'\
' beklenen pyproject.toml sürümüyle (5.2.0) eşleşmiyor.'
            sidar_retry_budget_for_failure 06_services \
              'run_pre_service_installer_smoke_gate' "$reason"
            if sidar_is_deterministic_failure_signal 'run_pre_service_installer_smoke_gate' \
              "$reason"; then
                echo deterministic
            else
                echo transient
            fi
            if sidar_phase_remediation_strategy 06_services \
              'run_pre_service_installer_smoke_gate' "$reason"; then
                echo retry-scheduled
            else
                echo no-retry
            fi
            sidar_emit_remediation_guidance 06_services \
              'run_pre_service_installer_smoke_gate' "$reason"
            report="$(find "$SCRIPT_DIR/artifacts/install/remediation" -type f \
              -name '*_06_services.log' | sort | tail -n 1)"
            cat "$report"
            """,
            "bash",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        text=True,
    )

    assert result.stdout.splitlines()[:3] == ["1", "deterministic", "no-retry"]
    assert "installer-smoke-gate-failure" in result.stdout
    assert "no-retry;manual-fix-required" in result.stdout
    assert "NEXT STEP" in result.stderr
    assert "aynı imza retry ile düzelmez" in result.stderr


def test_install_sidar_runtime_phase_skips_retry_when_remote_script_checksum_missing(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            info() { printf '%s\n' "$*" >&2; }
            warn() { printf '%s\n' "$*" >&2; }
            SCRIPT_DIR="$1"
            source ./scripts/install_modules/utils/install_remediation.sh
            ollama_reason='missing OLLAMA_INSTALL_SHA256'
            if sidar_phase_remediation_strategy 03_runtime 'fail' "$ollama_reason"; then
                echo retry-scheduled
                exit 1
            else
                echo no-retry
            fi
            report="$(find "$SCRIPT_DIR/artifacts/install/remediation" -type f \
              -name '*_03_runtime.log' | sort | tail -n 1)"
            cat "$report"
            """,
            "bash",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        text=True,
    )

    assert "no-retry" in result.stdout
    assert "reason=remote-script-checksum-missing" in result.stdout
    assert "action=no-retry;manual-fix-required" in result.stdout
    assert "missing-var=OLLAMA_INSTALL_SHA256" in result.stdout


def test_install_sidar_remote_script_checksum_guidance_covers_runtime_phase() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            info() { printf '%s\n' "$*" >&2; }
            warn() { printf '[warn] %s\n' "$*" >&2; }
            source ./scripts/install_modules/utils/install_remediation.sh
            ollama_reason='missing OLLAMA_INSTALL_SHA256'
            uv_reason='missing UV_INSTALL_SHA256'
            if sidar_emit_remediation_guidance 03_runtime 'fail' "$ollama_reason"; then
                echo ollama-guidance-emitted
            else
                echo ollama-guidance-skipped
            fi
            if sidar_emit_remediation_guidance 04_workspace 'fail' "$uv_reason"; then
                echo uv-guidance-emitted
            else
                echo uv-guidance-skipped
            fi
            """,
        ],
        check=True,
        capture_output=True,
        env={"SIDAR_INSTALL_TEST_MODE": "1", **os.environ},
        text=True,
    )

    assert "ollama-guidance-emitted" in result.stdout
    assert "uv-guidance-emitted" in result.stdout
    combined = result.stdout + result.stderr
    assert "OLLAMA_INSTALL_SHA256" in combined
    assert "UV_INSTALL_SHA256" in combined
    assert "https://ollama.com/install.sh" in combined
    assert "https://astral.sh/uv/install.sh" in combined
    assert "<hash>" in combined
    assert "./install_sidar.sh" in combined
    assert "TOFU" in combined or "tofu" in combined.lower()
    assert "ALLOW_UNVERIFIED_REMOTE_SCRIPTS" in combined

    remediation_util = Path("scripts/install_modules/utils/install_remediation.sh").read_text(
        encoding="utf-8"
    )
    assert "remote_script_checksum_hint" in remediation_util
    assert r'less "\$tmp"' not in remediation_util


def test_install_sidar_remote_script_checksum_hint_warns_about_deterministic_wall() -> None:
    remote_script_util = Path("scripts/install_modules/utils/remote_script.sh").read_text(
        encoding="utf-8"
    )
    assert "checksum_var" in remote_script_util
    assert "<hash>" in remote_script_util
    assert "./install_sidar.sh" in remote_script_util
    assert "no-retry;manual-fix-required" in remote_script_util
    assert "retry" in remote_script_util.lower()


def test_install_sidar_uses_single_source_project_version() -> None:
    script = installer_contract_sources()
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    project_version = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in pyproject.splitlines()
        if line.startswith("version =")
    )

    assert "resolve_install_sidar_version()" in script
    assert "sidar_version import resolve_version" in script
    assert "version[[:space:]]*=" in script
    assert "INSTALL_SIDAR_VERSION" in script
    assert "Kurulum Başlıyor (v5.2.3)" not in script
    assert "# Sürüm : 5.2.3" not in script
    assert f"v{project_version}" not in script


def test_install_sidar_runtime_reexec_guard_has_smoke_coverage() -> None:
    script = installer_contract_sources()
    smoke_tests = Path("tests/smoke/test_install_verification.py").read_text(encoding="utf-8")

    assert "verify_reexec_installer_or_fail()" in script
    assert (
        'verify_reexec_installer_or_fail "$HOME/Sidar/install_sidar.sh" "Mevcut $HOME/Sidar '
        're-exec"' in script
    )
    assert 'verify_reexec_installer_or_fail "$next_script" "Bootstrap clone re-exec"' in script
    assert "SIDAR_INSTALL_ALLOW_STALE_REEXEC" in script
    assert "test_install_sidar_home_reexec_hash_drift_blocks_stale_installer" in smoke_tests
    assert "test_install_sidar_bootstrap_reexec_hash_drift_blocks_stale_installer" in smoke_tests
    assert "stale-installer-ran" in smoke_tests
    assert "re-exec install_sidar.sh SHA256 farklı" in smoke_tests


def test_install_sidar_runtime_mode_is_selected_once_before_service_launch() -> None:
    script = installer_contract_sources()
    launch_body = script[
        script.index("launch_docker_services() {") : script.index(
            "# ── Çalışma Modu Seçimi", script.index("launch_docker_services() {")
        )
    ]
    select_body = script[
        script.index("select_runtime_mode() {") : script.index(
            "# ── Kurulum Sonrası IDE", script.index("select_runtime_mode() {")
        )
    ]

    assert "select_runtime_mode_early" not in script
    assert "select_runtime_mode" in Path("scripts/install_modules/phases/03_runtime.sh").read_text(
        encoding="utf-8"
    )
    assert "Çalışma modu seçimi:" in select_body
    assert "Geliştirici modu" in select_body
    assert "Tam Docker modu" in select_body
    assert "Çalışma modu seçimi:" not in launch_body
    assert "Geliştirici modu" not in launch_body
    assert "Tam Docker modu" not in launch_body
    assert (
        'local runtime_mode="${APP_RUNTIME_MODE_SELECTED:-${APP_RUNTIME_MODE:-docker}}"'
        in launch_body
    )
    assert "tekrar menü göstermeden" in launch_body


def test_install_sidar_loads_remote_checksum_defaults_without_overriding_operator_env(
    tmp_path: Path,
) -> None:
    """Checksum defaults must be tested independently of the invoking shell state."""
    checksum_file = tmp_path / "remote_checksums.env"
    checksum_file.write_text(
        ': "${OLLAMA_INSTALL_SHA256:=file-ollama}"\n: "${UV_INSTALL_SHA256:=file-uv}"\n',
        encoding="utf-8",
    )
    clean_env = os.environ.copy()
    for checksum_var in (
        "OLLAMA_INSTALL_SHA256",
        "UV_INSTALL_SHA256",
        "VOLTA_INSTALL_SHA256",
        "NVM_INSTALL_SHA256",
    ):
        clean_env.pop(checksum_var, None)

    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
            set -Eeuo pipefail
            export SIDAR_INSTALL_TEST_MODE=1
            export SIDAR_REMOTE_CHECKSUMS_FILE={checksum_file!s}
            export OLLAMA_INSTALL_SHA256=operator-ollama
            set --
            source ./install_sidar.sh
            printf 'ollama=%s\n' "$OLLAMA_INSTALL_SHA256"
            printf 'uv=%s\n' "$UV_INSTALL_SHA256"
            """,
        ],
        check=False,
        capture_output=True,
        env=clean_env,
        text=True,
    )

    assert result.returncode == 0
    assert "ollama=operator-ollama" in result.stdout
    assert "uv=file-uv" in result.stdout
    assert "remote_checksums.env" in result.stderr


def test_install_sidar_remote_script_checksum_failure_guides_operator() -> None:
    script = installer_contract_sources()
    docs = Path("README.md").read_text(encoding="utf-8")
    modular_note = Path("docs/module-notes/install_sidar_modularization.md").read_text(
        encoding="utf-8"
    )

    remote_script_util = Path("scripts/install_modules/utils/remote_script.sh").read_text(
        encoding="utf-8"
    )
    ollama_phase = Path("scripts/install_modules/phases/03_runtime_ollama.sh").read_text(
        encoding="utf-8"
    )

    assert "remote_script_checksum_hint()" in remote_script_util
    assert "download_verified_script()" in remote_script_util
    assert "load_remote_script_checksums()" in script
    assert "scripts/install_modules/remote_checksums.env" in script
    assert "utils/remote_script.sh" in script
    assert "phases/03_runtime_ollama.sh" in script
    assert "_ollama_install_step" in script
    assert "download_verified_script" in ollama_phase
    assert "checksum_var" in remote_script_util
    assert "<hash>" in remote_script_util
    assert "./install_sidar.sh" in remote_script_util
    assert r'less "\$tmp"' in remote_script_util
    assert "sha256sum" in remote_script_util
    assert "ALLOW_UNVERIFIED_REMOTE_SCRIPTS" in remote_script_util
    assert "UV_INSTALL_SHA256" in docs
    assert "OLLAMA_INSTALL_SHA256" in docs
    assert "https://astral.sh/uv/install.sh" in docs
    assert "scripts/install_modules/remote_checksums.env" in docs
    assert "https://ollama.com/install.sh" in docs
    assert "UV_INSTALL_SHA256" in modular_note
    assert "OLLAMA_INSTALL_SHA256" in modular_note
    assert "scripts/install_modules/remote_checksums.env" in modular_note


def test_volta_and_nvm_installs_use_soft_verified_download_not_raw_pipe_to_shell() -> None:
    """Regression test: Volta/NVM installs must not use an unverified curl|bash pipe.

    `curl ... | bash` pipe (supply-chain risk); they must go through the
    checksum-verified download flow, same as Ollama/uv, but via the
    non-fatal `download_verified_script_soft` variant so the existing
    Volta -> NVM -> apt NodeSource fallback chain still degrades gracefully
    instead of aborting the whole installer on a missing/rejected checksum.
    """
    system_phase = Path("scripts/install_modules/phases/03_system.sh").read_text(encoding="utf-8")
    remote_script_util = Path("scripts/install_modules/utils/remote_script.sh").read_text(
        encoding="utf-8"
    )

    assert "get.volta.sh | bash" not in system_phase
    assert "nvm-sh/nvm/v0.40.3/install.sh | bash" not in system_phase
    assert '"https://get.volta.sh"' in system_phase
    assert '"https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh"' in system_phase
    assert '"${VOLTA_INSTALL_SHA256:-}"' in system_phase
    assert '"${NVM_INSTALL_SHA256:-}"' in system_phase
    assert system_phase.count("download_verified_script_soft") == 2
    assert "download_verified_script_soft()" in remote_script_util


def test_node_install_fallbacks_report_failures_and_validate_apt_major() -> None:
    """Every Node fallback must explain degradation and enforce the .nvmrc major check."""
    system_phase = Path("scripts/install_modules/phases/03_system.sh").read_text(encoding="utf-8")

    assert "Volta node@${node_target_major} komutu başarısız oldu" in system_phase
    assert "Volta çalıştırılabilir dosyası bulunamadı" in system_phase
    assert "NVM install/alias default ${node_target_major} komutu başarısız oldu" in system_phase
    assert "NVM başlangıç dosyası bulunamadı" in system_phase
    assert "NodeSource apt deposu hazırlandı ancak apt update başarısız oldu" in system_phase
    assert "NodeSource apt deposu hazırlandı ancak nodejs paketi kurulamadı" in system_phase
    assert "ek Debian node-* bağımlılıklarını kurabilir" in system_phase
    assert (
        'warn_if_node_major_mismatch "$node_bin" "$node_target_major" "NodeSource"' in system_phase
    )
    assert (
        'warn_if_node_major_mismatch "$node_bin" "$node_target_major" '
        '"varsayılan apt fallback"' in system_phase
    )


def test_download_verified_script_soft_warns_and_returns_instead_of_exiting(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl_log = tmp_path / "curl.log"
    downloaded_body = "#!/usr/bin/env bash\necho downloaded-ok\n"
    curl_script = fake_bin / "curl"
    curl_script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf '%s\\n' \"$*\" >> {curl_log!s}\n"
        "out=''\n"
        "while [[ $# -gt 0 ]]; do\n"
        '  if [[ "$1" == \'-o\' ]]; then shift; out="$1"; fi\n'
        "  shift || true\n"
        "done\n"
        '[[ -n "$out" ]]\n'
        f"cat > \"$out\" <<'REMOTE_SCRIPT'\n{downloaded_body}REMOTE_SCRIPT\n"
        "exit 0\n",
        encoding="utf-8",
    )
    curl_script.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            export SIDAR_INSTALL_TEST_MODE=1
            set --
            source ./install_sidar.sh
            OFFLINE_MODE=false
            NO_INTERACTION=true
            unset ALLOW_UNVERIFIED_REMOTE_SCRIPTS
            if download_verified_script_soft 'https://example.invalid/install.sh' '' \
              'probe_install'; then
                echo "unexpected-success"
            else
                echo "soft-failure-rc=$?"
            fi
            echo "script-still-running"
            """,
        ],
        check=False,
        capture_output=True,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert curl_log.exists()
    assert "soft-failure-rc=1" in result.stdout
    assert "script-still-running" in result.stdout
    assert "PROBE_INSTALL_SHA256" in result.stderr


def test_remote_checksums_env_pins_volta_and_nvm_defaults() -> None:
    checksums = Path("scripts/install_modules/remote_checksums.env").read_text(encoding="utf-8")

    assert ': "${VOLTA_INSTALL_SHA256:=}"' in checksums
    assert ': "${NVM_INSTALL_SHA256:=}"' in checksums


def test_install_sidar_uv_steps_have_explicit_names_and_order() -> None:
    script = installer_contract_sources()
    runtime_phase = Path("scripts/install_modules/phases/03_runtime.sh").read_text(encoding="utf-8")
    workspace_phase = Path("scripts/install_modules/phases/04_workspace.sh").read_text(
        encoding="utf-8"
    )
    sync_deps_start = script.index("run_sync_deps_phase()")
    sync_deps_body = script[
        sync_deps_start : script.index("run_provision_models_phase()", sync_deps_start)
    ]

    assert "setup_uv" not in script
    assert "setup_python_env" not in script
    assert "install_uv_cli()" in script
    assert "create_uv_venv()" in script
    assert script.index("install_uv_cli()") < script.index("create_uv_venv()")
    assert "install_uv_cli" not in runtime_phase
    assert workspace_phase.index("install_uv_cli") < workspace_phase.index("create_uv_venv")
    assert workspace_phase.index("create_uv_venv") < workspace_phase.index("install_python_deps")
    assert sync_deps_body.index("install_uv_cli") < sync_deps_body.index("create_uv_venv")


def test_install_sidar_repo_url_is_env_overrideable_for_forks() -> None:
    script = installer_contract_sources()

    assert (
        'REPO_URL="${SIDAR_REPO_URL:-${REPO_URL:-https://github.com/niluferbagevi-gif/Sidar}}"'
        in script
    )
    assert 'REPO_URL="https://github.com/niluferbagevi-gif/Sidar"' not in script
    assert "SIDAR_REPO_URL=https://..." in script
    assert script.index("SIDAR_REPO_URL") < script.index('git clone "$REPO_URL"')


def test_install_sidar_uses_cross_platform_sed_inplace_wrapper() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    contract = installer_contract_sources()
    wrapper_start = script.index("sed_inplace() {")
    wrapper_end = script.index("\n}\n\n# BEGIN_BUNDLE_MODULES", wrapper_start) + len("\n}\n")
    wrapper_body = script[wrapper_start:wrapper_end]
    script_without_wrapper = script[:wrapper_start] + script[wrapper_end:]

    assert "Darwin) sed -i ''" in wrapper_body
    assert '*) sed -i "$expression" "$@"' in wrapper_body
    assert "sed -i " not in script_without_wrapper
    assert "sed_inplace 's/^ENABLE_MULTIMODAL=" in contract
    assert 'sed_inplace "s|^DATABASE_URL=.*|DATABASE_URL=' in contract


def test_install_sidar_centralizes_env_value_reads() -> None:
    script = installer_contract_sources()
    database_url_utils = Path("scripts/install_modules/utils/database_url.sh").read_text(
        encoding="utf-8"
    )

    assert "read_env_value_from_file()" in script
    assert 'current_backend=$(read_env_value_from_file "RAG_VECTOR_BACKEND" "$env_file")' in script
    assert 'openai_key=$(read_env_value_from_file "OPENAI_API_KEY" "$env_file"' in script
    assert "resolve_runtime_database_url_from_file()" in database_url_utils
    assert 'db_url="$(read_env_value_from_file "DATABASE_URL" "$env_file"' in database_url_utils
    assert 'compose_profiles=$(read_env_value_from_file "COMPOSE_PROFILES" "$env_file"' in script
    assert "cut -d= -f2-" not in script
    assert 'grep -E "^${key}="' not in script


def test_install_sidar_prompt_timeout_is_centralized() -> None:
    script = installer_contract_sources()

    assert 'SIDAR_PROMPT_TIMEOUT="${SIDAR_PROMPT_TIMEOUT:-180}"' in script
    assert "${2:-$SIDAR_PROMPT_TIMEOUT}" in script
    assert 'read -r -t "$SIDAR_PROMPT_TIMEOUT"' in script
    assert "SIDAR_PROMPT_TIMEOUT=180" in script
    assert "read -r -t 180" not in script
    assert "180 saniye içinde" not in script
    assert "${2:-180}" not in script


def test_install_sidar_flushes_typeahead_before_interactive_reads() -> None:
    script = installer_contract_sources()
    helpers = Path("scripts/install_modules/install_helpers.sh").read_text(encoding="utf-8")

    assert "clear_stdin_buffer()" in helpers
    assert "[[ -t 0 ]] || return 0" in helpers
    assert "read -r -t 0.01 _trash" in helpers
    assert "if ! declare -F clear_stdin_buffer" in script

    default_yes = script[
        script.index("prompt_yes_no_with_timeout_default_yes()") : script.index(
            "prompt_yes_no_with_timeout_default_no()"
        )
    ]
    default_no = script[
        script.index("prompt_yes_no_with_timeout_default_no()") : script.index(
            "cleanup_temp_install_modules_if_needed()"
        )
    ]
    assert 'clear_stdin_buffer\n    if read -r -t "$timeout_seconds"' in default_yes
    assert 'clear_stdin_buffer\n    if read -r -t "$timeout_seconds"' in default_no

    for prompt_marker in (
        "Entegrasyonu tamamladıktan sonra devam etmek için [ENTER]",
        "Seçiminiz (1 veya 2, varsayılan=1)",
        "Seçim [1/2, varsayılan=1]",
    ):
        read_pos = script.index(prompt_marker)
        window = script[max(0, read_pos - 120) : read_pos]
        assert "clear_stdin_buffer" in window

    secret_input_pos = script.index("IFS= read -rs input || true")
    assert "clear_stdin_buffer" in script[secret_input_pos - 120 : secret_input_pos]


def test_install_sidar_selects_pytorch_cuda_wheel_dynamically() -> None:
    script = installer_contract_sources()
    selector_start = script.index("select_pytorch_cuda_wheel_tag()")
    selector_body = script[
        selector_start : script.index("sync_pytorch_cuda_wheels()", selector_start)
    ]
    verify_body = script[
        script.index("verify_torch_cuda()") : script.index(
            "# ── 14.", script.index("verify_torch_cuda()")
        )
    ]

    assert "PyTorch cu124 fallback" not in script
    assert "--query-gpu=compute_cap" in script
    assert "PYTORCH_CUDA_WHEEL_TAG" in selector_body
    assert "compute_major >= 12" in selector_body
    assert "Blackwell" in selector_body
    assert "cu128" in selector_body
    assert "cu126" in selector_body
    assert "cu124" in selector_body
    assert "PYTORCH_CUDA_INDEX_URL" in script
    assert 'sync_pytorch_cuda_wheels "$(select_pytorch_cuda_wheel_tag)"' in verify_body
    sync_body = script[
        script.index("sync_pytorch_cuda_wheels()") : script.index("verify_torch_cuda()")
    ]
    assert "--reinstall-package torch" in sync_body
    assert "--reinstall-package torchvision" in sync_body
    assert "--reinstall-package torchaudio" not in sync_body
    assert "--extra dev-gpu" in sync_body
    assert "--extra gpu-runtime --no-dev" in sync_body
    assert "sync_args+=(--all-extras)" in sync_body
    assert "uv pip" not in script
    assert "uv tool install" not in script
    assert "python -m venv" not in script
    assert "python3 -m venv" not in script
    assert "virtualenv" not in script


def test_run_tests_builds_missing_docker_test_image_only_with_explicit_opt_in() -> None:
    script = _script()
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    preflight = script[
        script.index("prepare_docker_test_image()") : script.index("run_bats_shell_tests()")
    ]

    assert 'AUTO_BUILD_DOCKER_TEST_IMAGE="${AUTO_BUILD_DOCKER_TEST_IMAGE:-0}"' in script
    assert 'AUTO_BUILD_DOCKER_TEST_IMAGE: "1"' in ci
    assert 'DOCKER_TEST_IMAGE: "sidar:latest"' in ci
    assert 'DOCKER_TEST_IMAGE_BUILD_CONTEXT: "."' in ci
    assert "image: ${SIDAR_DOCKER_IMAGE:-sidar:latest}" in compose
    assert "build:" in compose and "context: ." in compose
    assert 'if [ "${AUTO_BUILD_DOCKER_TEST_IMAGE}" != "1" ]; then' in preflight
    assert 'local test_image="${DOCKER_TEST_IMAGE:-sidar:latest}"' in preflight
    assert 'docker image inspect "${test_image}"' in preflight
    assert 'docker build -t "${test_image}" "${build_context}"' in preflight
    assert (
        "ensure_uv_available && prepare_docker_test_image && ensure_runtime_dependencies" in script
    )


def test_run_tests_defaults_bats_to_required_in_ci_and_auto_detects_locally() -> None:
    script = _script()
    profile_block = script[
        script.index('if [ "${TEST_PROFILE}" = "ci" ]; then') : script.index(
            "PERFORMANCE_TEST_DIR="
        )
    ]

    assert profile_block.count('RUN_BATS_TESTS="${RUN_BATS_TESTS:-1}"') == 1
    assert profile_block.count('RUN_BATS_TESTS="${RUN_BATS_TESTS:-auto}"') == 1
    assert "BATS PATH üzerinde bulundu; yerel shell testleri otomatik etkinleştirildi" in script
    assert "Yerel profilde BATS bulunamadı; shell testleri varsayılan olarak atlanacak" in script
    assert "AUTO_INSTALL_CI_SYSTEM_DEPS=1 bash run_tests.sh" in script


def test_run_tests_offers_local_tty_bats_install_prompt_without_blocking_noninteractive_runs() -> (
    None
):
    script = _script()
    prompt_block = script[
        script.index("install_local_bats_dependencies()") : script.index(
            "# 0) Önceki test artefaktlarını temizle"
        )
    ]

    assert "configure_local_bats_shell_tests()" in prompt_block
    assert '[ "${TEST_PROFILE}" != "local" ]' in prompt_block
    assert '[ "${RUN_BATS_TESTS}" != "auto" ]' in prompt_block
    assert "if command -v bats >/dev/null 2>&1; then" in prompt_block
    assert "RUN_BATS_TESTS=1" in prompt_block
    assert (
        "BATS PATH üzerinde bulundu; yerel shell testleri otomatik etkinleştirildi" in prompt_block
    )
    assert '[ "${AUTO_INSTALL_CI_SYSTEM_DEPS}" = "1" ]' in prompt_block
    assert '[ "${SIDAR_PROMPT_LOCAL_BATS_INSTALL:-1}" != "1" ]' in prompt_block
    assert "[ ! -t 0 ] || [ ! -t 1 ] || [ ! -r /dev/tty ]" in prompt_block
    assert "IFS= read -r -n 1 local_reply < /dev/tty || true" in prompt_block
    assert "y|Y|e|E) install_local_bats_dependencies || true ;;" in prompt_block
    assert "RUN_BATS_TESTS=1" in prompt_block
    assert "Etkileşimli terminal bulunamadı; BATS kurulum prompt'u gösterilmedi" in prompt_block
    assert prompt_block.index("configure_local_bats_shell_tests") < prompt_block.index(
        "ℹ️ Test profili:"
    )


def test_run_tests_local_bats_auto_install_opt_in_is_effective_before_optional_skip() -> None:
    script = _script()
    prompt_block = script[
        script.index("configure_local_bats_shell_tests()") : script.index(
            "# 0) Önceki test artefaktlarını temizle"
        )
    ]

    assert 'if [ "${AUTO_INSTALL_CI_SYSTEM_DEPS}" = "1" ]; then' in prompt_block
    assert "install_local_bats_dependencies || true" in prompt_block
    assert prompt_block.index(
        'if [ "${AUTO_INSTALL_CI_SYSTEM_DEPS}" = "1" ]; then'
    ) < prompt_block.index("if [ ! -t 0 ] || [ ! -t 1 ] || [ ! -r /dev/tty ]; then")


def test_run_tests_reports_backend_failure_reason_when_ratchet_is_skipped() -> None:
    script = _script()
    ratchet_block = script[
        script.index("update_progressive_coverage_gate()") : script.index(
            "# 1) Backend kalite akışı"
        )
    ]

    assert 'record_backend_failure "pytest_failed"' in script
    assert 'record_backend_failure "bats_failed"' in script
    assert 'record_backend_failure "bats_missing"' in script
    assert 'record_backend_failure "security_failed"' in script
    assert 'record_backend_failure "ratchet_failed"' in script
    assert "Backend kalite akışı başarısız olduğu için coverage ratchet atlandı" in ratchet_block
    assert (
        "Test fazlarından biri başarısız olduğu için final coverage quality gate atlandı" in script
    )
    assert "$(format_backend_failure_reasons)" in ratchet_block
    assert "Backend Hata Nedenleri: $(format_backend_failure_reasons)" in script
    assert (
        "Pytest/coverage kalite kapısı geçmediği için coverage ratchet atlandı" not in ratchet_block
    )


def test_run_tests_preserves_explicit_coverage_fail_under_after_ratchet() -> None:
    script = _script()
    ratchet_block = script[
        script.index("update_progressive_coverage_gate()") : script.index(
            "# 1) Backend kalite akışı"
        )
    ]

    assert 'if [ "${COVERAGE_FAIL_UNDER_SOURCE}" = "explicit-override" ]; then' in ratchet_block
    assert "Açık COVERAGE_FAIL_UNDER override korundu" in ratchet_block
    assert 'COVERAGE_FAIL_UNDER="${DEFAULT_COVERAGE_FAIL_UNDER}"' in ratchet_block
    assert ratchet_block.index("explicit-override") < ratchet_block.index(
        'COVERAGE_FAIL_UNDER="${DEFAULT_COVERAGE_FAIL_UNDER}"'
    )


def test_run_tests_prepares_ci_system_deps_before_full_uv_sync() -> None:
    runtime_deps_block = _extract_run_tests_function("ensure_runtime_dependencies")

    assert "bash scripts/install_ci_system_deps.sh" in runtime_deps_block
    assert "portaudio.h eksikliğiyle başarısız olabilir" in runtime_deps_block
    assert runtime_deps_block.index(
        "bash scripts/install_ci_system_deps.sh"
    ) < runtime_deps_block.index("uv sync --frozen --all-extras")


def test_run_tests_records_backend_failure_when_required_bats_is_missing() -> None:
    bats_block = _extract_run_tests_function("run_bats_shell_tests")

    assert 'if [ "${RUN_BATS_TESTS}" != "1" ]; then' in bats_block
    assert "❌ bats yok — shell testleri çalıştırılamadı" in bats_block
    assert "bash scripts/install_ci_system_deps.sh" in bats_block
    missing_bats_start = bats_block.index(
        "if ! command -v bats >/dev/null 2>&1; then",
        bats_block.index("try_auto_install_ci_system_deps || true"),
    )
    missing_bats_block = bats_block[
        missing_bats_start : bats_block.index('echo "🐚 BATS shell testleri çalıştırılıyor..."')
    ]
    assert 'record_backend_failure "bats_missing"' in missing_bats_block
    assert "BACKEND_EXIT_CODE=1" in missing_bats_block
    assert "return 1" in missing_bats_block


def test_run_tests_auto_installs_ci_system_deps_only_with_explicit_opt_in() -> None:
    script = _script()
    auto_install_block = script[
        script.index("try_auto_install_ci_system_deps()") : script.index("run_bats_shell_tests()")
    ]
    bats_block = _extract_run_tests_function("run_bats_shell_tests")

    assert 'AUTO_INSTALL_CI_SYSTEM_DEPS="${AUTO_INSTALL_CI_SYSTEM_DEPS:-0}"' in script
    assert 'if [ "${AUTO_INSTALL_CI_SYSTEM_DEPS}" != "1" ]; then' in auto_install_block
    assert "sudo -n true" not in auto_install_block
    assert "bash scripts/install_ci_system_deps.sh" in auto_install_block
    assert "try_auto_install_ci_system_deps || true" in bats_block
    assert "AUTO_INSTALL_CI_SYSTEM_DEPS=1 bash run_tests.sh" in bats_block


def test_run_tests_writes_bats_junit_report_to_configurable_artifact_dir() -> None:
    script = _script()
    bats_block = _extract_run_tests_function("run_bats_shell_tests")

    assert 'BATS_REPORT_DIR="${BATS_REPORT_DIR:-artifacts/bats}"' in script
    assert (
        'if [[ "${BATS_REPORT_DIR}" != artifacts/* || "${BATS_REPORT_DIR}" == *".."* ]]; then'
        in script
    )
    assert "BATS_REPORT_DIR yalnız artifacts/ altında güvenli bir göreli yol olabilir" in script
    assert (
        "rm -rf .pytest_cache .coverage .coverage.* coverage.xml htmlcov tests/pytest.log "
        "web_ui_react/coverage web_ui_react/playwright-report web_ui_react/test-results "
        '"${BATS_REPORT_DIR}"' in script
    )
    assert 'mkdir -p "${BATS_REPORT_DIR}"' in bats_block
    assert "env -u DATABASE_URL -u TEST_DATABASE_URL -u POSTGRES_PASSWORD" in bats_block
    assert 'bats --report-formatter junit --output "${BATS_REPORT_DIR}" tests/shell' in bats_block
    assert "${BATS_REPORT_DIR}/report.xml" in bats_block


def test_install_sidar_bats_helper_clears_runtime_database_env() -> None:
    bats_file = Path("tests/shell/install_sidar_functions.bats").read_text(encoding="utf-8")
    helper_block = bats_file[
        bats_file.index("run_installer_function()") : bats_file.index(
            '@test "normalize_bool maps accepted true/false values and rejects unknown input"'
        )
    ]

    assert "unset DATABASE_URL TEST_DATABASE_URL POSTGRES_PASSWORD" in helper_block
    assert helper_block.index("unset DATABASE_URL") < helper_block.index(
        "source ./install_sidar.sh"
    )


def test_ci_uploads_bats_junit_report_artifact() -> None:
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "name: Upload BATS JUnit Report" in ci_workflow
    assert "name: bats-junit-report" in ci_workflow
    assert "path: artifacts/bats/report.xml" in ci_workflow
    assert "if-no-files-found: warn" in ci_workflow


def test_ci_uploads_test_summary_coverage_and_benchmark_reports() -> None:
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    artifact_block = ci_workflow[
        ci_workflow.index(
            "- name: Upload test summary, coverage XML/JSON + Benchmark JSON artifacts"
        ) : ci_workflow.index("- name: Upload Frontend Coverage Report")
    ]

    assert "name: backend-quality-trend-artifacts" in artifact_block
    assert "artifacts/test-summary.json" in artifact_block
    assert "coverage.json" in artifact_block
    assert "coverage.xml" in artifact_block
    assert "artifacts/benchmark/benchmark.json" in artifact_block
    assert "artifacts/benchmark/history.json" in artifact_block
    assert ".benchmarks/" in artifact_block
    assert "if-no-files-found: warn" in artifact_block


def test_ci_postgres_credentials_are_documented_as_test_only() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")

    assert "Test-only CI service credentials" in ci
    assert "ephemeral postgres service" in ci
    assert "POSTGRES_PASSWORD=sidar" in notes
    assert "yalnız GitHub Actions'ın ephemeral test servisi içindir" in notes
    assert "Production `.env` örnekleri" in notes


def test_pip_audit_skips_only_local_editable_package_and_uses_dated_policy() -> None:
    script = _script()
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    policy = Path("security/pip-audit-ignores.tsv").read_text(encoding="utf-8")
    security_readme = Path("security/README.md").read_text(encoding="utf-8")

    assert "python scripts/pip_audit_ignore_args.py" in script
    assert "PIP_AUDIT_ARTIFACT_DIR:-artifacts/security" in script
    assert "pip-audit-report.raw.json" in script
    assert "pip-audit-failure.json" in script
    assert 'pip-audit --skip-editable --timeout "${pip_audit_timeout}"' in script
    assert '--format json --output "${pip_audit_raw_report}"' in script
    assert 'python scripts/pip_audit_failure_artifact.py "${pip_audit_raw_report}"' in script
    assert "python scripts/pip_audit_ignore_args.py" in ci_workflow
    assert "mkdir -p artifacts/security" in ci_workflow
    assert (
        "pip-audit --skip-editable --timeout 30 --format json --output "
        "artifacts/security/pip-audit-report.raw.json" in ci_workflow
    )
    assert (
        "python scripts/pip_audit_failure_artifact.py artifacts/security/pip-audit-report.raw.json "
        "artifacts/security/pip-audit-failure.json --timeout 30" in ci_workflow
    )
    assert "name: security-audit-artifacts" in ci_workflow
    assert "artifacts/security/" in ci_workflow
    assert "GHSA-rrmf-rvhw-rf47" in policy
    assert "CVE-2025-3000" in policy
    assert "2026-09-15" in policy
    assert "security policy data" in security_readme
    assert "not the runtime" in security_readme
    assert "web/security.py" in security_readme
    assert "managers/security.py" in security_readme
    assert "artifacts/security/" in security_readme


def test_pip_audit_distinguishes_network_failures_from_real_vulnerabilities() -> None:
    """The quality gate must classify network/tunnel pip-audit failures.

    A real vulnerability finding must still fail the gate, but a transient
    tunnel/PyPI fetch error should be surfaced as a separate ``network``
    category in the failure artifact and — when explicitly opted in via
    ``PIP_AUDIT_ALLOW_NETWORK_FAILURE=1`` — must not red-line the local quality
    gate. CI keeps the strict default.
    """
    script = _script()
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    # Stderr is captured per-attempt for forensics and classification.
    assert "pip-audit-stderr.log" in script
    assert '2> "${pip_audit_stderr_log}"' in script
    assert '--stderr-log "${pip_audit_stderr_log}"' in script

    # Classifier output drives the routing decision.
    assert 'pip_audit_failure_category="unknown"' in script
    assert '"failure_category"' in script
    assert "PIP_AUDIT_ALLOW_NETWORK_FAILURE" in script

    # CI mirror: stderr captured, classifier invoked, category surfaced.
    assert "pip-audit-stderr.log" in ci_workflow
    assert "--stderr-log" in ci_workflow
    assert "failure_category=" in ci_workflow


def test_coverage_gate_routes_local_ci_and_campaign_profiles() -> None:
    """Coverage thresholds must be selectable per operational profile.

    AGENTS.md §2.5.4 separates the daily local gate (`pyproject.toml`
    ratchet-managed %100 baseline), the CI pre-merge gate — which
    inherits that same ratcheted baseline unless explicitly overridden — and
    the %100 coverage campaign. The script must surface all
    three knobs so a developer can run a fast local pass without colliding
    with the campaign target, while the campaign opt-in still aims at %100.
    """
    script = _script()
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    agents_md = Path("AGENTS.md").read_text(encoding="utf-8")

    # Three profile-specific override envs are documented in the script.
    assert "COVERAGE_FAIL_UNDER_LOCAL" in script
    assert "COVERAGE_FAIL_UNDER_CI" in script
    assert "COVERAGE_FAIL_UNDER_CAMPAIGN" in script

    # Campaign profile opt-in is honored both via the local toggle and the
    # autonomous loop's operation profile label (kept in sync with AGENTS.md).
    assert "COVERAGE_CAMPAIGN" in script
    assert "AUTONOMOUS_LOOP_OPERATION_PROFILE" in script
    assert "coverage-campaign" in script

    # Backward compatibility: a direct COVERAGE_FAIL_UNDER still wins, and
    # the user-visible echo reports which profile picked the threshold.
    assert "COVERAGE_FAIL_UNDER_SOURCE" in script
    assert "explicit-override" in script

    # Every standard profile uses the measured 100% result as its default
    # ratchet ceiling, so a later 99.x result cannot pass behind a slack gate.
    assert 'COVERAGE_RATCHET_MAX_GATE="100"' in script
    tests_notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")
    coverage_agent_docs = Path("docs/COVERAGE_AGENT_KULLANIMI.md").read_text(encoding="utf-8")
    optimization_plan = Path("docs/TEST_OPTIMIZATION_PLAN.md").read_text(encoding="utf-8")
    strict_runbook = Path("docs/runbooks/coverage-strict-local-ratchet.md").read_text(
        encoding="utf-8"
    )
    assert "Coverage gate ratcheted: %99 -> %100 (measured=%100.00)" in tests_notes
    assert "local/CI ratchet cap `%100`" in coverage_agent_docs
    assert "regresyonu fail-closed yakalar" in optimization_plan
    assert "Varsayılan local/CI cap: `%100`" in strict_runbook

    # pyproject.toml commits the measured 100% result as the merge floor.
    assert pyproject["tool"]["coverage"]["report"]["fail_under"] == 100

    # CI no longer hardcodes a stricter override for the main test job; it
    # inherits the same ratcheted pyproject.toml baseline as the local profile.
    assert 'COVERAGE_FAIL_UNDER_CI: "95"' not in ci_workflow

    # AGENTS.md documents the three-profile model explicitly.
    assert "COVERAGE_FAIL_UNDER_LOCAL" in agents_md
    assert "COVERAGE_FAIL_UNDER_CI" in agents_md
    assert "COVERAGE_FAIL_UNDER_CAMPAIGN" in agents_md


def test_ci_enables_uv_dependency_cache_for_main_test_job() -> None:
    """Large wheels (pyarrow, etc.) must come from the uv cache on retries."""
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    # Find the first setup-uv block in the workflow (the main test job).
    setup_uv_marker = "uses: astral-sh/setup-uv@v4"
    first_idx = ci_workflow.find(setup_uv_marker)
    assert first_idx != -1
    block = ci_workflow[first_idx : first_idx + 400]

    assert "enable-cache: true" in block
    assert "cache-dependency-glob" in block
    assert "uv.lock" in block


def test_ci_uses_shared_system_dependency_installer_without_duplicate_apt_step() -> None:
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "sudo apt-get install -y portaudio19-dev shellcheck bats" not in ci_workflow
    assert "run: bash scripts/install_ci_system_deps.sh" in ci_workflow
    assert 'echo "=== bats ===" && bats --version' in ci_workflow


def test_ci_requires_restored_benchmark_baseline_and_nightly_gpu_uses_full_profile() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    seed_workflow = Path(".github/workflows/benchmark-baseline-seed.yml").read_text(
        encoding="utf-8"
    )
    nightly_gpu = Path(".github/workflows/nightly-gpu-performance.yml").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")
    gitignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "uses: actions/cache@v4" in ci
    assert "id: benchmark-baseline-cache" in ci
    assert "path: .benchmarks" in ci
    assert (
        "benchmark-baseline-${{ runner.os }}-py311-${{ hashFiles('uv.lock') }}-"
        "${{ github.ref_name }}-${{ github.run_id }}" in ci
    )
    assert "benchmark-baseline-${{ runner.os }}-py311-${{ github.ref_name }}-" not in ci
    assert "Report benchmark baseline availability" in ci
    assert "Resolve benchmark baseline gate mode" in ci
    assert "mkdir -p .benchmarks" in ci
    assert 'echo "BENCHMARK_BASELINE_AVAILABLE=1" >> "$GITHUB_ENV"' in ci
    assert 'echo "BENCHMARK_COMPARE_REQUIRED=1" >> "$GITHUB_ENV"' not in ci
    assert 'echo "BENCHMARK_COMPARE_REQUIRED=0" >> "$GITHUB_ENV"' not in ci
    assert "Base lint/smoke/unit/coverage/frontend gates will still run" in ci
    assert "Benchmark baseline missing" in ci
    assert "exit 1" in ci
    assert "benchmark-compare:" in ci
    assert "Production readiness aggregate" in ci
    assert "needs: [test, benchmark-compare, gpu-inference-policy-gate]" in ci
    assert "Run canonical production-readiness gate" in ci
    assert "make production-readiness 2>&1 | tee artifacts/test_run.log" in ci
    assert (
        "TEST_PROFILE=ci RUN_BENCHMARKS=0 RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all"
        not in ci
    )
    assert "GITHUB_STEP_SUMMARY" in ci
    assert "benchmark compare is fail-closed" in ci
    assert "BENCHMARK_BASELINE_FILE: ${{ steps.benchmark-baseline.outputs.compare_file }}" in ci
    assert '--benchmark-compare="${BENCHMARK_BASELINE_FILE}"' in ci
    assert "BENCHMARK_COMPARE_FAIL: mean:10%" in ci
    assert ".benchmarks/" in gitignore
    assert 'RUN_GPU_BENCHMARKS: "full"' in nightly_gpu
    assert ".benchmarks/` dizinini repoya commit etmek yerine GitHub Actions cache" in notes
    assert "BENCHMARK_COMPARE_FAIL=mean:10%" in notes
    assert "koşu seed moduna düşmez" in notes
    assert "name: Benchmark baseline seed" in seed_workflow
    assert "workflow_dispatch:" in seed_workflow
    assert 'BENCHMARK_COMPARE_REQUIRED: "0"' in seed_workflow
    assert 'BENCHMARK_ENFORCE_COMPARE: "0"' in seed_workflow
    assert "--benchmark-warmup-iterations=100000" in seed_workflow
    assert "baseline-seed-manifest.json" in seed_workflow
    assert "next_strict_command" in seed_workflow
    assert (
        "BENCHMARK_COMPARE_REQUIRED=1 BENCHMARK_ENFORCE_COMPARE=1 "
        "RUN_BENCHMARKS=required ./run_tests.sh" in seed_workflow
    )
    assert (
        "Rerun normal CI / production-readiness after this cache/artifact is saved."
        in seed_workflow
    )
    assert "actions/cache/save@v4" in seed_workflow
    assert "actions/upload-artifact@v4" in seed_workflow
    assert "baseline-seed-manifest.json" in ci
    assert "Baseline files:" in ci
    assert "retention-days: 90" in ci
    assert (
        "benchmark-baseline-${{ runner.os }}-py311-${{ hashFiles('uv.lock') }}-"
        "${{ github.ref_name }}-${{ github.run_id }}" in seed_workflow
    )
    assert "Benchmark baseline seed" in readme
    assert ".github/workflows/benchmark-baseline-seed.yml" in readme
    assert "--benchmark-warmup-iterations=100000" in readme
    assert "baseline-seed-manifest.json" in readme
    assert "Benchmark baseline seed" in notes
    assert "baseline-seed-manifest.json" in notes
    assert "sonraki sıkı kapı komutunu" in notes


def test_gpu_concurrent_benchmark_uses_smoke_and_full_profiles() -> None:
    gpu_benchmark = Path("tests/performance/test_gpu_benchmark.py").read_text(encoding="utf-8")
    notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")
    env_advanced = Path(".env.advanced.example").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert 'os.getenv("RUN_GPU_BENCHMARKS", "smoke")' in gpu_benchmark
    assert 'if _GPU_BENCHMARK_PROFILE not in {"smoke", "full"}' in gpu_benchmark
    assert '"GPU_BENCH_CONCURRENT_WARMUP_ROUNDS"' in gpu_benchmark
    assert '"GPU_BENCH_CONCURRENT_ROUNDS"' in gpu_benchmark
    assert "warmup_rounds=_CONCURRENT_WARMUP_ROUNDS" in gpu_benchmark
    assert '10 if _GPU_BENCHMARK_PROFILE == "smoke" else _BENCH_ROUNDS' in gpu_benchmark
    assert "min_value=10" in gpu_benchmark
    assert (
        "GPU_BENCH_CONCURRENT_ROUNDS — eşzamanlı test ölçüm turu (smoke: 10, full: 20)"
        in gpu_benchmark
    )
    assert "rounds=_CONCURRENT_BENCH_ROUNDS" in gpu_benchmark
    assert "GPU_BENCH_CONCURRENT_ROUNDS=10" in notes
    assert "RUN_GPU_BENCHMARKS=smoke" in env_test_example
    assert "RUN_GPU_BENCHMARKS=smoke" in env_advanced
    assert "`qwen2.5-coder:7b`" in readme
    assert "`PROCESSOR` sütununun `100% GPU`" in readme
    assert "sağlıklı offload sinyalidir" in readme


def test_run_tests_executes_playwright_smoke_in_ci_and_auto_detects_local_browser_cache() -> None:
    script = _script()
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'RUN_FRONTEND_E2E: "1"' in ci
    assert 'FRONTEND_E2E_ENFORCE_RESULT: "1"' in ci
    assert 'RUN_FRONTEND_E2E="${RUN_FRONTEND_E2E:-1}"' in script
    assert 'RUN_FRONTEND_E2E="${RUN_FRONTEND_E2E:-auto}"' in script
    assert 'RUN_FRONTEND_E2E_AUTO_INSTALL="${RUN_FRONTEND_E2E_AUTO_INSTALL:-1}"' in script
    assert (
        'FRONTEND_E2E_RETRY_ON_FAIL="${FRONTEND_E2E_RETRY_ON_FAIL:-${RETRY_ON_FAIL:-1}}"' in script
    )
    assert script.count('BENCHMARK_ENFORCE_RESULT="${BENCHMARK_ENFORCE_RESULT:-1}"') >= 2
    assert "ENFORCE_FRONTEND_E2E" in script
    assert (
        script.count(
            'FRONTEND_E2E_ENFORCE_RESULT="${FRONTEND_E2E_ENFORCE_RESULT:-${ENFORCE_FRONTEND_E2E:-1}}"'
        )
        >= 2
    )
    assert (
        'if [ "${RUN_FRONTEND_E2E}" = "1" ] '
        '&& [ "${FRONTEND_E2E_MODE_EXIT_CODE}" -eq 0 ]; then' in script
    )
    assert "Frontend Playwright ortam hazırlığı başarısız" in script
    assert 'if [ "${RUN_FRONTEND_E2E}" != "1" ]; then' in script
    assert "export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1" in script
    assert (
        'FRONTEND_PLAYWRIGHT_SENTINEL="${FRONTEND_PLAYWRIGHT_SENTINEL:-.playwright-installed}"'
        in script
    )
    assert (
        'FRONTEND_PLAYWRIGHT_PACKAGE_LOCK="${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK:-package-lock.json}"'
        in script
    )
    assert "frontend_playwright_package_lock_fingerprint()" in script
    assert "sha256sum" in script
    assert "shasum -a 256" in script
    assert "cksum" in script
    assert "frontend_playwright_sentinel_cache_ready()" in script
    assert "frontend_playwright_chromium_cache_ready()" in script
    assert "install_local_frontend_playwright_chromium_cache()" in script
    assert "resolve_local_frontend_e2e_mode()" in script
    assert 'if [ "${requested_frontend_e2e}" != "auto" ]' in script
    assert 'if [ "${requested_frontend_e2e}" = "1" ]; then' in script
    assert "FRONTEND_E2E_MODE_EXIT_CODE=$?" in script
    assert 'if [ "${FRONTEND_COVERAGE_EXIT_CODE}" -ne 0 ]; then' in script
    assert 'if [ "${RUN_FRONTEND_E2E_AUTO_INSTALL}" != "1" ]; then' in script
    assert 'const { chromium } = require("@playwright/test");' in script
    assert "const executablePath = chromium.executablePath();" in script
    assert "if (!fs.existsSync(executablePath)) process.exit(1);" in script
    assert (
        'printf \'%s\\n%s\\n\' "${executable_path}" "${lock_fingerprint}" > '
        '"${FRONTEND_PLAYWRIGHT_SENTINEL}" || true' in script
    )
    assert 'rm -f "${FRONTEND_PLAYWRIGHT_SENTINEL}"' in script
    assert "unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD" in script
    assert "npx --no-install playwright install chromium" in script
    assert "Domain forbidden|server returned code 403|Download failed" in script
    assert "~/.cache/ms-playwright" in script
    assert "PLAYWRIGHT_BROWSERS_PATH" in script
    assert "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH" in script
    assert "PLAYWRIGHT_DOWNLOAD_HOST / PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST" in script
    assert "make production-readiness" in script
    assert (
        'PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER="${PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER:-${SCRIPT_DIR:-$(pwd)}/scripts/install_modules/utils/playwright_ubuntu_override.sh}"'
        in script
    )
    assert 'is_playwright_ubuntu_override_recommended "${os_release_path}"' in script
    assert (
        'run_playwright_ubuntu_override_install "${os_release_path}" "${playwright_timeout_ms}"'
        in script
    )
    assert "RUN_FRONTEND_E2E=1" in script
    assert "RUN_FRONTEND_E2E=0" in script
    assert "npx playwright install chromium" in script
    assert script.index("export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1") < script.index("npm ci")
    assert "package-lock.json bulundu; local/CI paritesi için 'npm ci'" in script
    assert "package-lock.json bulunamadı; doğrulama için 'npm install' fallback" in script
    assert script.index('if [ -f "package-lock.json" ]; then') < script.index("run_checked npm ci")
    assert script.index("run_checked npm ci") < script.index("run_checked npm install")
    package_json = json.loads(Path("web_ui_react/package.json").read_text(encoding="utf-8"))
    assert package_json["scripts"]["deps:update"] == "npm install"
    frontend_gate_block = script[
        script.index("# 3) Frontend React testleri") : script.index(
            "# 4) Final Durum Değerlendirmesi"
        )
    ]
    assert (
        frontend_gate_block.index("resolve_local_frontend_e2e_mode")
        < frontend_gate_block.index("npm run audit:high")
        < frontend_gate_block.index("npm run lint")
        < frontend_gate_block.index("npm run typecheck")
        < frontend_gate_block.index("npm run test:coverage")
    )
    assert "FRONTEND_NPM_AUDIT_RAN=1" in script
    assert "FRONTEND_NPM_AUDIT_EXIT_CODE=$?" in script
    assert "Dependency audit (npm run audit:high)" in script
    assert "Typecheck (npm run typecheck)" in script
    assert r"| Dependency audit | \`npm run audit:high\` |" in script
    assert r"| Typecheck | \`npm run typecheck\` |" in script
    assert "RUN_FRONTEND_E2E=${RUN_FRONTEND_E2E}" in script
    assert "run_frontend_e2e_with_retry()" in script
    assert 'if [ "${FRONTEND_E2E_RETRY_ON_FAIL}" != "1" ]; then' in script
    assert 'FRONTEND_E2E_NPM_SCRIPT="${FRONTEND_E2E_NPM_SCRIPT:-test:e2e:smoke}"' in script
    assert 'npm run "${frontend_e2e_script}"' in script
    assert "print_frontend_quality_summary()" in script
    assert "Frontend kalite kapısı özeti" in script
    assert "Frontend coverage artefaktı" in script
    assert "GITHUB_STEP_SUMMARY" in script
    assert "FRONTEND_E2E_EXIT_CODE=$?" in script
    assert 'if [ "${BENCHMARK_ENFORCE_RESULT}" = "1" ]; then' in script
    assert 'if [ "${FRONTEND_E2E_ENFORCE_RESULT}" = "1" ]; then' in script
    assert "Restore Playwright browser cache" in ci
    assert "~/.cache/ms-playwright" in ci
    assert "playwright-${{ runner.os }}-${{ hashFiles('web_ui_react/package-lock.json') }}" in ci
    assert ci.index("Restore Playwright browser cache") < ci.index(
        "Install Playwright Chromium for frontend smoke tests"
    )
    assert "npx playwright install --with-deps chromium" in ci
    assert 'FRONTEND_E2E_NPM_SCRIPT: "test:e2e:smoke"' in ci
    assert "name: Upload Playwright frontend smoke report" in ci
    assert "web_ui_react/playwright-report/" in ci
    assert "web_ui_react/test-results/" in ci
    readme = Path("README.md").read_text(encoding="utf-8")
    testing_doc = Path("docs/TESTING.md").read_text(encoding="utf-8")
    assert "Playwright Chromium cache / CDN 403" in readme
    assert "Frontend Playwright CDN 403 / restricted network" in testing_doc
    assert (
        "cd web_ui_react\nnpx playwright install chromium\ncd ..\nmake production-readiness"
        in readme
    )
    assert "~/.cache/ms-playwright" in testing_doc
    assert "PLAYWRIGHT_BROWSERS_PATH" in testing_doc
    assert "PLAYWRIGHT_DOWNLOAD_HOST" in testing_doc
    assert "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST" in testing_doc
    assert "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium" in testing_doc
    assert "403 Domain forbidden" in readme
    package_json = Path("web_ui_react/package.json").read_text(encoding="utf-8")
    assert '"typecheck": "tsc --noEmit && npm run typecheck:inventory"' in package_json
    assert (
        '"typecheck:inventory": "node ../scripts/check_frontend_typescript_migration.js"'
        in package_json
    )
    assert '"test:e2e:smoke": "playwright test e2e/chat-websocket.spec.js"' in package_json
    playwright = Path("web_ui_react/playwright.config.js").read_text(encoding="utf-8")
    assert '["html", { outputFolder: "playwright-report", open: "never" }]' in playwright
    assert 'outputDir: "test-results"' in playwright
    assert 'process.env.PLAYWRIGHT_HOST_PLATFORM_OVERRIDE || "auto-detect"' in playwright
    assert "process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined" in playwright
    assert "launchOptions: chromiumExecutablePath" in playwright
    assert "executablePath: chromiumExecutablePath" in playwright
    assert "metadata: { playwrightHostPlatformOverride }" in playwright
    assert "timeout: 75_000" in playwright
    assert "expect: { timeout: 30_000 }" in playwright

    vite_server = Path("web_ui_react/e2e/support/testViteServer.js").read_text(encoding="utf-8")
    websocket_spec = Path("web_ui_react/e2e/chat-websocket.spec.js").read_text(encoding="utf-8")
    assert "const READY_TIMEOUT_MS = 60_000" in vite_server
    assert 'host: "127.0.0.1"' in vite_server
    assert 'probe.listen(0, "127.0.0.1", resolve)' in vite_server
    assert "port," in vite_server
    assert "strictPort: true" in vite_server
    assert "html.includes('id=\"root\"')" in vite_server
    assert "`${url}/src/main.jsx`" in vite_server
    assert "`${url}/src/App.jsx`" in vite_server
    assert "`${url}/src/components/StatusBar.jsx`" in vite_server
    assert "`${url}/src/lib/routerShim.jsx`" in vite_server
    assert 'test.describe.configure({ mode: "serial" })' in websocket_spec
    assert (
        "await page.waitForSelector('[data-testid=\"ws-status\"]', { timeout: 30_000 })"
        in websocket_spec
    )
    assert "test.beforeAll(async () =>" in websocket_spec
    assert "test.afterAll(async () =>" in websocket_spec
    assert "SIDAR_E2E_FRONTEND_PORT" not in playwright
    assert "SIDAR_E2E_BACKEND_PORT" not in playwright
    assert "fullyParallel: true" in playwright
    assert "retries: process.env.CI ? 2 : 1" in playwright
    assert "retries: 0" not in playwright
    assert "workers: 1" not in playwright
    assert "storageState: undefined" in playwright
    assert "webServer:" not in playwright

    vite = Path("web_ui_react/vite.config.js").read_text(encoding="utf-8")
    websocket_spec = Path("web_ui_react/e2e/chat-websocket.spec.js").read_text(encoding="utf-8")
    mock_backend = Path("web_ui_react/e2e/support/mockSidarBackend.js").read_text(encoding="utf-8")
    vite_server = Path("web_ui_react/e2e/support/testViteServer.js").read_text(encoding="utf-8")
    assert 'backendUrl = process.env.SIDAR_BACKEND_URL || "http://127.0.0.1:7860"' in vite
    assert 'backendUrl.replace(/^http/, "ws")' in vite
    assert '"/ws":' in vite
    assert "target: webSocketUrl" in vite
    assert "ws: true" in vite
    assert "changeOrigin: true" in vite
    assert "proxyReqWs" in vite
    assert "sec-websocket-protocol" in vite
    assert "localhost:7860" not in vite
    assert "optimizeDeps:" in vite
    assert '"index.html"' in vite
    assert '"src/main.jsx"' in vite
    assert '"src/App.jsx"' in vite
    assert '"src/components/*.jsx"' in vite
    assert '"!src/**/*.test.{js,jsx}"' in vite
    assert '"!e2e/**"' in vite
    assert 'test.describe.configure({ mode: "serial" })' in websocket_spec
    assert "test.beforeAll(async () =>" in websocket_spec
    assert "test.beforeEach(async ({ page }) =>" in websocket_spec
    assert "test.afterAll(async () =>" in websocket_spec
    assert "backend = await startMockSidarBackend()" in websocket_spec
    assert "frontend = await startTestViteServer({ backendUrl: backend.url })" in websocket_spec
    assert "await page.goto(`${frontend.url}/chat`" in websocket_spec
    assert 'waitUntil: "domcontentloaded"' in websocket_spec
    assert "port = 0" in mock_backend
    assert 'server.listen(port, "0.0.0.0"' in mock_backend
    assert "port: address.port" in mock_backend
    assert "url: `http://127.0.0.1:${address.port}`" in mock_backend
    assert 'probe.listen(0, "127.0.0.1", resolve)' in vite_server
    assert "port," in vite_server
    assert "strictPort: true" in vite_server
    assert 'host: "127.0.0.1"' in vite_server
    assert "proxy: createSidarProxyConfig(backendUrl)" in vite_server
    assert "process.env.SIDAR_BACKEND_URL" not in vite_server
    assert "await page.context().clearCookies()" in websocket_spec
    assert "await page.addInitScript(() => localStorage.clear())" in websocket_spec
    assert ".toBeVisible({ timeout: 15_000 })" not in websocket_spec


def test_run_tests_tolerates_local_frontend_npm_audit_network_failures() -> None:
    """Frontend audit must not cascade-skip lint/coverage on local registry outages."""
    script = _script()
    package_json = Path("web_ui_react/package.json").read_text(encoding="utf-8")
    npm_audit_safe = Path("scripts/npm_audit_safe.js").read_text(encoding="utf-8")
    frontend_gate_block = script[
        script.index("# 3) Frontend React testleri") : script.index(
            "# 4) Final Durum Değerlendirmesi"
        )
    ]

    assert (
        '"audit:high": "node ../scripts/npm_audit_safe.js --level=high --retries=2"' in package_json
    )
    assert "function classifyAuditFailure" in npm_audit_safe
    assert "FRONTEND_NPM_AUDIT_ALLOW_NETWORK_FAILURE" in npm_audit_safe
    assert "FRONTEND_NPM_AUDIT_MAX_RETRIES" in npm_audit_safe
    assert "FRONTEND_NPM_AUDIT_NPM_BINARY" in npm_audit_safe
    assert (
        'spawnSync(options.npmBinary, ["audit", `--audit-level=${options.level}`, "--json"]'
        in npm_audit_safe
    )
    assert "npm-audit-report.raw.json" in npm_audit_safe
    assert "npm-audit-stderr.log" in npm_audit_safe
    assert "npm-audit-failure.json" in npm_audit_safe
    assert "audit endpoint returned an error" in npm_audit_safe
    assert "failure_category: category" in npm_audit_safe
    assert "hasAuditFindingsAtOrAboveLevel(payload, threshold)" in npm_audit_safe
    assert (
        "options.allowNetworkFailure = !process.env.CI && !process.env.GITHUB_ACTIONS"
        in npm_audit_safe
    )
    assert (
        frontend_gate_block.index("npm run audit:high")
        < frontend_gate_block.index("npm run lint")
        < frontend_gate_block.index("npm run typecheck")
        < frontend_gate_block.index("npm run test:coverage")
    )
    assert 'if [ "${FRONTEND_NPM_AUDIT_EXIT_CODE}" -ne 0 ]; then' in frontend_gate_block
    assert 'else\n          echo "🧹 Frontend lint' not in frontend_gate_block


def test_npm_audit_safe_fails_on_high_findings_even_when_npm_exits_zero(
    tmp_path: Path,
) -> None:
    """The JSON vulnerability counts must override an unreliable npm exit code."""
    audit_wrapper = Path("scripts/npm_audit_safe.js").resolve()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/usr/bin/env bash\n"
        "cat <<'JSON'\n"
        '{"metadata":{"vulnerabilities":{"info":0,"low":0,"moderate":0,'
        '"high":7,"critical":0,"total":7}}}\n'
        "JSON\n"
        "exit 0\n",
        encoding="utf-8",
    )
    npm.chmod(0o755)
    artifact_dir = tmp_path / "artifacts"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    # Volta gibi Node shim'leri child process başlamadan PATH'i yeniden
    # sıralayabilir. Wrapper'ın açık binary kontratı testi ortamdan bağımsız tutar.
    env["FRONTEND_NPM_AUDIT_NPM_BINARY"] = str(npm)

    result = subprocess.run(
        [
            "node",
            str(audit_wrapper),
            "--level=high",
            "--retries=1",
            f"--artifact-dir={artifact_dir}",
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 1
    assert "gerçek high veya üstü güvenlik bulgusu" in result.stderr
    failure = json.loads((artifact_dir / "npm-audit-failure.json").read_text(encoding="utf-8"))
    assert failure["failure_category"] == "vulnerability"
    assert failure["exit_code"] == 1
    assert failure["audit_level"] == "high"

    npm.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' "
        '\'{"metadata":{"vulnerabilities":{"moderate":3,"high":0,"critical":0}}}\'\n',
        encoding="utf-8",
    )
    npm.chmod(0o755)
    below_threshold = subprocess.run(
        [
            "node",
            str(audit_wrapper),
            "--level=high",
            "--retries=1",
            f"--artifact-dir={artifact_dir}",
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert below_threshold.returncode == 0, below_threshold.stderr
    assert not (artifact_dir / "npm-audit-failure.json").exists()


def test_npm_audit_safe_accepts_only_the_verified_brace_expansion_backport(
    tmp_path: Path,
) -> None:
    """The temporary advisory exception must be exact and fail closed."""
    audit_wrapper = Path("scripts/npm_audit_safe.js").resolve()
    npm = tmp_path / "npm"
    npm.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$AUDIT_JSON\"\nexit 1\n",
        encoding="utf-8",
    )
    npm.chmod(0o755)
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "node_modules/minimatch/node_modules/brace-expansion": {"version": "1.1.17"}
                }
            }
        ),
        encoding="utf-8",
    )
    vulnerabilities = {
        "brace-expansion": {
            "severity": "high",
            "via": [{"source": 1124334, "severity": "high"}],
        },
        "minimatch": {"severity": "high", "via": ["brace-expansion"]},
        "eslint": {"severity": "high", "via": ["minimatch"]},
    }

    def run_audit(
        payload: dict[str, object], *, test_now: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "AUDIT_JSON": json.dumps(payload),
            "FRONTEND_NPM_AUDIT_NPM_BINARY": str(npm),
        }
        if test_now is not None:
            env["FRONTEND_NPM_AUDIT_TEST_NOW"] = test_now
        return subprocess.run(
            [
                "node",
                str(audit_wrapper),
                "--level=high",
                "--retries=1",
                f"--artifact-dir={tmp_path / 'artifacts'}",
            ],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            env=env,
            text=True,
        )

    patched = run_audit(
        {
            "vulnerabilities": vulnerabilities,
            "metadata": {"vulnerabilities": {"high": 3}},
        }
    )
    assert patched.returncode == 0, patched.stderr
    assert "1.1.17 güvenlik backport'unu" in patched.stderr
    assert "docs/development/frontend-eslint-10-migration.md" in patched.stderr

    expired = run_audit(
        {
            "vulnerabilities": vulnerabilities,
            "metadata": {"vulnerabilities": {"high": 3}},
        },
        test_now="2026-09-30T00:00:00Z",
    )
    assert expired.returncode == 1
    assert "yeniden değerlendirme tarihi doldu" in expired.stderr
    failure = json.loads(
        (tmp_path / "artifacts/npm-audit-failure.json").read_text(encoding="utf-8")
    )
    assert failure["failure_category"] == "expired_exception"
    assert failure["exception_review_at"] == "2026-09-30T00:00:00Z"

    vulnerabilities["unrelated-package"] = {
        "severity": "critical",
        "via": [{"source": 9999999, "severity": "critical"}],
    }
    unrelated = run_audit(
        {
            "vulnerabilities": vulnerabilities,
            "metadata": {"vulnerabilities": {"high": 3, "critical": 1}},
        }
    )
    assert unrelated.returncode == 1
    assert "gerçek high veya üstü güvenlik bulgusu" in unrelated.stderr


def test_frontend_eslint_10_exception_has_a_bounded_migration_plan() -> None:
    """The temporary npm advisory exception must remain documented and removable."""
    plan = Path("docs/development/frontend-eslint-10-migration.md").read_text(encoding="utf-8")

    assert "yedi bağımsız güvenlik açığı değildir" in plan
    assert "eslint-plugin-react@7.37.5" in plan
    assert "eslint-plugin-jsx-a11y@6.10.2" in plan
    assert "**İlk yeniden değerlendirme:** 2026-09-30" in plan
    assert "`expired_exception` kategorisiyle fail-closed" in plan
    assert "FRONTEND_NPM_AUDIT_ALLOW_NETWORK_FAILURE=0 npm run audit:high" in plan
    assert "`PATCHED_BRACE_EXPANSION_*` istisnasını" in plan


def test_frontend_typescript_inventory_ratchet_fails_closed(tmp_path: Path) -> None:
    """The migration inventory must reject new untyped debt and typed regressions."""
    checker = Path("scripts/check_frontend_typescript_migration.js").resolve()
    source = tmp_path / "src"
    source.mkdir()
    (source / "legacy.jsx").write_text("export default null;\n", encoding="utf-8")
    (source / "typed.ts").write_text("export const value: number = 1;\n", encoding="utf-8")
    baseline = tmp_path / "typescript-migration-baseline.json"
    baseline.write_text(
        json.dumps({"maximum_untyped_files": 1, "minimum_typed_files": 1}), encoding="utf-8"
    )

    def run_inventory() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["node", str(checker), f"--root={tmp_path}"],
            check=False,
            capture_output=True,
            text=True,
        )

    assert run_inventory().returncode == 0

    (source / "new-debt.js").write_text("export const debt = true;\n", encoding="utf-8")
    increased = run_inventory()
    assert increased.returncode == 1
    assert "untyped source count increased: 2 > 1" in increased.stderr

    (source / "new-debt.js").unlink()
    (source / "typed.ts").unlink()
    decreased = run_inventory()
    assert decreased.returncode == 1
    assert "typed source count decreased: 0 < 1" in decreased.stderr


def test_frontend_quality_signals_do_not_fail_fast_after_lint() -> None:
    """Lint, typecheck, coverage, build and E2E must retain separate results."""
    frontend_gate_block = _script()[
        _script().index("# 3) Frontend React testleri") : _script().index(
            "# 4) Final Durum Değerlendirmesi"
        )
    ]

    assert "Bir kapının hatası sonraki sinyalleri" in frontend_gate_block
    assert (
        frontend_gate_block.index("run_checked npm run lint")
        < frontend_gate_block.index("run_checked npm run typecheck")
        < frontend_gate_block.index("run_checked npm run test:coverage")
        < frontend_gate_block.index("run_checked npm run build:budget")
        < frontend_gate_block.index("run_checked run_frontend_e2e_with_retry")
    )
    assert 'if [ "${FRONTEND_EXIT_CODE}" -eq 0 ]; then' not in frontend_gate_block
    validation_phase = Path("scripts/install_modules/phases/10_validation.sh").read_text(
        encoding="utf-8"
    )
    assert "summary_frontend_build" in validation_phase
    assert "read_install_test_summary_field frontend_bundle_budget" in validation_phase
    assert 'print_install_validation_gate_line "Frontend build"' in validation_phase

    frontend_readme = Path("web_ui_react/README.md").read_text(encoding="utf-8")
    assert (
        "Vite build, ESLint, TypeScript typecheck, Vitest coverage ve Playwright E2E"
        in frontend_readme
    )


def test_frontend_security_dependencies_are_patched_in_package_lock() -> None:
    package_json = json.loads(Path("web_ui_react/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(Path("web_ui_react/package-lock.json").read_text(encoding="utf-8"))

    scripts = package_json["scripts"]
    dev_deps = package_json["devDependencies"]
    locked_root = package_lock["packages"][""]
    locked_root_deps = locked_root["devDependencies"]
    locked_packages = package_lock["packages"]

    assert "preinstall" not in scripts
    assert scripts["build:budget"] == "npm run build && node scripts/check-bundle-budget.mjs"
    assert scripts["bundle:budget"] == "node scripts/check-bundle-budget.mjs"
    bundle_budget_script = Path("web_ui_react/scripts/check-bundle-budget.mjs").read_text(
        encoding="utf-8"
    )
    assert "SIDAR_TOTAL_JS_BUDGET_KB" in bundle_budget_script
    assert "SIDAR_TOTAL_GZIP_BUDGET_KB" in bundle_budget_script
    assert "SIDAR_BUNDLE_BUDGET_WARN_RATIO" in bundle_budget_script
    assert "buildBudgetUsage" in bundle_budget_script
    assert "watch dependency additions" in bundle_budget_script
    assert "productionBudgetGateActive" in bundle_budget_script
    assert "requireBudgetForProductionGate" in bundle_budget_script
    assert (
        "must be set when SIDAR_PRODUCTION_READINESS=1 or TEST_PROFILE=ci" in bundle_budget_script
    )
    assert "artifacts/frontend-bundle-budget.json" in bundle_budget_script
    assert "Top ${topChunks.length} JS chunks" in bundle_budget_script
    assert "hasInstallScript" not in locked_root
    assert dev_deps["@playwright/test"] == ">=1.60.0 <1.62.0"
    assert dev_deps["vite"] == "^8.0.16"
    assert dev_deps["ws"] == "^8.21.0"
    assert locked_root_deps["@playwright/test"] == ">=1.60.0 <1.62.0"
    assert locked_root_deps["vite"] == "^8.0.16"
    assert locked_root_deps["ws"] == "^8.21.0"
    assert locked_packages["node_modules/@playwright/test"]["version"].startswith("1.61.")
    assert locked_packages["node_modules/playwright"]["version"].startswith("1.61.")
    assert locked_packages["node_modules/vite"]["version"] == "8.0.16"
    assert locked_packages["node_modules/ws"]["version"] == "8.21.0"
    assert locked_packages["node_modules/vite"]["dependencies"]["postcss"] == "^8.5.15"
    assert locked_packages["node_modules/vite"]["dependencies"]["rolldown"] == "1.0.3"
    assert locked_packages["node_modules/vite"]["dependencies"]["tinyglobby"] == "^0.2.17"


def test_frontend_bundle_budget_warns_when_totals_approach_budget(tmp_path: Path) -> None:
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    chunk_path = assets_dir / "react-dom-near-budget.js"
    chunk_path.write_text("a" * 950, encoding="utf-8")
    report_path = tmp_path / "bundle-budget.json"

    env = os.environ.copy()
    env.update(
        {
            "SIDAR_REACT_DOM_CHUNK_BUDGET_KB": "220",
            "SIDAR_TOTAL_JS_BUDGET_KB": "1",
            "SIDAR_TOTAL_GZIP_BUDGET_KB": "10",
            "SIDAR_BUNDLE_BUDGET_WARN_RATIO": "0.9",
            "SIDAR_BUNDLE_BUDGET_REPORT_PATH": str(report_path),
            "SIDAR_BUNDLE_ASSETS_DIR": str(assets_dir),
        }
    )

    result = subprocess.run(
        ["node", "web_ui_react/scripts/check-bundle-budget.mjs"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert "Total JS is at" in result.stderr
    assert "watch dependency additions" in result.stderr
    assert report["budgetUsage"]["totalJs"]["warning"] is True
    assert report["budgetsKb"]["warnRatio"] == 0.9


def test_frontend_bundle_budget_requires_total_budgets_for_ci_gate(tmp_path: Path) -> None:
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    chunk_path = assets_dir / "react-dom-test.js"
    chunk_path.write_text("console.log('react-dom');\n", encoding="utf-8")
    report_path = tmp_path / "bundle-budget.json"

    env = os.environ.copy()
    env.pop("SIDAR_TOTAL_JS_BUDGET_KB", None)
    env.pop("SIDAR_TOTAL_GZIP_BUDGET_KB", None)
    env.update(
        {
            "TEST_PROFILE": "ci",
            "SIDAR_REACT_DOM_CHUNK_BUDGET_KB": "220",
            "SIDAR_BUNDLE_BUDGET_REPORT_PATH": str(report_path),
            "SIDAR_BUNDLE_ASSETS_DIR": str(assets_dir),
        }
    )

    result = subprocess.run(
        ["node", "web_ui_react/scripts/check-bundle-budget.mjs"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "SIDAR_TOTAL_JS_BUDGET_KB must be set" in result.stderr
    assert "SIDAR_TOTAL_GZIP_BUDGET_KB must be set" in result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["missingRequiredBudgets"] == [
        "SIDAR_TOTAL_JS_BUDGET_KB",
        "SIDAR_TOTAL_GZIP_BUDGET_KB",
    ]


def test_frontend_playwright_e2e_retries_once_and_preserves_retry_failure(tmp_path: Path) -> None:
    script = _script()
    helper = tmp_path / "frontend_e2e_retry.sh"
    helper.write_text(
        "#!/usr/bin/env bash\nset -uo pipefail\n"
        + script[
            script.index("run_frontend_e2e_with_retry() {") : script.index(
                "resolve_local_frontend_e2e_mode() {"
            )
        ]
        + "run_frontend_e2e_with_retry\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        """#!/usr/bin/env bash
count=0
[[ -f "${MOCK_NPM_COUNT}" ]] && count="$(cat "${MOCK_NPM_COUNT}")"
count=$((count + 1))
printf '%s' "${count}" > "${MOCK_NPM_COUNT}"
[[ "${count}" -ge "${MOCK_NPM_PASS_ON_ATTEMPT}" ]]
""",
        encoding="utf-8",
    )
    npm.chmod(0o755)
    count_file = tmp_path / "npm-count"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MOCK_NPM_COUNT": str(count_file),
        "MOCK_NPM_PASS_ON_ATTEMPT": "2",
        "FRONTEND_E2E_RETRY_ON_FAIL": "1",
        "FRONTEND_E2E_NPM_SCRIPT": "test:e2e:smoke",
    }

    success = subprocess.run([str(helper)], env=env, capture_output=True, text=True)

    assert success.returncode == 0
    assert count_file.read_text(encoding="utf-8") == "2"
    assert "ikinci denemede geçti" in success.stdout

    count_file.unlink()
    env["MOCK_NPM_PASS_ON_ATTEMPT"] = "3"
    failure = subprocess.run([str(helper)], env=env, capture_output=True, text=True)

    assert failure.returncode == 1
    assert count_file.read_text(encoding="utf-8") == "2"
    assert "retry sonrasında da başarısız" in failure.stdout


def test_benchmark_and_frontend_e2e_flakes_are_soft_local_but_hard_in_ci() -> None:
    script = _script()
    final_evaluation = script[script.index("# 4) Final Durum Değerlendirmesi") :]
    common_prefix = """
BACKEND_EXIT_CODE=0
FRONTEND_EXIT_CODE=0
FRONTEND_E2E_EXIT_CODE=1
BENCHMARK_EXIT_CODE=1
format_backend_failure_reasons() { printf 'none'; }
"""

    local_result = subprocess.run(
        [
            "bash",
            "-c",
            common_prefix
            + "TEST_PROFILE=local\nBENCHMARK_ENFORCE_RESULT=0\nFRONTEND_E2E_ENFORCE_RESULT=0\n"
            + final_evaluation,
        ],
        capture_output=True,
        text=True,
    )

    assert local_result.returncode == 0
    assert "Benchmark fazı başarısız" in local_result.stdout
    assert "Frontend Playwright E2E fazı retry sonrasında başarısız" in local_result.stdout

    ci_result = subprocess.run(
        [
            "bash",
            "-c",
            common_prefix
            + "TEST_PROFILE=ci\nBENCHMARK_ENFORCE_RESULT=1\nFRONTEND_E2E_ENFORCE_RESULT=1\n"
            + final_evaluation,
        ],
        capture_output=True,
        text=True,
    )

    assert ci_result.returncode == 1
    assert "Frontend E2E Çıkış Kodu: 1 (enforce=1)" in ci_result.stdout
    assert "Benchmark Çıkış Kodu: 1 (enforce=1)" in ci_result.stdout


def test_websocket_mount_status_is_resolved_before_first_paint() -> None:
    websocket_hook = Path("web_ui_react/src/hooks/useWebSocket.js").read_text(encoding="utf-8")

    assert (
        'import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";'
        in websocket_hook
    )
    assert (
        "useLayoutEffect(() => {\n    manualCloseRef.current = false;\n    connect();"
        in websocket_hook
    )
    assert "flushSync" not in websocket_hook


def test_shared_playwright_ubuntu_override_helper_runs_node_install_with_synthetic_os_release(
    tmp_path: Path,
) -> None:
    helper = Path("scripts/install_modules/utils/playwright_ubuntu_override.sh").resolve()
    os_release = tmp_path / "os-release"
    mock_install = tmp_path / "mock-install.sh"
    os_release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n', encoding="utf-8")
    mock_install.write_text(
        """#!/usr/bin/bash
printf '%s|%s|' "${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" \
  "${PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT:-}"
grep -q '^VERSION_ID="24.04"$' "${OS_RELEASE_PATH}"
""",
        encoding="utf-8",
    )
    mock_install.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -Eeuo pipefail; source "$1"; is_playwright_ubuntu_override_recommended "$2"; '
            'run_playwright_ubuntu_override_install "$2" 120000 "$3"',
            "bash",
            str(helper),
            str(os_release),
            str(mock_install),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "ubuntu24.04-x64|120000|"


def test_node_playwright_official_ubuntu26_support_disables_override(
    tmp_path: Path,
) -> None:
    helper = Path("scripts/install_modules/utils/playwright_ubuntu_override.sh").resolve()
    os_release = tmp_path / "os-release"
    mock_npx = tmp_path / "npx"
    npx_log = tmp_path / "npx.log"
    os_release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n', encoding="utf-8")
    mock_npx.write_text(
        """#!/usr/bin/bash
printf '%s\n' "$*" >> "${MOCK_NPX_LOG}"
if [[ "$*" == "--no-install playwright install --dry-run chromium" ]]; then
  printf 'browser: chromium\nplatform: ubuntu26.04-x64\n'
  exit 0
fi
if [[ "$*" == "--no-install playwright install chromium" ]]; then
  printf '%s|' "${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}"
  grep -q '^VERSION_ID="26.04"$' "${OS_RELEASE_PATH}"
  exit $?
fi
printf 'unexpected probe invocation: %s\n' "$*" >&2
exit 42
""",
        encoding="utf-8",
    )
    mock_npx.chmod(0o755)

    probe_and_install = (
        'set -Eeuo pipefail; source "$1"; '
        'if playwright_node_host_platform_is_officially_supported "$2" "$3" '
        "--no-install; then "
        'OS_RELEASE_PATH="$2" "$3" --no-install playwright install chromium; '
        'else run_playwright_ubuntu_override_install "$2" 120000 "$3" '
        "--no-install playwright install chromium; fi"
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            probe_and_install,
            "bash",
            str(helper),
            str(os_release),
            str(mock_npx),
        ],
        check=True,
        capture_output=True,
        env={"MOCK_NPX_LOG": str(npx_log)},
        text=True,
    )

    assert result.stdout.endswith("|")
    assert "ubuntu24.04-x64" not in result.stdout
    assert npx_log.read_text(encoding="utf-8").splitlines() == [
        "--no-install playwright install --dry-run chromium",
        "--no-install playwright install chromium",
    ]


def test_node_playwright_unsupported_ubuntu26_keeps_temporary_override(tmp_path: Path) -> None:
    """Older Playwright packages must retain the compatibility fallback."""
    helper = Path("scripts/install_modules/utils/playwright_ubuntu_override.sh").resolve()
    os_release = tmp_path / "os-release"
    mock_npx = tmp_path / "npx"
    os_release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n', encoding="utf-8")
    mock_npx.write_text(
        """#!/usr/bin/env bash
echo 'BEWARE: your OS is not officially supported by Playwright' >&2
exit 0
""",
        encoding="utf-8",
    )
    mock_npx.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; ! playwright_node_host_platform_is_officially_supported "$2" "$3" '
            "--no-install",
            "bash",
            str(helper),
            str(os_release),
            str(mock_npx),
        ],
        check=False,
    )
    assert result.returncode == 0


def test_shared_playwright_ubuntu_override_helper_uses_latest_supported_ubuntu_bundle(
    tmp_path: Path,
) -> None:
    helper = Path("scripts/install_modules/utils/playwright_ubuntu_override.sh").resolve()
    package_dir = tmp_path / "playwright"
    host_platform = (
        package_dir / "driver" / "package" / "lib" / "server" / "utils" / "hostPlatform.js"
    )
    mock_python = tmp_path / "python3"
    os_release = tmp_path / "os-release"
    host_platform.parent.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("# fake playwright\n", encoding="utf-8")
    host_platform.write_text(
        'module.exports = { known: ["ubuntu22.04-x64", "ubuntu24.04-x64", "ubuntu26.04-x64"] };',
        encoding="utf-8",
    )
    mock_python.write_text(
        f"""#!/usr/bin/bash
if [[ "$*" == "-m playwright install chromium" ]]; then
  printf '%s|' "${{PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}}"
  grep -q '^VERSION_ID="26.04"$' "${{OS_RELEASE_PATH}}"
  exit $?
fi
PYTHONPATH={tmp_path} python3 "$@"
""",
        encoding="utf-8",
    )
    mock_python.chmod(0o755)
    os_release.write_text('ID=ubuntu\nVERSION_ID="28.04"\n', encoding="utf-8")
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -Eeuo pipefail; source "$1"; run_playwright_ubuntu_override_install "$2" 120000 '
            '"$3" -m playwright install chromium',
            "bash",
            str(helper),
            str(os_release),
            str(mock_python),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "ubuntu26.04-x64|"


def test_playwright_phase_python_installer_still_resolves_latest_supported_ubuntu_bundle(
    tmp_path: Path,
) -> None:
    helper = Path("scripts/install_modules/utils/playwright_ubuntu_override.sh").resolve()
    phase = Path("scripts/install_modules/phases/13_playwright.sh").resolve()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock_python = bin_dir / "python"
    python_log = tmp_path / "python.log"
    os_release = tmp_path / "os-release"
    pyproject = tmp_path / "pyproject.toml"
    os_release.write_text('ID=ubuntu\nVERSION_ID="28.04"\n', encoding="utf-8")
    pyproject.write_text(
        '[dependency-groups]\ndev = ["playwright>=1.60,<1.62"]\n',
        encoding="utf-8",
    )
    mock_python.write_text(
        """#!/usr/bin/bash
printf 'args=%s\n' "$*" >> "${MOCK_PYTHON_LOG}"
if [[ "$*" == "-c import playwright" ]]; then
  exit 0
fi
if [[ "$*" == "-m playwright install chromium" ]]; then
  printf 'install-platform=%s\n' "${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-unset}" \
    >> "${MOCK_PYTHON_LOG}"
  grep -q '^VERSION_ID="26.04"$' "${OS_RELEASE_PATH}"
  exit $?
fi
if [[ "$*" == "-" ]]; then
  payload="$(cat)"
  if [[ "${payload}" == *"isOfficiallySupportedPlatform"* ]]; then
    printf 'host-support-probe\n' >> "${MOCK_PYTHON_LOG}"
    exit 1
  fi
  if [[ "${payload}" == *"ubuntu(\\d+\\.\\d+)-x64"* ]]; then
    printf 'latest-supported-probe\n' >> "${MOCK_PYTHON_LOG}"
    printf '26.04\n'
    exit 0
  fi
fi
printf 'unexpected python invocation: %s\n' "$*" >&2
exit 42
""",
        encoding="utf-8",
    )
    mock_python.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-x",
            "-c",
            """set -Eeuo pipefail
source "$1"
source "$2"
step() { printf 'STEP:%s\n' "$*"; }
info() { printf 'INFO:%s\n' "$*"; }
ok() { printf 'OK:%s\n' "$*"; }
warn() { printf 'WARN:%s\n' "$*"; }
read_env_value_from_file() { printf 'development\n'; }
playwright_linux_dependencies_ready() { return 0; }
PLAYWRIGHT_BROWSERS_MODE=always
SCRIPT_DIR="$3"
OS_RELEASE_PATH="$4"
install_playwright_browsers""",
            "bash",
            str(helper),
            str(phase),
            str(tmp_path),
            str(os_release),
        ],
        check=False,
        capture_output=True,
        env={
            "MOCK_PYTHON_LOG": str(python_log),
            "PATH": f"{bin_dir}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        },
        text=True,
    )
    if result.returncode != 0:
        python_log_content = (
            python_log.read_text(encoding="utf-8") if python_log.exists() else "<missing>"
        )
        pytest.fail(
            "\n".join(
                [
                    f"bash returncode={result.returncode}",
                    f"stdout:\n{result.stdout}",
                    f"stderr:\n{result.stderr}",
                    f"python.log:\n{python_log_content}",
                ]
            )
        )

    python_log_text = python_log.read_text(encoding="utf-8")
    assert "host-support-probe" in python_log_text
    assert "latest-supported-probe" in python_log_text
    assert "args=-m playwright install chromium" in python_log_text
    assert "install-platform=ubuntu26.04-x64" in python_log_text
    assert "proaktif OS override" in result.stdout


def test_shared_playwright_ubuntu_override_helper_skips_future_ubuntu_override() -> None:
    helper = Path("scripts/install_modules/utils/playwright_ubuntu_override.sh").resolve()

    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -Eeuo pipefail; source "$1"; tmp="$(mktemp)"; '
            'printf "ID=ubuntu\nVERSION_ID="32.04"\n" > "$tmp"; '
            '! is_playwright_ubuntu_override_recommended "$tmp"',
            "bash",
            str(helper),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0


def test_shared_playwright_ubuntu_override_helper_skips_override_when_upstream_supports_host(
    tmp_path: Path,
) -> None:
    helper = Path("scripts/install_modules/utils/playwright_ubuntu_override.sh").resolve()
    os_release = tmp_path / "os-release"
    mock_python = tmp_path / "mock-python.sh"
    probe_log = tmp_path / "probe.log"
    os_release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n', encoding="utf-8")
    mock_python.write_text(
        """#!/usr/bin/bash
printf '%s|%s' "${OS_RELEASE_PATH:-}" "${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-unset}" \
  > "${MOCK_PROBE_LOG}"
exit "${MOCK_PROBE_EXIT:-0}"
""",
        encoding="utf-8",
    )
    mock_python.chmod(0o755)
    env = {
        **os.environ,
        "MOCK_PROBE_LOG": str(probe_log),
        "PLAYWRIGHT_HOST_PLATFORM_OVERRIDE": "forced-before-probe",
    }

    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -Eeuo pipefail; source "$1"; '
            'playwright_host_platform_is_officially_supported "$2" "$3"',
            "bash",
            str(helper),
            str(os_release),
            str(mock_python),
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert probe_log.read_text(encoding="utf-8") == f"{os_release}|unset"


def test_shared_playwright_ubuntu_override_helper_lists_modern_chromium_dependencies() -> None:
    helper = Path("scripts/install_modules/utils/playwright_ubuntu_override.sh").read_text(
        encoding="utf-8"
    )

    assert "playwright_ubuntu_dependency_packages()" in helper
    assert "playwright_missing_ubuntu_dependencies()" in helper
    assert "apt list --installed" in helper
    assert 'gtk_package="libgtk-3-0"' in helper
    assert 'gtk_package="libgtk-3-0t64"' in helper
    assert "libxshmfence1" in helper
    assert "libnss3" in helper
    assert "libnspr4" in helper
    assert "libasound2t64" in helper
    phase = Path("scripts/install_modules/phases/13_playwright.sh").read_text(encoding="utf-8")
    assert "playwright_linux_dependencies_ready" in phase
    assert "playwright_missing_ubuntu_dependencies" in phase
    assert "apt ön taraması eksik Chromium bağımlılıkları buldu" in phase
    assert (
        '! playwright_host_platform_is_officially_supported "$_pw_os_release_path" "${PY_CMD[@]}"'
        in phase
    )


@pytest.mark.parametrize(
    ("ubuntu_version", "expects_ubuntu_override"),
    [
        ("26.04", True),
        ("24.04", False),
    ],
)
def test_local_frontend_playwright_sentinel_skips_repeat_node_resolution_and_removes_stale_cache(
    tmp_path: Path,
    ubuntu_version: str,
    expects_ubuntu_override: bool,
) -> None:
    helper_script = tmp_path / "frontend_playwright_helpers.sh"
    helper_script.write_text(
        _run_tests_frontend_playwright_helpers(),
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    browser = tmp_path / "chromium"
    sentinel = tmp_path / ".playwright-installed"
    node_log = tmp_path / "node.log"
    npx_log = tmp_path / "npx.log"
    os_release = tmp_path / "os-release"
    package_lock = tmp_path / "package-lock.json"
    os_release.write_text(f'ID=ubuntu\nVERSION_ID="{ubuntu_version}"\n', encoding="utf-8")
    package_lock.write_text("lock-v1\n", encoding="utf-8")
    node = bin_dir / "node"
    node.write_text(
        """#!/usr/bin/env bash
printf 'node\\n' >> "${MOCK_NODE_LOG}"
if [[ -f "${MOCK_BROWSER}" ]]; then
  printf '%s' "${MOCK_BROWSER}"
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    npx = bin_dir / "npx"
    npx.write_text(
        """#!/usr/bin/bash
printf '%s\\n' "$*" >> "${MOCK_NPX_LOG}"
touch "${MOCK_BROWSER}"
""",
        encoding="utf-8",
    )
    node.chmod(0o755)
    npx.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-x",
            "-c",
            """set -Eeuo pipefail
source "$1"
if [[ "${EXPECTS_UBUNTU_OVERRIDE}" == 1 ]]; then
  is_playwright_ubuntu_override_recommended "${OS_RELEASE_PATH}"
else
  ! is_playwright_ubuntu_override_recommended "${OS_RELEASE_PATH}"
fi
RUN_FRONTEND_E2E=auto
resolve_local_frontend_e2e_mode
[[ "${RUN_FRONTEND_E2E}" == 1 ]]
[[ "$(head -n 1 "${FRONTEND_PLAYWRIGHT_SENTINEL}")" == "${MOCK_BROWSER}" ]]
[[ "$(wc -l < "${MOCK_NODE_LOG}")" -eq 2 ]]
grep -qx -- '--no-install playwright install chromium' "${MOCK_NPX_LOG}"
RUN_FRONTEND_E2E=auto
resolve_local_frontend_e2e_mode
[[ "${RUN_FRONTEND_E2E}" == 1 ]]
[[ "$(wc -l < "${MOCK_NODE_LOG}")" -eq 2 ]]
[[ "$(wc -l < "${MOCK_NPX_LOG}")" -eq "${EXPECTED_NPX_CALLS}" ]]
printf 'lock-v2\\n' > "${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK}"
RUN_FRONTEND_E2E=auto
RUN_FRONTEND_E2E_AUTO_INSTALL=0
resolve_local_frontend_e2e_mode
[[ "${RUN_FRONTEND_E2E}" == 1 ]]
[[ "$(wc -l < "${MOCK_NODE_LOG}")" -eq 3 ]]
rm -f "${MOCK_BROWSER}"
RUN_FRONTEND_E2E=auto
resolve_local_frontend_e2e_mode
[[ "${RUN_FRONTEND_E2E}" == 0 ]]
[[ ! -e "${FRONTEND_PLAYWRIGHT_SENTINEL}" ]]
[[ "$(wc -l < "${MOCK_NODE_LOG}")" -eq 4 ]]""",
            "bash",
            str(helper_script),
        ],
        check=False,
        capture_output=True,
        env={
            "EXPECTS_UBUNTU_OVERRIDE": "1" if expects_ubuntu_override else "0",
            "EXPECTED_NPX_CALLS": "2" if expects_ubuntu_override else "1",
            "FRONTEND_PLAYWRIGHT_SENTINEL": str(sentinel),
            "FRONTEND_PLAYWRIGHT_PACKAGE_LOCK": str(package_lock),
            "MOCK_BROWSER": str(browser),
            "MOCK_NODE_LOG": str(node_log),
            "MOCK_NPX_LOG": str(npx_log),
            "OS_RELEASE_PATH": str(os_release),
            "PATH": f"{bin_dir}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
            "RUN_FRONTEND_E2E_AUTO_INSTALL": "1",
        },
        text=True,
    )
    if result.returncode != 0:
        node_log_content = (
            node_log.read_text(encoding="utf-8") if node_log.exists() else "<missing>"
        )
        npx_log_content = npx_log.read_text(encoding="utf-8") if npx_log.exists() else "<missing>"
        sentinel_content = (
            sentinel.read_text(encoding="utf-8") if sentinel.exists() else "<missing>"
        )
        pytest.fail(
            "\n".join(
                [
                    f"bash returncode={result.returncode}",
                    f"ubuntu_version={ubuntu_version}",
                    f"expects_ubuntu_override={expects_ubuntu_override}",
                    f"stdout:\n{result.stdout}",
                    f"stderr:\n{result.stderr}",
                    f"node.log:\n{node_log_content}",
                    f"npx.log:\n{npx_log_content}",
                    f"sentinel:\n{sentinel_content}",
                ]
            )
        )

    assert "Chromium cache'i otomatik kuruldu" in result.stdout
    assert "Chromium sentinel cache'i hazır" in result.stdout
    assert "Chromium cache'i hazırlanamadı" in result.stdout
    expected_npx_log = ["--no-install playwright install chromium"]
    if expects_ubuntu_override:
        expected_npx_log.insert(0, "--no-install playwright install --dry-run chromium")
    assert npx_log.read_text(encoding="utf-8").splitlines() == expected_npx_log


def test_forced_frontend_playwright_mode_attempts_cache_install_before_failing(
    tmp_path: Path,
) -> None:
    helper_script = tmp_path / "frontend_playwright_helpers.sh"
    helper_script.write_text(
        _run_tests_frontend_playwright_helpers(),
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    node_log = tmp_path / "node.log"
    npx_log = tmp_path / "npx.log"
    os_release = tmp_path / "os-release"
    package_lock = tmp_path / "package-lock.json"
    os_release.write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    package_lock.write_text("lock-v1\n", encoding="utf-8")
    node = bin_dir / "node"
    node.write_text(
        """#!/usr/bin/env bash
printf 'node\\n' >> "${MOCK_NODE_LOG}"
exit 1
""",
        encoding="utf-8",
    )
    npx = bin_dir / "npx"
    npx.write_text(
        """#!/usr/bin/bash
printf '%s\\n' "$*" >> "${MOCK_NPX_LOG}"
exit 1
""",
        encoding="utf-8",
    )
    node.chmod(0o755)
    npx.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-x",
            "-c",
            """set -Eeuo pipefail
source "$1"
RUN_FRONTEND_E2E=1
! resolve_local_frontend_e2e_mode
[[ "${RUN_FRONTEND_E2E}" == 1 ]]
[[ "$(wc -l < "${MOCK_NODE_LOG}")" -eq 1 ]]
grep -qx -- '--no-install playwright install chromium' "${MOCK_NPX_LOG}" """,
            "bash",
            str(helper_script),
        ],
        check=False,
        capture_output=True,
        env={
            "FRONTEND_PLAYWRIGHT_SENTINEL": str(tmp_path / ".playwright-installed"),
            "FRONTEND_PLAYWRIGHT_PACKAGE_LOCK": str(package_lock),
            "MOCK_NODE_LOG": str(node_log),
            "MOCK_NPX_LOG": str(npx_log),
            "OS_RELEASE_PATH": str(os_release),
            "PATH": f"{bin_dir}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
            "RUN_FRONTEND_E2E_AUTO_INSTALL": "1",
        },
        text=True,
    )
    if result.returncode != 0:
        node_log_content = (
            node_log.read_text(encoding="utf-8") if node_log.exists() else "<missing>"
        )
        npx_log_content = npx_log.read_text(encoding="utf-8") if npx_log.exists() else "<missing>"
        pytest.fail(
            "\n".join(
                [
                    f"bash returncode={result.returncode}",
                    f"stdout:\n{result.stdout}",
                    f"stderr:\n{result.stderr}",
                    f"node.log:\n{node_log_content}",
                    f"npx.log:\n{npx_log_content}",
                ]
            )
        )

    assert "Chromium cache'i bulunamadı" in result.stdout
    assert "RUN_FRONTEND_E2E=1" in result.stdout


def test_vitest_coverage_explicitly_lists_fully_covered_source_files() -> None:
    vite = Path("web_ui_react/vite.config.js").read_text(encoding="utf-8")

    assert 'include: ["src/**/*.{js,jsx,ts,tsx}"]' in vite
    assert 'reporter: [["text", { skipFull: false }], "text-summary", "html", "lcov"]' in vite
    assert "skipFull: false" in vite


def test_run_tests_stage_argument_contract_is_documented_and_wired() -> None:
    script = _script()

    assert (
        "Usage: bash run_tests.sh [--stage "
        "all|static|unit|integration|smoke|e2e|backend|frontend|bats[,..]]" in script
    )
    assert "normalize_test_stages()" in script
    assert "stage_all_selected()" in script
    assert "stage_selected()" in script
    assert "backend_infra_required_for_stage()" in script
    assert "SIDAR_RUN_BACKEND_PYTEST=0" in script
    assert (
        "if stage_selected backend || stage_selected unit || stage_selected integration || "
        "stage_selected smoke || stage_selected e2e; then" in script
    )
    assert "elif stage_selected static; then" in script
    assert "Unit-only stage: Docker/DB/Ollama önkoşulları atlandı." in script


def test_run_tests_stage_filters_pytest_phase_directories() -> None:
    script = _script()

    assert "local run_unit_phase=0" in script

    phase1_block = _run_tests_block_between(
        "local phase1_cmd=(",
        'echo "➡️ Aşama 1 (Unit) komutu',
    )
    assert '"${base_pytest_cmd[@]}"' in phase1_block
    assert '"--junitxml=${TEST_SUMMARY_JUNIT_DIR}/backend-unit.xml"' in phase1_block
    assert "tests/unit" in phase1_block

    assert "phase2_dirs+=(tests/integration)" in script
    assert "phase2_dirs+=(tests/smoke)" in script
    assert "phase2_dirs+=(tests/e2e)" in script
    assert 'local phase2_workers="${INTEGRATION_PYTEST_WORKERS:-2}"' in script

    phase2_parent = script.index('if [ "${#phase2_dirs[@]}" -gt 0 ]; then')
    phase2_block = _run_tests_block_between(
        "phase2_cmd=(",
        'echo "➡️ Aşama 2 (Integration/Smoke/E2E) komutu',
        start_offset=phase2_parent,
    )
    assert '"${filtered_phase2_cmd[@]}"' in phase2_block
    assert '"${phase2_cov_args[@]}"' in phase2_block
    assert (
        '"--junitxml=${TEST_SUMMARY_JUNIT_DIR}/backend-integration-smoke-e2e.xml"' in phase2_block
    )
    assert '-n "${phase2_workers}"' in phase2_block
    assert '"${phase2_dirs[@]}"' in phase2_block

    assert 'echo "ℹ️ Aşama 1 (Unit) atlandı (--stage=${RUN_TESTS_STAGE})."' in script
    assert (
        'echo "ℹ️ Aşama 2 (Integration/Smoke/E2E) atlandı (--stage=${RUN_TESTS_STAGE})."' in script
    )


def test_docker_compose_redis_has_healthcheck_and_healthy_dependencies() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    redis_start = compose.index("  redis:")
    postgres_start = compose.index("  postgres:", redis_start)
    redis_block = compose[redis_start:postgres_start]

    assert "healthcheck:" in redis_block
    assert '"CMD-SHELL", "redis-cli -a' in redis_block
    assert "ping | grep -q PONG" in redis_block
    assert "interval: 5s" in redis_block
    assert "timeout: 3s" in redis_block
    assert "retries: 20" in redis_block
    assert "redis:\n        condition: service_started" not in compose
    assert compose.count("redis:\n        condition: service_healthy") >= 4


def test_docker_compose_redis_requires_password_and_is_bound_to_loopback() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    redis_start = compose.index("  redis:")
    postgres_start = compose.index("  postgres:", redis_start)
    redis_block = compose[redis_start:postgres_start]

    assert "--requirepass" in redis_block
    assert "REDIS_PASSWORD:?" in redis_block
    assert "127.0.0.1:${REDIS_PORT:-6379}:6379" in redis_block
    assert "0.0.0.0:" not in redis_block


def test_install_sidar_remote_module_trust_root_requires_commit_pin() -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "resolve_remote_module_ref()" in install_script
    assert "validate_remote_module_trust_root()" in install_script
    assert "SIDAR_BOOTSTRAP_PINNED_REF=<40 karakter commit SHA>" in install_script
    assert "SIDAR_INSTALL_ALLOW_MUTABLE_MODULE_REF=1" in install_script
    assert '[[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]' in install_script
    assert "resolve_github_ref_commit_sha()" in install_script
    assert "api.github.com/repos/${owner_repo}/commits/${ref}" in install_script
    assert 'ls-remote "$repo_url"' in install_script
    assert '[[ "$github_token" =~ ^[A-Za-z0-9_]+$ ]] || return 1' in install_script


def test_install_sidar_resolves_mutable_ref_without_anonymous_github_api(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git_script = fake_bin / "git"
    git_script.write_text(
        "#!/usr/bin/env bash\n"
        "printf '0123456789abcdef0123456789abcdef01234567\\trefs/heads/main\\n'\n",
        encoding="utf-8",
    )
    git_script.chmod(0o755)
    curl_script = fake_bin / "curl"
    curl_script.write_text(
        "#!/usr/bin/env bash\nprintf 'anonymous API fallback must not run\\n' >&2\nexit 99\n",
        encoding="utf-8",
    )
    curl_script.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            "source ./install_sidar.sh >/dev/null 2>&1; "
            "resolve_github_ref_commit_sha https://github.com/example/project.git main",
        ],
        capture_output=True,
        env={
            "HOME": os.environ.get("HOME", "/tmp"),
            "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin",
            "SIDAR_INSTALL_TEST_MODE": "1",
        },
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "0123456789abcdef0123456789abcdef01234567"
    assert "anonymous API fallback" not in result.stderr


def test_install_sidar_does_not_use_anonymous_api_when_git_resolution_fails(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command in ("git", "curl"):
        script = fake_bin / command
        script.write_text(
            f"#!/usr/bin/env bash\nprintf '{command} invoked\\n' >> \"$CALL_LOG\"\nexit 1\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
    call_log = tmp_path / "calls.log"

    result = subprocess.run(
        [
            "bash",
            "-c",
            "source ./install_sidar.sh >/dev/null 2>&1; "
            "resolve_github_ref_commit_sha https://github.com/example/project.git main",
        ],
        capture_output=True,
        env={
            "CALL_LOG": str(call_log),
            "HOME": os.environ.get("HOME", "/tmp"),
            "PATH": f"{fake_bin}{os.pathsep}/usr/bin:/bin",
            "SIDAR_INSTALL_TEST_MODE": "1",
        },
        text=True,
    )

    assert result.returncode != 0
    assert call_log.read_text(encoding="utf-8").splitlines() == ["git invoked"]


def test_ci_publish_standalone_installer_depends_on_installer_smoke_only() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    publish_block = ci[ci.index("  publish-standalone-installer:") :]
    publish_block = publish_block[: publish_block.index("    steps:")]

    assert "needs: [installer-smoke]" in publish_block
    assert "needs: [production-readiness, pg-stress]" not in publish_block
    assert "Heavy runtime gates" in publish_block


def test_install_sidar_embedded_remote_module_ref_is_pinned_commit() -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert 'SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="unknown"' not in install_script
    assert re.search(
        r'^SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="[0-9a-f]{40}"$',
        install_script,
        re.MULTILINE,
    )


def test_install_sidar_validate_remote_module_trust_root_blocks_raw_github_main() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            textwrap.dedent(
                """\
                set -Eeuo pipefail
                source ./install_sidar.sh >/dev/null 2>&1
                SIDAR_INSTALL_MODULE_BASE_URL="https://raw.githubusercontent.com"
                SIDAR_INSTALL_MODULE_BASE_URL+="/niluferbagevi-gif/Sidar/main"
                SIDAR_INSTALL_MODULE_BASE_URL+="/scripts/install_modules"
                remote_base="$(resolve_remote_module_base)"
                validate_remote_module_trust_root "$remote_base"
                """
            ),
        ],
        capture_output=True,
        env={
            "HOME": os.environ.get("HOME", "/tmp"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "SIDAR_INSTALL_TEST_MODE": "1",
        },
        text=True,
    )

    assert result.returncode != 0
    assert "Fallback modül güven kökü zayıf" in result.stderr
    assert "mutable GitHub ref (main)" in result.stderr


def test_install_sidar_resolve_remote_module_base_accepts_commit_pinned_raw_github() -> None:
    pinned_ref = "0123456789abcdef0123456789abcdef01234567"
    result = subprocess.run(
        [
            "bash",
            "-c",
            textwrap.dedent(
                f"""\
                set -Eeuo pipefail
                source ./install_sidar.sh >/dev/null 2>&1
                SIDAR_BOOTSTRAP_PINNED_REF={pinned_ref}
                unset SIDAR_INSTALL_MODULE_BASE_URL
                resolve_remote_module_base
                """
            ),
        ],
        check=True,
        capture_output=True,
        env={
            "HOME": os.environ.get("HOME", "/tmp"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "SIDAR_INSTALL_TEST_MODE": "1",
        },
        text=True,
    )

    assert result.stdout.strip() == (
        "https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/"
        f"{pinned_ref}/scripts/install_modules"
    )


def test_installer_warns_when_production_env_shares_local_generated_secrets() -> None:
    env_phase = Path("scripts/install_modules/phases/08_env.sh").read_text(encoding="utf-8")

    assert "sidar_production_secret_rotation_keys()" in env_phase
    assert "emit_production_secret_rotation_notice()" in env_phase
    for key in (
        "API_KEY",
        "JWT_SECRET_KEY",
        "MEMORY_ENCRYPTION_KEY",
        "AUTONOMY_WEBHOOK_SECRET",
        "SWARM_FEDERATION_SHARED_SECRET",
        "GITHUB_WEBHOOK_SECRET",
        "GRAFANA_ADMIN_PASSWORD",
        "METRICS_TOKEN",
    ):
        assert key in env_phase
    assert "docs/runbooks/production-secret-rotation.md" in env_phase
    assert "python -m scripts.rotate_production_secrets" in env_phase
    assert 'emit_production_secret_rotation_notice "$src"' in env_phase
    assert "sidar_shared_production_secret_keys()" in env_phase
    assert "production_secret_rotation_gate_passes()" in env_phase
    assert "SIDAR_ENV=production kalıcılaştırması engellendi" in env_phase
    propagate_start = env_phase.index("propagate_shared_secrets_to_env_variants()")
    propagate_end = env_phase.index("# GPU tespiti", propagate_start)
    propagate_block = env_phase[propagate_start:propagate_end]
    assert '".env.production:.env.production.example"' not in propagate_block
    assert ".env.production bilinçli olarak oluşturulmaz veya doldurulmaz" in propagate_block


def test_installer_pin_finalize_workflow_is_one_documented_command() -> None:
    finalize = Path("scripts/finalize_install_module_pin.sh").read_text(encoding="utf-8")
    sync = Path("scripts/sync_install_module_hashes.sh").read_text(encoding="utf-8")
    makefile = Path("Makefile").read_text(encoding="utf-8")
    checklist = Path(".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")

    assert "make finalize-install-module-pin" in sync
    assert "finalize-install-module-pin:" in makefile
    assert "bash scripts/finalize_install_module_pin.sh" in makefile
    assert "git diff --cached --quiet -- scripts/install_modules" in finalize
    assert 'source_commit="$(git rev-parse HEAD)"' in finalize
    assert '--target "$TARGET" --check-manifest-only' in finalize
    assert '--stamp-commit "$source_commit"' in finalize
    assert '--target "$TARGET" --check-pin' in finalize
    assert "git commit -m" in finalize
    assert "make finalize-install-module-pin" in checklist


def test_production_secret_rotation_gate_rejects_shared_values(tmp_path: Path) -> None:
    local_env = tmp_path / ".env"
    production_env = tmp_path / ".env.production"
    shared = "shared-secret-value-abcdefghijklmnopqrstuvwxyz"
    local_env.write_text(f"API_KEY={shared}\n", encoding="utf-8")
    production_env.write_text(f"API_KEY={shared}\n", encoding="utf-8")

    probe = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/install_modules/utils/env_utils.sh; "
            "source scripts/install_modules/phases/08_env.sh; "
            'SCRIPT_DIR="$1"; warn() { :; }; '
            'if production_secret_rotation_gate_passes "$1/.env"; then echo allowed; '
            "else echo blocked; fi",
            "gate-probe",
            str(tmp_path),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=True,
    )

    assert probe.stdout.strip() == "blocked"


def test_production_secret_rotation_gate_rejects_missing_production_profile(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("API_KEY=local-only-secret\n", encoding="utf-8")

    probe = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/install_modules/utils/env_utils.sh; "
            "source scripts/install_modules/phases/08_env.sh; "
            'SCRIPT_DIR="$1"; warn() { :; }; '
            'if production_secret_rotation_gate_passes "$1/.env"; then echo allowed; '
            "else echo blocked; fi",
            "gate-probe",
            str(tmp_path),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=True,
    )

    assert probe.stdout.strip() == "blocked"
