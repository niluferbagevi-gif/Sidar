#!/usr/bin/env bash

# Helper functions sourced by run_tests.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

resolve_docker_compose_cmd() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD=(docker compose)
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD=(docker-compose)
    return 0
  fi
  return 1
}

load_test_database_password_env() {
  local test_dotenv_file="${DOTENV_FILE:-.env.test}"
  local password_file=""
  password_file="$(mktemp)" || {
    echo "❌ Test PostgreSQL parolası için güvenli geçici dosya oluşturulamadı."
    return 1
  }
  chmod 600 "${password_file}"

  if ! DOTENV_FILE="${test_dotenv_file}" uv run python - "${password_file}" <<'PY_TEST_DB_PASSWORD'
from pathlib import Path
import sys

from scripts.sync_database_passwords import _effective_postgres_password, discover_env_chain

password = _effective_postgres_password(discover_env_chain())
if not password:
    raise SystemExit("POSTGRES_PASSWORD dotenv zincirinde çözülemedi")
Path(sys.argv[1]).write_text(password, encoding="utf-8")
PY_TEST_DB_PASSWORD
  then
    rm -f "${password_file}"
    echo "❌ Test PostgreSQL parolası dotenv zincirinden çözülemedi."
    return 1
  fi

  POSTGRES_PASSWORD="$(cat "${password_file}")"
  rm -f "${password_file}"
  if [ -z "${POSTGRES_PASSWORD}" ]; then
    echo "❌ Test PostgreSQL parolası boş olamaz."
    return 1
  fi
  export POSTGRES_PASSWORD
  echo "✅ Test PostgreSQL parolası dotenv zincirinden güvenli biçimde çözüldü (değer loglanmadı)."
}

# Pytest's test-profile dotenv is an intentional override layer.  Remove its
# explicit PostgreSQL URLs before exporting the freshly prepared sidar_test DSN;
# otherwise a legacy ?ssl=disable URL can overwrite that process value during
# collection and make asyncpg fall back to the shared degraded SQLite database.
sanitize_test_database_url_overrides() {
  local test_dotenv_file="${DOTENV_FILE:-.env.test}"

  if [ ! -f "${test_dotenv_file}" ]; then
    return 0
  fi

  if ! uv run python - "${test_dotenv_file}" <<'PY_SANITIZE_TEST_DATABASE_URLS'
from pathlib import Path
import sys

from scripts.sync_database_passwords import remove_explicit_database_urls_from_text

path = Path(sys.argv[1])
original = path.read_text(encoding="utf-8")
updated, summary = remove_explicit_database_urls_from_text(original)
if updated != original:
    path.write_text(updated, encoding="utf-8")
print(",".join(summary["removed_keys"]))
PY_SANITIZE_TEST_DATABASE_URLS
  then
    echo "❌ Test dotenv DATABASE_URL pre-flight temizliği başarısız: ${test_dotenv_file}"
    return 1
  fi

  echo "✅ Test dotenv PostgreSQL URL override pre-flight kontrolü tamamlandı: ${test_dotenv_file}"
}

sync_postgres_login_role() {
  local admin_db_user="$1"
  local role_name="$2"
  local role_password="$3"

  if [ -z "${role_name}" ] || [ -z "${role_password}" ]; then
    echo "❌ PostgreSQL rol adı ve parolası boş olamaz."
    return 1
  fi

  "${DOCKER_COMPOSE_CMD[@]}" exec -T postgres psql \
    -U "${admin_db_user}" -d postgres \
    -v ON_ERROR_STOP=1 \
    -v role_name="${role_name}" \
    -v role_password="${role_password}" <<'SQL_SYNC_POSTGRES_ROLE'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'role_name', :'role_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role_name') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'role_name', :'role_password') \gexec
SQL_SYNC_POSTGRES_ROLE
}

resolve_ollama_base_url() {
  local raw_url="${OLLAMA_URL:-http://localhost:11434}"
  raw_url="${raw_url%/}"
  raw_url="${raw_url%/api}"
  printf '%s' "${raw_url}"
}

sync_ollama_models() {
  local sync_mode="${OLLAMA_MODEL_SYNC:-auto}"
  if [ "${sync_mode}" = "0" ] || [ "${sync_mode}" = "false" ]; then
    echo "ℹ️ OLLAMA_MODEL_SYNC=${sync_mode}; Ollama model senkronizasyonu atlanıyor."
    return 0
  fi

  if ! command -v ollama >/dev/null 2>&1; then
    echo "ℹ️ 'ollama' CLI bulunamadı; model health check adımı atlanıyor."
    return 0
  fi

  local ollama_base_url
  ollama_base_url="$(resolve_ollama_base_url)"

  if command -v curl >/dev/null 2>&1; then
    if ! curl -fsS --max-time 5 "${ollama_base_url}/api/tags" >/dev/null 2>&1; then
      echo "⚠️ Ollama API erişilemedi (${ollama_base_url}/api/tags); model health check atlanıyor."
      return 0
    fi
  elif ! ollama list >/dev/null 2>&1; then
    echo "⚠️ Ollama listesi alınamadı; model health check atlanıyor."
    return 0
  fi

  local required_models_raw="${OLLAMA_REQUIRED_MODELS:-${CODING_MODEL:-qwen2.5-coder:7b}}"
  local -a required_models=()
  local -A seen_models=()
  local model

  IFS=',' read -r -a _parsed_models <<< "${required_models_raw}"
  for model in "${_parsed_models[@]}"; do
    model="${model## }"
    model="${model%% }"
    if [ -z "${model}" ]; then
      continue
    fi
    if [ -z "${seen_models[${model}]+x}" ]; then
      required_models+=("${model}")
      seen_models["${model}"]=1
    fi
  done

  if [ "${#required_models[@]}" -eq 0 ]; then
    echo "ℹ️ Kontrol edilecek Ollama modeli tanımlı değil (OLLAMA_REQUIRED_MODELS boş)."
    return 0
  fi

  echo "🩺 Ollama model health check: ${required_models[*]}"

  local model_list
  model_list="$(ollama list 2>/dev/null || true)"
  if [ -z "${model_list}" ]; then
    echo "⚠️ Ollama model listesi boş/alınamadı; eksik model kontrolü atlanıyor."
    return 0
  fi

  local auto_pull_missing="${OLLAMA_AUTO_PULL_MISSING:-1}"
  local missing_count=0

  for model in "${required_models[@]}"; do
    if printf '%s\n' "${model_list}" | awk 'NR>1 {print $1}' | grep -Fxq "${model}"; then
      echo "✅ Ollama modeli hazır: ${model}"
      continue
    fi

    missing_count=$((missing_count + 1))
    echo "⚠️ Eksik Ollama modeli: ${model}"

    if [ "${auto_pull_missing}" = "1" ] || [ "${auto_pull_missing}" = "true" ]; then
      echo "⬇️ Model indiriliyor: ollama pull ${model}"
      if ollama pull "${model}"; then
        echo "✅ Model indirildi: ${model}"
      else
        echo "⚠️ Model indirilemedi: ${model} (manuel: ollama pull ${model})"
      fi
    else
      echo "ℹ️ Otomatik indirme kapalı (OLLAMA_AUTO_PULL_MISSING=${auto_pull_missing}). Manuel: ollama pull ${model}"
    fi
  done

  if [ "${missing_count}" -eq 0 ]; then
    echo "✅ Ollama model senkronizasyonu tamamlandı; tüm gerekli etiketler mevcut."
  fi
}

ensure_test_services() {
  if [ "${AUTO_DOCKER_TEST_SERVICES:-1}" != "1" ]; then
    echo "ℹ️ AUTO_DOCKER_TEST_SERVICES=0 verildi, Redis/PostgreSQL otomatik başlatma adımı atlanıyor."
    export SMOKE_SKIP_EXTERNAL_INFRA="${SMOKE_SKIP_EXTERNAL_INFRA:-1}"
    echo "ℹ️ SMOKE_SKIP_EXTERNAL_INFRA=${SMOKE_SKIP_EXTERNAL_INFRA} (otomatik servis başlatma kapalı)."
    return 0
  fi

  if ! resolve_docker_compose_cmd; then
    echo "❌ Docker Compose bulunamadı; zorunlu Redis/PostgreSQL test altyapısı başlatılamadı."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  local running_services
  running_services="$("${DOCKER_COMPOSE_CMD[@]}" ps --status running --services 2>/dev/null || true)"
  local redis_running=0
  local postgres_running=0

  if printf '%s\n' "${running_services}" | grep -qx "redis"; then
    redis_running=1
  fi
  if printf '%s\n' "${running_services}" | grep -qx "postgres"; then
    postgres_running=1
  fi

  if [ "${redis_running}" -eq 1 ] && [ "${postgres_running}" -eq 1 ]; then
    echo "ℹ️ Redis ve PostgreSQL zaten çalışıyor; mevcut servisler kullanılacak."
    wait_for_test_services_ready
    return $?
  fi

  echo "🐳 Test öncesi bağımlı servisler başlatılıyor: redis, postgres"
  if ! "${DOCKER_COMPOSE_CMD[@]}" up -d redis postgres; then
    echo "❌ Redis/PostgreSQL docker servisleri başlatılamadı (daemon çalışmıyor olabilir)."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if ! wait_for_test_services_ready; then
    return 1
  fi
  DOCKER_TEST_SERVICES_STARTED=1
}

wait_for_test_services_ready() {
  # İlk image pull sonrasında PostgreSQL healthcheck'i 60 saniyeyi aşabilir.
  # Varsayılan pencere 180 saniyedir ve açık env değerleriyle ayarlanabilir.
  local max_attempts="${TEST_SERVICES_READY_MAX_ATTEMPTS:-90}"
  local sleep_seconds="${TEST_SERVICES_READY_SLEEP_SECONDS:-2}"
  local attempt=1

  echo "⏳ Redis/PostgreSQL hazır olana kadar bekleniyor (max deneme: ${max_attempts})..."
  while [ "${attempt}" -le "${max_attempts}" ]; do
    local redis_ready=0
    local postgres_ready=0

    if "${DOCKER_COMPOSE_CMD[@]}" exec -T redis redis-cli ping >/dev/null 2>&1; then
      redis_ready=1
    fi

    if "${DOCKER_COMPOSE_CMD[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER:-sidar}" -d "${POSTGRES_DB:-sidar}" >/dev/null 2>&1; then
      postgres_ready=1
    fi

    if [ "${redis_ready}" -eq 1 ] && [ "${postgres_ready}" -eq 1 ]; then
      echo "✅ Redis ve PostgreSQL hazır."
      return 0
    fi

    echo "ℹ️ Servisler henüz hazır değil (deneme ${attempt}/${max_attempts}); ${sleep_seconds}s bekleniyor..."
    sleep "${sleep_seconds}"
    attempt=$((attempt + 1))
  done

  echo "❌ Redis/PostgreSQL beklenen sürede hazır olamadı."
  echo "ℹ️ Zorunlu altyapı hazır olmadığı için smoke testleri skip'e çevrilmeyecek; backend kapısı başarısız olacak."
  "${DOCKER_COMPOSE_CMD[@]}" ps postgres redis || true
  "${DOCKER_COMPOSE_CMD[@]}" logs --tail 80 postgres redis || true
  BACKEND_EXIT_CODE=1
  return 1
}


is_safe_postgres_identifier() {
  local identifier="$1"
  [[ "${identifier}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
}

postgres_identifiers_equal() {
  local left="$1"
  local right="$2"
  # DROP/CREATE ifadeleri identifier'ları tırnaksız kullandığı için PostgreSQL
  # bunları küçük harfe katlar. Koruma da aynı semantiği uygulamalıdır.
  [ "${left,,}" = "${right,,}" ]
}

gpu_hardware_available() {
  command -v nvidia-smi >/dev/null 2>&1 || command -v nvidia-smi.exe >/dev/null 2>&1
}

prepare_test_database() {
  local test_db_name="${TEST_DATABASE_NAME:-sidar_test}"
  local primary_db_name="${POSTGRES_DB:-sidar}"
  local test_db_user="${TEST_DATABASE_USER:-${POSTGRES_USER:-sidar}}"
  local test_db_password="${TEST_DATABASE_PASSWORD:-${POSTGRES_PASSWORD:-sidar}}"
  local test_db_host="${POSTGRES_HOST:-127.0.0.1}"
  local admin_db_user="${POSTGRES_ADMIN_USER:-${POSTGRES_USER:-sidar}}"
  local test_db_port="${POSTGRES_PORT:-5432}"
  local reset_test_db="${RESET_TEST_DATABASE:-1}"

  if [ "${AUTO_PREPARE_TEST_DB:-1}" != "1" ]; then
    echo "ℹ️ AUTO_PREPARE_TEST_DB=0 verildi; test veritabanı hazırlığı atlanıyor."
    return 0
  fi

  if [ "${SMOKE_SKIP_EXTERNAL_INFRA:-0}" = "1" ]; then
    echo "ℹ️ SMOKE_SKIP_EXTERNAL_INFRA=1; harici altyapı mevcut değil, test veritabanı hazırlığı atlanıyor."
    return 0
  fi

  if ! is_safe_postgres_identifier "${test_db_name}"; then
    echo "❌ Geçersiz TEST_DATABASE_NAME: yalnız [A-Za-z_][A-Za-z0-9_]* biçimindeki PostgreSQL identifier kabul edilir."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if postgres_identifiers_equal "${test_db_name}" "${primary_db_name}"; then
    echo "❌ TEST_DATABASE_NAME (${test_db_name}) ana POSTGRES_DB (${primary_db_name}) ile aynı olamaz; veri kaybını önlemek için hazırlık durduruldu."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if ! is_safe_postgres_identifier "${test_db_user}"; then
    echo "❌ Geçersiz TEST_DATABASE_USER: yalnız [A-Za-z_][A-Za-z0-9_]* biçimindeki PostgreSQL identifier kabul edilir."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if [ "${#DOCKER_COMPOSE_CMD[@]}" -eq 0 ] && ! resolve_docker_compose_cmd; then
    echo "⚠️ Docker Compose bulunamadı; test veritabanı hazırlığı atlanıyor."
    return 0
  fi

  if [ "${test_db_user}" = "${POSTGRES_USER:-sidar}" ] && [ "${test_db_password}" != "${POSTGRES_PASSWORD}" ]; then
    echo "❌ TEST_DATABASE_PASSWORD ana PostgreSQL parolasından farklıysa ayrı bir TEST_DATABASE_USER tanımlanmalıdır."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  echo "🗄️ İzole test veritabanı hazırlanıyor: ${test_db_name}"
  echo "🔐 PostgreSQL ana rol parolası doğrulanıyor: ${POSTGRES_USER:-sidar}"
  if ! sync_postgres_login_role "${admin_db_user}" "${POSTGRES_USER:-sidar}" "${POSTGRES_PASSWORD}"; then
    echo "❌ PostgreSQL ana rol parolası güncellenemedi: ${POSTGRES_USER:-sidar}"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  echo "🔐 Test rolü doğrulanıyor: ${test_db_user}"
  if ! sync_postgres_login_role "${admin_db_user}" "${test_db_user}" "${test_db_password}"; then
    echo "❌ Test rolü oluşturma/güncelleme başarısız oldu: ${test_db_user}"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if [ "${reset_test_db}" = "1" ]; then
    echo "♻️ RESET_TEST_DATABASE=1; test veritabanı sıfırlanıyor: ${test_db_name}"
    if ! "${DOCKER_COMPOSE_CMD[@]}" exec -T postgres psql \
      -U "${test_db_user}" -d postgres \
      -v ON_ERROR_STOP=1 \
      -c "DROP DATABASE IF EXISTS ${test_db_name} WITH (FORCE);" \
      -c "CREATE DATABASE ${test_db_name};"; then
      echo "❌ Test veritabanı sıfırlanamadı: ${test_db_name}"
      BACKEND_EXIT_CODE=1
      return 1
    fi
  else
    if ! "${DOCKER_COMPOSE_CMD[@]}" exec -T postgres psql \
      -U "${test_db_user}" -d postgres \
      -v ON_ERROR_STOP=1 \
      -c "SELECT 1 FROM pg_database WHERE datname='${test_db_name}'" \
      | tail -n +3 | head -n 1 | grep -q 1; then
      if ! "${DOCKER_COMPOSE_CMD[@]}" exec -T postgres psql \
        -U "${test_db_user}" -d postgres \
        -v ON_ERROR_STOP=1 \
        -c "CREATE DATABASE ${test_db_name};"; then
        echo "❌ Test veritabanı oluşturulamadı: ${test_db_name}"
        BACKEND_EXIT_CODE=1
        return 1
      fi
    fi
  fi

  if ! "${DOCKER_COMPOSE_CMD[@]}" exec -T postgres psql \
    -U "${admin_db_user}" -d postgres \
    -v ON_ERROR_STOP=1 \
    -c "GRANT ALL PRIVILEGES ON DATABASE ${test_db_name} TO ${test_db_user};"; then
    echo "❌ Test veritabanı yetkileri atanamadı: ${test_db_name} -> ${test_db_user}"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  # SQLAlchemy async engine için test URL'i asyncpg sürücüsü ile üretilir.
  export DATABASE_URL="postgresql+asyncpg://${test_db_user}:${test_db_password}@${test_db_host}:${test_db_port}/${test_db_name}"
  export TEST_DATABASE_URL="${DATABASE_URL}"
  echo "ℹ️ DATABASE_URL izole test veritabanı için ayarlandı (kimlik bilgileri loglanmadı): ${test_db_host}:${test_db_port}/${test_db_name}"

  if ! uv run python -c "import asyncpg" >/dev/null 2>&1; then
    echo "❌ asyncpg bulunamadı. Alembic migrasyonu için gerekli runtime bağımlılıkları eksik."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  echo "📦 Alembic migrasyonları uygulanıyor (upgrade head)..."
  if ! uv run alembic upgrade head; then
    echo "❌ Alembic migrasyonu başarısız oldu."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if [ "${RUN_ALEMBIC_DOWNGRADE_CHECK:-1}" = "1" ]; then
    echo "↩️ Alembic downgrade/upgrade zinciri doğrulanıyor (downgrade base && upgrade head)..."
    if ! uv run alembic downgrade base; then
      echo "❌ Alembic downgrade base doğrulaması başarısız oldu."
      BACKEND_EXIT_CODE=1
      return 1
    fi
    if ! uv run alembic upgrade head; then
      echo "❌ Alembic downgrade sonrası upgrade head doğrulaması başarısız oldu."
      BACKEND_EXIT_CODE=1
      return 1
    fi
  else
    echo "⚠️ Alembic downgrade/upgrade zinciri atlandı (RUN_ALEMBIC_DOWNGRADE_CHECK=0)."
  fi

  echo "✅ Test veritabanı ve migrasyon hazırlığı tamamlandı."
  return 0
}

cleanup_test_services() {
  if [ "${DOCKER_TEST_SERVICES_STARTED}" -ne 1 ]; then
    return 0
  fi
  if [ "${#DOCKER_COMPOSE_CMD[@]}" -eq 0 ] && ! resolve_docker_compose_cmd; then
    echo "⚠️ Test sonrası servisler durdurulamadı: Docker Compose komutu bulunamadı."
    return 0
  fi

  echo "🧹 Test sonrası docker servisleri durduruluyor: redis, postgres"
  if ! run_checked "${DOCKER_COMPOSE_CMD[@]}" stop redis postgres >/dev/null 2>&1; then
    echo "⚠️ Redis/PostgreSQL servisleri durdurulurken hata oluştu."
  fi
}
