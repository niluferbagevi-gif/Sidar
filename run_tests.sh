#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

run_precommit_autofix() {
  if ! command -v ruff >/dev/null 2>&1; then
    echo "⚠️ 'ruff' bulunamadı; pre-commit autofix adımı atlanıyor."
    return 0
  fi

  echo "🧹 Pre-commit autofix: ruff check --fix --unsafe-fixes ."
  if ! ruff check --fix --unsafe-fixes .; then
    echo "❌ Ruff autofix sonrası lint kontrolleri başarısız. Testler durduruldu."
    return 1
  fi
}

check_python_version() {
  if ! python - <<'PY'
import sys

major, minor = sys.version_info[:2]
if (major, minor) < (3, 11) or (major, minor) >= (3, 13):
    raise SystemExit(1)
PY
  then
    local current_python
    current_python="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
    echo "❌ Desteklenmeyen Python sürümü: ${current_python}"
    echo "ℹ️ Bu proje için desteklenen aralık: >=3.11, <3.13 (Python 3.11 veya 3.12)."
    echo "ℹ️ Not: Uyumlu sürüm kullanılmadığında SQLAlchemy gibi bağımlılıklar yüklenemez ve ModuleNotFoundError alınabilir."
    exit 1
  fi
}

check_python_version

run_precommit_autofix || exit 1

DEFAULT_COVERAGE_FAIL_UNDER="$(python - <<'PY'
from configparser import ConfigParser
from pathlib import Path

cfg = ConfigParser()
cfg.read(Path(".coveragerc"))
print(cfg.get("report", "fail_under", fallback="90"))
PY
)"

COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-${DEFAULT_COVERAGE_FAIL_UNDER}}"
IS_CI_ENV=0
if [ "${CI:-0}" = "true" ] || [ "${CI:-0}" = "1" ]; then
  IS_CI_ENV=1
fi

TEST_PROFILE="${TEST_PROFILE:-}"
if [ -z "${TEST_PROFILE}" ]; then
  if [ "${IS_CI_ENV}" -eq 1 ]; then
    TEST_PROFILE="ci"
  else
    TEST_PROFILE="local"
  fi
fi

if [ "${TEST_PROFILE}" != "ci" ] && [ "${TEST_PROFILE}" != "local" ]; then
  echo "⚠️ Geçersiz TEST_PROFILE='${TEST_PROFILE}'. 'local' profiline düşülüyor."
  TEST_PROFILE="local"
fi

if [ "${TEST_PROFILE}" = "ci" ]; then
  AUTO_OPEN_ARTIFACTS=0
  PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
  RUN_BENCHMARKS="${RUN_BENCHMARKS:-auto}"
  RUN_STATIC_ANALYSIS="${RUN_STATIC_ANALYSIS:-1}"
else
  AUTO_OPEN_ARTIFACTS="${AUTO_OPEN_ARTIFACTS:-1}"
  PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
  RUN_BENCHMARKS="${RUN_BENCHMARKS:-0}"
  RUN_STATIC_ANALYSIS="${RUN_STATIC_ANALYSIS:-1}"
fi

PERFORMANCE_TEST_DIR="${PERFORMANCE_TEST_DIR:-tests/performance}"
BENCHMARK_BASELINE_NAME="${BENCHMARK_BASELINE_NAME:-baseline}"
BENCHMARK_COMPARE_NAME="${BENCHMARK_COMPARE_NAME:-${BENCHMARK_BASELINE_NAME}}"
BENCHMARK_ENABLE_COMPARE="${BENCHMARK_ENABLE_COMPARE:-0}"
BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-0}"
BENCHMARK_JSON_OUTPUT="${BENCHMARK_JSON_OUTPUT:-artifacts/benchmark/benchmark.json}"
BENCHMARK_TREND_COMPARE="${BENCHMARK_TREND_COMPARE:-0}"
BENCHMARK_TREND_HISTORY="${BENCHMARK_TREND_HISTORY:-artifacts/benchmark/history.json}"
BENCHMARK_TREND_WINDOW="${BENCHMARK_TREND_WINDOW:-10}"
BENCHMARK_TREND_MAX_REGRESSION_PCT="${BENCHMARK_TREND_MAX_REGRESSION_PCT:-15}"
AUTO_HEAL_ON_FAILURE="${AUTO_HEAL_ON_FAILURE:-1}"
AUTO_HEAL_MAX_ATTEMPTS="${AUTO_HEAL_MAX_ATTEMPTS:-12}"
AUTO_HEAL_LOG_PATH="${AUTO_HEAL_LOG_PATH:-artifacts/mypy_errors.log}"

BACKEND_EXIT_CODE=0
FRONTEND_EXIT_CODE=0
BENCHMARK_EXIT_CODE=0
DOCKER_TEST_SERVICES_STARTED=0
DOCKER_COMPOSE_CMD=()

if ! [[ "${COVERAGE_FAIL_UNDER}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "⚠️ Geçersiz COVERAGE_FAIL_UNDER değeri: '${COVERAGE_FAIL_UNDER}'. Varsayılan 90 kullanılacak."
  COVERAGE_FAIL_UNDER="90"
fi

echo "ℹ️ Coverage quality gate eşiği: ${COVERAGE_FAIL_UNDER} (pytest --cov-fail-under ile .coveragerc fail_under değerini override eder)"
echo "ℹ️ Test profili: ${TEST_PROFILE} (CI=${IS_CI_ENV}, AUTO_OPEN_ARTIFACTS=${AUTO_OPEN_ARTIFACTS}, RUN_BENCHMARKS=${RUN_BENCHMARKS}, RUN_STATIC_ANALYSIS=${RUN_STATIC_ANALYSIS})"

# 0) Önceki test artefaktlarını temizle (idempotent başlangıç)
rm -rf .pytest_cache .coverage .coverage.* coverage.xml htmlcov tests/pytest.log web_ui_react/coverage

open_artifact() {
  local target="$1"
  if [ "${IS_CI_ENV}" -eq 1 ]; then
    return 0
  fi

  if [ ! -e "$target" ] || [ "${AUTO_OPEN_ARTIFACTS}" != "1" ]; then
    return 0
  fi

  # WSL2 öncelikli kontroller
  if [ -n "${WSL_DISTRO_NAME:-}" ] && command -v wslview >/dev/null 2>&1; then
    wslview "$target" >/dev/null 2>&1 &
  elif [ -n "${WSL_DISTRO_NAME:-}" ] && command -v explorer.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
    explorer.exe "$(wslpath -w "$target")" >/dev/null 2>&1 &
  # Standart Linux/macOS fallback'leri
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$target" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "$target" >/dev/null 2>&1 &
  elif command -v start >/dev/null 2>&1; then
    start "" "$target" >/dev/null 2>&1 &
  else
    echo "ℹ️ Otomatik açma için desteklenen komut bulunamadı: $target"
  fi
}

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
ensure_uv_available() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "❌ Bu script uv standardını zorunlu kılar ancak 'uv' bulunamadı."
    echo "ℹ️ Önce uv kurun: https://docs.astral.sh/uv/"
    BACKEND_EXIT_CODE=1
    return 1
  fi
  return 0
}

run_static_analysis_gates() {
  if [ "${RUN_STATIC_ANALYSIS}" != "1" ]; then
    echo "ℹ️ Statik analiz adımı atlandı (RUN_STATIC_ANALYSIS=${RUN_STATIC_ANALYSIS})."
    return 0
  fi
  echo "🔍 Linter ve Type Checker çalıştırılıyor..."
  if ! uv run ruff check .; then
    BACKEND_EXIT_CODE=1
    return 1
  fi
  mkdir -p "$(dirname "${AUTO_HEAL_LOG_PATH}")"
  local attempt=0
  local auto_heal_prompt_done=0
  while [ "${attempt}" -le "${AUTO_HEAL_MAX_ATTEMPTS}" ]; do
    if uv run mypy . 2>&1 | tee "${AUTO_HEAL_LOG_PATH}"; then
      return 0
    fi
    if [ "${AUTO_HEAL_ON_FAILURE}" != "1" ] || [ "${attempt}" -ge "${AUTO_HEAL_MAX_ATTEMPTS}" ]; then
      BACKEND_EXIT_CODE=1
      return 1
    fi
    if [ "${IS_CI_ENV}" -ne 1 ] && [ "${auto_heal_prompt_done}" -eq 0 ]; then
      local confirm_auto_heal
      read -r -p "⚠️ Mypy hataları bulundu. Otonom iyileştirme döngüsü başlatılsın mı? (e/H): " confirm_auto_heal
      case "${confirm_auto_heal}" in
        [eE]|[eE][vV][eE][tT]|[yY]|[yY][eE][sS])
          echo "ℹ️ Kullanıcı onayı alındı, otonom iyileştirme döngüsü başlatılıyor."
          ;;
        *)
          echo "ℹ️ Kullanıcı otonom iyileştirme döngüsünü reddetti. Statik analiz adımı başarısız sayılıyor."
          BACKEND_EXIT_CODE=1
          return 1
          ;;
      esac
      auto_heal_prompt_done=1
    fi
    echo "⚠️ Mypy hataları tespit edildi. Otonom iyileştirme döngüsü başlatılıyor... (deneme $((attempt + 1))/${AUTO_HEAL_MAX_ATTEMPTS})"
    if ! uv run python -m scripts.auto_heal --log "${AUTO_HEAL_LOG_PATH}" --source mypy; then
      echo "❌ Otonom ajan düzeltme planını uygulayamadı."
      BACKEND_EXIT_CODE=1
      return 1
    fi
    echo "✅ Otonom iyileştirme tamamlandı. Mypy yeniden çalıştırılıyor..."
    attempt=$((attempt + 1))
  done
}

run_security_analysis_gates() {
  if [ "${RUN_SECURITY_ANALYSIS:-1}" != "1" ]; then
    echo "ℹ️ Güvenlik analizi adımı atlandı (RUN_SECURITY_ANALYSIS=${RUN_SECURITY_ANALYSIS:-1})."
    return 0
  fi

  echo "🛡️ Hızlı SAST + bağımlılık güvenlik taraması çalıştırılıyor..."
  if ! uv run bandit -c pyproject.toml -q -r .; then
    echo "❌ Bandit güvenlik taraması başarısız."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if ! uv run pip-audit; then
    echo "❌ pip-audit güvenlik taraması başarısız."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  return 0
}

ensure_test_services() {
  if [ "${AUTO_DOCKER_TEST_SERVICES:-1}" != "1" ]; then
    echo "ℹ️ AUTO_DOCKER_TEST_SERVICES=0 verildi, Redis/PostgreSQL otomatik başlatma adımı atlanıyor."
    export SMOKE_SKIP_EXTERNAL_INFRA="${SMOKE_SKIP_EXTERNAL_INFRA:-1}"
    echo "ℹ️ SMOKE_SKIP_EXTERNAL_INFRA=${SMOKE_SKIP_EXTERNAL_INFRA} (otomatik servis başlatma kapalı)."
    return 0
  fi

  if ! resolve_docker_compose_cmd; then
    echo "⚠️ Docker Compose bulunamadı; Redis/PostgreSQL otomatik başlatılamadı."
    export SMOKE_SKIP_EXTERNAL_INFRA=1
    echo "ℹ️ SMOKE_SKIP_EXTERNAL_INFRA=1 ayarlandı; harici altyapı smoke testleri atlanacak."
    return 0
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
    echo "❌ Redis/PostgreSQL docker servisleri başlatılamadı."
    export SMOKE_SKIP_EXTERNAL_INFRA=1
    echo "ℹ️ SMOKE_SKIP_EXTERNAL_INFRA=1 ayarlandı; harici altyapı smoke testleri atlanacak."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  wait_for_test_services_ready
  DOCKER_TEST_SERVICES_STARTED=1
}

wait_for_test_services_ready() {
  local max_attempts="${TEST_SERVICES_READY_MAX_ATTEMPTS:-30}"
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
  export SMOKE_SKIP_EXTERNAL_INFRA=1
  echo "ℹ️ SMOKE_SKIP_EXTERNAL_INFRA=1 ayarlandı; harici altyapı smoke testleri atlanacak."
  BACKEND_EXIT_CODE=1
  return 1
}

prepare_test_database() {
  local test_db_name="${TEST_DATABASE_NAME:-sidar_test}"
  local test_db_user="${POSTGRES_USER:-sidar}"
  local test_db_password="${POSTGRES_PASSWORD:-sidar_test}"
  local test_db_host="${POSTGRES_HOST:-localhost}"
  local test_db_port="${POSTGRES_PORT:-5432}"
  local reset_test_db="${RESET_TEST_DATABASE:-1}"

  if [ "${AUTO_PREPARE_TEST_DB:-1}" != "1" ]; then
    echo "ℹ️ AUTO_PREPARE_TEST_DB=0 verildi; test veritabanı hazırlığı atlanıyor."
    return 0
  fi

  if [ "${#DOCKER_COMPOSE_CMD[@]}" -eq 0 ] && ! resolve_docker_compose_cmd; then
    echo "⚠️ Docker Compose bulunamadı; test veritabanı hazırlığı atlanıyor."
    return 0
  fi

  echo "🗄️ İzole test veritabanı hazırlanıyor: ${test_db_name}"
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

  export DATABASE_URL="postgresql+asyncpg://${test_db_user}:${test_db_password}@${test_db_host}:${test_db_port}/${test_db_name}"
  export TEST_DATABASE_URL="${DATABASE_URL}"
  echo "ℹ️ DATABASE_URL test için ayarlandı: ${DATABASE_URL}"

  echo "📦 Alembic migrasyonları uygulanıyor (upgrade head)..."
  if ! uv run alembic upgrade head; then
    echo "❌ Alembic migrasyonu başarısız oldu."
    BACKEND_EXIT_CODE=1
    return 1
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
  "${DOCKER_COMPOSE_CMD[@]}" stop redis postgres >/dev/null 2>&1 || \
    echo "⚠️ Redis/PostgreSQL servisleri durdurulurken hata oluştu."
}

trap cleanup_test_services EXIT

run_pytest_coverage_report() {
  echo "📊 Pytest + Coverage + Quality Gate çalıştırılıyor..."
  local test_dotenv_file="${DOTENV_FILE:-.env.test}"
  echo "ℹ️ Test ortam değişken dosyası: DOTENV_FILE=${test_dotenv_file}"
  if ! python - <<'PY' >/dev/null 2>&1
import tomllib
from pathlib import Path

data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
opt_deps = data.get("project", {}).get("optional-dependencies", {})
deps = opt_deps.get("test") or opt_deps.get("dev") or opt_deps.get("all") or []
deps_l = [d.lower() for d in deps]
assert any("pytest-cov" in d for d in deps_l), "pytest-cov"
assert any("pytest-xdist" in d for d in deps_l), "pytest-xdist"
PY
  then
    echo "❌ pyproject.toml test bağımlılıklarında pytest-cov/pytest-xdist doğrulaması başarısız."
    BACKEND_EXIT_CODE=1
    return
  fi

  if ! python - <<'PY' >/dev/null 2>&1
import coverage  # noqa: F401
import pytest_cov  # noqa: F401
import pytest_asyncio  # noqa: F401
PY
  then
    echo "⚠️ Test ve coverage araçları (pytest-asyncio vb.) eksik. all+dev opsiyonel bağımlılıkları otomatik kuruluyor..."
    echo "ℹ️ all+dev bağımlılıkları uv ile senkronize ediliyor..."
    uv sync --extra all --extra dev

    if ! python -c "import pytest_asyncio" >/dev/null 2>&1; then
      echo "❌ Geliştirici bağımlılıklarının otomatik kurulumu başarısız oldu."
      BACKEND_EXIT_CODE=1
      return
    fi
  fi

  # -c pyproject.toml ile marker/addopts ayarlarının kök dizinden bağımsız şekilde
  # her çağrıda kesin yüklenmesi garanti edilir.
  # Coverage rapor formatları pyproject.toml addopts üzerinden merkezi yönetilir.
  # Sadece fail-under eşiği gerektiğinde CLI'dan override edilir.
  local base_pytest_cmd=(env "DOTENV_FILE=${test_dotenv_file}" uv run pytest -c pyproject.toml --cov-fail-under="${COVERAGE_FAIL_UNDER}")

  if [ "${ENABLE_GPU_TESTS:-1}" != "1" ]; then
    echo "ℹ️ GPU testleri atlanıyor (Çalıştırmak için: ENABLE_GPU_TESTS=1 bash run_tests.sh)"
    base_pytest_cmd+=(-m "not gpu")
  else
    if ! command -v nvidia-smi >/dev/null 2>&1 && ! command -v nvidia-smi.exe >/dev/null 2>&1; then
      echo "⚠️ ENABLE_GPU_TESTS=1 verildi ancak nvidia-smi bulunamadı. GPU testleri güvenli fallback ile atlanıyor."
      base_pytest_cmd+=(-m "not gpu")
    else
      echo "🔥 GPU testleri de dahil ediliyor!"
      if [ "${RUN_GPU_STRESS:-0}" != "1" ]; then
        export RUN_GPU_STRESS=1
        echo "ℹ️ GPU tespit edildiği için testlerde RUN_GPU_STRESS=1 otomatik etkinleştirildi."
      fi
    fi
  fi

  if python -c "import xdist" >/dev/null 2>&1; then
    base_pytest_cmd+=(-n "${PYTEST_WORKERS}")
  fi

  # Benchmark ölçümlerinin doğruluğu için performans testleri bu aşamada
  # özellikle hariç tutulur ve aşağıda tek çekirdekli ayrı fazda çalıştırılır.
  base_pytest_cmd+=(--ignore=tests/performance)
  if [ "${PERFORMANCE_TEST_DIR}" != "tests/performance" ] && [ -d "${PERFORMANCE_TEST_DIR}" ]; then
    base_pytest_cmd+=(--ignore="${PERFORMANCE_TEST_DIR}")
  fi

  # Aşama 1: Unit testler (yüksek paralellik)
  local phase1_cmd=("${base_pytest_cmd[@]}" tests/unit)
  echo "➡️ Aşama 1 (Unit) komutu: ${phase1_cmd[*]}"
  "${phase1_cmd[@]}"
  local phase1_exit=$?

  # Aşama 2: Integration/Smoke/E2E testleri (sınırlı paralellik)
  local phase2_workers="${INTEGRATION_PYTEST_WORKERS:-2}"
  local phase2_cmd=("${base_pytest_cmd[@]}")
  local filtered_phase2_cmd=()
  local skip_next=0
  for arg in "${phase2_cmd[@]}"; do
    if [ "${skip_next}" -eq 1 ]; then
      skip_next=0
      continue
    fi
    if [ "${arg}" = "-n" ]; then
      skip_next=1
      continue
    fi
    filtered_phase2_cmd+=("${arg}")
  done
  phase2_cmd=("${filtered_phase2_cmd[@]}" -n "${phase2_workers}" tests/integration tests/smoke tests/e2e)
  echo "➡️ Aşama 2 (Integration/Smoke/E2E) komutu: ${phase2_cmd[*]}"
  "${phase2_cmd[@]}"
  local phase2_exit=$?

  if [ "${phase1_exit}" -ne 0 ] || [ "${phase2_exit}" -ne 0 ]; then
    BACKEND_EXIT_CODE=1
  else
    BACKEND_EXIT_CODE=0
  fi

  # xdist altında bazı koşullarda sadece .coverage.* shard'ları kalabilir.
  # Önce bunları birleştirmeyi dener, başarısızsa quality gate'i fail eder.
  if [ ! -f ".coverage" ] && [ "${BACKEND_EXIT_CODE}" -eq 0 ]; then
    if compgen -G ".coverage.*" > /dev/null; then
      echo "ℹ️ .coverage bulunamadı fakat .coverage.* shard dosyaları tespit edildi. coverage combine deneniyor..."
      if python -m coverage combine && python -m coverage html -d htmlcov && python -m coverage xml -o coverage.xml; then
        echo "✅ coverage combine başarılı; raporlar yeniden üretildi."
      else
        echo "❌ coverage combine başarısız oldu. Paralel testlerde coverage verisi toparlanamadı."
        BACKEND_EXIT_CODE=1
      fi
    else
      echo "⚠️ Uyarı: Testler başarılı görünüyor ancak .coverage dosyası üretilemedi. xdist worker'ları crash olmuş olabilir."
      BACKEND_EXIT_CODE=1
    fi
  fi

  if [ -f "htmlcov/index.html" ]; then
    echo "✅ Coverage HTML raporu oluşturuldu: htmlcov/index.html"
    open_artifact "htmlcov/index.html"
  else
    echo "⚠️ Coverage raporu oluşturulamadı: htmlcov/index.html bulunamadı."
  fi
}

# 1) Backend testleri + coverage (pyproject addopts ile) + quality gate
if ensure_uv_available && sync_ollama_models && ensure_test_services && prepare_test_database && run_static_analysis_gates && run_security_analysis_gates; then
  run_pytest_coverage_report
else
  echo "❌ Backend testleri atlandı: önkoşul adımlarından biri başarısız."
  BACKEND_EXIT_CODE=1
fi

# 2) Kritik yol performans baseline testleri (pytest-benchmark)
if [ "${RUN_BENCHMARKS}" = "0" ]; then
  echo "⚠️ Benchmark testleri RUN_BENCHMARKS=0 ile atlandı."
  echo "⚠️ Performans regresyonlarının erken tespiti için CI/local pipeline'larda benchmark fazını düzenli çalıştırın."
  echo "ℹ️ Öneri (lokal): RUN_BENCHMARKS=required bash run_tests.sh"
  echo "ℹ️ Öneri (hedefli): uv run pytest -q ${PERFORMANCE_TEST_DIR} --benchmark-json=${BENCHMARK_JSON_OUTPUT}"
elif [ -d "${PERFORMANCE_TEST_DIR}" ]; then
  echo "📊 Aşama 2: Performans benchmark testleri tek çekirdek üzerinde koşturuluyor..."
  benchmark_dotenv_file="${DOTENV_FILE:-.env.test}"
  mkdir -p "$(dirname "${BENCHMARK_JSON_OUTPUT}")"
  benchmark_cmd=(
    env "DOTENV_FILE=${benchmark_dotenv_file}" uv run python -m pytest -c pyproject.toml -v "${PERFORMANCE_TEST_DIR}" -n 0 --no-cov
    --benchmark-save="${BENCHMARK_BASELINE_NAME}"
    --benchmark-json="${BENCHMARK_JSON_OUTPUT}"
  )

  if [ "${BENCHMARK_ENABLE_COMPARE}" = "1" ]; then
    if compgen -G ".benchmarks/*/*_${BENCHMARK_COMPARE_NAME}.json" > /dev/null; then
      echo "📈 Benchmark karşılaştırması etkin (--benchmark-compare=${BENCHMARK_COMPARE_NAME})."
      benchmark_cmd+=(--benchmark-compare="${BENCHMARK_COMPARE_NAME}")
    else
      echo "⚠️ Benchmark karşılaştırması atlandı: '.benchmarks' altında '${BENCHMARK_COMPARE_NAME}' etiketiyle eşleşen kayıt bulunamadı."
      if [ "${BENCHMARK_COMPARE_REQUIRED}" = "1" ]; then
        echo "❌ BENCHMARK_COMPARE_REQUIRED=1 iken karşılaştırma için baseline bulunamadı."
        BENCHMARK_EXIT_CODE=1
      fi
    fi
  else
    echo "ℹ️ Benchmark karşılaştırması devre dışı (BENCHMARK_ENABLE_COMPARE=0)."
  fi

  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ]; then
    echo "➡️ Çalıştırılan komut: ${benchmark_cmd[*]}"
    "${benchmark_cmd[@]}"
    BENCHMARK_EXIT_CODE=$?
  fi

  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ] && [ -f "${BENCHMARK_JSON_OUTPUT}" ]; then
    echo "✅ Benchmark JSON raporu oluşturuldu: ${BENCHMARK_JSON_OUTPUT}"
  elif [ "${BENCHMARK_EXIT_CODE}" -eq 0 ]; then
    echo "⚠️ Benchmark testleri geçti ancak JSON raporu bulunamadı: ${BENCHMARK_JSON_OUTPUT}"
    BENCHMARK_EXIT_CODE=1
  fi

  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ] && [ "${BENCHMARK_TREND_COMPARE}" = "1" ]; then
    if [ -f "coverage.xml" ] && [ -f "${BENCHMARK_JSON_OUTPUT}" ]; then
      echo "📉 Benchmark trend + coverage.xml karşılaştırması çalıştırılıyor..."
      if ! python scripts/ci/check_benchmark_coverage_trend.py \
        --benchmark-json "${BENCHMARK_JSON_OUTPUT}" \
        --coverage-xml coverage.xml \
        --history-json "${BENCHMARK_TREND_HISTORY}" \
        --window "${BENCHMARK_TREND_WINDOW}" \
        --max-regression-pct "${BENCHMARK_TREND_MAX_REGRESSION_PCT}"; then
        echo "❌ Benchmark trend karşılaştırması kalite kapısından kaldı."
        BENCHMARK_EXIT_CODE=1
      fi
    else
      echo "⚠️ Benchmark trend karşılaştırması atlandı: coverage.xml veya benchmark JSON bulunamadı."
      BENCHMARK_EXIT_CODE=1
    fi
  fi
else
  echo "⚠️ Benchmark testi atlandı: ${PERFORMANCE_TEST_DIR} bulunamadı."
  if [ "${RUN_BENCHMARKS}" = "required" ]; then
    echo "❌ RUN_BENCHMARKS=required iken benchmark dizini bulunamadı."
    BENCHMARK_EXIT_CODE=1
  fi
fi

# 3) Frontend React testleri ve coverage (web_ui_react varsa zorunlu quality gate)
if [ -d "web_ui_react" ] && [ -f "web_ui_react/package.json" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "❌ web_ui_react dizini var ama npm bulunamadı — React testleri çalıştırılamıyor."
    FRONTEND_EXIT_CODE=1
  else
    echo "🚀 Frontend (React) Testleri Başlıyor..."
    if pushd web_ui_react > /dev/null; then
      # Yerel ortamda yavaşlığı önlemek için CI değişkenine göre davran.
      if [ "${CI:-0}" = "true" ] || [ "${CI:-0}" = "1" ]; then
        echo "ℹ️ CI ortamı tespit edildi, 'npm ci' çalıştırılıyor..."
        npm ci
      else
        echo "ℹ️ Yerel ortam tespit edildi, 'npm install' çalıştırılıyor..."
        npm install
      fi
      local_npm_ci_exit=$?
      if [ "${local_npm_ci_exit}" -ne 0 ]; then
        FRONTEND_EXIT_CODE=${local_npm_ci_exit}
      else
        npm run test:coverage
        FRONTEND_EXIT_CODE=$?
      fi

      for report in coverage/lcov-report/index.html coverage/index.html; do
        open_artifact "$PWD/$report"
      done

      popd > /dev/null || true
    else
      FRONTEND_EXIT_CODE=1
    fi
  fi
elif [ -d "web_ui_react" ]; then
  echo "⚠️ Frontend testleri atlandı: web_ui_react/package.json bulunamadı."
fi

echo "======================================================"

# 4) Final Durum Değerlendirmesi
if [ "${BACKEND_EXIT_CODE}" -ne 0 ] || [ "${FRONTEND_EXIT_CODE}" -ne 0 ] || [ "${BENCHMARK_EXIT_CODE}" -ne 0 ]; then
  echo "❌ Bazı testler veya kalite kapıları (coverage) başarısız oldu!"
  echo "   Backend Çıkış Kodu: ${BACKEND_EXIT_CODE}"
  echo "   Frontend Çıkış Kodu: ${FRONTEND_EXIT_CODE}"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE}"
  exit 1
else
  echo "✅ Tüm Backend, Frontend ve Benchmark testleri BAŞARIYLA tamamlandı!"
  exit 0
fi
