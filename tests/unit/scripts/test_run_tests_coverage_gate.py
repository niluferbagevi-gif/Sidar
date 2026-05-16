from __future__ import annotations

import subprocess
from pathlib import Path

RUN_TESTS = Path("run_tests.sh")


def _script() -> str:
    return RUN_TESTS.read_text(encoding="utf-8")


def _install_script_with_modules() -> str:
    parts = [Path("install_sidar.sh").read_text(encoding="utf-8")]
    parts.extend(
        module.read_text(encoding="utf-8")
        for module in sorted(Path("scripts/install_modules").glob("*.sh"))
    )
    parts.extend(
        phase.read_text(encoding="utf-8")
        for phase in sorted(Path("scripts/install_phases").glob("*.sh"))
    )
    return "\n".join(parts)


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
    script = _install_script_with_modules()
    env_module = Path("scripts/install_modules/env_utils.sh").read_text(encoding="utf-8")

    assert "ensure_env_file_secrets_after_uv_sync" in script
    assert 'ok "Python bağımlılıkları kilitli uv.lock üzerinden senkronlandı."' in script
    assert "ensure_env_file_secrets_after_uv_sync" in env_module[
        env_module.index("install_python_deps()") : env_module.index("# ── 5.1 Pyright")
    ]
    assert "Boş .env dosyası uv sync sonrası .env.example ile dolduruldu." in script
    assert "POSTGRES_PASSWORD otomatik ve güvenli bir değerle oluşturuldu" in script


def test_install_sidar_masks_secret_log_stream_before_tee(tmp_path: Path) -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    start = script.index("mask_install_log_stream()")
    end = script.index("# Kurulum loglarını", start)
    helper = tmp_path / "mask_helper.sh"
    sample = tmp_path / "sample.log"
    helper.write_text(script[start:end], encoding="utf-8")
    sample.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql+asyncpg://sidar:superSecret123@localhost:5432/sidar",
                "+ generated_password=superSecret123",
                "+ sed -i s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=superSecret123| .env",
                "--password superSecret123",
                "normal line",
            ]
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["bash", "-c", 'source "$1"; cat "$2" | mask_install_log_stream', "_", str(helper), str(sample)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "mask_install_log_stream | tee -i" in script
    assert "superSecret123" not in proc.stdout
    assert "DATABASE_URL=****" in proc.stdout
    assert "generated_password=****" in proc.stdout
    assert "POSTGRES_PASSWORD=****" in proc.stdout
    assert "--password ****" in proc.stdout
    assert "normal line" in proc.stdout


def test_install_sidar_requires_stash_before_destructive_git_recovery() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    recovery_start = script.index("Stash pop sırasında çakışma oluştu")
    recovery = script[recovery_start : script.index('SCRIPT_DIR="$TARGET_DIR"', recovery_start)]

    assert "latest_stash_ref_for_message()" in script
    assert "ensure_git_recovery_backup_stash()" in script
    assert 'git stash push -u -m "$STASH_MESSAGE" >/dev/null 2>&1 || fail' in script
    assert 'STASH_REF="$(latest_stash_ref_for_message "$STASH_MESSAGE")"' in script
    assert "git reset --hard origin/main && git clean -fd" not in script
    assert "Çakışmayı otomatik temizlemek için" not in script
    assert 'recovery_backup_ref="$(ensure_git_recovery_backup_stash "$STASH_REF")"' in recovery
    assert recovery.index("ensure_git_recovery_backup_stash") < recovery.index("git clean -fd")
    assert "Kurtarma öncesi stash yedeği: $recovery_backup_ref" in recovery
    assert "Yerel değişiklik yedeği: $recovery_backup_ref" in recovery
    assert "--no-interaction modunda otomatik reset/clean uygulanmadı" in recovery


def test_install_sidar_treats_change_me_placeholders_as_weak_secrets() -> None:
    script = _install_script_with_modules()

    assert "change-me*|replace-with-*" in script
    assert 'is_weak_secret_value "$val" && return 0' in script


def test_install_sidar_uses_entropy_heuristic_for_weak_passwords() -> None:
    script = _install_script_with_modules()
    db_module = Path("scripts/install_modules/db_credentials.sh").read_text(encoding="utf-8")

    assert "is_low_entropy_secret_value()" in script
    assert "entropy_bits < 80" in script
    assert "Password1Password1Password1" in script
    assert "qwerty123qwerty123" in script
    assert 'is_low_entropy_secret_value "$value" && return 0' in script
    assert 'if is_weak_secret_value "$db_password"; then' in db_module
    assert 'case "$db_password" in' not in db_module
    assert 'sidar|postgres|password|admin|changeme|123456)' not in db_module


def test_install_sidar_loads_known_weak_secrets_from_central_denylist() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    denylist_lines = [
        line
        for line in Path("scripts/known_weak_secrets.txt").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    denylist_keys = {line.split("=", 1)[0] for line in denylist_lines if "=" in line}
    denylist_values = [line.split("=", 1)[1] if "=" in line else line for line in denylist_lines]

    assert "known_weak_secrets_file()" in script
    assert "is_known_weak_secret_value" in script
    assert "scripts/known_weak_secrets.txt" in script
    assert ".env.example" in script[script.index("_is_missing_or_insecure()") :]
    assert {"API_KEY", "JWT_SECRET_KEY", "MEMORY_ENCRYPTION_KEY"} <= denylist_keys
    assert {"AUTONOMY_WEBHOOK_SECRET", "SWARM_FEDERATION_SHARED_SECRET", "GITHUB_WEBHOOK_SECRET"} <= denylist_keys
    assert "METRICS_TOKEN" in denylist_keys
    assert all(value not in script for value in denylist_values)


def test_install_sidar_pins_remote_installer_checksums() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "PINNED_REMOTE_SCRIPT_CHECKSUMS=(" in script
    assert "uv_install|https://releases.astral.sh/github/uv/releases/download/0.11.11/uv-installer.sh" in script
    assert "3a020f8d69019caca567c9038999d130b0ea85866483caf2042c386cb685aef4" in script
    assert "ollama_install|https://github.com/ollama/ollama/releases/download/v0.24.0/install.sh" in script
    assert "25f64b810b947145095956533e1bdf56eacea2673c55a7e586be4515fc882c9f" in script
    assert "pinned_remote_script_field()" in script
    assert 'pinned_url="$(pinned_remote_script_field "$script_label" url' in script
    assert 'pinned_sha="$(pinned_remote_script_field "$script_label" sha256' in script
    assert 'script_url="$pinned_url"' in script
    assert 'expected_sha="$pinned_sha"' in script

def test_install_sidar_supports_target_dir_and_repo_url_overrides() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert 'TARGET_DIR="${SIDAR_TARGET_DIR:-$HOME/Sidar}"' in script
    assert 'SIDAR_TARGET_DIR boş olamaz' in script
    assert '"~/"*) TARGET_DIR="$HOME/${TARGET_DIR#~/}"' in script
    assert '*) TARGET_DIR="$(pwd)/$TARGET_DIR"' in script
    assert 'TARGET_DIR="${TARGET_DIR%/}"' in script
    assert "SIDAR_TARGET_DIR=/tmp/Sidar" in script
    assert 'REPO_URL="${SIDAR_REPO_URL:-https://github.com/niluferbagevi-gif/Sidar}"' in script
    assert 'git clone "$REPO_URL" "$TARGET_DIR"' in script

def test_install_sidar_supports_wsl_memory_and_swap_overrides() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert 'WSL_MEMORY_OVERRIDE_GB="${WSL_MEMORY_GB:-}"' in script
    assert 'WSL_SWAP_OVERRIDE_GB="${WSL_SWAP_GB:-}"' in script
    assert 'if [[ "$arg" == --* ]]; then' in script
    assert '--wsl-memory) PENDING_WSL_OVERRIDE_ARG="memory"' in script
    assert '--wsl-memory=*) WSL_MEMORY_OVERRIDE_GB="${arg#*=}"' in script
    assert '--wsl-swap) PENDING_WSL_OVERRIDE_ARG="swap"' in script
    assert '--wsl-swap=*) WSL_SWAP_OVERRIDE_GB="${arg#*=}"' in script
    assert "_normalize_wsl_gb_override()" in script
    assert 'value=$((10#$normalized))' in script
    assert 'target_memory_gb=$(_normalize_wsl_gb_override "$WSL_MEMORY_OVERRIDE_GB"' in script
    assert 'target_swap_gb=$(_normalize_wsl_gb_override "$WSL_SWAP_OVERRIDE_GB"' in script
    assert 'force_replace == "true"' in script
    assert '"memory" "$target_memory" "$wsl_memory_override_active"' in script
    assert '"swap" "$target_swap" "$wsl_swap_override_active"' in script
    assert "--wsl-memory <GB> / --wsl-memory=<GB>" in script
    assert "WSL_MEMORY_GB=16 / WSL_SWAP_GB=8" in script







def test_install_sidar_uses_central_env_reader_for_values(tmp_path: Path) -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    db_module = Path("scripts/install_modules/db_credentials.sh").read_text(encoding="utf-8")
    env_file = tmp_path / "sample.env"
    env_file.write_text(
        "# DATABASE_URL=postgresql://ignored:ignored@example/sidar\n"
        "DATABASE_URL=  \"postgresql://sidar:pw@example/sidar\"  # trailing comment\r\n"
        "POSTGRES_PASSWORD='quoted pw'\n",
        encoding="utf-8",
    )
    helper_file = tmp_path / "env_reader.sh"
    helper_start = script.index("read_env_value_from_file()")
    helper_end = script.index("resolve_ollama_version_url()", helper_start)
    helper_file.write_text(script[helper_start:helper_end], encoding="utf-8")

    proc = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; read_env_value_from_file DATABASE_URL "$2"; read_env_value_from_file POSTGRES_PASSWORD "$2"',
            "_",
            str(helper_file),
            str(env_file),
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert proc.stdout.splitlines() == ["postgresql://sidar:pw@example/sidar", "quoted pw"]
    assert "read_env_value_from_file" in db_module
    assert "cut -d= -f2-" not in script
    assert "cut -d= -f2-" not in db_module
    assert 'grep -E "^${key}="' not in script

def test_install_sidar_uses_portable_sed_inplace_wrapper(tmp_path: Path) -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    db_module = Path("scripts/install_modules/db_credentials.sh").read_text(encoding="utf-8")
    helpers = Path("scripts/install_modules/install_helpers.sh").read_text(encoding="utf-8")
    sample = tmp_path / "sample.env"
    sample.write_text("POSTGRES_PASSWORD=weak\nKEEP=yes\n", encoding="utf-8")

    proc = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; sed_inplace "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=strong|" "$2"; cat "$2"',
            "_",
            "scripts/install_modules/install_helpers.sh",
            str(sample),
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "sed_inplace()" in helpers
    assert "sudo_sed_inplace()" in helpers
    assert "sed_cmd+=(-i ''" in helpers
    assert "sed_supports_gnu_inplace" in helpers
    assert "POSTGRES_PASSWORD=strong" in proc.stdout
    assert "sed -i " not in script
    assert "sudo sed -E -i" not in script
    assert "sed_inplace" in db_module

def test_install_sidar_uses_single_runtime_mode_selection() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    combined = _install_script_with_modules()
    launch_start = script.index("launch_docker_services()")
    select_start = script.index("select_runtime_mode()")
    launch_section = script[launch_start:select_start]
    select_section = script[select_start:script.index("# ── Kurulum Sonrası IDE", select_start)]

    assert "select_runtime_mode_early" not in combined
    assert combined.count("Kurulum çalışma modu seçimi:") == 1
    assert combined.count("1) Geliştirici modu (önerilen): uygulama local, altyapı servisleri Docker") == 1
    assert combined.count("2) Tam Docker modu: web/agent dahil tüm servisler Docker") == 1
    assert 'read -r -t 180 -p "Seçim [1/2, varsayılan=1]: "' not in launch_section
    assert "select_runtime_mode" in launch_section
    assert "APP_RUNTIME_MODE_SELECTED" in launch_section
    assert 'APP_RUNTIME_MODE="$runtime_mode"' in select_section
    assert 'APP_RUNTIME_MODE_SELECTED="$runtime_mode"' in select_section
    assert "select_runtime_mode" in Path("scripts/install_phases/99_full_install.sh").read_text(encoding="utf-8")

def test_install_sidar_parallel_prefetches_docker_images() -> None:
    script = _install_script_with_modules()

    assert "install_parallel_prefetch_enabled()" in script
    assert "start_docker_image_prefetch_async()" in script
    assert "wait_for_docker_image_prefetch()" in script
    assert "cancel_docker_image_prefetch_if_running()" in script
    assert 'case "${INSTALL_PARALLEL_PREFETCH:-1}"' in script
    assert "docker_image_prefetch_" in script
    assert (
        'COMPOSE_PROFILES="$compose_profiles" "${docker_compose_cmd[@]}" pull '
        '"${prefetch_services[@]}"'
    ) in script
    assert 'start_docker_image_prefetch_async "$APP_RUNTIME_MODE_SELECTED"' in script
    assert "wait_for_docker_image_prefetch" in script
    assert "INSTALL_PARALLEL_PREFETCH=1|0" in script
    assert "cancel_docker_image_prefetch_if_running" in script

def test_install_sidar_triggers_opt_in_auto_heal_on_failure() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    assert "install_auto_heal_on_failure_enabled()" in script
    assert "start_install_auto_heal_on_failure" in script
    assert "INSTALL_AUTO_HEAL_ON_FAILURE=1" in script
    assert "scripts/auto_heal.py" in script
    assert "--source install" in script
    assert "--hitl-approve" in script
    assert 'local hitl_approve="${INSTALL_AUTO_HEAL_HITL_APPROVE:-no}"' in script
    assert "install_failure_context_" in script
    assert "install_auto_heal_" in script
    assert 'local mode="${INSTALL_AUTO_HEAL_MODE:-background}"' in script
    assert 'trap - ERR' in script

def test_install_sidar_sources_modular_install_components() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")

    for module_name in [
        "install_helpers.sh",
        "gpu_utils.sh",
        "env_utils.sh",
        "db_credentials.sh",
        "ollama_models.sh",
    ]:
        assert f'"{module_name}"' in script
    for phase_name in [
        "00_doctor.sh",
        "01_system.sh",
        "02_python.sh",
        "03_models.sh",
        "04_smoke.sh",
        "99_full_install.sh",
    ]:
        assert f'"{phase_name}"' in script
    assert 'source "${INSTALL_MODULE_DIR}/${module_name}"' in script
    assert 'source "${INSTALL_PHASE_DIR}/${phase_name}"' in script
    assert "REMOTE_PHASE_BASE" in script
    assert "detect_gpu()" in Path("scripts/install_modules/gpu_utils.sh").read_text(encoding="utf-8")
    env_utils = Path("scripts/install_modules/env_utils.sh").read_text(encoding="utf-8")
    assert "install_uv_cli()" in env_utils
    assert "create_uv_venv()" in env_utils
    assert env_utils.index("install_uv_cli()") < env_utils.index("create_uv_venv()")
    assert "setup_uv()" not in env_utils
    assert "setup_python_env()" not in env_utils
    assert "harden_database_credentials()" in Path("scripts/install_modules/db_credentials.sh").read_text(encoding="utf-8")
    assert "download_ollama_models()" in Path("scripts/install_modules/ollama_models.sh").read_text(encoding="utf-8")
    assert "run_prepare_system_phase()" in Path("scripts/install_phases/01_system.sh").read_text(encoding="utf-8")
    assert "run_sync_deps_phase()" in Path("scripts/install_phases/02_python.sh").read_text(encoding="utf-8")
    assert "run_full_install_phase()" in Path("scripts/install_phases/99_full_install.sh").read_text(encoding="utf-8")

    bundler = Path("scripts/tools/bundle_install_sidar.sh").read_text(encoding="utf-8")
    assert 'PHASE_DIR="${ROOT_DIR}/scripts/install_phases"' in bundler
    assert '# --- PHASE: ' in bundler
    assert 'awk -v module_dir="$MODULE_DIR" -v phase_dir="$PHASE_DIR"' in bundler


def test_install_sidar_centralizes_installer_version_and_phase_orchestration() -> None:
    script = Path("install_sidar.sh").read_text(encoding="utf-8")
    combined = _install_script_with_modules()
    pyproject_version = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in Path("pyproject.toml").read_text(encoding="utf-8").splitlines()
        if line.startswith("version =")
    )

    assert "resolve_installer_version()" in script
    assert 'pyproject_path="$SCRIPT_DIR/pyproject.toml"' in script
    assert 'SIDAR_INSTALLER_VERSION="$(resolve_installer_version)"' in script
    assert pyproject_version not in script
    assert f"v{pyproject_version}" not in script
    assert 'printf "║          Sidar AI — Kurulum Başlıyor (v%-9s)        ║\\n" "$SIDAR_INSTALLER_VERSION"' in script
    assert "run_prepare_system_phase()" not in script
    assert "run_sync_deps_phase()" not in script
    assert "run_provision_models_phase()" not in script
    assert "run_smoke_phase()" not in script
    assert "run_full_install_phase" in script
    assert "run_full_install_phase()" in combined
