from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import textwrap
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

RUN_TESTS = Path("run_tests.sh")


def _script() -> str:
    return RUN_TESTS.read_text(encoding="utf-8")


def _run_tests_block_between(start_marker: str, end_marker: str, *, start_offset: int = 0) -> str:
    """Return a run_tests.sh block for structure-oriented shell assertions."""
    script = _script()
    start = script.index(start_marker, start_offset)
    return script[start : script.index(end_marker, start)]


def installer_contract_sources() -> str:
    """Return the modular installer contract surface as one searchable string."""
    paths = [Path("install_sidar.sh"), *sorted(Path("scripts/install_modules").rglob("*.sh"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_run_tests_function(name: str) -> str:
    script = _script()
    start_marker = f"{name}() {{"
    start = script.index(start_marker)
    next_function = script.index("\nresolve_docker_compose_cmd()", start)
    return script[start:next_function]


def test_run_tests_omits_set_e_but_centralizes_exit_code_checks_via_run_checked() -> None:
    """Regression test: run_tests.sh intentionally runs without `set -e` (it must

    keep running later test phases/quality gates even after an earlier one
    fails, then aggregate a combined exit code), but every command whose exit
    code feeds into that aggregate must go through the shared run_checked()
    helper instead of ad hoc, inconsistent `cmd; x=$?` / `cmd || true` patterns.
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
    assert coverage_fail_under >= 99

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
        'sync_postgres_login_role "${admin_db_user}" "${POSTGRES_USER:-sidar}" "${POSTGRES_PASSWORD}"'
        in script
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
        "BENCHMARK_COMPARE_REQUIRED=1 BENCHMARK_ENFORCE_COMPARE=1 RUN_BENCHMARKS=required ./run_tests.sh"
        in script
    )
    assert "GitHub Actions cache/artifact üzerinden seed/restore eder" in script
    assert "BENCHMARK_COMPARE_REQUIRED=1 iken karşılaştırma için baseline bulunamadı" in script
    assert 'if [ "${IS_CI_ENV}" -eq 1 ]; then' in script
    assert (
        "Yerel bootstrap: BENCHMARK_COMPARE_REQUIRED=1 olsa da baseline bulunamadığı için ilk benchmark koşusu karşılaştırmasız çalıştırılacak"
        in script
    )
    assert "benchmark_compare_target_found=0" in script
    assert "benchmark_compare_target_found=1" in script
    assert "Benchmark baseline kaydı hazır: ${BENCHMARK_COMPARE_FILE}" in script
    assert "Sonraki benchmark koşusunda --benchmark-compare=${BENCHMARK_COMPARE_SELECTOR}" in script
    assert (
        "Benchmark JSON üretildi ancak .benchmarks altında '${BENCHMARK_COMPARE_NAME}' baseline kaydı doğrulanamadı"
        in script
    )


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
    assert "BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh" in readme
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


def test_pytest_conftest_checks_env_test_postgres_password_parity() -> None:
    conftest = Path("tests/conftest.py").read_text(encoding="utf-8")

    assert "_assert_test_dotenv_postgres_parity()" in conftest
    assert ".env.test içindeki POSTGRES_PASSWORD" in conftest
    assert "scripts/sync_database_passwords.py --all-envs" in conftest
    assert "InvalidPasswordError" in conftest
    assert conftest.index("_load_pytest_dotenv_chain()") < conftest.index(
        "_assert_test_dotenv_postgres_parity()"
    )


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
        "--production-readiness) RUN_CI_FULL_VALIDATION=true; "
        "NO_INTERACTION=true ;;"
    ) in install_script
    assert (
        'if [[ "$AUTO_ENV_TYPE" == "production" '
        '&& "$RUN_CI_FULL_VALIDATION" != true ]]; then'
    ) in install_script
    assert "RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all" in install_script
    run_tests_script = Path("run_tests.sh").read_text(encoding="utf-8")
    assert (
        'PRODUCTION_READINESS_COMMAND="TEST_PROFILE=ci RUN_BENCHMARKS=required '
        'RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"'
    ) in run_tests_script
    assert "Development full validation başarıyla tamamlandı" in run_tests_script
    assert "Production readiness profili çalıştırılmadı" in run_tests_script
    assert "Tam doğrulama durumu: ÇALIŞTIRILMADI" not in run_tests_script
    assert "assert_production_readiness_request" in run_tests_script
    assert "production_readiness_gate_active" in run_tests_script
    assert "SIDAR_PRODUCTION_READINESS=1" in validation_phase
    assert "run_install_frontend_quality_validation()" in validation_phase
    assert "run_tests.sh --stage frontend" in validation_phase
    assert "lint, typecheck, test:coverage, test:e2e:smoke" in validation_phase
    assert "SIDAR_PRODUCTION_READINESS" in install_script
    assert "sidar_install_production_gate_required()" in validation_phase
    assert "Production readiness gate başarısız" in validation_phase
    assert "Development tam doğrulaması başarısız oldu" in validation_phase
    assert "production-ready/merge kabulü için tam doğrulama başarıyla geçmelidir" in validation_phase
    assert "Tam doğrulama sonucu: HATA" in validation_phase
    assert "uygulama geliştirme amacıyla çalışabilir" in validation_phase
    assert "production-ready sayılmaz" in validation_phase
    assert "PRODUCTION GATE: Tam CI/e2e/benchmark doğrulaması zorunludur" in validation_phase
    assert "DEVELOPMENT UYARISI" in validation_phase
    assert "production_readiness_status_reported=false" in validation_phase
    assert "Development full validation geçti = geliştirici ortamı sağlıklı" in validation_phase
    assert (
        "env TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
        "SIDAR_PRODUCTION_READINESS=1 AUTO_OPEN_ARTIFACTS=0"
    ) in validation_phase
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
    assert "**“Development full validation geçti”**: geliştirici ortamı sağlıklı" in readme
    assert "**“Production readiness çalıştırılmadı”**: release/merge/dağıtım öncesinde" in readme
    assert (
        "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
        "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
    ) in readme
    assert "frontend stage'in atlandığını görmek normaldir" in testing
    assert "Coverage yüzdesi yalnız tüm ilgili test fazları geçtiğinde" in testing
    assert "frontend kalite kapısı ise bilinçli opt-in gerektirir" in install_options
    assert "--with-integration verilmediği için frontend stage çalıştırılmadı" in install_options


def test_ci_workflow_documents_and_seeds_benchmark_baseline() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    testing = Path("docs/TESTING.md").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in ci
    assert "seed_benchmark_baseline:" in ci
    assert "seed-benchmark-baseline:" in ci
    assert "Seed benchmark baseline cache" in ci
    assert '--benchmark-save="${BENCHMARK_BASELINE_NAME}"' in ci
    assert "benchmark-baseline-seed" in ci
    assert "if: ${{ github.event_name != 'workflow_dispatch' || !inputs.seed_benchmark_baseline }}" in ci
    assert "Benchmark baseline missing" in ci
    assert "CI benchmark baseline cache boşsa ne yapılır?" in testing
    assert "seed_benchmark_baseline" in testing
    assert "benchmark-baseline-seed" in testing
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
    assert summary["production_ready"] is False
    assert summary["backend_failed_tests"] == []


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
    assert "Production readiness: GEÇMEDİ" in result.stdout
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
    assert "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all" in result.stdout
    assert result.stdout.count("Production readiness:") == 1
    assert "Production readiness: GEÇMEDİ" not in result.stdout


def test_install_alembic_logs_revision_and_db_source_observability() -> None:
    alembic_phase = Path("scripts/install_modules/phases/12_alembic.sh").read_text(
        encoding="utf-8"
    )

    assert "mask_alembic_db_url()" in alembic_phase
    assert "log_alembic_revision_observation()" in alembic_phase
    assert "Alembic DB URL kaynağı:" in alembic_phase
    assert "Alembic DB URL (maskeli):" in alembic_phase
    assert "Alembic current revizyon:" in alembic_phase
    assert "Alembic head revizyon:" in alembic_phase
    assert 'DB_URL_SOURCE=".env:DATABASE_URL"' in alembic_phase
    assert 'DB_URL_SOURCE=".env:POSTGRES_*"' in alembic_phase
    assert 'DB_URL_SOURCE=".env:DATABASE_URL (yenilendi)"' in alembic_phase
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
    assert "return \"process-env\"" in env_phase
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
    test_target_block = collect_block[
        test_start : collect_block.index("printf '%s", test_start)
    ]
    assert "if _sync_real_keys_to_test_env_enabled; then" in test_target_block
    assert 'targets+=("$optional_env_file")' in test_target_block
    assert "varsayılan güvenli davranış" in test_target_block
    assert "SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV=1" in test_target_block

def test_install_sidar_propagates_api_keys_to_env_variants_after_collection() -> None:
    install_script = Path("scripts/install_modules/phases/08_env.sh").read_text(encoding="utf-8")

    api_keys_start = install_script.index("sidar_user_api_key_names()")
    api_keys_block = install_script[api_keys_start : install_script.index("}", api_keys_start)]
    for key in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "JIRA_TOKEN",
        "TEAMS_WEBHOOK_URL",
    ):
        assert key in api_keys_block

    collect_start = install_script.index("collect_api_keys_interactive()")
    collect_block = install_script[
        collect_start : install_script.index("report_env_api_key_status()", collect_start)
    ]
    assert "mapfile -t KEY_ORDER < <(sidar_user_api_key_names)" in collect_block
    assert "_api_key_env_targets()" in collect_block
    assert 'local -a targets=("$env_file")' in collect_block
    assert 'local advanced_env_file="$SCRIPT_DIR/.env.advanced"' in collect_block
    assert 'optional_env_file="$SCRIPT_DIR/.env.development"' in collect_block
    assert 'optional_env_file="$SCRIPT_DIR/.env.test"' in collect_block
    assert "SIDAR_SYNC_REAL_KEYS_TO_TEST_ENV:-0" in collect_block
    assert "_sync_real_keys_to_test_env_enabled" in collect_block
    assert 'targets+=("$optional_env_file")' in collect_block
    assert "varsayılan güvenli davranış" in collect_block
    assert "mapfile -t target_env_files < <(_api_key_env_targets)" in collect_block
    assert 'for target in "${target_env_files[@]}"' in collect_block
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
            python_env.index("install_python_deps()") : python_env.index("install_pyright_lsp_tool()")
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
        "Manuel çözün veya '$TARGET_DIR' içinde 'git reset --hard origin/main && git clean -fd' çalıştırın"
        not in script
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
    assert "uv sync --frozen --extra dev-light" in readme
    assert "uv sync --frozen --extra dev-light" in testing_doc
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
        '"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${MISSING_PACKAGES[@]}"'
        in installer
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
    assert "RUN_GPU_STRESS=1 RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 bash run_tests.sh --stage all" in makefile
    assert "production-readiness:" in makefile
    assert (
        "TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 "
        "SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
    ) in makefile
    assert "frontend-gate:" in makefile
    assert "RUN_FRONTEND_E2E=1 FRONTEND_E2E_ENFORCE_RESULT=1 bash run_tests.sh --stage frontend" in makefile
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
    assert "id: check-core-install-manifest" in config
    assert "entry: uv run python scripts/tools/update_core_install_manifest.py --check" in config
    assert "id: check-install-module-hashes" in config
    assert (
        "entry: uv run python scripts/tools/update_install_module_hash_manifest.py "
        "--target install_sidar.sh --check"
    ) in config
    assert "stages: [pre-commit, pre-push]" in config
    assert ".sidar_manifest" in config
    assert "core/(memory|multimodal)" in config
    assert "scripts/install_modules/.*\\.(sh|ps1)" in config
    assert "uv run pre-commit install --hook-type pre-commit --hook-type pre-push" in readme
    assert "check-core-install-manifest" in readme
    assert "check-install-module-hashes" in readme
    assert "installer manifest drift" in readme
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
    update_tool = Path("scripts/tools/update_core_install_manifest.py").read_text(
        encoding="utf-8"
    )

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
    assert "SIDAR_INSTALL_TEST_MODE=1 SIDAR_INSTALL_VERSION_PROBE_ONLY=1 bash dist/install_sidar.sh" in ci_workflow
    assert "name: standalone-install-sidar" in ci_workflow
    assert "path: |" in ci_workflow
    assert "dist/install_sidar.sh" in ci_workflow
    assert "dist/MODULE_HASHES.txt" in ci_workflow
    assert "dist/INSTALLER_USAGE.md" in ci_workflow
    assert "softprops/action-gh-release@v2" in ci_workflow
    assert "github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v')" in ci_workflow
    assert "tag_name: ${{ startsWith(github.ref, 'refs/tags/v') && github.ref_name || 'installer-main' }}" in ci_workflow
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
    assert "Preferred release/bundle install" in bundle_script
    assert "Last-resort raw fallback" in bundle_script
    assert "raw main/install_sidar.sh yalnız release bundle mevcut değilse son çare" in bundle_script
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
    assert "Release bundle (önerilen)" in readme
    assert "varsayılan Release bundle, raw fallback son çare" in modularization_note
    assert "Normal kullanıcı, temiz kurulum, kurumsal/offline veya interneti kısıtlı" in readme
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
        install_script.index("use_existing_install_module_tree_if_available || true") : install_script.index(
            "if [[ \"${INSTALL_MODULES_DOWNLOADED:-0}\" != \"1\" ]]; then"
        )
    ]
    assert module_resolution_flow.index("use_existing_install_module_tree_if_available || true") < module_resolution_flow.index(
        "download_install_modules_to_temp"
    )
    missing_module_flow = install_script[install_script.index("use_existing_install_module_tree_if_available || true") :]
    assert missing_module_flow.index("download_install_modules_to_temp \"$REMOTE_MODULE_BASE\"") < missing_module_flow.index(
        "bootstrap_clone_and_reexec"
    )


def test_install_sidar_sources_existing_cwd_module_tree_before_remote_fallback(tmp_path: Path) -> None:
    runner_dir = tmp_path / "runner"
    runner_dir.mkdir()
    shutil.copy2("install_sidar.sh", runner_dir / "install_sidar.sh")

    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -Eeuo pipefail; script_path="$1"; set --; source "$script_path"; printf "%s\n" "$INSTALL_MODULE_DIR"',
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
            f'set -Eeuo pipefail; script_path="$1"; set --; source "$script_path"; {module_checks}; '
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

    assert 'SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES="${SIDAR_INSTALL_MODULE_DOWNLOAD_RETRIES:-5}"' in install_script
    assert "--retry-all-errors" in install_script
    assert "--connect-timeout" in install_script
    assert "--max-time" in install_script
    assert "remote_install_module_status_is_retryable()" in install_script
    assert "000|403|408|409|425|429|5??" in install_script
    assert "remote_install_module_retry_sleep" in install_script
    assert "Retry-After:" in install_script
    assert "SIDAR_INSTALL_MODULE_CACHE_ROOT" in install_script
    assert 'cache_sentinel="${cache_path}.ok"' in install_script
    assert "Fallback modül cache'den kullanıldı" in install_script
    assert "Cache korunur; aynı komut tekrar çalıştırıldığında başarılı modüller yeniden kullanılacaktır." in install_script
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
    main_body = script[
        script.index("main() {") : script.index(
            '\n}\n\nif [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]'
        )
    ]

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
    env_utils = Path("scripts/install_modules/utils/env_utils.sh").read_text(encoding="utf-8")
    ollama_utils = Path("scripts/install_modules/utils/ollama_models.sh").read_text(
        encoding="utf-8"
    )
    bundler = Path("scripts/tools/bundle_install_sidar.sh").read_text(encoding="utf-8")
    install_script = installer_contract_sources()

    assert "sidar_source_install_utils()" in helper
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
        'sidar_source_install_utils "python_env.sh" "database_url.sh" "db_credentials.sh" "env_utils.sh"'
        in workspace_phase
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
    assert services_phase.index(
        "Servis öncesi installer smoke gate Python bağımlılıkları doğrulanıyor"
    ) < services_phase.index(
        "Servis öncesi installer smoke gate başlamadan PostgreSQL dotenv profilleri eşitleniyor"
    )
    assert services_phase.index(
        "Servis öncesi installer smoke gate başlamadan PostgreSQL dotenv profilleri eşitleniyor"
    ) < services_phase.index("uv run pytest -q --no-cov -p no:xdist -x")
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
    assert "/dev/dxg" in preflight_utils
    assert "libcuda" in preflight_utils
    assert "Ollama API" in preflight_utils
    assert "detect_gpu()" in gpu_utils
    assert "setup_nvidia_docker()" in gpu_utils
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
    assert "sync_postgres_env_with_database_url()" in db_url_utils
    assert "ensure_database_url_defaults()" in db_url_utils
    assert "setup_env_file()" in env_utils
    assert 'ADVANCED_ENV_FILE="$SCRIPT_DIR/.env.advanced"' in env_utils
    assert 'ADVANCED_EXAMPLE_FILE="$SCRIPT_DIR/.env.advanced.example"' in env_utils
    assert 'cp "$ADVANCED_EXAMPLE_FILE" "$ADVANCED_ENV_FILE"' in env_utils
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

    assert 'module_dir "/utils' in bundler
    assert 'module_dir "/phases' in bundler


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
            sidar_retry_budget_for_failure 03_runtime 'sh /tmp/ollama_install_script' 'sudo: timed out'
            SIDAR_INSTALL_REMEDIATION_MAX_ATTEMPTS_TRANSIENT=2 \
                sidar_retry_budget_for_failure 03_runtime 'network fetch' 'temporary failure'
            sidar_retry_budget_for_failure 03_runtime 'pytest' 'deterministic failure'
            sidar_retry_budget_for_failure 04_workspace 'unknown' 'unknown'
            if sidar_is_deterministic_failure_signal 'sh /tmp/ollama_install_script' 'sudo: timed out deterministic'; then
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
    main_body = script[
        script.index("main() {") : script.index(
            '\n}\n\nif [[ "${SIDAR_INSTALL_TEST_MODE:-0}" != "1" ]]'
        )
    ]
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
            sidar_phase_remediation_strategy 03_runtime 'sh /tmp/ollama_install_script' 'sudo: timed out'
            report="$(find "$SCRIPT_DIR/artifacts/install/remediation" -type f -name '*_03_runtime.log' | sort | tail -n 1)"
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
            sidar_phase_remediation_strategy 03_runtime 'sh /tmp/ollama_install_script' 'sudo: timed out'
            report="$(find "$SCRIPT_DIR/artifacts/install/remediation" -type f -name '*_03_runtime.log' | sort | tail -n 1)"
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
    """Regression test: SIDAR_ENV unset/empty/unrecognized must fail closed

    (reject the volume reset) instead of silently defaulting to "development"
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
    """Regression test: both the password-hardening reset path and the

    smoke-test-forced reset path must go through the same SIDAR_ENV safety
    gate, so the smoke-test path can't bypass a brake the other one enforced.
    """
    services_phase = Path("scripts/install_modules/phases/06_services.sh").read_text(
        encoding="utf-8"
    )

    assert "sidar_postgres_volume_reset_allowed_for_env() {" in services_phase
    assert 'sidar_postgres_volume_reset_allowed_for_env "$env_file" || return 0' in services_phase
    assert 'sidar_postgres_volume_reset_allowed_for_env "$SCRIPT_DIR/.env"' in services_phase
    assert services_phase.count("sidar_postgres_volume_reset_allowed_for_env") == 3


def test_create_directories_permission_steps_no_longer_swallow_errors_silently() -> None:
    """Regression test: chmod/chown/setfacl failures in create_directories()

    must surface a diagnostic warning instead of being fully swallowed via
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
    """Regression test: the three near-duplicate awk-based .wslconfig helpers

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
            reason='Servis öncesi installer smoke gate başarısız: INSTALL_SIDAR_VERSION=<boş> beklenen pyproject.toml sürümüyle (5.2.0) eşleşmiyor.'
            sidar_retry_budget_for_failure 06_services 'run_pre_service_installer_smoke_gate' "$reason"
            if sidar_is_deterministic_failure_signal 'run_pre_service_installer_smoke_gate' "$reason"; then
                echo deterministic
            else
                echo transient
            fi
            if sidar_phase_remediation_strategy 06_services 'run_pre_service_installer_smoke_gate' "$reason"; then
                echo retry-scheduled
            else
                echo no-retry
            fi
            sidar_emit_remediation_guidance 06_services 'run_pre_service_installer_smoke_gate' "$reason"
            report="$(find "$SCRIPT_DIR/artifacts/install/remediation" -type f -name '*_06_services.log' | sort | tail -n 1)"
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
            report="$(find "$SCRIPT_DIR/artifacts/install/remediation" -type f -name '*_03_runtime.log' | sort | tail -n 1)"
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
        'verify_reexec_installer_or_fail "$HOME/Sidar/install_sidar.sh" "Mevcut $HOME/Sidar re-exec"'
        in script
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
    checksum_file = tmp_path / "remote_checksums.env"
    checksum_file.write_text(
        ': "${OLLAMA_INSTALL_SHA256:=file-ollama}"\n' ': "${UV_INSTALL_SHA256:=file-uv}"\n',
        encoding="utf-8",
    )

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
        env=os.environ.copy(),
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
    """Regression test: Volta/NVM installs must not use an unverified

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
            unset ALLOW_UNVERIFIED_REMOTE_SCRIPTS
            if download_verified_script_soft 'https://example.invalid/install.sh' '' 'probe_install'; then
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

    assert "read_env_value_from_file()" in script
    assert 'current_backend=$(read_env_value_from_file "RAG_VECTOR_BACKEND" "$env_file")' in script
    assert 'openai_key=$(read_env_value_from_file "OPENAI_API_KEY" "$env_file"' in script
    assert 'DB_URL=$(read_env_value_from_file "DATABASE_URL" "$ENV_FILE")' in script
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
    assert "--reinstall-package torch" in script
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
    assert "Test fazlarından biri başarısız olduğu için final coverage quality gate atlandı" in script
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


def test_run_tests_records_backend_failure_when_required_bats_is_missing() -> None:
    script = _script()
    bats_block = script[
        script.index("run_bats_shell_tests()") : script.index("enforce_combined_coverage_gate()")
    ]

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
    bats_block = script[
        script.index("run_bats_shell_tests()") : script.index("enforce_combined_coverage_gate()")
    ]

    assert 'AUTO_INSTALL_CI_SYSTEM_DEPS="${AUTO_INSTALL_CI_SYSTEM_DEPS:-0}"' in script
    assert 'if [ "${AUTO_INSTALL_CI_SYSTEM_DEPS}" != "1" ]; then' in auto_install_block
    assert "sudo -n true" not in auto_install_block
    assert "bash scripts/install_ci_system_deps.sh" in auto_install_block
    assert "try_auto_install_ci_system_deps || true" in bats_block
    assert "AUTO_INSTALL_CI_SYSTEM_DEPS=1 bash run_tests.sh" in bats_block


def test_run_tests_writes_bats_junit_report_to_configurable_artifact_dir() -> None:
    script = _script()
    bats_block = script[
        script.index("run_bats_shell_tests()") : script.index("enforce_combined_coverage_gate()")
    ]

    assert 'BATS_REPORT_DIR="${BATS_REPORT_DIR:-artifacts/bats}"' in script
    assert (
        'if [[ "${BATS_REPORT_DIR}" != artifacts/* || "${BATS_REPORT_DIR}" == *".."* ]]; then'
        in script
    )
    assert "BATS_REPORT_DIR yalnız artifacts/ altında güvenli bir göreli yol olabilir" in script
    assert (
        "rm -rf .pytest_cache .coverage .coverage.* coverage.xml htmlcov tests/pytest.log "
        'web_ui_react/coverage web_ui_react/playwright-report web_ui_react/test-results "${BATS_REPORT_DIR}"'
        in script
    )
    assert 'mkdir -p "${BATS_REPORT_DIR}"' in bats_block
    assert 'bats --report-formatter junit --output "${BATS_REPORT_DIR}" tests/shell' in bats_block
    assert "${BATS_REPORT_DIR}/report.xml" in bats_block


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
        "pip-audit --skip-editable --timeout 30 --format json --output artifacts/security/pip-audit-report.raw.json"
        in ci_workflow
    )
    assert (
        "python scripts/pip_audit_failure_artifact.py artifacts/security/pip-audit-report.raw.json artifacts/security/pip-audit-failure.json --timeout 30"
        in ci_workflow
    )
    assert "name: security-audit-artifacts" in ci_workflow
    assert "artifacts/security/" in ci_workflow
    assert "GHSA-rrmf-rvhw-rf47" in policy
    assert "CVE-2025-3000" in policy
    assert "2026-09-15" in policy


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
    ratchet-managed %99 baseline), the CI pre-merge gate — which
    inherits that same ratcheted baseline unless explicitly overridden — and
    the aspirational %100 coverage campaign. The script must surface all
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

    # Local/CI ratchet cap leaves a 1-point slack by default; campaign and
    # explicit strict-local opt-in open to 100.
    assert 'COVERAGE_RATCHET_MAX_GATE="99"' in script
    assert 'COVERAGE_RATCHET_MAX_GATE="100"' in script
    assert "COVERAGE_STRICT_LOCAL_RATCHET" in script
    tests_notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")
    coverage_agent_docs = Path("docs/COVERAGE_AGENT_KULLANIMI.md").read_text(encoding="utf-8")
    assert "Coverage gate ratcheted: %90 -> %99 (measured=%100.00)" in tests_notes
    assert "günlük local/CI ratchet cap `%99`" in coverage_agent_docs
    assert (
        '[ "${COVERAGE_CAMPAIGN_PROFILE}" -eq 1 ] || [ "${COVERAGE_STRICT_LOCAL_RATCHET:-0}" = "1" ]'
        in script
    )

    # pyproject.toml holds the ratchet-managed baseline (currently %99 and only
    # ever raised by coverage_ratchet.py), not the campaign target.
    assert pyproject["tool"]["coverage"]["report"]["fail_under"] >= 99

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
        "benchmark-baseline-${{ runner.os }}-py311-${{ github.ref_name }}-${{ github.run_id }}"
        in ci
    )
    assert "Resolve benchmark baseline gate mode" in ci
    assert "mkdir -p .benchmarks" in ci
    assert 'echo "BENCHMARK_COMPARE_REQUIRED=1" >> "$GITHUB_ENV"' in ci
    assert 'echo "BENCHMARK_COMPARE_REQUIRED=0" >> "$GITHUB_ENV"' not in ci
    assert "Benchmark baseline missing" in ci
    assert "exit 1" in ci
    assert "make production-readiness 2>&1 | tee artifacts/test_run.log" in ci
    assert "GITHUB_STEP_SUMMARY" in ci
    assert "CI production-readiness is fail-closed" in ci
    assert 'BENCHMARK_ENFORCE_COMPARE: "1"' in ci
    assert 'BENCHMARK_COMPARE_REQUIRED: "1"' not in ci
    assert 'BENCHMARK_COMPARE_FAIL: "mean:10%"' in ci
    assert ".benchmarks/" in gitignore
    assert 'RUN_GPU_BENCHMARKS: "full"' in nightly_gpu
    assert ".benchmarks/` dizinini repoya commit etmek yerine GitHub Actions cache" in notes
    assert "BENCHMARK_COMPARE_FAIL=mean:10%" in notes
    assert "koşu seed moduna düşmez" in notes
    assert "name: Benchmark baseline seed" in seed_workflow
    assert "workflow_dispatch:" in seed_workflow
    assert 'BENCHMARK_COMPARE_REQUIRED: "0"' in seed_workflow
    assert 'BENCHMARK_ENFORCE_COMPARE: "0"' in seed_workflow
    assert "actions/cache/save@v4" in seed_workflow
    assert "actions/upload-artifact@v4" in seed_workflow
    assert "benchmark-baseline-${{ runner.os }}-py311-${{ github.ref_name }}-${{ github.run_id }}" in seed_workflow
    assert "Benchmark baseline seed" in readme
    assert "Benchmark baseline seed" in notes


def test_gpu_concurrent_benchmark_uses_smoke_and_full_profiles() -> None:
    gpu_benchmark = Path("tests/performance/test_gpu_benchmark.py").read_text(encoding="utf-8")
    notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")
    env_advanced = Path(".env.advanced.example").read_text(encoding="utf-8")

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
    assert 'if [ "${RUN_FRONTEND_E2E}" = "1" ]; then' in script
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
        'printf \'%s\\n%s\\n\' "${executable_path}" "${lock_fingerprint}" > "${FRONTEND_PLAYWRIGHT_SENTINEL}" || true'
        in script
    )
    assert 'rm -f "${FRONTEND_PLAYWRIGHT_SENTINEL}"' in script
    assert "unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD" in script
    assert "npx --no-install playwright install chromium" in script
    assert (
        'PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER="${PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER:-${SCRIPT_DIR:-$(pwd)}/scripts/install_modules/utils/playwright_ubuntu_override.sh}"'
        in script
    )
    assert 'is_playwright_ubuntu_override_recommended "${os_release_path}"' in script
    assert (
        'run_playwright_ubuntu_override_install "${os_release_path}" "${playwright_timeout_ms}"'
        in script
    )
    assert "npx burada yalnızca gerçek browser install komutu olarak geçirilir" in script
    assert "RUN_FRONTEND_E2E=1" in script
    assert "RUN_FRONTEND_E2E=0" in script
    assert "npx playwright install chromium" in script
    assert script.index("export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1") < script.index("npm install")
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
    assert "npx playwright install --with-deps chromium" in ci
    assert 'FRONTEND_E2E_NPM_SCRIPT: "test:e2e:smoke"' in ci
    assert "name: Upload Playwright frontend smoke report" in ci
    assert "web_ui_react/playwright-report/" in ci
    assert "web_ui_react/test-results/" in ci
    package_json = Path("web_ui_react/package.json").read_text(encoding="utf-8")
    assert '"typecheck": "tsc --noEmit"' in package_json
    assert '"test:e2e:smoke": "playwright test e2e/chat-websocket.spec.js"' in package_json
    playwright = Path("web_ui_react/playwright.config.js").read_text(encoding="utf-8")
    assert '["html", { outputFolder: "playwright-report", open: "never" }]' in playwright
    assert 'outputDir: "test-results"' in playwright
    assert 'process.env.PLAYWRIGHT_HOST_PLATFORM_OVERRIDE || "auto-detect"' in playwright
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
    assert (
        'spawnSync("npm", ["audit", `--audit-level=${options.level}`, "--json"]' in npm_audit_safe
    )
    assert "npm-audit-report.raw.json" in npm_audit_safe
    assert "npm-audit-stderr.log" in npm_audit_safe
    assert "npm-audit-failure.json" in npm_audit_safe
    assert "audit endpoint returned an error" in npm_audit_safe
    assert "failure_category: category" in npm_audit_safe
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
printf '%s|%s|' "${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" "${PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT:-}"
grep -q '^VERSION_ID="24.04"$' "${OS_RELEASE_PATH}"
""",
        encoding="utf-8",
    )
    mock_install.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -Eeuo pipefail; source "$1"; is_playwright_ubuntu_override_recommended "$2"; run_playwright_ubuntu_override_install "$2" 120000 "$3"',
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


def test_shared_playwright_ubuntu_override_helper_does_not_probe_node_install_command(
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
if [[ "$*" == "--no-install playwright install chromium" ]]; then
  printf '%s|' "${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}"
  grep -q '^VERSION_ID="24.04"$' "${OS_RELEASE_PATH}"
  exit $?
fi
printf 'unexpected probe invocation: %s\n' "$*" >&2
exit 42
""",
        encoding="utf-8",
    )
    mock_npx.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -Eeuo pipefail; source "$1"; run_playwright_ubuntu_override_install "$2" 120000 "$3" --no-install playwright install chromium',
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

    assert result.stdout == "ubuntu24.04-x64|"
    assert npx_log.read_text(encoding="utf-8").splitlines() == [
        "--no-install playwright install chromium"
    ]


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
            'set -Eeuo pipefail; source "$1"; run_playwright_ubuntu_override_install "$2" 120000 "$3" -m playwright install chromium',
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
  printf 'install-platform=%s\n' "${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-unset}" >> "${MOCK_PYTHON_LOG}"
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
        pytest.fail(
            "\n".join(
                [
                    f"bash returncode={result.returncode}",
                    f"stdout:\n{result.stdout}",
                    f"stderr:\n{result.stderr}",
                    f"python.log:\n{python_log.read_text(encoding='utf-8') if python_log.exists() else '<missing>'}",
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
            'set -Eeuo pipefail; source "$1"; tmp="$(mktemp)"; printf "ID=ubuntu\nVERSION_ID="32.04"\n" > "$tmp"; ! is_playwright_ubuntu_override_recommended "$tmp"',
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
printf '%s|%s' "${OS_RELEASE_PATH:-}" "${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-unset}" > "${MOCK_PROBE_LOG}"
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
            'set -Eeuo pipefail; source "$1"; playwright_host_platform_is_officially_supported "$2" "$3"',
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
    script = _script()
    helper_script = tmp_path / "frontend_playwright_helpers.sh"
    helper_script.write_text(
        script[
            script.index("FRONTEND_PLAYWRIGHT_SENTINEL=") : script.index(
                "# 3) Frontend React testleri"
            )
        ],
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
[[ "$(wc -l < "${MOCK_NPX_LOG}")" -eq 1 ]]
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
        pytest.fail(
            "\n".join(
                [
                    f"bash returncode={result.returncode}",
                    f"ubuntu_version={ubuntu_version}",
                    f"expects_ubuntu_override={expects_ubuntu_override}",
                    f"stdout:\n{result.stdout}",
                    f"stderr:\n{result.stderr}",
                    f"node.log:\n{node_log.read_text(encoding='utf-8') if node_log.exists() else '<missing>'}",
                    f"npx.log:\n{npx_log.read_text(encoding='utf-8') if npx_log.exists() else '<missing>'}",
                    f"sentinel:\n{sentinel.read_text(encoding='utf-8') if sentinel.exists() else '<missing>'}",
                ]
            )
        )

    assert "Chromium cache'i otomatik kuruldu" in result.stdout
    assert "Chromium sentinel cache'i hazır" in result.stdout
    assert "Chromium cache'i hazırlanamadı" in result.stdout
    assert npx_log.read_text(encoding="utf-8").splitlines() == [
        "--no-install playwright install chromium"
    ]


def test_forced_frontend_playwright_mode_attempts_cache_install_before_failing(
    tmp_path: Path,
) -> None:
    script = _script()
    helper_script = tmp_path / "frontend_playwright_helpers.sh"
    helper_script.write_text(
        script[
            script.index("FRONTEND_PLAYWRIGHT_SENTINEL=") : script.index(
                "# 3) Frontend React testleri"
            )
        ],
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
        pytest.fail(
            "\n".join(
                [
                    f"bash returncode={result.returncode}",
                    f"stdout:\n{result.stdout}",
                    f"stderr:\n{result.stderr}",
                    f"node.log:\n{node_log.read_text(encoding='utf-8') if node_log.exists() else '<missing>'}",
                    f"npx.log:\n{npx_log.read_text(encoding='utf-8') if npx_log.exists() else '<missing>'}",
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
        "Usage: bash run_tests.sh [--stage all|static|unit|integration|smoke|e2e|backend|frontend|bats[,..]]"
        in script
    )
    assert "normalize_test_stages()" in script
    assert "stage_all_selected()" in script
    assert "stage_selected()" in script
    assert "backend_infra_required_for_stage()" in script
    assert "SIDAR_RUN_BACKEND_PYTEST=0" in script
    assert (
        "if stage_selected backend || stage_selected unit || stage_selected integration || stage_selected smoke || stage_selected e2e; then"
        in script
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
        '"--junitxml=${TEST_SUMMARY_JUNIT_DIR}/backend-integration-smoke-e2e.xml"'
        in phase2_block
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
    assert 'test: ["CMD", "redis-cli", "ping"]' in redis_block
    assert "interval: 5s" in redis_block
    assert "timeout: 3s" in redis_block
    assert "retries: 20" in redis_block
    assert "redis:\n        condition: service_started" not in compose
    assert compose.count("redis:\n        condition: service_healthy") >= 4
