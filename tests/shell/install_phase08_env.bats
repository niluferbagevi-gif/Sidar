#!/usr/bin/env bats
# shellcheck disable=SC2016  # Test snippets intentionally expand in the child bash process.

bats_require_minimum_version 1.5.0

repo_root() {
  cd "$BATS_TEST_DIRNAME/../.." && pwd
}

run_phase08_function() {
  local snippet="$1"
  run bash -c '
    set -Eeuo pipefail
    SCRIPT_DIR="$2"
    export SCRIPT_DIR
    warn() { printf "WARN:%s\n" "$*"; }
    info() { printf "INFO:%s\n" "$*"; }
    ok() { printf "OK:%s\n" "$*"; }
    read_env_value_from_file() {
      local key="$1" file="$2"
      sed -n "s/^${key}=//p" "$file" | tail -n 1
    }
    sed_inplace() { sed -i "$1" "$2"; }
    source "$1/scripts/install_modules/phases/08_env.sh"
    eval "$3"
  ' _ "$(repo_root)" "$(mktemp -d)" "$snippet"
}

@test "phase 08 production rotation gate rejects shared secrets and accepts isolated values" {
  run_phase08_function '
    trap "rm -rf \"$SCRIPT_DIR\"" EXIT
    keys=(API_KEY JWT_SECRET_KEY MEMORY_ENCRYPTION_KEY AUTONOMY_WEBHOOK_SECRET SWARM_FEDERATION_SHARED_SECRET GITHUB_WEBHOOK_SECRET GRAFANA_ADMIN_PASSWORD METRICS_TOKEN)
    : > "$SCRIPT_DIR/.env"
    : > "$SCRIPT_DIR/.env.production"
    for key in "${keys[@]}"; do
      printf "%s=local-%s-strong-value-2026\n" "$key" "$key" >> "$SCRIPT_DIR/.env"
      printf "%s=local-%s-strong-value-2026\n" "$key" "$key" >> "$SCRIPT_DIR/.env.production"
    done
    ! production_secret_rotation_gate_passes "$SCRIPT_DIR/.env"

    : > "$SCRIPT_DIR/.env.production"
    for key in "${keys[@]}"; do
      printf "%s=production-%s-isolated-value-2026\n" "$key" "$key" >> "$SCRIPT_DIR/.env.production"
    done
    production_secret_rotation_gate_passes "$SCRIPT_DIR/.env"
  '

  [ "$status" -eq 0 ]
  [[ "$output" == *"production kalıcılaştırması engellendi"* ]]
}

@test "phase 08 GPU propagation updates development and advanced without touching production" {
  run_phase08_function '
    trap "rm -rf \"$SCRIPT_DIR\"" EXIT
    cat > "$SCRIPT_DIR/.env" <<EOF
USE_GPU=true
REQUIRE_GPU=true
GPU_MIXED_PRECISION=true
COMPOSE_PROFILES=gpu
EOF
    for name in development advanced production; do
      cat > "$SCRIPT_DIR/.env.$name" <<EOF
USE_GPU=false
REQUIRE_GPU=false
GPU_MIXED_PRECISION=false
COMPOSE_PROFILES=cpu
EOF
    done

    propagate_gpu_settings_to_env_variants "$SCRIPT_DIR/.env"
    grep -q "^USE_GPU=true$" "$SCRIPT_DIR/.env.development"
    grep -q "^COMPOSE_PROFILES=gpu$" "$SCRIPT_DIR/.env.advanced"
    grep -q "^USE_GPU=false$" "$SCRIPT_DIR/.env.production"
    grep -q "^COMPOSE_PROFILES=cpu$" "$SCRIPT_DIR/.env.production"
  '

  [ "$status" -eq 0 ]
}

@test "phase 08 API_GROUPS covers every SIDAR_USER_SECRET_ENV_KEYS key exactly once" {
  # Regression test for a friend code review finding: SIDAR_USER_SECRET_ENV_KEYS
  # (install_sidar.sh) is documented as the single source of truth for user
  # secret keys, but _api_groups_definition() in 08_env.sh (which drives the
  # zenity/whiptail/read interactive collector) used to be a hand-maintained
  # list that silently fell out of sync with it: GOOGLE_API_KEY, JIRA_API_TOKEN
  # and META_GRAPH_API_TOKEN were added to SIDAR_USER_SECRET_ENV_KEYS for log
  # masking/reporting but never to the interactive groups, so the install
  # wizard never asked for them. This asserts every key in
  # SIDAR_USER_SECRET_ENV_KEYS appears in _api_groups_definition() exactly
  # once (and vice versa), so a future addition to one without the other
  # fails CI instead of shipping silently.
  run bash -c '
    set -Eeuo pipefail
    repo_root="$1"

    # Pull the real SIDAR_USER_SECRET_ENV_KEYS array declaration verbatim out
    # of install_sidar.sh (without sourcing/running the whole installer).
    array_src="$(sed -n "/^SIDAR_USER_SECRET_ENV_KEYS=($/,/^)$/p" "$repo_root/install_sidar.sh")"
    [[ -n "$array_src" ]]
    eval "$array_src"
    (( ${#SIDAR_USER_SECRET_ENV_KEYS[@]} > 0 ))

    warn() { :; }
    info() { :; }
    ok() { :; }
    source "$repo_root/scripts/install_modules/phases/08_env.sh"

    mapfile -t user_keys < <(sidar_user_api_key_names)
    mapfile -t group_lines < <(_api_groups_definition)

    declare -A group_key_count=()
    for line in "${group_lines[@]}"; do
      keys_csv="${line#*|}"
      IFS="," read -r -a keys <<< "$keys_csv"
      for k in "${keys[@]}"; do
        group_key_count["$k"]=$(( ${group_key_count["$k"]:-0} + 1 ))
      done
    done

    missing=()
    duplicated=()
    for k in "${user_keys[@]}"; do
      count="${group_key_count[$k]:-0}"
      if (( count == 0 )); then
        missing+=("$k")
      elif (( count > 1 )); then
        duplicated+=("$k")
      fi
      unset "group_key_count[$k]"
    done

    # Anything left in group_key_count is a group key with no matching entry
    # in SIDAR_USER_SECRET_ENV_KEYS -- also a drift bug, just the other way.
    extra=("${!group_key_count[@]}")

    if (( ${#missing[@]} > 0 )); then
      printf "MISSING_FROM_API_GROUPS:%s\n" "${missing[@]}"
    fi
    if (( ${#duplicated[@]} > 0 )); then
      printf "DUPLICATED_IN_API_GROUPS:%s\n" "${duplicated[@]}"
    fi
    if (( ${#extra[@]} > 0 )); then
      printf "EXTRA_IN_API_GROUPS_NOT_IN_USER_KEYS:%s\n" "${extra[@]}"
    fi

    [[ ${#missing[@]} -eq 0 && ${#duplicated[@]} -eq 0 && ${#extra[@]} -eq 0 ]]
  ' _ "$(repo_root)"

  [ "$status" -eq 0 ]
}

@test "phase 08 secret propagation never creates a production env file" {
  run_phase08_function '
    trap "rm -rf \"$SCRIPT_DIR\"" EXIT
    cat > "$SCRIPT_DIR/.env" <<EOF
API_KEY=local-api-key-strong-value-2026
JWT_SECRET_KEY=local-jwt-key-strong-value-2026
EOF
    touch "$SCRIPT_DIR/.env.development.example" "$SCRIPT_DIR/.env.test.example" "$SCRIPT_DIR/.env.advanced.example"
    is_weak_secret_value() { return 0; }
    is_known_weak_secret_value() { return 0; }
    is_env_example_secret_value() { return 0; }
    sync_database_env_chain_after_setup() { :; }

    propagate_shared_secrets_to_env_variants "$SCRIPT_DIR/.env"
    [[ ! -e "$SCRIPT_DIR/.env.production" ]]
  '

  [ "$status" -eq 0 ]
}
