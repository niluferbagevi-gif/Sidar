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
