#!/usr/bin/env bats
# shellcheck disable=SC2016  # Test snippets intentionally expand in the child bash process.

bats_require_minimum_version 1.5.0

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

run_phase06_function() {
  local snippet="$1"
  run bash -c '
    set -Eeuo pipefail
    SCRIPT_DIR="$1"
    export SCRIPT_DIR
    warn() { printf "WARN:%s\n" "$*"; }
    info() { printf "INFO:%s\n" "$*"; }
    ok() { printf "OK:%s\n" "$*"; }
    fail() { printf "FAIL:%s\n" "$*"; return 19; }
    clear_stdin_buffer() { :; }
    read_env_value_from_file() {
      local key="$1" file="$2"
      sed -n "s/^${key}=//p" "$file" | tail -n 1
    }
    source "$SCRIPT_DIR/scripts/install_modules/phases/06_services.sh"
    eval "$2"
  ' _ "$(repo_root)" "$snippet"
}

@test "phase 06 Docker gate retries deterministically and succeeds before Compose" {
  run_phase06_function '
    calls=0
    docker() {
      calls=$((calls + 1))
      [[ "$calls" -eq 3 ]]
    }
    sleep() { printf "sleep:%s\n" "$1"; }
    WSL2=false
    NO_INTERACTION=true
    AUTO_INSTALL=true

    phase06_docker_daemon_gate_or_fail
    [[ "$calls" -eq 3 ]]
  '

  [ "$status" -eq 0 ]
  [[ "$output" == *"deneme 1/3"* ]]
  [[ "$output" == *"deneme 2/3"* ]]
  [[ "$output" == *"3. denemede başarılı"* ]]
}

@test "phase 06 Docker gate fails closed after its bounded retry budget" {
  run_phase06_function '
    docker() { return 1; }
    sleep() { :; }
    WSL2=false
    NO_INTERACTION=true
    AUTO_INSTALL=true

    phase06_docker_daemon_gate_or_fail
  '

  [ "$status" -eq 19 ]
  [[ "$output" == *"Docker daemon doğrulanamadı (3 deneme)"* ]]
}

@test "phase 06 volume reset policy permits development but protects production and unknown envs" {
  run_phase06_function '
    tmpdir="$(mktemp -d)"
    trap "rm -rf \"$tmpdir\"" EXIT

    printf "SIDAR_ENV=development\n" > "$tmpdir/.env"
    sidar_postgres_volume_reset_allowed_for_env "$tmpdir/.env"

    printf "SIDAR_ENV=production\n" > "$tmpdir/.env"
    ! sidar_postgres_volume_reset_allowed_for_env "$tmpdir/.env"
    ALLOW_PRODUCTION_DB_VOLUME_RESET=1 sidar_postgres_volume_reset_allowed_for_env "$tmpdir/.env"

    : > "$tmpdir/.env"
    ! sidar_postgres_volume_reset_allowed_for_env "$tmpdir/.env"
    printf "SIDAR_ENV=surprise\n" > "$tmpdir/.env"
    ! sidar_postgres_volume_reset_allowed_for_env "$tmpdir/.env"
  '

  [ "$status" -eq 0 ]
  [[ "$output" == *"güvenlik freni"* ]]
  [[ "$output" == *"güvenli varsayılan: reddet"* ]]
  [[ "$output" == *"tanınmadı"* ]]
}
