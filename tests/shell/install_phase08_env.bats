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
