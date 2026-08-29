#!/usr/bin/env bash

set -euo pipefail

# Generates a disposable secret that actually passes the fail-closed policy in
# scripts/secret_strength.py::is_weak_secret (also used at runtime via
# core/config_secrets.py). Two things that look "random enough" still fail it
# often enough to matter here:
#   - Human-readable placeholders like "compose-gate-jwt-secret-key-32-chars"
#     fail outright (dictionary words, low entropy): config.py's
#     Config.__init__ then raises ValueError for JWT_SECRET_KEY/API_KEY/
#     POSTGRES_PASSWORD, so sidar-web crash-loops on boot before this gate's
#     own healthz/readyz/migration assertions ever run.
#   - Plain high-entropy output (e.g. `openssl rand -hex`) still trips the
#     policy's short-substring denylist (tokens like "abc"/"root") often
#     enough (~0.5% per value, measured) to make CI flaky across 9 generated
#     secrets per run. So generate with `secrets.token_urlsafe` (wide,
#     mixed-case alphabet — far fewer accidental denylist collisions) and
#     retry against the real checker instead of assuming any one draw passes.
# See tests/unit/scripts/test_production_compose_validation.py::
# test_generated_gate_env_secrets_satisfy_production_entropy_policy.
random_secret() {
  python3 - <<'PY'
import secrets
import sys

sys.path.insert(0, ".")
from scripts.secret_strength import is_weak_secret

for _ in range(50):
    candidate = secrets.token_urlsafe(32)
    if not is_weak_secret(candidate):
        print(candidate)
        break
else:
    raise SystemExit("random_secret: no strong value in 50 attempts")
PY
}

project_name="${PRODUCTION_COMPOSE_PROJECT_NAME:-sidar-production-gate}"
env_file="${PRODUCTION_COMPOSE_ENV_FILE:-.env.production.compose-gate}"
web_port="${PRODUCTION_COMPOSE_WEB_PORT:-17860}"
export SIDAR_RUNTIME_ENV_FILE="${SIDAR_RUNTIME_ENV_FILE:-$env_file}"
# The base Compose file intentionally keeps the historical sidar_postgres_data
# name for normal development. The production evidence gate must not attach to
# that persistent database: doing so leaks state into migrations/readiness and
# lets `down --volumes` delete developer data. Namespace the gate volume with
# the same independently configurable project name as its containers.
export SIDAR_POSTGRES_VOLUME_NAME="${SIDAR_POSTGRES_VOLUME_NAME:-${project_name}_postgres_data}"
# docker-compose.yml's container_name fields interpolate ${COMPOSE_PROJECT_NAME:-sidar}
# (see docker-compose.yml) so this isolated gate stack never collides with a
# developer's already-running dev stack (both would otherwise be literally
# "sidar_ollama" etc. on the same Docker daemon -- "Conflict. The container
# name ... is already in use"). --project-name alone already threads through
# to this interpolation on the Compose versions this repo has been verified
# against, but exporting COMPOSE_PROJECT_NAME explicitly keeps that from being
# an undocumented, version-dependent assumption.
export COMPOSE_PROJECT_NAME="$project_name"
compose=(docker compose --project-name "$project_name" --env-file "$env_file" -f docker-compose.yml -f docker-compose.production.yml --profile cpu)

cleanup() {
  local status=$?
  if [[ "$status" -ne 0 ]]; then
    mkdir -p artifacts/production-compose
    "${compose[@]}" ps --all | tee artifacts/production-compose/ps.txt 2>&1 || true
    "${compose[@]}" logs --no-color 2>&1 | tee artifacts/production-compose/compose.log || true
  fi
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  if [[ "${PRODUCTION_COMPOSE_ENV_FILE:-}" == "" ]]; then
    rm -f "$env_file"
  fi
  return "$status"
}
trap cleanup EXIT

if [[ "${PRODUCTION_COMPOSE_ENV_FILE:-}" == "" ]]; then
  cat >"$env_file" <<EOF
SIDAR_ENV=production
APP_RUNTIME_MODE=production
SIDAR_RUNTIME_ENV_FILE=$env_file
SIDAR_POSTGRES_VOLUME_NAME=$SIDAR_POSTGRES_VOLUME_NAME
AI_PROVIDER=ollama
CODING_MODEL=qwen2.5-coder:7b
POSTGRES_DB=sidar
POSTGRES_USER=sidar
POSTGRES_PASSWORD=$(random_secret)
REDIS_PASSWORD=$(random_secret)
GRAFANA_ADMIN_PASSWORD=$(random_secret)
METRICS_TOKEN=$(random_secret)
API_KEY=$(random_secret)
JWT_SECRET_KEY=$(random_secret)
AUTONOMY_WEBHOOK_SECRET=$(random_secret)
SWARM_FEDERATION_SHARED_SECRET=$(random_secret)
GITHUB_WEBHOOK_SECRET=$(random_secret)
MEMORY_ENCRYPTION_KEY=MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=
GUARDRAILS_REQUIRED=true
DB_DEGRADED_MODE_ON_POSTGRES_FAILURE=false
RAG_REQUIRED_FOR_READINESS=true
WEB_PORT=$web_port
SIDAR_DATA_MOUNT=sidar_data_prod
SIDAR_LOGS_MOUNT=sidar_logs_prod
SIDAR_TEMP_MOUNT=sidar_temp_prod
EOF
  chmod 600 "$env_file"
fi

"${compose[@]}" config --quiet
if [[ "${PRODUCTION_COMPOSE_CONFIG_ONLY:-0}" == "1" ]]; then
  exit 0
fi

"${compose[@]}" up --detach --build --wait sidar-web

for service in postgres redis sidar-web; do
  container_id="$("${compose[@]}" ps --quiet "$service")"
  [[ -n "$container_id" ]]
  [[ "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")" == "healthy" ]]
done

curl --fail --silent --show-error "http://127.0.0.1:${web_port}/healthz" >/dev/null
curl --fail --silent --show-error "http://127.0.0.1:${web_port}/readyz" >/dev/null

heads="$("${compose[@]}" run --rm --no-deps sidar-migrate uv run alembic heads | sed '/^[[:space:]]*$/d' | tail -1)"
current="$("${compose[@]}" run --rm --no-deps sidar-migrate uv run alembic current | sed '/^[[:space:]]*$/d' | tail -1)"
[[ -n "$heads" && "$current" == *"${heads%% *}"* ]]

marker="production-compose-$RANDOM-$RANDOM"
"${compose[@]}" exec -T sidar-web sh -c "printf '%s' '$marker' > /app/data/.production-compose-marker"
"${compose[@]}" restart sidar-web
"${compose[@]}" up --detach --wait sidar-web
[[ "$("${compose[@]}" exec -T sidar-web cat /app/data/.production-compose-marker)" == "$marker" ]]
curl --fail --silent --show-error "http://127.0.0.1:${web_port}/healthz" >/dev/null

"${compose[@]}" stop --timeout 20 sidar-web
web_id="$("${compose[@]}" ps --all --quiet sidar-web)"
[[ "$(docker inspect --format '{{.State.ExitCode}}' "$web_id")" == "0" ]]

echo "Production Compose boot/readiness/migration/restart/persistence/shutdown evidence passed."
