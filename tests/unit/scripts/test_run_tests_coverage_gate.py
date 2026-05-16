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
    assert 'BASH_REMATCH' not in script[script.index("resolve_benchmark_compare_target()") :]
    assert 'benchmark_cmd+=(--benchmark-compare="${BENCHMARK_COMPARE_SELECTOR}")' in script
    assert "baseline=${BENCHMARK_COMPARE_FILE}" in script
    assert "İlk benchmark koşusu --benchmark-save=${BENCHMARK_BASELINE_NAME}" in script
    assert "BENCHMARK_COMPARE_REQUIRED=1 iken karşılaştırma için baseline bulunamadı" in script


def test_advanced_env_examples_enable_benchmark_compare_without_requiring_existing_baseline() -> None:
    env_advanced = Path(".env.advanced").read_text(encoding="utf-8")
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")

    for content in (env_advanced, env_test_example):
        assert "BENCHMARK_ENABLE_COMPARE=1" in content
        assert "BENCHMARK_COMPARE_REQUIRED=0" in content
        assert "BENCHMARK_COMPARE_NAME=baseline" in content

    assert "Override hiyerarşisi" in env_advanced
    assert "AUTONOMOUS_LOOP_COVERAGE_XML=coverage.xml" in env_advanced
    assert "SIDAR_EVENT_BUS_BACKEND=redis" in env_advanced
    assert "SIDAR_RABBITMQ_URL=" in env_advanced
    assert "SIDAR_KAFKA_BOOTSTRAP_SERVERS=" in env_advanced
    assert "SIDAR_JUDGE_AUTO_FEEDBACK_ENABLED=true" in env_advanced
    assert "AUTONOMOUS_LOOP_MUTATION_ENABLED=true" in env_advanced
    assert "ENABLE_LORA_TRAINING=false" in env_advanced
    assert "DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime" in env_advanced


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
    assert "OLLAMA_NUM_PARALLEL=4" in env_development


def test_test_env_uses_stronger_postgres_password_and_runtime_database_url() -> None:
    env_test_example = Path(".env.test.example").read_text(encoding="utf-8")

    assert "POSTGRES_PASSWORD=sidar_test_secure_pw" in env_test_example
    assert "POSTGRES_PASSWORD=sidar\n" not in env_test_example
    assert "DATABASE_URL=postgresql" not in env_test_example
    assert "TEST_DATABASE_URL=" not in env_test_example
    assert "izole test DATABASE_URL değerini çalışma zamanında üretir" in env_test_example


def test_install_sidar_bootstraps_env_secrets_after_uv_sync() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "ensure_env_file_secrets_after_uv_sync" in script
    assert 'ok "Python bağımlılıkları kilitli uv.lock üzerinden senkronlandı."' in script
    assert "ensure_env_file_secrets_after_uv_sync" in script[
        script.index("install_python_deps()") : script.index("# ── 5.1 Pyright")
    ]
    assert "Boş .env dosyası uv sync sonrası .env.example ile dolduruldu." in script
    assert "POSTGRES_PASSWORD otomatik ve güvenli bir değerle oluşturuldu" in script


def test_install_sidar_treats_change_me_placeholders_as_weak_secrets() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "change-me*|replace-with-*" in script
    assert 'is_weak_secret_value "$val" && return 0' in script


def test_install_sidar_uses_central_weak_secret_hash_registry() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    weak_hashes = Path("scripts/known_weak_secret_hashes.txt").read_text(encoding="utf-8")

    assert "is_example_secret_value" in script
    assert "is_known_weak_secret_hash" in script
    assert "scripts/known_weak_secret_hashes.txt" in script
    assert "historical API_KEY sample" in weak_hashes
    assert "historical JWT_SECRET_KEY sample" in weak_hashes
    assert "historical METRICS_TOKEN sample" in weak_hashes
    assert 'API_KEY" "change-me-api-key"' in script
    assert "historical API_KEY sample" not in script


def test_install_sidar_uses_entropy_heuristics_for_weak_passwords() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert 'case "$db_password" in' not in script
    assert 'if is_weak_secret_value "$db_password"; then' in script
    assert "is_low_entropy_secret_value" in script
    assert "entropy < 80" in script
    assert "qwerty*|password*|test123*" in script
    assert "DATABASE_URL varsayılan/zayıf parola içeriyor (${db_user}:***)" in script


def test_install_sidar_redacts_sensitive_log_stream_before_tee() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "redact_install_log_stream" in script
    assert 'exec > >(redact_install_log_stream | tee -i >(strip_ansi_stream > "$LOG_FILE")) 2>&1' in script
    assert "SENSITIVE_ASSIGNMENT" in script
    assert "DB_URL_WITH_PASSWORD" in script
    assert "AUTH_HEADER" in script
    assert "generated_password|safe_db_url|container_db_url|db_password" in script


def test_install_sidar_requires_stash_ref_before_destructive_git_cleanup() -> None:
    repo_phase = Path("scripts/install_modules/phases/02_repo.sh").read_text(encoding="utf-8")

    assert 'local STASH_REF=""' in repo_phase
    assert "git stash list -n 1 --format='%gd'" in repo_phase
    assert 'git stash pop "$STASH_REF"' in repo_phase
    assert 'git rev-parse -q --verify "$STASH_REF"' in repo_phase
    assert "git clean -fd çalıştırılmadı" in repo_phase
    assert "Stash yedeği ${STASH_REF} korunarak" in repo_phase
    assert "Stash yedeği korunuyor: ${STASH_REF}" in repo_phase
    assert "Manuel çözün veya '$TARGET_DIR' içinde 'git reset --hard origin/main && git clean -fd' çalıştırın" not in repo_phase


def test_install_sidar_loads_phase_modules_for_repo_and_system_steps() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    system_phase = Path("scripts/install_modules/phases/01_system.sh").read_text(encoding="utf-8")
    repo_phase = Path("scripts/install_modules/phases/02_repo.sh").read_text(encoding="utf-8")
    bundler = Path("scripts/tools/bundle_install_sidar.sh").read_text(encoding="utf-8")

    assert '"phases/01_system.sh"' in script
    assert '"phases/02_repo.sh"' in script
    assert 'source "$install_phase_path"' in script
    assert "install_system_dependencies()" not in script
    assert "sync_repo()" not in script
    assert "install_system_dependencies()" in system_phase
    assert "sync_repo()" in repo_phase
    assert "report_repo_lookup_context()" in repo_phase
    assert "-type f" in bundler
    assert "*.sh" in bundler
    assert "maxdepth 1" not in bundler
