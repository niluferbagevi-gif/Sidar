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

@test "Playwright Ubuntu override helpers detect Ubuntu 25+ and normalize the synthetic os-release" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/ubuntu26" <<EOF
ID=ubuntu
VERSION_ID="26.04"
EOF
    cat > "$tmpdir/ubuntu24" <<EOF
ID=ubuntu
VERSION_ID="24.04"
EOF
    cat > "$tmpdir/debian26" <<EOF
ID=debian
VERSION_ID="26"
EOF

    is_playwright_ubuntu_override_recommended "$tmpdir/ubuntu26"
    ! is_playwright_ubuntu_override_recommended "$tmpdir/ubuntu24"
    ! is_playwright_ubuntu_override_recommended "$tmpdir/debian26"
    prepare_playwright_ubuntu_override_file "$tmpdir/ubuntu26" "$tmpdir/override"
    grep -q "^ID=ubuntu$" "$tmpdir/override"
    grep -q "^VERSION_ID=\\\"24.04\\\"$" "$tmpdir/override"
  '
  [ "$status" -eq 0 ]
}

@test "resolve_playwright_python_spec reads the pyproject dependency-group and has a safe fallback" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/pyproject.toml" <<EOF
[dependency-groups]
dev = [
  "playwright>=1.60,<2.0",
]
EOF

    [[ "$(resolve_playwright_python_spec "$tmpdir/pyproject.toml")" == "playwright>=1.60,<2.0" ]]
    [[ "$(resolve_playwright_python_spec "$tmpdir/missing.toml")" == "playwright>=1.60,<2.0" ]]
  '
  [ "$status" -eq 0 ]
}

@test "install_playwright_browsers skips uv add when installed Playwright satisfies the repo spec" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=debian
VERSION_ID="13"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
printf "%s|%s\\n" "\$*" "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" >> "$tmpdir/python.log"
case "\$*" in
  "-c import playwright") exit 0 ;;
  "-m playwright install --with-deps chromium") echo "ERROR: Playwright does not support chromium on debian13-x64" >&2; exit 1 ;;
  "-m playwright install chromium")
    if [[ "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" == "ubuntu24.04-x64" ]]; then exit 0; fi
    echo "ERROR: Playwright does not support chromium on debian13-x64" >&2
    exit 1
    ;;
  "- playwright>=1.60,<2.0") exit 1 ;;
esac
exit 1
EOF
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
touch "$tmpdir/uv-called"
exit 99
EOF
    chmod +x "$tmpdir/bin/python" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    [[ ! -e "$tmpdir/uv-called" ]]
    grep -q "^- playwright>=1.60,<2.0|$" "$tmpdir/python.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"gereksiz uv add upgrade fallback atlanıyor"* ]]
  [[ "$output" == *"OS override fallback ile tamamlandı"* ]]
}

@test "install_playwright_browsers upgrades outdated Playwright with the repo spec" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=debian
VERSION_ID="13"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
printf "%s|%s\\n" "\$*" "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" >> "$tmpdir/python.log"
case "\$*" in
  "-c import playwright") exit 0 ;;
  "-m playwright install --with-deps chromium") echo "ERROR: Playwright does not support chromium on debian13-x64" >&2; exit 1 ;;
  "-m playwright install chromium")
    if [[ -e "$tmpdir/upgraded" ]]; then exit 0; fi
    echo "ERROR: Playwright does not support chromium on debian13-x64" >&2
    exit 1
    ;;
  "- playwright>=1.60,<2.0") exit 0 ;;
esac
exit 1
EOF
    cat > "$tmpdir/bin/uv" <<EOF
#!/usr/bin/env bash
printf "%s\\n" "\$*" >> "$tmpdir/uv.log"
touch "$tmpdir/upgraded"
EOF
    chmod +x "$tmpdir/bin/python" "$tmpdir/bin/uv"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    grep -q "^add --dev playwright>=1.60,<2.0$" "$tmpdir/uv.log"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"playwright>=1.60,<2.0 şartını sağlamıyor"* ]]
  [[ "$output" == *"upgrade fallback ile tamamlandı"* ]]
}

@test "install_playwright_browsers starts with the OS override on Ubuntu 25+" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=ubuntu
VERSION_ID="26.04"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
printf "%s|%s|%s\\n" "\$*" "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" "\${OS_RELEASE_PATH:-}" >> "$tmpdir/python.log"
EOF
    chmod +x "$tmpdir/bin/python"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    [[ "$(wc -l < "$tmpdir/python.log")" -eq 2 ]]
    sed -n "1p" "$tmpdir/python.log" | grep -q "^-c import playwright||$tmpdir/os-release$"
    sed -n "2p" "$tmpdir/python.log" | grep -q "^-m playwright install chromium|ubuntu24.04-x64|"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"ubuntu24.04 OS override kurulumu doğrudan deneniyor"* ]]
  [[ "$output" == *"proaktif OS override ile tamamlandı"* ]]
  [[ "$output" != *"--with-deps"* ]]
}

@test "install_playwright_browsers preserves the standard with-deps path on Ubuntu 24.04" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    mkdir -p "$tmpdir/bin"
    cat > "$tmpdir/os-release" <<EOF
ID=ubuntu
VERSION_ID="24.04"
EOF
    cat > "$tmpdir/bin/python" <<EOF
#!/usr/bin/env bash
printf "%s|%s|%s\\n" "\$*" "\${PLAYWRIGHT_HOST_PLATFORM_OVERRIDE:-}" "\${OS_RELEASE_PATH:-}" >> "$tmpdir/python.log"
EOF
    chmod +x "$tmpdir/bin/python"
    export PATH="$tmpdir/bin:$PATH"
    export OS_RELEASE_PATH="$tmpdir/os-release"
    PLAYWRIGHT_BROWSERS_MODE=always

    install_playwright_browsers

    [[ "$(wc -l < "$tmpdir/python.log")" -eq 2 ]]
    sed -n "2p" "$tmpdir/python.log" | grep -q "^-m playwright install --with-deps chromium||$tmpdir/os-release$"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"yalnızca Chromium (--with-deps) kuruluyor"* ]]
  [[ "$output" == *"Playwright kurulumu tamamlandı (chromium, --with-deps)"* ]]
  [[ "$output" != *"proaktif OS override"* ]]
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


@test "propagate_shared_secrets_to_env_variants always syncs PostgreSQL credentials" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    master_pw="MasterStrongDbToken_1234567890"
    stale_pw="sidar_test_secure_pw"
    preserved_api_key="N7b_Uz9mKq2pR8tYv3wXc5aHj6sDf4Gh"

    cat > "$tmpdir/.env" <<ENV
POSTGRES_PASSWORD=${master_pw}
DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@postgres:5432/sidar
API_KEY=MasterApiKeyValue_1234567890
ENV

    for variant in .env.development .env.test .env.advanced; do
      cat > "$tmpdir/$variant" <<ENV
POSTGRES_PASSWORD=${stale_pw}
DATABASE_URL=postgresql+asyncpg://sidar:${stale_pw}@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:${stale_pw}@postgres:5432/sidar
API_KEY=${preserved_api_key}
ENV
      cat > "$tmpdir/${variant}.example" <<ENV
POSTGRES_PASSWORD=example_password
DATABASE_URL=postgresql+asyncpg://sidar:example_password@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:example_password@postgres:5432/sidar
API_KEY=example_api_key
ENV
    done

    SCRIPT_DIR="$tmpdir"
    propagate_shared_secrets_to_env_variants "$tmpdir/.env"

    for variant in .env.development .env.test .env.advanced; do
      grep -q "^POSTGRES_PASSWORD=${master_pw}$" "$tmpdir/$variant"
      grep -q "^DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@127.0.0.1:5432/sidar$" "$tmpdir/$variant"
      grep -q "^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@postgres:5432/sidar$" "$tmpdir/$variant"
      grep -q "^API_KEY=${preserved_api_key}$" "$tmpdir/$variant"
    done
  '
  [ "$status" -eq 0 ]
}


@test "modular harden_database_credentials syncs explicit env variants" {
  run_installer_function '
    source ./scripts/install_modules/utils/db_credentials.sh
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    env_file="$tmpdir/.env"
    variant_file="$tmpdir/.env.test"

    cat > "$env_file" <<ENV
SIDAR_ENV=development
DATABASE_URL=postgresql+asyncpg://sidar:postgres@127.0.0.1:5432/sidar?ssl=disable
POSTGRES_PASSWORD=postgres
ENV
    cat > "$variant_file" <<ENV
POSTGRES_PASSWORD=sidar_test_secure_pw
DATABASE_URL=postgresql+asyncpg://sidar:sidar_test_secure_pw@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:sidar_test_secure_pw@postgres:5432/sidar
ENV

    generate_secure_token() { printf "%s\n" "GeneratedStrongDbToken_1234567890"; }
    harden_database_credentials "$env_file" "$variant_file"

    grep -q "^POSTGRES_PASSWORD=GeneratedStrongDbToken_1234567890$" "$variant_file"
    grep -q "^DATABASE_URL=postgresql+asyncpg://sidar:GeneratedStrongDbToken_1234567890@127.0.0.1:5432/sidar?ssl=disable$" "$variant_file"
    grep -q "^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:GeneratedStrongDbToken_1234567890@postgres:5432/sidar$" "$variant_file"
  '
  [ "$status" -eq 0 ]
}

@test "modular sync_postgres_env_with_database_url forces default env variant consistency" {
  run_installer_function '
    source ./scripts/install_modules/utils/db_credentials.sh
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    env_file="$tmpdir/.env"
    master_pw="MasterStrongDbToken_1234567890"
    stale_pw="sidar_test_secure_pw"

    cat > "$env_file" <<ENV
DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@127.0.0.1:5432/sidar?ssl=disable
POSTGRES_PASSWORD=old_value_that_should_be_replaced
ENV
    for variant in .env.development .env.test .env.advanced; do
      cat > "$tmpdir/${variant}.example" <<ENV
POSTGRES_PASSWORD=example_password
DATABASE_URL=postgresql+asyncpg://sidar:example_password@127.0.0.1:5432/sidar
ENV
      cat > "$tmpdir/$variant" <<ENV
POSTGRES_PASSWORD=${stale_pw}
DATABASE_URL=postgresql+asyncpg://sidar:${stale_pw}@127.0.0.1:5432/sidar
SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:${stale_pw}@postgres:5432/sidar
ENV
    done

    SCRIPT_DIR="$tmpdir"
    sync_postgres_env_with_database_url "$env_file"

    for variant in .env.development .env.test .env.advanced; do
      grep -q "^POSTGRES_USER=sidar$" "$tmpdir/$variant"
      grep -q "^POSTGRES_PASSWORD=${master_pw}$" "$tmpdir/$variant"
      grep -q "^POSTGRES_DB=sidar$" "$tmpdir/$variant"
      grep -q "^DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@127.0.0.1:5432/sidar?ssl=disable$" "$tmpdir/$variant"
      grep -q "^SIDAR_CONTAINER_DATABASE_URL=postgresql+asyncpg://sidar:${master_pw}@postgres:5432/sidar$" "$tmpdir/$variant"
    done
  '
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
    [[ "${events[*]}" == "banner repo_context detect_environment source:wsl_gpu_preflight.sh source:wsl_integration_autofix.sh wsl_preflight" ]]
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

@test "ensure_postgres_databases_exist reads password and creates only missing DBs" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    psql_calls="$tmpdir/psql_calls.log"
    psql_create="$tmpdir/psql_create.log"
    cat > "$tmpdir/psql" <<"EOF"
#!/usr/bin/env bash
printf "%s\n" "$*" >> "__CALLS__"
if [[ "$*" == *"SELECT 1 FROM pg_database WHERE datname = 'sidar'"* ]]; then
  echo "1"
  exit 0
fi
if [[ "$*" == *"CREATE DATABASE"* ]]; then
  printf "%s\n" "$*" >> "__CREATE__"
fi
exit 0
EOF
    sed -i "s#__CALLS__#$psql_calls#g" "$tmpdir/psql"
    sed -i "s#__CREATE__#$psql_create#g" "$tmpdir/psql"
    chmod +x "$tmpdir/psql"
    PATH="$tmpdir:$PATH"
    hash -r

    ensure_postgres_databases_exist "127.0.0.1" "5432" "sidar" "super-secret" "sidar"

    grep -q -- "-h 127.0.0.1 -p 5432 -U sidar -d postgres" "$psql_calls"
    grep -q -- "CREATE DATABASE \"sidar_development\" OWNER \"sidar\";" "$psql_create"
    grep -q -- "CREATE DATABASE \"sidar_test\" OWNER \"sidar\";" "$psql_create"
    if grep -q -- "CREATE DATABASE \"sidar\" OWNER \"sidar\";" "$psql_create"; then
      exit 1
    fi
  '
  [ "$status" -eq 0 ]
}

@test "ensure_postgres_databases_exist fails closed on psql password authentication errors" {
  run_installer_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT
    cat > "$tmpdir/psql" <<"EOF"
#!/usr/bin/env bash
printf "%s\n" "psql: error: password authentication failed for user sidar" >&2
exit 2
EOF
    chmod +x "$tmpdir/psql"
    PATH="$tmpdir:$PATH"
    hash -r

    ensure_postgres_databases_exist "127.0.0.1" "5432" "sidar" "wrong-password" "sidar"
  '
  [ "$status" -eq 1 ]
  [[ "$output" == *"PostgreSQL auth başarısız"* ]]
}
