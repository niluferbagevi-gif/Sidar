#!/usr/bin/env bash

set -euo pipefail

project_name="${PRODUCTION_COMPOSE_PROJECT_NAME:-sidar-production-gate}"
env_file="${PRODUCTION_COMPOSE_ENV_FILE:-.env.production.compose-gate}"
web_port="${PRODUCTION_COMPOSE_WEB_PORT:-17860}"
export SIDAR_RUNTIME_ENV_FILE="${SIDAR_RUNTIME_ENV_FILE:-$env_file}"
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
AI_PROVIDER=ollama
CODING_MODEL=qwen2.5-coder:7b
POSTGRES_DB=sidar
POSTGRES_USER=sidar
POSTGRES_PASSWORD=compose-gate-postgres-password-32
REDIS_PASSWORD=compose-gate-redis-password-32
GRAFANA_ADMIN_PASSWORD=compose-gate-grafana-admin-password-32
METRICS_TOKEN=compose-gate-metrics-token-32-characters
API_KEY=compose-gate-api-key-32-characters
JWT_SECRET_KEY=compose-gate-jwt-secret-key-32-characters
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
