from __future__ import annotations

import shutil
import subprocess
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
    variants_block = install_script[
        variants_start : install_script.index(")", variants_start)
    ]
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
    assert "POSTGRES_DB=sidar_development" in env_development
    assert "OLLAMA_NUM_PARALLEL=4" in env_development
    assert "GPU_MEMORY_FRACTION=0.8" in env_development
    assert "LLM_GPU_MEMORY_FRACTION=0.6" in env_development
    assert "RAG_GPU_MEMORY_FRACTION=0.3" in env_development
    assert "JWT_SECRET_KEY=replace-with-a-local-development-jwt-secret-32-plus-chars" in env_development


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


def test_ci_system_dependency_installer_provisions_shellcheck() -> None:
    installer = Path("scripts/install_ci_system_deps.sh").read_text(encoding="utf-8")

    assert "PACKAGES=(portaudio19-dev shellcheck)" in installer
    assert "MISSING_PACKAGES=()" in installer
    assert 'apt-get install -y --no-install-recommends "${MISSING_PACKAGES[@]}"' in installer


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
    assert "sudo apt-get install -y bats shellcheck" in ci_workflow
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
    assert "path: dist/install_sidar.sh" in ci_workflow
    assert "softprops/action-gh-release@v2" in ci_workflow
    assert "files: dist/install_sidar.sh" in ci_workflow

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


def test_install_sidar_single_file_fallback_downloads_all_modules(tmp_path: Path) -> None:
    remote_modules = tmp_path / "remote"
    runner_dir = tmp_path / "runner"
    shutil.copytree("scripts/install_modules", remote_modules)
    runner_dir.mkdir()
    shutil.copy2("install_sidar.sh", runner_dir / "install_sidar.sh")

    expected_modules = (
        "install_helpers.sh",
        "utils/install_remediation.sh",
        "utils/wsl_gpu_preflight.sh",
        "utils/gpu_utils.sh",
        "utils/python_env.sh",
        "utils/db_credentials.sh",
        "utils/env_utils.sh",
        "utils/ollama_models.sh",
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
    assert "install_modules" in result.stdout


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
    assert "harden_database_credentials" in env_utils
    assert "download_ollama_models()" in ollama_utils
    assert "qwen2.5-coder:7b" in ollama_utils

    assert 'module_dir "/utils' in bundler
    assert 'module_dir "/phases' in bundler


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
    assert "sidar_phase_remediation_strategy()" in remediation_utils
    assert "sidar_resume_after_remediation()" in remediation_utils
    assert "uv.lock" in remediation_utils
    assert "uv lock" in remediation_utils
    assert "exec env" in remediation_utils
    assert "artifacts/install/remediation" in remediation_utils


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
