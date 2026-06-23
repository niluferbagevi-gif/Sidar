from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

RUN_TESTS = Path("run_tests.sh")


def _script() -> str:
    return RUN_TESTS.read_text(encoding="utf-8")


def _extract_run_tests_function(name: str) -> str:
    script = _script()
    start_marker = f"{name}() {{"
    start = script.index(start_marker)
    next_function = script.index("\nresolve_docker_compose_cmd()", start)
    return script[start:next_function]


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
    coveragerc = Path(".coveragerc")

    assert coveragerc.exists()
    content = coveragerc.read_text(encoding="utf-8")
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "[report]" in content
    # .coveragerc is the *local* baseline (stable, achievable); the campaign
    # target lives in the COVERAGE_CAMPAIGN profile, not in this file.
    assert "fail_under = 90" in content
    assert "fail_under = 100" not in content
    assert pyproject["tool"]["coverage"]["run"]["branch"] is True
    assert "fail_under" not in pyproject["tool"]["coverage"]["report"]

    coverage_agent_docs = Path("docs/COVERAGE_AGENT_KULLANIMI.md").read_text(encoding="utf-8")
    test_plan_docs = Path("docs/TEST_OPTIMIZATION_PLAN.md").read_text(encoding="utf-8")
    project_report = Path("docs/PROJE_RAPORU.md").read_text(encoding="utf-8")

    assert "güncel repo gate: `%90`" in coverage_agent_docs
    assert "Branch coverage ölçümü `[tool.coverage.run] branch = true`" in test_plan_docs
    assert "Coverage Quality Gate" in project_report
    assert "fail_under=90" in project_report or "fail_under = 90" in project_report
    assert not any(
        line.strip() == ".coveragerc"
        for line in Path(".gitignore").read_text(encoding="utf-8").splitlines()
    )
    assert 'COVERAGE_RATCHET_STATE_FILE="${COVERAGE_RATCHET_STATE_FILE:-.coveragerc}"' in script
    assert "validate_coverage_ratchet_state()" in script
    assert 'if [ ! -f "${COVERAGE_RATCHET_STATE_FILE}" ]; then' in script
    assert "Coverage ratchet state dosyası bulunamadı" in script
    assert "Coverage ratchet baseline sıfırlanmış olabilir" in script
    assert 'DEFAULT_COVERAGE_FAIL_UNDER="$(validate_coverage_ratchet_state)" || exit 1' in script


def test_run_tests_defers_coverage_fail_under_until_combined_report() -> None:
    script = _script()

    assert "--cov-fail-under=0" in script
    assert 'coverage report --fail-under="${COVERAGE_FAIL_UNDER}"' in script
    # The user-facing echo surfaces both the baseline source and the resolved
    # profile so a developer can tell which gate they are running against.
    assert ".coveragerc baseline=" in script
    assert "profile=${COVERAGE_FAIL_UNDER_SOURCE}" in script


def test_run_tests_uses_loadgroup_distribution_for_xdist_state_isolation() -> None:
    script = _script()
    notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")

    assert 'PYTEST_DIST_MODE="${PYTEST_DIST_MODE:-loadgroup}"' in script
    assert 'base_pytest_cmd+=(-n "${PYTEST_WORKERS}" --dist "${PYTEST_DIST_MODE}")' in script
    assert 'local phase1_cmd=("${base_pytest_cmd[@]}" tests/unit)' in script
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

    assert "uv run python -m coverage html -d htmlcov" in gate_function
    assert "uv run python -m coverage xml -o coverage.xml" in gate_function
    assert "uv run python -m coverage json -o coverage.json" in gate_function


def test_gpu_defaults_are_cpu_friendly_and_auto_detect_runtime_hardware() -> None:
    script = _script()
    installer = Path("install_sidar.sh").read_text(encoding="utf-8")
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
    assert "USE_GPU=false" in env_development_example
    assert "REQUIRE_GPU=false" in env_development_example

    assert "REQUIRE_GPU=true" in installer
    assert "REQUIRE_GPU=false" in installer
    assert "USE_GPU=true, REQUIRE_GPU=true, GPU_MIXED_PRECISION=true" in installer
    assert "USE_GPU=false, REQUIRE_GPU=false, GPU_MIXED_PRECISION=false" in installer
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


def test_run_tests_enforces_benchmark_compare_and_requires_baseline_by_default() -> None:
    script = _script()

    assert 'BENCHMARK_ENABLE_COMPARE="${BENCHMARK_ENABLE_COMPARE:-1}"' in script
    assert script.count('BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-1}"') >= 2
    assert script.index('if [ "${TEST_PROFILE}" = "ci" ]; then') < script.index(
        'BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-1}"'
    )
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

    assert 'os.getenv("SIDAR_FORMAT_TABLE_MAX_MEAN_MS", "15.0")' in benchmark_test
    assert "format_table_mean_ms" in benchmark_test
    assert "async def _warm_postgresql_connection_pool(db: Database) -> None:" in benchmark_test
    assert 'await conn.execute("SELECT 1")' in benchmark_test
    assert "loop.run_until_complete(_warm_postgresql_connection_pool(db))" in benchmark_test
    assert "warmup_rounds=5" in benchmark_test
    assert "rounds=25" in benchmark_test


def test_benchmark_docs_require_uv_and_review_before_promoting_latest_baseline() -> None:
    notes = Path("docs/module-notes/tests.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")
    env_advanced = Path(".env.advanced.example").read_text(encoding="utf-8")

    assert "uv run pytest tests/performance/ --benchmark-save=baseline" in notes
    assert "commit_info.dirty" in notes
    assert "version-sort" in notes
    assert "2026-06-22 performans değerlendirmesinde 13 benchmark" in notes
    assert "test_format_table_handles_large_dataset_quickly` yaklaşık `3.7 ms" in notes
    assert "SIDAR_FORMAT_TABLE_MAX_MEAN_MS=15.0" in notes
    assert "test_gpu_vram_peak_under_load` için yaklaşık `2249 ms` mean" in notes
    assert "BENCHMARK_COMPARE_REQUIRED=1" in notes
    assert "BENCHMARK_ENFORCE_COMPARE=1" in notes
    assert "commit_info.dirty" in readme
    assert "version-sort" in readme
    assert "yerel profil de varsayılan `BENCHMARK_COMPARE_REQUIRED=1` nedeniyle fail-closed" in readme
    assert "BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh" in readme
    assert "BENCHMARK_COMPARE_REQUIRED=1" in readme
    assert "BENCHMARK_ENFORCE_COMPARE=1" in readme
    assert (
        "restore/seed edilmiş *_baseline.json kayıtları içinden en güncel eşleşmeyi seçer"
        in env_advanced
    )
    assert "Yeni makine/boş cache bootstrap istisnasında ilk baseline" in env_advanced
    assert "BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh" in env_advanced
    assert "SIDAR_FORMAT_TABLE_MAX_MEAN_MS=15.0" in env_advanced
    assert "mevcut 0004_baseline.json" not in env_advanced


def test_advanced_env_examples_enable_benchmark_compare_without_requiring_existing_baseline() -> (
    None
):
    env_advanced = Path(".env.advanced.example").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")

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


def test_install_sidar_propagates_api_keys_to_env_variants_after_collection() -> None:
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")

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
    assert '"$SCRIPT_DIR/.env.development" "$SCRIPT_DIR/.env.test"' in collect_block
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
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "ensure_env_file_secrets_after_uv_sync" in script
    assert 'ok "Python bağımlılıkları kilitli uv.lock üzerinden senkronlandı."' in script
    assert (
        "ensure_env_file_secrets_after_uv_sync"
        in script[script.index("install_python_deps()") : script.index("# ── 5.1 Pyright")]
    )
    assert "Boş .env dosyası uv sync sonrası .env.example ile dolduruldu." in script
    assert "POSTGRES_PASSWORD otomatik ve güvenli bir değerle oluşturuldu" in script


def test_install_sidar_treats_change_me_placeholders_as_weak_secrets() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "change-me*|replace-with-*" in script
    assert 'is_weak_secret_value "$val" && return 0' in script


def test_install_sidar_uses_central_known_weak_secret_list() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert 'if is_weak_secret_value "$db_password"; then' in script
    assert 'case "$db_password" in' not in script
    assert "secret_strength.py" in script
    assert "Password1" not in script


def test_install_sidar_never_runs_destructive_git_cleanup_without_stash_guard() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "resolve_sidar_locale()" in script
    assert "SIDAR_LOCALE" in script
    assert "${LANG:-${LC_ALL:-${LC_MESSAGES:-tr}}}" in script
    assert "sidar_t()" in script
    assert "Usage:" in script
    assert "Unknown argument:" in script
    assert "Select installer message language" in script


def test_ci_system_dependency_installer_provisions_shell_test_tools() -> None:
    installer = Path("scripts/install_ci_system_deps.sh").read_text(encoding="utf-8")
    sidar_installer = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "PACKAGES=(portaudio19-dev shellcheck bats)" in installer
    assert (
        "curl wget git build-essential shellcheck bats software-properties-common"
        in sidar_installer
    )
    assert (
        "AUTO_BUILD_DOCKER_TEST_IMAGE=1 DOCKER_TEST_IMAGE=sidar:latest bash run_tests.sh"
        in installer
    )
    assert "MISSING_PACKAGES=()" in installer
    assert "SUDO=(sudo -n)" in installer
    assert "if ! sudo -n true >/dev/null 2>&1; then" in installer
    assert "Passwordless or cached sudo is required for non-interactive installation." in installer
    assert "Run 'sudo -v' first" in installer
    assert (
        '"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${MISSING_PACKAGES[@]}"'
        in installer
    )


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

    assert '"pre-commit>=4.0.0,<5.0.0"' in pyproject
    assert "id: ruff-check" in config
    assert "entry: uv run ruff check --force-exclude" in config
    assert "id: ruff-format-check" in config
    assert "entry: uv run ruff format --check --force-exclude" in config
    assert "id: mypy" in config
    assert "entry: uv run mypy ." in config
    assert "pass_filenames: false" in config
    assert "id: shellcheck" in config
    assert "entry: uv run shellcheck --severity=warning -x" in config
    assert "autonomous_loop" in config
    assert "scripts/.*\\.(sh|bash)" in config


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
    readme = Path("README.md").read_text(encoding="utf-8")
    modularization_note = Path("docs/module-notes/install_sidar_modularization.md").read_text(
        encoding="utf-8"
    )

    assert "tags:" in ci_workflow
    assert '"v*"' in ci_workflow
    assert "bash scripts/tools/bundle_install_sidar.sh" in ci_workflow
    assert "bash -n dist/install_sidar.sh" in ci_workflow
    assert "name: standalone-install-sidar" in ci_workflow
    assert "path: |" in ci_workflow
    assert "dist/install_sidar.sh" in ci_workflow
    assert "dist/MODULE_HASHES.txt" in ci_workflow
    assert "softprops/action-gh-release@v2" in ci_workflow
    assert "files: |" in ci_workflow

    dynamic_url = "https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/main/install_sidar.sh"
    release_url = (
        "https://github.com/niluferbagevi-gif/Sidar/releases/latest/download/install_sidar.sh"
    )
    assert release_url in readme
    assert release_url in modularization_note
    for content in (readme, modularization_note):
        assert dynamic_url in content
        assert "git clone https://github.com/niluferbagevi-gif/Sidar.git" in content
        assert "uv sync --all-extras" in content
        assert "dinamik modül" in content
    assert "Varsayılan çevrimiçi kurulum yöntemi dinamik modül indiren betiktir" in readme
    assert "Standart çevrimiçi kullanıcı akışında ana yöntem" in modularization_note
    assert "Kurumsal, offline veya interneti kısıtlı" in readme
    assert "monolitik Release bundle" in modularization_note


def test_install_sidar_root_guard_allows_explicit_test_mode_only() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert '"${EUID:-$(id -u)}" -eq 0 && "${SIDAR_INSTALL_TEST_MODE:-0}" != "1"' in script


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
    assert "Test modu file:// fallback modül doğrulaması atlandı" in result.stderr
    assert "install_modules" in result.stdout


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
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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
    db_utils = Path("scripts/install_modules/utils/db_credentials.sh").read_text(encoding="utf-8")
    env_utils = Path("scripts/install_modules/utils/env_utils.sh").read_text(encoding="utf-8")
    ollama_utils = Path("scripts/install_modules/utils/ollama_models.sh").read_text(
        encoding="utf-8"
    )
    bundler = Path("scripts/tools/bundle_install_sidar.sh").read_text(encoding="utf-8")
    install_script = Path("install_sidar.sh").read_text(encoding="utf-8")

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
        'sidar_source_install_utils "python_env.sh" "db_credentials.sh" "env_utils.sh"'
        in workspace_phase
    )
    assert 'sidar_source_install_utils "ollama_models.sh"' in services_phase
    assert "sync_database_passwords_before_smoke_tests" in services_phase
    assert "ensure_env_test_postgres_password_matches_base_before_smoke" in services_phase
    assert "ensure_postgres_volume_reset_before_smoke_tests" in services_phase
    assert "uv run python scripts/sync_database_passwords.py --all-envs" in services_phase
    assert "uv run python scripts/sync_postgres_password.py" in services_phase
    assert "POSTGRES_PASSWORD değeri .env ile uyuşmuyor" in services_phase
    assert "docker compose down --volumes --remove-orphans" in services_phase
    assert "PostgreSQL volume reset doğrulanamadı" in services_phase
    assert services_phase.index(
        "sync_database_passwords_before_smoke_tests"
    ) < services_phase.index("run_smoke_tests")
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
    assert "create_uv_venv()" in python_env_utils
    assert "install_python_deps()" in python_env_utils
    assert "uv sync" in python_env_utils
    assert "uv pip" not in python_env_utils
    assert "uv tool install" not in python_env_utils
    assert "harden_database_credentials()" in db_utils
    assert "sync_postgres_env_with_database_url()" in db_utils
    assert "ensure_database_url_defaults()" in db_utils
    assert "setup_env_file()" in env_utils
    assert 'ADVANCED_ENV_FILE="$SCRIPT_DIR/.env.advanced"' in env_utils
    assert 'ADVANCED_EXAMPLE_FILE="$SCRIPT_DIR/.env.advanced.example"' in env_utils
    assert 'cp "$ADVANCED_EXAMPLE_FILE" "$ADVANCED_ENV_FILE"' in env_utils
    assert "propagate_shared_secrets_to_env_variants" in env_utils
    assert "sync_database_env_chain_after_setup()" in env_utils
    assert "uv run python -m scripts.sync_database_passwords --remove-explicit-urls" in env_utils
    assert "sync_database_env_chain_after_setup()" in install_script
    assert (
        "uv run python -m scripts.sync_database_passwords --remove-explicit-urls" in install_script
    )
    assert "migrasyon DSN'i POSTGRES_* parçalarından üretildi" in install_script
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


def test_install_sidar_ollama_install_keeps_sudo_alive_and_tolerates_post_install_rc() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    strict_mode_pos = script.index("set -Eeuo pipefail")
    default_pos = script.index('export GPU_AVAILABLE="${GPU_AVAILABLE:-false}"')
    phase_runner_pos = script.index('sidar_run_install_phase "01_context"')

    assert strict_mode_pos < default_pos < phase_runner_pos


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
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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


def test_install_sidar_remote_script_checksum_missing_is_classified_deterministic() -> None:
    result = subprocess.run(
        [
            "bash",
            "-c",
            """
            set -Eeuo pipefail
            source ./scripts/install_modules/utils/install_remediation.sh
            ollama_reason='ollama_install checksum değeri tanımlı değil. Supply-chain doğrulamasını korumak için OLLAMA_INSTALL_SHA256 değişkenini ayarlayın.'
            uv_reason='uv_install checksum değeri tanımlı değil. Supply-chain doğrulamasını korumak için UV_INSTALL_SHA256 değişkenini ayarlayın.'
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
            ollama_reason='ollama_install checksum değeri tanımlı değil. Supply-chain doğrulamasını korumak için OLLAMA_INSTALL_SHA256 değişkenini ayarlayın.'
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
            ollama_reason='ollama_install checksum değeri tanımlı değil. Supply-chain doğrulamasını korumak için OLLAMA_INSTALL_SHA256 değişkenini ayarlayın.'
            uv_reason='uv_install checksum değeri tanımlı değil. Supply-chain doğrulamasını korumak için UV_INSTALL_SHA256 değişkenini ayarlayın.'
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
    assert "TOFU" in combined or "tofu" in combined.lower()
    assert "ALLOW_UNVERIFIED_REMOTE_SCRIPTS" in combined


def test_install_sidar_remote_script_checksum_hint_warns_about_deterministic_wall() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    assert "no-retry;manual-fix-required" in script
    assert "deterministiktir" in script
    assert "auto-heal/retry aynı duvara çarpar" in script


def test_install_sidar_uses_single_source_project_version() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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


def test_install_sidar_runtime_mode_is_selected_once_before_service_launch() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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


def test_install_sidar_remote_script_checksum_failure_guides_operator() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    docs = Path("README.md").read_text(encoding="utf-8")
    modular_note = Path("docs/module-notes/install_sidar_modularization.md").read_text(
        encoding="utf-8"
    )

    assert "remote_script_checksum_hint()" in script
    assert "Supply-chain doğrulamasını korumak" in script
    assert r'less "\$tmp"' in script
    assert r"export ${checksum_var}=\$(sha256sum" in script
    assert "ALLOW_UNVERIFIED_REMOTE_SCRIPTS=1" in script
    assert "UV_INSTALL_SHA256" in docs
    assert "OLLAMA_INSTALL_SHA256" in docs
    assert "https://astral.sh/uv/install.sh" in docs
    assert "https://ollama.com/install.sh" in docs
    assert "UV_INSTALL_SHA256" in modular_note
    assert "OLLAMA_INSTALL_SHA256" in modular_note


def test_install_sidar_uv_steps_have_explicit_names_and_order() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert (
        'REPO_URL="${SIDAR_REPO_URL:-${REPO_URL:-https://github.com/niluferbagevi-gif/Sidar}}"'
        in script
    )
    assert 'REPO_URL="https://github.com/niluferbagevi-gif/Sidar"' not in script
    assert "SIDAR_REPO_URL=https://..." in script
    assert script.index("SIDAR_REPO_URL") < script.index('git clone "$REPO_URL"')


def test_install_sidar_uses_cross_platform_sed_inplace_wrapper() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    wrapper_start = script.index("sed_inplace() {")
    wrapper_end = script.index("\n}\n\n# BEGIN_BUNDLE_MODULES", wrapper_start) + len("\n}\n")
    wrapper_body = script[wrapper_start:wrapper_end]
    script_without_wrapper = script[:wrapper_start] + script[wrapper_end:]

    assert "Darwin) sed -i ''" in wrapper_body
    assert '*) sed -i "$expression" "$@"' in wrapper_body
    assert "sed -i " not in script_without_wrapper
    assert "sed_inplace 's/^ENABLE_MULTIMODAL=" in script
    assert 'sed_inplace "s|^DATABASE_URL=.*|DATABASE_URL=' in script


def test_install_sidar_centralizes_env_value_reads() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "read_env_value_from_file()" in script
    assert 'current_backend=$(read_env_value_from_file "RAG_VECTOR_BACKEND" "$env_file")' in script
    assert 'openai_key=$(read_env_value_from_file "OPENAI_API_KEY" "$env_file"' in script
    assert 'DB_URL=$(read_env_value_from_file "DATABASE_URL" "$ENV_FILE")' in script
    assert 'compose_profiles=$(read_env_value_from_file "COMPOSE_PROFILES" "$env_file"' in script
    assert "cut -d= -f2-" not in script
    assert 'grep -E "^${key}="' not in script


def test_install_sidar_prompt_timeout_is_centralized() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert 'SIDAR_PROMPT_TIMEOUT="${SIDAR_PROMPT_TIMEOUT:-180}"' in script
    assert "${2:-$SIDAR_PROMPT_TIMEOUT}" in script
    assert 'read -r -t "$SIDAR_PROMPT_TIMEOUT"' in script
    assert "SIDAR_PROMPT_TIMEOUT=180" in script
    assert "read -r -t 180" not in script
    assert "180 saniye içinde" not in script
    assert "${2:-180}" not in script


def test_install_sidar_flushes_typeahead_before_interactive_reads() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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
        script.index("prompt_yes_no_with_timeout_default_no()") : script.index("on_install_error()")
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
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
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

    assert 'record_backend_failure "bats_missing"' in script
    assert 'record_backend_failure "bats_failed"' in script
    assert "Backend kalite akışı başarısız olduğu için coverage ratchet atlandı" in ratchet_block
    assert "$(format_backend_failure_reasons)" in ratchet_block
    assert "Backend Hata Nedenleri: $(format_backend_failure_reasons)" in script
    assert (
        "Pytest/coverage kalite kapısı geçmediği için coverage ratchet atlandı" not in ratchet_block
    )


def test_run_tests_requires_bats_when_shell_tests_are_enabled() -> None:
    script = _script()
    bats_block = script[
        script.index("run_bats_shell_tests()") : script.index("enforce_combined_coverage_gate()")
    ]

    assert 'if [ "${RUN_BATS_TESTS}" != "1" ]; then' in bats_block
    assert "RUN_BATS_TESTS=1 ancak BATS bulunamadı" in bats_block
    assert "bash scripts/install_ci_system_deps.sh" in bats_block
    assert "BACKEND_EXIT_CODE=1" in bats_block
    assert "shell testleri opsiyonel olduğu için atlandı" not in bats_block


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


def test_ci_uploads_benchmark_reports_and_reviewable_baseline_candidates() -> None:
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    artifact_block = ci_workflow[
        ci_workflow.index(
            "- name: Upload Coverage XML + Benchmark JSON artifacts"
        ) : ci_workflow.index("- name: Upload Frontend Coverage Report")
    ]

    assert "name: backend-quality-trend-artifacts" in artifact_block
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

    AGENTS.md §2.5.4 separates the daily local gate (`.coveragerc` baseline),
    the stricter CI pre-merge gate, and the aspirational %100 coverage
    campaign. The script must surface all three knobs so a developer can run
    a fast local pass without colliding with the campaign target, while CI
    keeps a stricter pre-merge bar and the campaign opt-in still aims at %100.
    """

    script = _script()
    ci_workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    coveragerc = Path(".coveragerc").read_text(encoding="utf-8")
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

    # .coveragerc holds a sustainable baseline, not the campaign target.
    assert "fail_under = 90" in coveragerc
    assert "fail_under = 100" not in coveragerc

    # CI workflow sets the stricter pre-merge override for the main test job.
    assert "COVERAGE_FAIL_UNDER_CI:" in ci_workflow

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


def test_ci_restores_or_seeds_benchmark_baseline_and_nightly_gpu_uses_full_profile() -> None:
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    nightly_gpu = Path(".github/workflows/nightly-gpu-performance.yml").read_text(encoding="utf-8")
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
    assert 'echo "BENCHMARK_COMPARE_REQUIRED=0" >> "$GITHUB_ENV"' in ci
    assert "GITHUB_STEP_SUMMARY" in ci
    assert "reviewable baseline artifact/cache candidate" in ci
    assert 'BENCHMARK_ENFORCE_COMPARE: "1"' in ci
    assert 'BENCHMARK_COMPARE_REQUIRED: "1"' not in ci
    assert 'BENCHMARK_COMPARE_FAIL: "mean:10%"' in ci
    assert ".benchmarks/" in gitignore
    assert 'RUN_GPU_BENCHMARKS: "full"' in nightly_gpu
    assert ".benchmarks/` dizinini repoya commit etmek yerine GitHub Actions cache" in notes
    assert "BENCHMARK_COMPARE_FAIL=mean:10%" in notes
    assert "Cache boşsa ilk koşu seed baseline moduna alınır" in notes


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
    assert 'ENFORCE_FRONTEND_E2E' in script
    assert script.count(
        'FRONTEND_E2E_ENFORCE_RESULT="${FRONTEND_E2E_ENFORCE_RESULT:-${ENFORCE_FRONTEND_E2E:-1}}"'
    ) >= 2
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
    assert 'if [ "${RUN_FRONTEND_E2E}" != "auto" ]; then' in script
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
        < frontend_gate_block.index("npm run test:coverage")
    )
    assert "FRONTEND_NPM_AUDIT_RAN=1" in script
    assert "FRONTEND_NPM_AUDIT_EXIT_CODE=$?" in script
    assert "Dependency audit (npm run audit:high)" in script
    assert r"| Dependency audit | \`npm run audit:high\` |" in script
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
    assert '"/ws": { target: webSocketUrl, ws: true }' in vite
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
    assert "await page.goto(`${frontend.url}/chat`)" in websocket_spec
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

    assert '"audit:high": "node ../scripts/npm_audit_safe.js --level=high --retries=2"' in package_json
    assert "function classifyAuditFailure" in npm_audit_safe
    assert "FRONTEND_NPM_AUDIT_ALLOW_NETWORK_FAILURE" in npm_audit_safe
    assert "FRONTEND_NPM_AUDIT_MAX_RETRIES" in npm_audit_safe
    assert 'spawnSync("npm", ["audit", `--audit-level=${options.level}`, "--json"]' in npm_audit_safe
    assert "npm-audit-report.raw.json" in npm_audit_safe
    assert "npm-audit-stderr.log" in npm_audit_safe
    assert "npm-audit-failure.json" in npm_audit_safe
    assert "audit endpoint returned an error" in npm_audit_safe
    assert "failure_category: category" in npm_audit_safe
    assert "options.allowNetworkFailure = !process.env.CI && !process.env.GITHUB_ACTIONS" in npm_audit_safe
    assert (
        frontend_gate_block.index("npm run audit:high")
        < frontend_gate_block.index("npm run lint")
        < frontend_gate_block.index("npm run test:coverage")
    )


def test_frontend_security_dependencies_are_patched_in_package_lock() -> None:
    package_json = json.loads(Path("web_ui_react/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads(Path("web_ui_react/package-lock.json").read_text(encoding="utf-8"))

    dev_deps = package_json["devDependencies"]
    locked_root_deps = package_lock["packages"][""]["devDependencies"]
    locked_packages = package_lock["packages"]

    assert dev_deps["vite"] == "^8.0.16"
    assert dev_deps["ws"] == "^8.21.0"
    assert locked_root_deps["vite"] == "^8.0.16"
    assert locked_root_deps["ws"] == "^8.21.0"
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
        """#!/usr/bin/env bash
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


def test_shared_playwright_ubuntu_override_helper_skips_override_when_upstream_supports_host(
    tmp_path: Path,
) -> None:
    helper = Path("scripts/install_modules/utils/playwright_ubuntu_override.sh").resolve()
    os_release = tmp_path / "os-release"
    mock_python = tmp_path / "mock-python.sh"
    probe_log = tmp_path / "probe.log"
    os_release.write_text('ID=ubuntu\nVERSION_ID="26.04"\n', encoding="utf-8")
    mock_python.write_text(
        """#!/usr/bin/env bash
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

    assert 'gtk_package="libgtk-3-0"' in helper
    assert 'gtk_package="libgtk-3-0t64"' in helper
    assert "libxshmfence1" in helper
    installer = Path("install_sidar.sh").read_text(encoding="utf-8")
    assert (
        '! playwright_host_platform_is_officially_supported "$_pw_os_release_path" "${PY_CMD[@]}"'
        in installer
    )


def test_local_frontend_playwright_sentinel_skips_repeat_node_resolution_and_removes_stale_cache(
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
    browser = tmp_path / "chromium"
    sentinel = tmp_path / ".playwright-installed"
    node_log = tmp_path / "node.log"
    npx_log = tmp_path / "npx.log"
    package_lock = tmp_path / "package-lock.json"
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
        """#!/usr/bin/env bash
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
            "-c",
            """set -Eeuo pipefail
source "$1"
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
        check=True,
        capture_output=True,
        env={
            "FRONTEND_PLAYWRIGHT_SENTINEL": str(sentinel),
            "FRONTEND_PLAYWRIGHT_PACKAGE_LOCK": str(package_lock),
            "MOCK_BROWSER": str(browser),
            "MOCK_NODE_LOG": str(node_log),
            "MOCK_NPX_LOG": str(npx_log),
            "PATH": f"{bin_dir}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
            "RUN_FRONTEND_E2E_AUTO_INSTALL": "1",
        },
        text=True,
    )

    assert "Chromium cache'i otomatik kuruldu" in result.stdout
    assert "Chromium sentinel cache'i hazır" in result.stdout
    assert "Chromium cache'i hazırlanamadı" in result.stdout


def test_vitest_coverage_explicitly_lists_fully_covered_source_files() -> None:
    vite = Path("web_ui_react/vite.config.js").read_text(encoding="utf-8")

    assert 'include: ["src/**/*.{js,jsx}"]' in vite
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
    assert 'local phase1_cmd=("${base_pytest_cmd[@]}" tests/unit)' in script
    assert "phase2_dirs+=(tests/integration)" in script
    assert "phase2_dirs+=(tests/smoke)" in script
    assert "phase2_dirs+=(tests/e2e)" in script
    assert 'echo "ℹ️ Aşama 1 (Unit) atlandı (--stage=${RUN_TESTS_STAGE})."' in script
    assert (
        'echo "ℹ️ Aşama 2 (Integration/Smoke/E2E) atlandı (--stage=${RUN_TESTS_STAGE})."' in script
    )
    assert (
        'phase2_cmd=("${filtered_phase2_cmd[@]}" "${phase2_cov_args[@]}" -n "${phase2_workers}" "${phase2_dirs[@]}")'
        in script
    )
