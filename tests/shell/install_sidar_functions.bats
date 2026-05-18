#!/usr/bin/env bats

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

run_installer_function() {
  local snippet="$1"
  local root
  root="$(repo_root)"
  run bash -c '
    set -Eeuo pipefail
    repo_root="$1"
    test_snippet="$2"
    cd "$repo_root"
    export SIDAR_INSTALL_TEST_MODE=1
    set --
    source ./install_sidar.sh
    eval "$test_snippet"
  ' _ "$root" "$snippet"
}

@test "normalize_bool maps accepted true/false values and rejects unknown input" {
  run_installer_function '
    [[ "$(normalize_bool yes)" == "true" ]]
    [[ "$(normalize_bool EVET)" == "true" ]]
    [[ "$(normalize_bool 0)" == "false" ]]
    [[ "$(normalize_bool hayır)" == "false" ]]
    [[ -z "$(normalize_bool maybe)" ]]
  '
  [ "$status" -eq 0 ]
}

@test "resolve_runtime_mode_choice normalizes local/docker aliases and falls back to ask" {
  run_installer_function '
    [[ "$(resolve_runtime_mode_choice 1)" == "local" ]]
    [[ "$(resolve_runtime_mode_choice geliştirici)" == "local" ]]
    [[ "$(resolve_runtime_mode_choice full-docker)" == "docker" ]]
    [[ "$(resolve_runtime_mode_choice unexpected)" == "ask" ]]
  '
  [ "$status" -eq 0 ]
}

@test "is_weak_secret_value rejects placeholders and accepts high entropy tokens" {
  run_installer_function '
    is_weak_secret_value postgres
    is_weak_secret_value change-me-please
    is_weak_secret_value Password1
    if is_weak_secret_value N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh; then
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
}

@test "harden_database_credentials rewrites weak DATABASE_URL and syncs postgres env values" {
  local tmpdir env_file
  tmpdir="$(mktemp -d)"
  env_file="$tmpdir/.env"
  cat > "$env_file" <<'ENV'
SIDAR_ENV=development
DATABASE_URL=postgresql+asyncpg://sidar:postgres@localhost:5432/sidar?ssl=disable
POSTGRES_PASSWORD=postgres
ENV

  run_installer_function "
    generate_secure_token() { printf '%s\\n' 'GeneratedStrongDbToken_1234567890'; }
    harden_database_credentials '$env_file'
    grep -q '^DATABASE_URL=postgresql+asyncpg://sidar:GeneratedStrongDbToken_1234567890@localhost:5432/sidar?ssl=disable$' '$env_file'
    grep -q '^POSTGRES_PASSWORD=GeneratedStrongDbToken_1234567890$' '$env_file'
    grep -q '^POSTGRES_USER=sidar$' '$env_file'
    grep -q '^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:GeneratedStrongDbToken_1234567890@postgres:5432/sidar$' '$env_file'
  "
  rm -rf "$tmpdir"
  [ "$status" -eq 0 ]
}

@test "harden_database_credentials leaves strong DATABASE_URL passwords unchanged" {
  local tmpdir env_file
  tmpdir="$(mktemp -d)"
  env_file="$tmpdir/.env"
  cat > "$env_file" <<'ENV'
SIDAR_ENV=production
DATABASE_URL=postgresql+asyncpg://sidar:N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh@localhost:5432/sidar
POSTGRES_PASSWORD=N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh
ENV

  run_installer_function "
    harden_database_credentials '$env_file'
    grep -q '^DATABASE_URL=postgresql+asyncpg://sidar:N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh@localhost:5432/sidar$' '$env_file'
    grep -q '^POSTGRES_PASSWORD=N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh$' '$env_file'
    if grep -q '^SIDAR_CONTAINER_DATABASE_URL=' '$env_file'; then
      exit 1
    fi
  "
  rm -rf "$tmpdir"
  [ "$status" -eq 0 ]
}

@test "SIDAR_LOCALE=en renders installer help in English" {
  local root
  root="$(repo_root)"
  run env SIDAR_INSTALL_TEST_MODE=1 SIDAR_LOCALE=en bash "$root/install_sidar.sh" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage:"* ]]
  [[ "$output" == *"Select installer message language"* ]]
  [[ "$output" != *"Kullanım:"* ]]
}

@test "LANG=en_US renders invalid argument warnings in English" {
  local root
  root="$(repo_root)"
  run env -u SIDAR_LOCALE SIDAR_INSTALL_TEST_MODE=1 LANG=en_US.UTF-8 bash "$root/install_sidar.sh" --not-a-real-flag
  [ "$status" -eq 1 ]
  [[ "$output" == *"Unknown argument: --not-a-real-flag"* ]]
  [[ "$output" != *"Bilinmeyen argüman"* ]]
}

@test "default installer help remains Turkish" {
  local root
  root="$(repo_root)"
  run env SIDAR_INSTALL_TEST_MODE=1 SIDAR_LOCALE=tr bash "$root/install_sidar.sh" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Kullanım:"* ]]
  [[ "$output" == *"Kurulum mesaj dilini seçer"* ]]
}

@test "01_context phase runs environment detection before WSL GPU preflight" {
  run_installer_function '
    events=()
    banner() { events+=(banner); }
    report_repo_lookup_context() { events+=(repo_context); }
    detect_environment() { events+=(detect_environment); WSL2=false; }
    sidar_source_install_utils() { events+=("source:$*"); }
    run_wsl2_gpu_preflight() { events+=(wsl_preflight); }
    verify_offline_bundle_manifest() { events+=(offline_manifest); }
    OFFLINE_MODE=false

    sidar_phase_initialize_context
    [[ "${events[*]}" == "banner repo_context detect_environment source:wsl_gpu_preflight.sh wsl_preflight" ]]
  '
  [ "$status" -eq 0 ]
}

@test "01_context phase fails offline quality gate when bundle directory is missing" {
  run_installer_function '
    banner() { :; }
    report_repo_lookup_context() { :; }
    detect_environment() { WSL2=false; }
    sidar_source_install_utils() { :; }
    run_wsl2_gpu_preflight() { :; }
    resolve_offline_packages_dir() { return 1; }
    OFFLINE_MODE=true

    sidar_phase_initialize_context
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"Çevrimdışı mod etkin ancak offline_packages dizini bulunamadı."* ]]
}

@test "03_runtime phase performs hardware/runtime gates but never provisions uv workspace" {
  run_installer_function '
    events=()
    sidar_source_install_utils() { events+=("source:$*"); }
    ensure_prerequisites() { events+=(ensure_prerequisites); }
    select_runtime_mode() { events+=(select_runtime_mode); APP_RUNTIME_MODE_SELECTED=local; }
    detect_gpu() { events+=(detect_gpu); }
    setup_nvidia_docker() { events+=(setup_nvidia_docker); }
    install_uv_cli() { events+=(unexpected_uv); return 99; }
    create_uv_venv() { events+=(unexpected_venv); return 99; }
    install_python_deps() { events+=(unexpected_deps); return 99; }

    sidar_phase_runtime_prerequisites
    [[ "${events[*]}" == "source:gpu_utils.sh ensure_prerequisites select_runtime_mode detect_gpu setup_nvidia_docker" ]]
  '
  [ "$status" -eq 0 ]
}

@test "04_workspace local mode enforces uv venv and uv sync quality gate ordering" {
  run_installer_function '
    events=()
    APP_RUNTIME_MODE_SELECTED=local
    sidar_source_install_utils() { events+=("source:$*"); }
    install_uv_cli() { events+=(install_uv_cli); }
    create_uv_venv() { events+=(create_uv_venv); }
    install_python_deps() { events+=(install_python_deps); }
    install_pyright_lsp_tool() { events+=(install_pyright_lsp_tool); }
    verify_torch_cuda() { events+=(verify_torch_cuda); }
    create_directories() { events+=(create_directories); }
    setup_vscode_workspace() { events+=(setup_vscode_workspace); }
    setup_env_file() { events+=(setup_env_file); }

    sidar_phase_workspace_config
    [[ "${events[*]}" == "source:python_env.sh db_credentials.sh env_utils.sh install_uv_cli create_uv_venv install_python_deps install_pyright_lsp_tool verify_torch_cuda create_directories setup_vscode_workspace setup_env_file" ]]
  '
  [ "$status" -eq 0 ]
}

@test "04_workspace docker mode skips local uv provisioning but still prepares workspace files" {
  run_installer_function '
    events=()
    APP_RUNTIME_MODE_SELECTED=docker
    sidar_source_install_utils() { events+=("source:$*"); }
    install_uv_cli() { events+=(unexpected_uv); return 99; }
    create_uv_venv() { events+=(unexpected_venv); return 99; }
    install_python_deps() { events+=(unexpected_deps); return 99; }
    install_pyright_lsp_tool() { events+=(unexpected_pyright); return 99; }
    verify_torch_cuda() { events+=(unexpected_torch); return 99; }
    create_directories() { events+=(create_directories); }
    setup_vscode_workspace() { events+=(setup_vscode_workspace); }
    setup_env_file() { events+=(setup_env_file); }

    sidar_phase_workspace_config
    [[ "${events[*]}" == "source:python_env.sh db_credentials.sh env_utils.sh create_directories setup_vscode_workspace setup_env_file" ]]
  '
  [ "$status" -eq 0 ]
}

@test "06 services phases gate local migrations models smoke and audit in order" {
  run_installer_function '
    events=()
    APP_RUNTIME_MODE_SELECTED=local
    sidar_source_install_utils() { events+=("source:$*"); }
    prepare_docker_for_migrations() { events+=(prepare_docker_for_migrations); }
    run_migrations() { events+=(run_migrations); }
    download_ollama_models() { events+=(download_ollama_models); }
    launch_docker_services() { events+=(launch_docker_services); }
    run_smoke_tests() { events+=(run_smoke_tests); }
    run_test_artifact_audit() { events+=(run_test_artifact_audit); }

    sidar_phase_local_migrations_and_models
    sidar_phase_services_and_validation
    [[ "${events[*]}" == "source:ollama_models.sh prepare_docker_for_migrations run_migrations download_ollama_models launch_docker_services run_smoke_tests run_test_artifact_audit" ]]
  '
  [ "$status" -eq 0 ]
}

@test "06 services docker mode marks local-only gates as skipped" {
  run_installer_function '
    events=()
    APP_RUNTIME_MODE_SELECTED=docker
    sidar_source_install_utils() { events+=("source:$*"); }
    prepare_docker_for_migrations() { events+=(unexpected_prepare); return 99; }
    run_migrations() { events+=(unexpected_migration); return 99; }
    download_ollama_models() { events+=(unexpected_models); return 99; }
    launch_docker_services() { events+=(launch_docker_services); }
    run_smoke_tests() { events+=(unexpected_smoke); return 99; }
    run_test_artifact_audit() { events+=(unexpected_audit); return 99; }

    sidar_phase_local_migrations_and_models
    sidar_phase_services_and_validation
    [[ "${events[*]}" == "source:ollama_models.sh launch_docker_services" ]]
    [[ "$MIGRATION_STATUS" == "tam_docker_modu_nedeniyle_atlandi" ]]
    [[ "$SMOKE_TEST_STATUS" == "tam_docker_modu_nedeniyle_atlandi" ]]
    [[ "$AUDIT_STATUS" == "tam_docker_modu_nedeniyle_atlandi" ]]
  '
  [ "$status" -eq 0 ]
}

@test "WSL GPU preflight supports explicit off and CPU skip modes" {
  run_installer_function '
    sidar_source_install_utils wsl_gpu_preflight.sh
    WSL2=true
    FORCE_CPU=false
    SIDAR_WSL_GPU_PREFLIGHT=off
    run_wsl2_gpu_preflight
    FORCE_CPU=true
    SIDAR_WSL_GPU_PREFLIGHT=strict
    run_wsl2_gpu_preflight
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"SIDAR_WSL_GPU_PREFLIGHT=off"* ]]
  [[ "$output" == *"--cpu etkin"* ]]
}

@test "auto-heal resume skips completed phases and reruns failed phase" {
  run_installer_function '
    SIDAR_INSTALL_RESUME_FROM_PHASE=04_workspace
    called=0
    phase_fn() { called=$((called + 1)); }

    sidar_run_install_phase 03_runtime phase_fn
    [[ "$called" -eq 0 ]]
    sidar_run_install_phase 04_workspace phase_fn
    [[ "$called" -eq 1 ]]
  '
  [ "$status" -eq 0 ]
}

@test "auto-heal strategy routes uv sync workspace failures to remediation" {
  run_installer_function '
    sidar_remediate_uv_sync_failure() { printf "%s\n" "uv-remediation-called"; return 0; }
    sidar_phase_remediation_strategy 04_workspace "uv sync --frozen --all-extras" ""
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"uv-remediation-called"* ]]
}

@test "auto-heal can be disabled for deterministic fail-fast installer runs" {
  run_installer_function '
    SIDAR_INSTALL_AUTO_HEAL=0
    SIDAR_CURRENT_INSTALL_PHASE=04_workspace
    if sidar_handle_install_failure 1 10 "uv sync" "uv sync"; then
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
}

@test "postgres volume discovery catches Sidar volumes after project directory mismatch" {
  run_installer_function '
    docker() {
      if [[ "$1" == "volume" && "$2" == "ls" ]]; then
        printf "%s\n" "oldproj_postgres_data" "sidar_postgres_data" "other_postgres_data"
        return 0
      fi
      if [[ "$1" == "volume" && "$2" == "inspect" ]]; then
        printf "%s\n" "<no value>|<no value>"
        return 0
      fi
      return 0
    }

    mapfile -t discovered < <(sidar_discover_postgres_volumes "freshclone" postgres_data)
    [[ "${#discovered[@]}" -eq 1 ]]
    [[ "${discovered[0]}" == "sidar_postgres_data" ]]
  '
  [ "$status" -eq 0 ]
}

@test "postgres password hardening reset runs compose down fallback when no volume is directly detected" {
  run_installer_function '
    down_called=false
    fake_compose() {
      case "$1" in
        config)
          if [[ "${2:-}" == "--volumes" ]]; then
            printf "%s\n" "postgres_data"
          fi
          ;;
        down)
          down_called=true
          [[ "$*" == *"--volumes"* ]]
          [[ "$*" == *"--remove-orphans"* ]]
          ;;
        ps)
          return 0
          ;;
      esac
      return 0
    }
    docker() {
      if [[ "$1" == "volume" && "$2" == "ls" ]]; then
        return 0
      fi
      if [[ "$1" == "volume" && "$2" == "inspect" ]]; then
        return 1
      fi
      return 0
    }

    DB_PASSWORD_HARDENED=true
    POSTGRES_VOLUME_RESET_DONE=false
    AUTO_RESET_POSTGRES_VOLUME_ON_PASSWORD_CHANGE=1
    AUTO_RESET_POSTGRES_VOLUMES=true
    NO_INTERACTION=true

    maybe_reset_postgres_volume_after_password_hardening fake_compose -- postgres redis
    [[ "$down_called" == true ]]
    [[ "$POSTGRES_VOLUME_RESET_DONE" == true ]]
  '
  [ "$status" -eq 0 ]
}
