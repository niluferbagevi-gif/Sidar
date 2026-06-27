#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || exit 1

RUN_TESTS_STAGE="${RUN_TESTS_STAGE:-all}"
print_usage() {
  cat <<'USAGE'
Usage: bash run_tests.sh [--stage all|static|unit|integration|smoke|e2e|backend|frontend|bats[,..]]

Stage examples:
  bash run_tests.sh --stage static
  bash run_tests.sh --stage unit
  bash run_tests.sh --stage integration,smoke
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --stage)
      if [ "$#" -lt 2 ] || [ -z "${2:-}" ]; then
        echo "❌ --stage için değer gerekli." >&2
        print_usage >&2
        exit 2
      fi
      RUN_TESTS_STAGE="$2"
      shift 2
      ;;
    --stage=*)
      RUN_TESTS_STAGE="${1#--stage=}"
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      echo "❌ Bilinmeyen argüman: $1" >&2
      print_usage >&2
      exit 2
      ;;
  esac
done

normalize_test_stages() {
  local raw="${RUN_TESTS_STAGE:-all}"
  raw="${raw// /}"
  raw="${raw,,}"
  if [ -z "${raw}" ]; then
    raw="all"
  fi
  local normalized=","
  local item
  IFS=',' read -ra _stage_items <<< "${raw}"
  for item in "${_stage_items[@]}"; do
    case "${item}" in
      all|static|unit|integration|smoke|e2e|backend|frontend|bats)
        normalized+="${item},"
        ;;
      "")
        ;;
      *)
        echo "❌ Geçersiz --stage değeri: ${item}" >&2
        print_usage >&2
        exit 2
        ;;
    esac
  done
  RUN_TESTS_STAGE="${normalized}"
}

normalize_test_stages

stage_all_selected() {
  [[ "${RUN_TESTS_STAGE}" == *,all,* ]]
}

stage_selected() {
  local stage="$1"
  stage_all_selected || [[ "${RUN_TESTS_STAGE}" == *,"${stage}",* ]]
}

backend_infra_required_for_stage() {
  stage_all_selected || stage_selected backend || stage_selected integration || stage_selected smoke || stage_selected e2e
}

BATS_REPORT_DIR="${BATS_REPORT_DIR:-artifacts/bats}"
if [[ "${BATS_REPORT_DIR}" != artifacts/* || "${BATS_REPORT_DIR}" == *".."* ]]; then
  echo "❌ BATS_REPORT_DIR yalnız artifacts/ altında güvenli bir göreli yol olabilir: ${BATS_REPORT_DIR}"
  exit 1
fi

# Codespaces/WSL overlay dosya sistemlerinde uv hardlink denemesi eksik paket-data dosyası
# semptomlarına yol açabildiği için UV_LINK_MODE=copy ile deterministik kurulum tercih edilir.
if [ -z "${UV_LINK_MODE:-}" ] && {
  [ "${CODESPACES:-}" = "true" ] ||
  [ "${GITHUB_CODESPACES:-}" = "true" ] ||
  grep -qi microsoft /proc/version 2>/dev/null
}; then
  export UV_LINK_MODE=copy
fi

PROJECT_VENV_ENV="${UV_PROJECT_ENVIRONMENT:-.venv}"
case "${PROJECT_VENV_ENV}" in
  /*) PROJECT_VENV_DIR="${PROJECT_VENV_ENV}" ;;
  *) PROJECT_VENV_DIR="${SCRIPT_DIR}/${PROJECT_VENV_ENV}" ;;
esac

read_preferred_python_version() {
  if [ -n "${SIDAR_PYTHON_VERSION:-}" ]; then
    printf '%s' "${SIDAR_PYTHON_VERSION}"
    return 0
  fi
  if [ -f "${SCRIPT_DIR}/.python-version" ]; then
    head -n 1 "${SCRIPT_DIR}/.python-version" | tr -d '[:space:]'
    return 0
  fi
  printf '3.11'
}

assert_venv_writable() {
  if [ ! -d "${PROJECT_VENV_DIR}" ]; then
    return 0
  fi

  local owner
  owner="$(stat -c %U "${PROJECT_VENV_DIR}" 2>/dev/null || true)"
  if [ -n "${owner}" ] && [ "${owner}" != "${USER:-$(id -un)}" ]; then
    echo "❌ .venv sahipliği mevcut kullanıcıyla uyuşmuyor (owner=${owner}, user=${USER:-$(id -un)})."
    echo "   Düzeltme: sudo chown -R ${USER:-$(id -un)}:${USER:-$(id -un)} \"${PROJECT_VENV_DIR}\""
    return 1
  fi

  if [ ! -w "${PROJECT_VENV_DIR}" ]; then
    echo "❌ .venv dizini yazılabilir değil: ${PROJECT_VENV_DIR}"
    echo "   Düzeltme: sudo chown -R ${USER:-$(id -un)}:${USER:-$(id -un)} \"${PROJECT_VENV_DIR}\""
    return 1
  fi

  return 0
}


if ! assert_venv_writable; then
  exit 1
fi


ensure_project_venv() {
  export UV_PROJECT_ENVIRONMENT="${PROJECT_VENV_ENV}"

  if ! command -v uv >/dev/null 2>&1; then
    return 0
  fi

  local preferred_python
  preferred_python="$(read_preferred_python_version)"
  local recreate_venv=0

  if [ ! -x "${PROJECT_VENV_DIR}/bin/python" ]; then
    recreate_venv=1
  elif ! "${PROJECT_VENV_DIR}/bin/python" - <<'PY_VENV_CHECK' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)
PY_VENV_CHECK
  then
    recreate_venv=1
  elif [ -n "${preferred_python}" ] && ! "${PROJECT_VENV_DIR}/bin/python" - "${preferred_python}" <<'PY_VENV_VERSION' >/dev/null 2>&1
import sys

preferred = sys.argv[1].strip()
if not preferred:
    raise SystemExit(0)
major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
# Only enforce major.minor pins such as 3.11; patch-level pins remain uv's job.
parts = preferred.split(".")
if len(parts) >= 2 and all(part.isdigit() for part in parts[:2]):
    raise SystemExit(0 if major_minor == ".".join(parts[:2]) else 1)
raise SystemExit(0)
PY_VENV_VERSION
  then
    recreate_venv=1
  fi

  if [ "${recreate_venv}" -eq 1 ]; then
    echo "ℹ️ Proje sanal ortamı hazırlanıyor: uv venv --python ${preferred_python} ${PROJECT_VENV_ENV}"
    rm -rf "${PROJECT_VENV_DIR}"
    uv venv --python "${preferred_python}" "${PROJECT_VENV_ENV}"
  fi

  if [ -f "${PROJECT_VENV_DIR}/bin/activate" ]; then
    # shellcheck disable=SC1090
    source "${PROJECT_VENV_DIR}/bin/activate"
  fi
}

ensure_project_venv

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

run_precommit_autofix() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "⚠️ 'uv' bulunamadı; pre-commit autofix adımı atlanıyor."
    return 0
  fi

  local ruff_autofix_cmd=(uv run ruff check --fix)
  local unsafe_fixes="${RUFF_AUTOFIX_UNSAFE:-0}"
  local unsafe_rules="${RUFF_AUTOFIX_UNSAFE_RULES:-I,UP}"
  if [ "${unsafe_fixes}" = "1" ]; then
    if [ -z "${unsafe_rules}" ]; then
      echo "⚠️ RUFF_AUTOFIX_UNSAFE=1 ancak RUFF_AUTOFIX_UNSAFE_RULES boş; unsafe fixler atlanıyor."
    else
      ruff_autofix_cmd+=(--unsafe-fixes --select "${unsafe_rules}")
      echo "⚠️ Ruff unsafe fixleri sınırlı selector listesiyle çalışacak: ${unsafe_rules}"
    fi
  fi
  ruff_autofix_cmd+=(.)

  echo "🧹 Pre-commit autofix: ${ruff_autofix_cmd[*]}"
  if ! "${ruff_autofix_cmd[@]}"; then
    echo "❌ Ruff autofix sonrası lint kontrolleri başarısız. Testler durduruldu."
    return 1
  fi
}

check_python_version() {
  if ! python - <<'PY'
import sys

major, minor = sys.version_info[:2]
if (major, minor) < (3, 11) or (major, minor) >= (3, 12):
    raise SystemExit(1)
PY
  then
    local current_python
    current_python="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
    echo "❌ Desteklenmeyen Python sürümü: ${current_python}"
    echo "ℹ️ Bu proje için desteklenen aralık: >=3.11, <3.12 (yalnızca Python 3.11)."
    echo "ℹ️ Not: Uyumlu sürüm kullanılmadığında SQLAlchemy gibi bağımlılıklar yüklenemez ve ModuleNotFoundError alınabilir."
    exit 1
  fi
}

check_python_version

generate_test_secret_value() {
  python - <<'PY_SECRET' 2>/dev/null || openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n='
import secrets
print(secrets.token_urlsafe(32))
PY_SECRET
}

render_generated_secret_sentinels() {
  local target="$1"
  local generated_password=""

  if [ ! -f "${target}" ] || ! grep -q '^POSTGRES_PASSWORD=__GENERATE__$' "${target}"; then
    return 0
  fi

  generated_password="$(generate_test_secret_value)"
  if [ -z "${generated_password}" ]; then
    echo "⚠️ POSTGRES_PASSWORD=__GENERATE__ için parola üretilemedi; '${target}' dosyasını elle güncelleyin."
    return 1
  fi

  python - "${target}" "${generated_password}" <<'PY_RENDER'
from pathlib import Path
import sys

path = Path(sys.argv[1])
password = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
path.write_text(
    "\n".join(
        f"POSTGRES_PASSWORD={password}" if line == "POSTGRES_PASSWORD=__GENERATE__" else line
        for line in lines
    )
    + "\n",
    encoding="utf-8",
)
PY_RENDER
  echo "✅ '${target}' içindeki POSTGRES_PASSWORD=__GENERATE__ güçlü lokal parola ile değiştirildi."
}

# Test ortam değişken dosyasının (.env.test veya DOTENV_FILE ile belirtilen)
# var olduğundan emin olur; yoksa .env.test.example şablonundan otomatik
# olarak oluşturur. Böylece yeni klonlanan bir checkout'ta `bash run_tests.sh`
# elle hazırlık gerektirmeden çalışabilir.
ensure_test_dotenv() {
  local target="${DOTENV_FILE:-.env.test}"
  local template=".env.test.example"

  if [ -f "${target}" ]; then
    return 0
  fi

  if [ ! -f "${template}" ]; then
    echo "⚠️ '${target}' bulunamadı ve şablon '${template}' da mevcut değil; varsayılan değerlerle devam edilecek."
    return 0
  fi

  echo "ℹ️ '${target}' bulunamadı; '${template}' şablonundan otomatik oluşturuluyor."
  if cp "${template}" "${target}"; then
    render_generated_secret_sentinels "${target}" || true
    echo "✅ '${target}' oluşturuldu. Lokal ihtiyaçlarınıza göre düzenleyebilirsiniz (sırlar yalnızca bu dosyada tutulur)."
  else
    echo "⚠️ '${target}' otomatik oluşturulamadı; ortam değişkenleri olmadan devam edilecek."
  fi
}

ensure_test_dotenv

cleanup_zone_identifier_artifacts() {
  if [ "${CLEAN_ZONE_IDENTIFIER_ARTIFACTS:-1}" != "1" ]; then
    echo "ℹ️ Zone.Identifier temizliği devre dışı (CLEAN_ZONE_IDENTIFIER_ARTIFACTS=${CLEAN_ZONE_IDENTIFIER_ARTIFACTS:-0})."
    return 0
  fi

  echo "🧹 Windows Zone.Identifier yan dosyaları temizleniyor..."
  if ! uv run python scripts/cleanup_zone_identifier.py --root .; then
    echo "❌ Zone.Identifier temizliği başarısız oldu."
    return 1
  fi
}

cleanup_zone_identifier_artifacts || exit 1

run_precommit_autofix || exit 1

COVERAGE_RATCHET_STATE_FILE="${COVERAGE_RATCHET_STATE_FILE:-.coveragerc}"
COVERAGE_RATCHET_MIN_EXISTING_GATE="${COVERAGE_RATCHET_MIN_EXISTING_GATE:-5}"

validate_coverage_ratchet_state() {
  if [ ! -f "${COVERAGE_RATCHET_STATE_FILE}" ]; then
    echo "❌ Coverage ratchet state dosyası bulunamadı: ${COVERAGE_RATCHET_STATE_FILE}" >&2
    echo "   Bu dosya repo'ya commit edilmeli ve .gitignore kapsamına alınmamalıdır." >&2
    echo "   Baseline kaybı, coverage gate'in %0'dan yeniden başlamasına neden olabilir." >&2
    return 1
  fi

  python - "${COVERAGE_RATCHET_STATE_FILE}" "${COVERAGE_RATCHET_MIN_EXISTING_GATE}" <<'PY_RATCHET_STATE'
from configparser import ConfigParser
from pathlib import Path
import sys

state_path = Path(sys.argv[1])
min_gate = float(sys.argv[2])
cfg = ConfigParser()
cfg.read(state_path)
if not cfg.has_section("report") or not cfg.has_option("report", "fail_under"):
    raise SystemExit(f"{state_path} içinde [report] fail_under bulunamadı")
try:
    gate = float(cfg.get("report", "fail_under"))
except ValueError as exc:
    raise SystemExit(f"{state_path} içindeki fail_under sayısal değil") from exc
if gate < min_gate:
    raise SystemExit(
        f"{state_path} fail_under={gate:g}; beklenen minimum {min_gate:g}. "
        "Coverage ratchet baseline sıfırlanmış olabilir."
    )
print(f"{gate:g}")
PY_RATCHET_STATE
}

DEFAULT_COVERAGE_FAIL_UNDER="$(validate_coverage_ratchet_state)" || exit 1

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

# AGENTS.md §2.5.4: coverage hedefleri üç ayrı operasyon profilinde izlenir.
#   - local profile  → COVERAGE_FAIL_UNDER_LOCAL    (varsayılan: .coveragerc)
#   - ci profile     → COVERAGE_FAIL_UNDER_CI       (varsayılan: .coveragerc)
#   - campaign opt-in → COVERAGE_FAIL_UNDER_CAMPAIGN (varsayılan: 100)
# Doğrudan COVERAGE_FAIL_UNDER atanırsa o değer her profilin önüne geçer
# (geri uyumluluk için korunur). Coverage campaign opt-in'i ya CLI'dan
# COVERAGE_CAMPAIGN=1 ile ya da otonom döngünün
# AUTONOMOUS_LOOP_OPERATION_PROFILE=coverage-campaign etiketi ile tetiklenir.
COVERAGE_CAMPAIGN_PROFILE=0
if [ "${COVERAGE_CAMPAIGN:-0}" = "1" ] \
    || [ "${AUTONOMOUS_LOOP_OPERATION_PROFILE:-}" = "coverage-campaign" ]; then
  COVERAGE_CAMPAIGN_PROFILE=1
fi

if [ -n "${COVERAGE_FAIL_UNDER:-}" ]; then
  COVERAGE_FAIL_UNDER_SOURCE="explicit-override"
elif [ "${COVERAGE_CAMPAIGN_PROFILE}" -eq 1 ]; then
  COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER_CAMPAIGN:-100}"
  COVERAGE_FAIL_UNDER_SOURCE="campaign"
elif [ "${TEST_PROFILE}" = "ci" ]; then
  COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER_CI:-${DEFAULT_COVERAGE_FAIL_UNDER}}"
  COVERAGE_FAIL_UNDER_SOURCE="ci"
else
  COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER_LOCAL:-${DEFAULT_COVERAGE_FAIL_UNDER}}"
  COVERAGE_FAIL_UNDER_SOURCE="local"
fi

# Yerel/CI profillerinde ratchet üst sınırını varsayılan 99'da tutarak %0.x
# dalgalanma için 1 puanlık tampon bırakıyoruz; coverage kampanyasında veya
# bilinçli strict-local opt-in'de %100 aspirasyonel hedefe izin veriyoruz.
# Açık COVERAGE_RATCHET_MAX_GATE atandıysa o değer her profilin önüne geçer.
if [ -z "${COVERAGE_RATCHET_MAX_GATE:-}" ]; then
  if [ "${COVERAGE_CAMPAIGN_PROFILE}" -eq 1 ] || [ "${COVERAGE_STRICT_LOCAL_RATCHET:-0}" = "1" ]; then
    COVERAGE_RATCHET_MAX_GATE="100"
  else
    COVERAGE_RATCHET_MAX_GATE="99"
  fi
fi
export COVERAGE_RATCHET_MAX_GATE

if [ "${TEST_PROFILE}" = "ci" ]; then
  AUTO_OPEN_ARTIFACTS=0
  PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
  PYTEST_DIST_MODE="${PYTEST_DIST_MODE:-loadgroup}"
  RUN_BENCHMARKS="${RUN_BENCHMARKS:-auto}"
  RUN_STATIC_ANALYSIS="${RUN_STATIC_ANALYSIS:-1}"
  RUN_BATS_TESTS="${RUN_BATS_TESTS:-1}"
  RUN_FRONTEND_E2E="${RUN_FRONTEND_E2E:-1}"
else
  AUTO_OPEN_ARTIFACTS="${AUTO_OPEN_ARTIFACTS:-1}"
  PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
  PYTEST_DIST_MODE="${PYTEST_DIST_MODE:-loadgroup}"
  RUN_BENCHMARKS="${RUN_BENCHMARKS:-required}"
  RUN_STATIC_ANALYSIS="${RUN_STATIC_ANALYSIS:-1}"
  RUN_BATS_TESTS="${RUN_BATS_TESTS:-auto}"
  RUN_FRONTEND_E2E="${RUN_FRONTEND_E2E:-auto}"
fi
RUN_FRONTEND_E2E_AUTO_INSTALL="${RUN_FRONTEND_E2E_AUTO_INSTALL:-1}"
# RETRY_ON_FAIL genel kullanıcı kısayoludur; namespaced değer verilirse öncelik ondadır.
FRONTEND_E2E_RETRY_ON_FAIL="${FRONTEND_E2E_RETRY_ON_FAIL:-${RETRY_ON_FAIL:-1}}"
FRONTEND_E2E_NPM_SCRIPT="${FRONTEND_E2E_NPM_SCRIPT:-test:e2e:smoke}"
if [ "${TEST_PROFILE}" = "ci" ]; then
  BENCHMARK_ENFORCE_RESULT="${BENCHMARK_ENFORCE_RESULT:-1}"
  FRONTEND_E2E_ENFORCE_RESULT="${FRONTEND_E2E_ENFORCE_RESULT:-${ENFORCE_FRONTEND_E2E:-1}}"
else
  # Playwright smoke senaryoları stabil hale geldi; çalıştığı anda sonucu kalite kapısını kırar.
  # Geçici yerel flake araştırması için FRONTEND_E2E_ENFORCE_RESULT=0 veya ENFORCE_FRONTEND_E2E=0 verilebilir.
  BENCHMARK_ENFORCE_RESULT="${BENCHMARK_ENFORCE_RESULT:-1}"
  FRONTEND_E2E_ENFORCE_RESULT="${FRONTEND_E2E_ENFORCE_RESULT:-${ENFORCE_FRONTEND_E2E:-1}}"
fi

SIDAR_RUN_BACKEND_PYTEST=1
if ! stage_all_selected; then
  RUN_STATIC_ANALYSIS=0
  RUN_BATS_TESTS=0
  RUN_FRONTEND_E2E=0
  RUN_BENCHMARKS=0
  SIDAR_RUN_BACKEND_PYTEST=0
  if stage_selected static; then
    RUN_STATIC_ANALYSIS=1
  fi
  if stage_selected backend || stage_selected unit || stage_selected integration || stage_selected smoke || stage_selected e2e; then
    SIDAR_RUN_BACKEND_PYTEST=1
  fi
  if stage_selected bats; then
    RUN_BATS_TESTS=1
  fi
  if stage_selected frontend; then
    RUN_FRONTEND_E2E=1
  fi
fi

if [ "${RUN_FRONTEND_E2E}" != "1" ]; then
  # Yerel auto/opt-out akışında npm paket kurulumu browser binary indirmemeli.
  # Auto modu, frontend bağımlılıkları hazırlandıktan sonra cache'deki Node
  # Playwright Chromium executable'ını doğrular; cache eksikse kontrollü npx
  # adımıyla tek seferlik kurulumu deneyerek smoke kapısını etkinleştirir.
  export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
fi

PERFORMANCE_TEST_DIR="${PERFORMANCE_TEST_DIR:-tests/performance}"
BENCHMARK_BASELINE_NAME="${BENCHMARK_BASELINE_NAME:-baseline}"
BENCHMARK_COMPARE_NAME="${BENCHMARK_COMPARE_NAME:-${BENCHMARK_BASELINE_NAME}}"
BENCHMARK_ENABLE_COMPARE="${BENCHMARK_ENABLE_COMPARE:-1}"
if [ "${TEST_PROFILE}" = "ci" ]; then
  BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-1}"
  BENCHMARK_ENFORCE_COMPARE="${BENCHMARK_ENFORCE_COMPARE:-1}"
  BENCHMARK_COMPARE_FAIL="${BENCHMARK_COMPARE_FAIL:-mean:10%}"
else
  BENCHMARK_COMPARE_REQUIRED="${BENCHMARK_COMPARE_REQUIRED:-0}"
  # Yerel profil ilk kurulumda baseline seed edebilsin diye karşılaştırma zorunluluğu varsayılan kapalıdır.
  # Sıkı yerel regresyon kapısı için BENCHMARK_COMPARE_REQUIRED=1, rapor-only karşılaştırma için BENCHMARK_ENFORCE_COMPARE=0 verin.
  BENCHMARK_ENFORCE_COMPARE="${BENCHMARK_ENFORCE_COMPARE:-1}"
  BENCHMARK_COMPARE_FAIL="${BENCHMARK_COMPARE_FAIL:-mean:15%}"
fi
BENCHMARK_DISABLE_GC="${BENCHMARK_DISABLE_GC:-1}"
BENCHMARK_WARMUP="${BENCHMARK_WARMUP:-on}"
BENCHMARK_WARMUP_ITERATIONS="${BENCHMARK_WARMUP_ITERATIONS:-100000}"
BENCHMARK_JSON_OUTPUT="${BENCHMARK_JSON_OUTPUT:-artifacts/benchmark/benchmark.json}"
BENCHMARK_TREND_COMPARE="${BENCHMARK_TREND_COMPARE:-0}"
BENCHMARK_TREND_HISTORY="${BENCHMARK_TREND_HISTORY:-artifacts/benchmark/history.json}"
BENCHMARK_TREND_WINDOW="${BENCHMARK_TREND_WINDOW:-10}"
BENCHMARK_TREND_MAX_REGRESSION_PCT="${BENCHMARK_TREND_MAX_REGRESSION_PCT:-15}"
AUTO_HEAL_ON_FAILURE="${AUTO_HEAL_ON_FAILURE:-0}"
AUTO_HEAL_MAX_ATTEMPTS="${AUTO_HEAL_MAX_ATTEMPTS:-2}"
AUTO_HEAL_BATCH_RETRIES="${AUTO_HEAL_BATCH_RETRIES:-0}"
AUTO_HEAL_LOG_PATH="${AUTO_HEAL_LOG_PATH:-artifacts/mypy_errors.log}"
AUTO_BUILD_DOCKER_TEST_IMAGE="${AUTO_BUILD_DOCKER_TEST_IMAGE:-0}"
AUTO_INSTALL_CI_SYSTEM_DEPS="${AUTO_INSTALL_CI_SYSTEM_DEPS:-0}"
DOCKER_TEST_IMAGE_BUILD_CONTEXT="${DOCKER_TEST_IMAGE_BUILD_CONTEXT:-.}"
AUTO_HEAL_RESULT_PATH="${AUTO_HEAL_RESULT_PATH:-artifacts/auto_heal_result.json}"

BACKEND_EXIT_CODE=0
FRONTEND_EXIT_CODE=0
FRONTEND_LINT_EXIT_CODE=0
FRONTEND_COVERAGE_EXIT_CODE=0
FRONTEND_NPM_AUDIT_EXIT_CODE=0
FRONTEND_E2E_EXIT_CODE=0
FRONTEND_LINT_RAN=0
FRONTEND_COVERAGE_RAN=0
FRONTEND_NPM_AUDIT_RAN=0
FRONTEND_E2E_RAN=0
BENCHMARK_EXIT_CODE=0
FRONTEND_COVERAGE_REPORT_PATH="web_ui_react/coverage/index.html"
FRONTEND_PLAYWRIGHT_REPORT_PATH="web_ui_react/playwright-report/index.html"
DOCKER_TEST_SERVICES_STARTED=0
DOCKER_COMPOSE_CMD=()
BACKEND_FAILURE_REASONS=()

record_backend_failure() {
  local reason="$1"
  local existing
  for existing in "${BACKEND_FAILURE_REASONS[@]}"; do
    if [ "${existing}" = "${reason}" ]; then
      return 0
    fi
  done
  BACKEND_FAILURE_REASONS+=("${reason}")
}

format_backend_failure_reasons() {
  if [ "${#BACKEND_FAILURE_REASONS[@]}" -eq 0 ]; then
    printf 'belirlenemedi'
    return 0
  fi

  local reason
  printf '%s' "${BACKEND_FAILURE_REASONS[0]}"
  for reason in "${BACKEND_FAILURE_REASONS[@]:1}"; do
    printf ', %s' "${reason}"
  done
}

format_quality_status() {
  local code="$1"
  local ran="${2:-1}"
  local label_not_run="${3:-çalışmadı}"
  if [ "${ran}" != "1" ]; then
    printf '%s' "${label_not_run}"
  elif [ "${code}" = "0" ]; then
    printf 'geçti'
  else
    printf 'başarısız (exit=%s)' "${code}"
  fi
}

print_frontend_quality_summary() {
  echo ""
  echo "🧭 Frontend kalite kapısı özeti"
  echo "   Lint (npm run lint): $(format_quality_status "${FRONTEND_LINT_EXIT_CODE}" "${FRONTEND_LINT_RAN}")"
  echo "   Coverage (npm run test:coverage): $(format_quality_status "${FRONTEND_COVERAGE_EXIT_CODE}" "${FRONTEND_COVERAGE_RAN}")"
  echo "   Dependency audit (npm run audit:high): $(format_quality_status "${FRONTEND_NPM_AUDIT_EXIT_CODE}" "${FRONTEND_NPM_AUDIT_RAN}")"
  echo "   Playwright (${FRONTEND_E2E_NPM_SCRIPT}): $(format_quality_status "${FRONTEND_E2E_EXIT_CODE}" "${FRONTEND_E2E_RAN}" "atlanmış") (enforce=${FRONTEND_E2E_ENFORCE_RESULT})"
  if [ -f "${FRONTEND_COVERAGE_REPORT_PATH}" ]; then
    echo "   Frontend coverage artefaktı: ${FRONTEND_COVERAGE_REPORT_PATH}"
  else
    echo "   Frontend coverage artefaktı: üretilmedi (${FRONTEND_COVERAGE_REPORT_PATH})"
  fi
  if [ -f "${FRONTEND_PLAYWRIGHT_REPORT_PATH}" ]; then
    echo "   Playwright artefaktı: ${FRONTEND_PLAYWRIGHT_REPORT_PATH}"
  fi
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
      echo "### Frontend quality gate"
      echo ""
      echo "| Gate | Command | Result |"
      echo "| --- | --- | --- |"
      echo "| Lint | \`npm run lint\` | $(format_quality_status "${FRONTEND_LINT_EXIT_CODE}" "${FRONTEND_LINT_RAN}" "skipped") |"
      echo "| Coverage | \`npm run test:coverage\` | $(format_quality_status "${FRONTEND_COVERAGE_EXIT_CODE}" "${FRONTEND_COVERAGE_RAN}" "skipped") |"
      echo "| Dependency audit | \`npm run audit:high\` | $(format_quality_status "${FRONTEND_NPM_AUDIT_EXIT_CODE}" "${FRONTEND_NPM_AUDIT_RAN}" "skipped") |"
      echo "| Playwright smoke | \`npm run ${FRONTEND_E2E_NPM_SCRIPT}\` | $(format_quality_status "${FRONTEND_E2E_EXIT_CODE}" "${FRONTEND_E2E_RAN}" "skipped") |"
      echo ""
      echo "- Coverage artifact: \`${FRONTEND_COVERAGE_REPORT_PATH}\`"
      echo "- Playwright artifact: \`${FRONTEND_PLAYWRIGHT_REPORT_PATH}\`"
    } >> "${GITHUB_STEP_SUMMARY}"
  fi
}

if ! [[ "${COVERAGE_FAIL_UNDER}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "⚠️ Geçersiz COVERAGE_FAIL_UNDER değeri: '${COVERAGE_FAIL_UNDER}'. Varsayılan 90 kullanılacak."
  COVERAGE_FAIL_UNDER="90"
fi

install_local_bats_dependencies() {
  echo "📦 BATS ve yerel kalite kapısı sistem bağımlılıkları kuruluyor..."
  if ! bash scripts/install_ci_system_deps.sh; then
    echo "⚠️ BATS sistem bağımlılıkları kurulamadı; shell testleri bu çalıştırmada atlanacak."
    return 1
  fi
  if ! command -v bats >/dev/null 2>&1; then
    echo "⚠️ Sistem bağımlılığı kurulumundan sonra BATS hâlâ PATH üzerinde bulunamadı; shell testleri bu çalıştırmada atlanacak."
    return 1
  fi

  RUN_BATS_TESTS=1
  echo "✅ BATS hazır; yerel shell testleri bu çalıştırmada etkinleştirildi."
}

configure_local_bats_shell_tests() {
  if [ "${TEST_PROFILE}" != "local" ] || [ "${RUN_BATS_TESTS}" != "auto" ]; then
    return 0
  fi
  if command -v bats >/dev/null 2>&1; then
    RUN_BATS_TESTS=1
    echo "✅ BATS PATH üzerinde bulundu; yerel shell testleri otomatik etkinleştirildi."
    return 0
  fi

  echo "⚠️ Yerel profilde BATS bulunamadı; shell testleri varsayılan olarak atlanacak. CI paritesi için: bash scripts/install_ci_system_deps.sh"
  echo "   Etkileşimsiz opt-in otomatik kurulum: AUTO_INSTALL_CI_SYSTEM_DEPS=1 bash run_tests.sh"

  if [ "${AUTO_INSTALL_CI_SYSTEM_DEPS}" = "1" ]; then
    install_local_bats_dependencies || true
    return 0
  fi
  if [ "${SIDAR_PROMPT_LOCAL_BATS_INSTALL:-1}" != "1" ]; then
    return 0
  fi
  if [ ! -t 0 ] || [ ! -t 1 ] || [ ! -r /dev/tty ]; then
    echo "ℹ️ Etkileşimli terminal bulunamadı; BATS kurulum prompt'u gösterilmedi."
    return 0
  fi

  local local_reply=""
  printf "❓ BATS ve gerekli sistem bağımlılıkları şimdi kurulsun mu? [y/N] " > /dev/tty
  IFS= read -r -n 1 local_reply < /dev/tty || true
  printf '\n' > /dev/tty
  case "${local_reply}" in
    y|Y|e|E) install_local_bats_dependencies || true ;;
    *) echo "ℹ️ BATS kurulumu kullanıcı tarafından atlandı." ;;
  esac
}

echo "ℹ️ Coverage quality gate eşiği: ${COVERAGE_FAIL_UNDER} (profile=${COVERAGE_FAIL_UNDER_SOURCE}, .coveragerc baseline=${DEFAULT_COVERAGE_FAIL_UNDER}, ratchet cap=${COVERAGE_RATCHET_MAX_GATE}); açık COVERAGE_FAIL_UNDER verilirse final coverage report --fail-under ile override edilir."
configure_local_bats_shell_tests
echo "ℹ️ Test profili: ${TEST_PROFILE} (CI=${IS_CI_ENV}, AUTO_OPEN_ARTIFACTS=${AUTO_OPEN_ARTIFACTS}, RUN_BENCHMARKS=${RUN_BENCHMARKS}, RUN_STATIC_ANALYSIS=${RUN_STATIC_ANALYSIS}, RUN_BATS_TESTS=${RUN_BATS_TESTS}, RUN_FRONTEND_E2E=${RUN_FRONTEND_E2E})"

# 0) Önceki test artefaktlarını temizle (idempotent başlangıç)
rm -rf .pytest_cache .coverage .coverage.* coverage.xml htmlcov tests/pytest.log web_ui_react/coverage web_ui_react/playwright-report web_ui_react/test-results "${BATS_REPORT_DIR}" sidar.egg-info build/

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

apply_dark_mode_to_frontend_coverage_report() {
  local coverage_dir="$1"
  local dark_css="${coverage_dir}/sidar_dark_mode.css"

  if [ ! -d "${coverage_dir}" ]; then
    return 0
  fi

  cat > "${dark_css}" <<'CSS_DARK'
:root {
  color-scheme: dark;
}

html, body {
  background-color: #0f1117 !important;
  color: #e6edf3 !important;
}

a {
  color: #58a6ff !important;
}

.coverage-summary,
table.coverage-summary td,
table.coverage-summary th,
.wrapper,
.pad1,
.footer {
  background: #0f1117 !important;
  color: #e6edf3 !important;
}

.coverage-summary tbody tr:hover {
  background: #1c2230 !important;
}

.fl,
.cline-any,
.cstat-no,
.cbranch-no,
.cstat-yes,
.cbranch-yes {
  color: #e6edf3 !important;
}
CSS_DARK

  if ! uv run python - "${coverage_dir}" "${dark_css}" <<'PY'
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

coverage_dir = Path(sys.argv[1]).resolve()
dark_css = Path(sys.argv[2]).resolve()
index_files = sorted(coverage_dir.rglob("index.html"))
missing: list[str] = []
link_pattern = re.compile(
    r'(<link\b[^>]*\bhref=["\'][^"\']*base\.css["\'][^>]*>)',
    re.IGNORECASE,
)

for html_path in index_files:
    content = html_path.read_text(encoding="utf-8")
    if "sidar_dark_mode.css" not in content:
        href = os.path.relpath(dark_css, html_path.parent).replace(os.sep, "/")
        dark_link = f'<link rel="stylesheet" href="{href}" />'
        if link_pattern.search(content):
            content = link_pattern.sub(r"\1\n" + dark_link, content, count=1)
        elif "</head>" in content.lower():
            content = re.sub(r"</head>", dark_link + "\n</head>", content, count=1, flags=re.IGNORECASE)
        else:
            content = dark_link + "\n" + content
        html_path.write_text(content, encoding="utf-8")

    if "sidar_dark_mode.css" not in html_path.read_text(encoding="utf-8"):
        missing.append(str(html_path.relative_to(coverage_dir)))

if missing:
    print(
        "Dark mode coverage CSS link could not be injected into: " + ", ".join(missing),
        file=sys.stderr,
    )
    sys.exit(1)
PY
  then
    return 1
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
  mkdir -p "$(dirname "${AUTO_HEAL_RESULT_PATH}")"
  local attempt=0
  local auto_heal_prompt_done=0
  while [ "${attempt}" -le "${AUTO_HEAL_MAX_ATTEMPTS}" ]; do
    local mypy_attempt_log
    if [[ "${AUTO_HEAL_LOG_PATH}" == *.log ]]; then
      mypy_attempt_log="${AUTO_HEAL_LOG_PATH%.log}.attempt-$((attempt + 1)).log"
    else
      mypy_attempt_log="${AUTO_HEAL_LOG_PATH}.attempt-$((attempt + 1))"
    fi
    if uv run mypy 2>&1 | tee "${AUTO_HEAL_LOG_PATH}" "${mypy_attempt_log}"; then
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
    if ! uv run python -m scripts.auto_heal --log "${AUTO_HEAL_LOG_PATH}" --source mypy --batch-retries "${AUTO_HEAL_BATCH_RETRIES}" --output "${AUTO_HEAL_RESULT_PATH}"; then
      echo "❌ Otonom ajan düzeltme planını uygulayamadı. Sonuç artefaktı: ${AUTO_HEAL_RESULT_PATH}"
      BACKEND_EXIT_CODE=1
      return 1
    fi
    echo "✅ Otonom iyileştirme tamamlandı. Sonuç artefaktı: ${AUTO_HEAL_RESULT_PATH}. Mypy yeniden çalıştırılıyor..."
    attempt=$((attempt + 1))
  done
}

resolve_benchmark_compare_target() {
  local requested_name="${1:-baseline}"
  local latest_file=""

  BENCHMARK_COMPARE_SELECTOR=""
  BENCHMARK_COMPARE_FILE=""

  if [ ! -d ".benchmarks" ]; then
    return 1
  fi

  if [ "${requested_name}" = "latest" ]; then
    latest_file="$(find .benchmarks -type f -name "*.json" -print 2>/dev/null | sort -V | tail -n 1)"
  else
    latest_file="$(find .benchmarks -type f -name "*_${requested_name}.json" -print 2>/dev/null | sort -V | tail -n 1)"
  fi

  if [ -z "${latest_file}" ]; then
    return 1
  fi

  # pytest-benchmark alias çözümlemesi bazı nested .benchmarks
  # yerleşimlerinde etiketi (örn. "baseline") dosyaya eşleyemeyebiliyor.
  # Bu nedenle karşılaştırma hedefini deterministik olarak bulduğumuz JSON
  # dosyasının tam path'iyle geçiriyoruz.
  BENCHMARK_COMPARE_FILE="${latest_file}"
  BENCHMARK_COMPARE_SELECTOR="${latest_file}"
  return 0
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

  local pip_audit_timeout="${PIP_AUDIT_TIMEOUT:-30}"
  local pip_audit_max_retries="${PIP_AUDIT_MAX_RETRIES:-2}"
  local pip_audit_attempt=1
  local pip_audit_wait_seconds="${PIP_AUDIT_RETRY_WAIT_SECONDS:-5}"
  local pip_audit_artifact_dir="${PIP_AUDIT_ARTIFACT_DIR:-artifacts/security}"
  local pip_audit_raw_report="${pip_audit_artifact_dir}/pip-audit-report.raw.json"
  local pip_audit_failure_artifact="${pip_audit_artifact_dir}/pip-audit-failure.json"
  local pip_audit_stderr_log="${pip_audit_artifact_dir}/pip-audit-stderr.log"
  mkdir -p "${pip_audit_artifact_dir}"
  : > "${pip_audit_stderr_log}"

  local pip_audit_ignore_args=()
  if ! mapfile -t pip_audit_ignore_args < <(python scripts/pip_audit_ignore_args.py); then
    echo "❌ pip-audit ignore politikası geçersiz veya süresi dolmuş."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  while [ "${pip_audit_attempt}" -le "${pip_audit_max_retries}" ]; do
    rm -f "${pip_audit_raw_report}"
    : > "${pip_audit_stderr_log}"
    if uv run --with pip-audit pip-audit --skip-editable --timeout "${pip_audit_timeout}" \
      --format json --output "${pip_audit_raw_report}" "${pip_audit_ignore_args[@]}" \
      2> "${pip_audit_stderr_log}"; then
      rm -f "${pip_audit_failure_artifact}"
      return 0
    fi
    if [ -s "${pip_audit_stderr_log}" ]; then
      echo "--- pip-audit stderr (deneme ${pip_audit_attempt}/${pip_audit_max_retries}) ---"
      cat "${pip_audit_stderr_log}"
      echo "--- end ---"
    fi
    if [ "${pip_audit_attempt}" -lt "${pip_audit_max_retries}" ]; then
      echo "⚠️ pip-audit başarısız oldu (deneme ${pip_audit_attempt}/${pip_audit_max_retries}). ${pip_audit_wait_seconds}s sonra yeniden denenecek..."
      sleep "${pip_audit_wait_seconds}"
    fi
    pip_audit_attempt=$((pip_audit_attempt + 1))
  done

  echo "❌ pip-audit güvenlik taraması ${pip_audit_max_retries} denemede başarısız."
  if python scripts/pip_audit_failure_artifact.py "${pip_audit_raw_report}" "${pip_audit_failure_artifact}" \
      --timeout "${pip_audit_timeout}" --stderr-log "${pip_audit_stderr_log}"; then
    echo "🧾 pip-audit hata artefaktı yazıldı: ${pip_audit_failure_artifact}"
  else
    echo "⚠️ pip-audit hata artefaktı üretilemedi."
  fi

  # Ağ kaynaklı hatayı gerçek güvenlik bulgusundan ayır. Yerel kalite kapısında
  # ağ kesintilerinde sessiz uyarı, CI'da varsayılan olarak sert hata davranışı
  # uygulanır. Kullanıcı PIP_AUDIT_ALLOW_NETWORK_FAILURE ile davranışı
  # geçersiz kılabilir.
  local pip_audit_failure_category="unknown"
  if [ -f "${pip_audit_failure_artifact}" ]; then
    pip_audit_failure_category="$(
      python -c '
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
try:
    print(json.loads(path.read_text(encoding="utf-8")).get("failure_category", "unknown"))
except Exception:
    print("unknown")
' "${pip_audit_failure_artifact}" 2>/dev/null || echo unknown
    )"
  fi
  local pip_audit_network_default="0"
  if [ -z "${CI:-}" ] && [ -z "${GITHUB_ACTIONS:-}" ]; then
    pip_audit_network_default="1"
  fi
  local pip_audit_allow_network="${PIP_AUDIT_ALLOW_NETWORK_FAILURE:-${pip_audit_network_default}}"

  if [ "${pip_audit_failure_category}" = "network" ] && [ "${pip_audit_allow_network}" = "1" ]; then
    echo "⚠️ pip-audit ağ/tünel hatası nedeniyle tamamlanamadı — bu gerçek bir güvenlik bulgusu DEĞİLDİR."
    echo "    Ayrıntılar: ${pip_audit_stderr_log}"
    echo "    Strict mod için: PIP_AUDIT_ALLOW_NETWORK_FAILURE=0 ./run_tests.sh"
    return 0
  fi

  if [ "${pip_audit_failure_category}" = "network" ]; then
    echo "❌ pip-audit ağ/tünel hatası strict modda fail edildi (PIP_AUDIT_ALLOW_NETWORK_FAILURE=${pip_audit_allow_network})."
  elif [ "${pip_audit_failure_category}" = "vulnerability" ]; then
    echo "❌ pip-audit gerçek güvenlik bulgusu raporladı (failure_category=vulnerability)."
  else
    echo "❌ pip-audit hata sınıflandırması belirsiz (failure_category=${pip_audit_failure_category})."
  fi
  BACKEND_EXIT_CODE=1
  return 1
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
    echo "⚠️ Redis/PostgreSQL docker servisleri başlatılamadı (daemon çalışmıyor olabilir)."
    export SMOKE_SKIP_EXTERNAL_INFRA=1
    echo "ℹ️ SMOKE_SKIP_EXTERNAL_INFRA=1 ayarlandı; harici altyapı smoke testleri atlanacak."
    return 0
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


is_safe_postgres_identifier() {
  local identifier="$1"
  [[ "${identifier}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
}

gpu_hardware_available() {
  command -v nvidia-smi >/dev/null 2>&1 || command -v nvidia-smi.exe >/dev/null 2>&1
}

prepare_test_database() {
  local test_db_name="${TEST_DATABASE_NAME:-sidar_test}"
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
  "${DOCKER_COMPOSE_CMD[@]}" stop redis postgres >/dev/null 2>&1 || \
    echo "⚠️ Redis/PostgreSQL servisleri durdurulurken hata oluştu."
}

trap cleanup_test_services EXIT

ensure_runtime_dependencies() {
  if uv run python - <<'PY' >/dev/null 2>&1
import asyncpg  # noqa: F401
import alembic  # noqa: F401
import coverage  # noqa: F401
import pytest_cov  # noqa: F401
import pytest_asyncio  # noqa: F401
PY
  then
    return 0
  fi

  echo "⚠️ Runtime bağımlılıkları eksik (asyncpg/alembic/coverage/pytest eklentileri)."
  echo "ℹ️ Dev + postgres extras uv ile senkronize ediliyor (uv sync --frozen --all-extras)..."
  if ! uv sync --frozen --all-extras; then
    echo "❌ Runtime bağımlılıklarının otomatik kurulumu başarısız oldu."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if ! uv run python - <<'PY' >/dev/null 2>&1
import asyncpg  # noqa: F401
import alembic  # noqa: F401
import coverage  # noqa: F401
import pytest_cov  # noqa: F401
import pytest_asyncio  # noqa: F401
PY
  then
    echo "❌ Runtime bağımlılık doğrulaması başarısız: asyncpg/alembic/coverage/pytest eklentileri yüklenemedi."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  echo "✅ Runtime bağımlılıkları doğrulandı."
  return 0
}

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

  # -c pyproject.toml ile marker/addopts ayarlarının kök dizinden bağımsız şekilde
  # her çağrıda kesin yüklenmesi garanti edilir. Doğrudan/tekil pytest debug
  # çağrıları yanıltıcı coverage gate hatası üretmesin diye coverage seçenekleri
  # pyproject addopts yerine yalnız bu kalite kapısı içinde açıkça verilir.
  # Faz bazlı pytest-cov raporları .coveragerc fail_under değerini kullanarak
  # erken başarısız olmasın diye burada 0 ile nötrlenir; asıl kalite kapısı
  # tüm fazlar birleştirildikten sonra coverage report --fail-under ile uygulanır.
  local coverage_pytest_opts=(
    --cov=agent
    --cov=core
    --cov=managers
    --cov=plugins
    --cov=web
    --cov-report=term-missing
    --cov-report=html
    --cov-report=xml
  )
  local base_pytest_cmd=(
    env "DOTENV_FILE=${test_dotenv_file}" uv run pytest -c pyproject.toml
    "${coverage_pytest_opts[@]}"
    --cov-fail-under=0
  )

  local enable_gpu_tests="${ENABLE_GPU_TESTS:-auto}"
  if [ "${enable_gpu_tests}" = "auto" ]; then
    if gpu_hardware_available; then
      enable_gpu_tests="1"
      echo "ℹ️ GPU donanımı tespit edildi; ENABLE_GPU_TESTS=auto -> 1."
    else
      enable_gpu_tests="0"
      echo "ℹ️ GPU donanımı tespit edilmedi; ENABLE_GPU_TESTS=auto -> 0 ve GPU testleri atlanacak."
    fi
  fi

  if [ "${enable_gpu_tests}" != "1" ]; then
    echo "ℹ️ GPU testleri atlanıyor (Çalıştırmak için: ENABLE_GPU_TESTS=1 bash run_tests.sh)"
    base_pytest_cmd+=(-m "not gpu")
  else
    if ! gpu_hardware_available; then
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
    # `xdist_group` ile işaretlenen process-global state testlerini aynı worker'da
    # seri çalıştırırken işaretsiz testlerde paralelliği korur.
    base_pytest_cmd+=(-n "${PYTEST_WORKERS}" --dist "${PYTEST_DIST_MODE}")
  fi

  # Coverage raporlarını XML/JSON olarak dışa aktararak otomatik araçların
  # (ör. coverage hotspot analizi ve otonom test üretim döngüsü) makinece
  # okunabilir artefaktlardan beslenmesini garanti ederiz.
  base_pytest_cmd+=(--cov-report=json)

  # Benchmark ölçümlerinin doğruluğu için performans testleri bu aşamada
  # özellikle hariç tutulur ve aşağıda tek çekirdekli ayrı fazda çalıştırılır.
  base_pytest_cmd+=(--ignore=tests/performance)
  if [ "${PERFORMANCE_TEST_DIR}" != "tests/performance" ] && [ -d "${PERFORMANCE_TEST_DIR}" ]; then
    base_pytest_cmd+=(--ignore="${PERFORMANCE_TEST_DIR}")
  fi

  local run_unit_phase=0
  local phase2_dirs=()
  if stage_selected backend || stage_selected unit; then
    run_unit_phase=1
  fi
  if stage_selected backend || stage_selected integration; then
    phase2_dirs+=(tests/integration)
  fi
  if stage_selected backend || stage_selected smoke; then
    phase2_dirs+=(tests/smoke)
  fi
  if stage_selected backend || stage_selected e2e; then
    phase2_dirs+=(tests/e2e)
  fi

  # Aşama 1: Unit testler (yüksek paralellik)
  local phase1_exit=0
  if [ "${run_unit_phase}" -eq 1 ]; then
    local phase1_cmd=("${base_pytest_cmd[@]}" tests/unit)
    echo "➡️ Aşama 1 (Unit) komutu: ${phase1_cmd[*]}"
    "${phase1_cmd[@]}"
    phase1_exit=$?
  else
    echo "ℹ️ Aşama 1 (Unit) atlandı (--stage=${RUN_TESTS_STAGE})."
  fi

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
  local phase2_exit=0
  if [ "${#phase2_dirs[@]}" -gt 0 ]; then
    local phase2_cov_args=()
    if [ "${run_unit_phase}" -eq 1 ]; then
      # Aşama 2 coverage verisini Aşama 1 ile birleştiririz; entegrasyon testleri
      # tek başına fail-under kalite barajına tabi tutulmaz.
      phase2_cov_args+=(--cov-append)
    fi
    phase2_cmd=("${filtered_phase2_cmd[@]}" "${phase2_cov_args[@]}" -n "${phase2_workers}" "${phase2_dirs[@]}")
    echo "➡️ Aşama 2 (Integration/Smoke/E2E) komutu: ${phase2_cmd[*]}"
    "${phase2_cmd[@]}"
    phase2_exit=$?
  else
    echo "ℹ️ Aşama 2 (Integration/Smoke/E2E) atlandı (--stage=${RUN_TESTS_STAGE})."
  fi

  if [ "${phase1_exit}" -ne 0 ] || [ "${phase2_exit}" -ne 0 ]; then
    record_backend_failure "pytest_failed"
    BACKEND_EXIT_CODE=1
  else
    BACKEND_EXIT_CODE=0
  fi

  # xdist altında bazı koşullarda sadece .coverage.* shard'ları kalabilir.
  # Önce bunları birleştirmeyi dener, başarısızsa quality gate'i fail eder.
  if [ ! -f ".coverage" ] && [ "${BACKEND_EXIT_CODE}" -eq 0 ]; then
    if compgen -G ".coverage.*" > /dev/null; then
      echo "ℹ️ .coverage bulunamadı fakat .coverage.* shard dosyaları tespit edildi. coverage combine deneniyor..."
      if uv run python -m coverage combine; then
        echo "✅ coverage combine başarılı; final rapor üretimi bir sonraki adımda yapılacak."
      else
        echo "❌ coverage combine başarısız oldu. Paralel testlerde coverage verisi toparlanamadı."
        record_backend_failure "coverage_combine_failed"
        BACKEND_EXIT_CODE=1
      fi
    else
      echo "⚠️ Uyarı: Testler başarılı görünüyor ancak .coverage dosyası üretilemedi. xdist worker'ları crash olmuş olabilir."
      record_backend_failure "coverage_data_missing"
      BACKEND_EXIT_CODE=1
    fi
  fi

  enforce_combined_coverage_gate

  if [ -f "htmlcov/index.html" ]; then
    echo "✅ Coverage HTML raporu oluşturuldu: htmlcov/index.html"
    open_artifact "htmlcov/index.html"
  else
    echo "⚠️ Coverage raporu oluşturulamadı: htmlcov/index.html bulunamadı."
  fi
}

prepare_docker_test_image() {
  if [ "${AUTO_BUILD_DOCKER_TEST_IMAGE}" != "1" ]; then
    echo "ℹ️ Docker test imajı otomatik build edilmedi (AUTO_BUILD_DOCKER_TEST_IMAGE=${AUTO_BUILD_DOCKER_TEST_IMAGE})."
    return 0
  fi

  local test_image="${DOCKER_TEST_IMAGE:-sidar:latest}"
  local build_context="${DOCKER_TEST_IMAGE_BUILD_CONTEXT}"
  if [[ ! "${test_image}" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/:@-]*$ ]]; then
    echo "❌ Geçersiz DOCKER_TEST_IMAGE değeri: ${test_image}"
    return 1
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "❌ AUTO_BUILD_DOCKER_TEST_IMAGE=1 ancak Docker CLI bulunamadı."
    return 1
  fi
  if docker image inspect "${test_image}" >/dev/null 2>&1; then
    echo "✅ Docker test imajı hazır: ${test_image}"
    return 0
  fi
  if [ ! -f "${build_context}/Dockerfile" ]; then
    echo "❌ Docker test imajı build edilemedi: ${build_context}/Dockerfile bulunamadı."
    return 1
  fi

  echo "🐳 Docker test imajı bulunamadı; build başlatılıyor: docker build -t ${test_image} ${build_context}"
  if docker build -t "${test_image}" "${build_context}"; then
    export DOCKER_TEST_IMAGE="${test_image}"
    echo "✅ Docker test imajı hazırlandı: ${test_image}"
    return 0
  fi

  echo "❌ Docker test imajı build edilemedi: ${test_image}"
  return 1
}


try_auto_install_ci_system_deps() {
  if [ "${AUTO_INSTALL_CI_SYSTEM_DEPS}" != "1" ]; then
    return 1
  fi

  echo "📦 Eksik CI sistem bağımlılıkları otomatik kuruluyor..."
  if bash scripts/install_ci_system_deps.sh; then
    return 0
  fi

  echo "⚠️ CI sistem bağımlılıkları otomatik kurulamadı."
  return 1
}


run_bats_shell_tests() {
  if [ "${RUN_BATS_TESTS}" != "1" ]; then
    echo "ℹ️ BATS shell testleri atlandı (RUN_BATS_TESTS=${RUN_BATS_TESTS})."
    return 0
  fi

  if ! command -v bats >/dev/null 2>&1; then
    try_auto_install_ci_system_deps || true
  fi

  if ! command -v bats >/dev/null 2>&1; then
    echo "❌ RUN_BATS_TESTS=1 ancak BATS bulunamadı. Debian/Ubuntu için: bash scripts/install_ci_system_deps.sh"
    echo "   Parolasız sudo kullanılabiliyorsa opt-in otomatik kurulum: AUTO_INSTALL_CI_SYSTEM_DEPS=1 bash run_tests.sh"
    record_backend_failure "bats_missing"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  echo "🐚 BATS shell testleri çalıştırılıyor..."
  mkdir -p "${BATS_REPORT_DIR}"
  if bats --report-formatter junit --output "${BATS_REPORT_DIR}" tests/shell; then
    echo "✅ BATS shell testleri geçti. JUnit raporu: ${BATS_REPORT_DIR}/report.xml"
    return 0
  fi

  echo "❌ BATS shell testleri başarısız."
  record_backend_failure "bats_failed"
  BACKEND_EXIT_CODE=1
  return 1
}

enforce_combined_coverage_gate() {
  if [ "${BACKEND_EXIT_CODE}" -ne 0 ]; then
    echo "ℹ️ Test fazlarından biri başarısız olduğu için final coverage quality gate atlandı."
    return 0
  fi

  if [ ! -f ".coverage" ]; then
    echo "⚠️ Final coverage quality gate çalıştırılamadı: .coverage bulunamadı."
    record_backend_failure "coverage_data_missing"
    BACKEND_EXIT_CODE=1
    return 0
  fi

  echo "📊 Final birleşik coverage raporları yenileniyor..."
  if ! uv run python -m coverage html -d htmlcov; then
    echo "❌ Coverage HTML raporu üretilemedi."
    record_backend_failure "coverage_html_report_failed"
    BACKEND_EXIT_CODE=1
    return 0
  fi
  if ! uv run python -m coverage xml -o coverage.xml; then
    echo "❌ Coverage XML raporu üretilemedi."
    record_backend_failure "coverage_xml_report_failed"
    BACKEND_EXIT_CODE=1
    return 0
  fi
  if ! uv run python -m coverage json -o coverage.json; then
    echo "❌ Coverage JSON raporu üretilemedi."
    record_backend_failure "coverage_json_report_failed"
    BACKEND_EXIT_CODE=1
    return 0
  fi

  echo "🧪 Final coverage quality gate doğrulanıyor: coverage report --fail-under=${COVERAGE_FAIL_UNDER}"
  if uv run python -m coverage report --fail-under="${COVERAGE_FAIL_UNDER}"; then
    echo "✅ Final coverage quality gate geçti (eşik: ${COVERAGE_FAIL_UNDER})."
  else
    echo "❌ Final coverage quality gate başarısız oldu (eşik: ${COVERAGE_FAIL_UNDER})."
    record_backend_failure "coverage_gate_failed"
    BACKEND_EXIT_CODE=1
  fi
}

update_progressive_coverage_gate() {
  if [ "${COVERAGE_RATCHET_ENABLED:-1}" != "1" ]; then
    echo "ℹ️ Coverage ratcheting devre dışı (COVERAGE_RATCHET_ENABLED=${COVERAGE_RATCHET_ENABLED:-0})."
    return 0
  fi

  if [ "${BACKEND_EXIT_CODE}" -ne 0 ]; then
    echo "ℹ️ Backend kalite akışı başarısız olduğu için coverage ratchet atlandı (nedenler: $(format_backend_failure_reasons))."
    return 0
  fi

  if [ ! -f "coverage.json" ]; then
    echo "⚠️ coverage.json bulunamadı; coverage ratchet uygulanamadı."
    return 0
  fi

  echo "📈 Coverage ratcheting kontrolü çalıştırılıyor (step=${COVERAGE_RATCHET_STEP:-1}, min=${COVERAGE_RATCHET_MIN_GATE:-5}, max=${COVERAGE_RATCHET_MAX_GATE:-100})..."
  if uv run python scripts/coverage_ratchet.py \
    --coveragerc "${COVERAGE_RATCHET_STATE_FILE}" \
    --coverage-json coverage.json \
    --step "${COVERAGE_RATCHET_STEP:-1}" \
    --min-gate "${COVERAGE_RATCHET_MIN_GATE:-5}" \
    --max-gate "${COVERAGE_RATCHET_MAX_GATE:-100}"; then
    DEFAULT_COVERAGE_FAIL_UNDER="$(python - "${COVERAGE_RATCHET_STATE_FILE}" <<'PY_RATCHET_GATE'
from configparser import ConfigParser
from pathlib import Path
import sys

cfg = ConfigParser()
cfg.read(Path(sys.argv[1]))
print(cfg.get("report", "fail_under", fallback="5"))
PY_RATCHET_GATE
)"
    COVERAGE_FAIL_UNDER="${DEFAULT_COVERAGE_FAIL_UNDER}"
  else
    echo "❌ Coverage ratcheting başarısız oldu."
    BACKEND_EXIT_CODE=1
  fi
}

# 1) Backend kalite akışı (3 faz):
#    Faz-1: Ollama model senkronizasyonu (otonom ajan beyni)
#    Faz-2: Statik analiz + otonom iyileştirme
#    Faz-3: Ağır altyapı (Redis/PostgreSQL) + DB hazırlık + pytest coverage
if [ "${SIDAR_RUN_BACKEND_PYTEST}" = "1" ]; then
  if backend_infra_required_for_stage; then
    if ensure_uv_available && prepare_docker_test_image && ensure_runtime_dependencies && sync_ollama_models && run_static_analysis_gates && load_test_database_password_env && ensure_test_services && prepare_test_database; then
      run_pytest_coverage_report
      run_bats_shell_tests
      update_progressive_coverage_gate
    else
      echo "❌ Backend testleri atlandı: önkoşul adımlarından biri başarısız."
      BACKEND_EXIT_CODE=1
    fi
  elif ensure_uv_available && ensure_runtime_dependencies && run_static_analysis_gates; then
    echo "ℹ️ Unit-only stage: Docker/DB/Ollama önkoşulları atlandı."
    run_pytest_coverage_report
    update_progressive_coverage_gate
  else
    echo "❌ Backend testleri atlandı: unit-only önkoşul adımlarından biri başarısız."
    BACKEND_EXIT_CODE=1
  fi
elif stage_selected static; then
  if ensure_uv_available && ensure_runtime_dependencies && run_static_analysis_gates; then
    echo "✅ Static stage tamamlandı."
  else
    echo "❌ Static stage başarısız."
    BACKEND_EXIT_CODE=1
  fi
else
  echo "ℹ️ Backend pytest/static kalite akışı atlandı (--stage=${RUN_TESTS_STAGE})."
fi

# Güvenlik kapıları pytest yürütümünü bloke etmez; sonuç final çıkışta değerlendirilir.
if ! run_security_analysis_gates; then
  echo "⚠️ Güvenlik analizi başarısız oldu; pytest sonuçları üretildi, final çıkış kodu başarısız olarak işaretlenecek."
  BACKEND_EXIT_CODE=1
fi

# 2) Kritik yol performans baseline testleri (pytest-benchmark)
if [ "${RUN_BENCHMARKS}" = "0" ]; then
  echo "⚠️ Benchmark testleri RUN_BENCHMARKS=0 ile atlandı."
  if gpu_hardware_available || [ "${USE_GPU:-0}" = "1" ]; then
    echo "⚠️ GPU/hızlandırıcı algılandı; performans regresyonlarını erken yakalamak için benchmark fazını kapatmayın."
    echo "ℹ️ Öneri (lokal GPU): RUN_BENCHMARKS=required bash run_tests.sh"
  fi
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
    --benchmark-warmup="${BENCHMARK_WARMUP}"
    --benchmark-warmup-iterations="${BENCHMARK_WARMUP_ITERATIONS}"
  )
  if [ "${BENCHMARK_DISABLE_GC}" = "1" ]; then
    benchmark_cmd+=(--benchmark-disable-gc)
  fi

  benchmark_compare_target_found=0
  if [ "${BENCHMARK_ENABLE_COMPARE}" = "1" ]; then
    if resolve_benchmark_compare_target "${BENCHMARK_COMPARE_NAME}"; then
      benchmark_compare_target_found=1
      benchmark_cmd+=(--benchmark-compare="${BENCHMARK_COMPARE_SELECTOR}")
      if [ "${BENCHMARK_ENFORCE_COMPARE}" = "1" ]; then
        echo "📈 Benchmark karşılaştırma kapısı etkin (--benchmark-compare=${BENCHMARK_COMPARE_SELECTOR}; baseline=${BENCHMARK_COMPARE_FILE}; regresyon_eşiği=${BENCHMARK_COMPARE_FAIL})."
        benchmark_cmd+=(--benchmark-compare-fail="${BENCHMARK_COMPARE_FAIL}")
      else
        echo "⚠️ Benchmark karşılaştırması rapor modunda (--benchmark-compare=${BENCHMARK_COMPARE_SELECTOR}; baseline=${BENCHMARK_COMPARE_FILE})."
        echo "ℹ️ Varsayılan sıkı kapıyı geçici rapor moduna almak için BENCHMARK_ENFORCE_COMPARE=0 kullanın."
      fi
    else
      echo "⚠️ Benchmark karşılaştırması atlandı: '.benchmarks' altında '${BENCHMARK_COMPARE_NAME}' etiketiyle eşleşen kayıt bulunamadı."
      echo "ℹ️ İlk benchmark koşusu --benchmark-save=${BENCHMARK_BASELINE_NAME} ile baseline kaydedecek; sonraki koşularda otomatik karşılaştırma yapılacak."
      echo "ℹ️ İlk makine/bootstrap istisnası: BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh"
      echo "ℹ️ Sıkı karşılaştırma: BENCHMARK_COMPARE_REQUIRED=1 BENCHMARK_ENFORCE_COMPARE=1 RUN_BENCHMARKS=required ./run_tests.sh"
      echo "ℹ️ CI, .benchmarks baseline'ını repo commit'i yerine GitHub Actions cache/artifact üzerinden seed/restore eder."
      if [ "${BENCHMARK_COMPARE_REQUIRED}" = "1" ]; then
        if [ "${IS_CI_ENV}" -eq 1 ]; then
          echo "❌ BENCHMARK_COMPARE_REQUIRED=1 iken karşılaştırma için baseline bulunamadı."
          echo "ℹ️ CI bootstrap için cache/artifact baseline restore edin veya seed job'ında BENCHMARK_COMPARE_REQUIRED=0 kullanın."
          BENCHMARK_EXIT_CODE=1
        else
          echo "⚠️ Yerel bootstrap: BENCHMARK_COMPARE_REQUIRED=1 olsa da baseline bulunamadığı için ilk benchmark koşusu karşılaştırmasız çalıştırılacak."
          echo "ℹ️ Bu koşu --benchmark-save=${BENCHMARK_BASELINE_NAME} ile baseline seed eder; sonraki yerel koşular tekrar sıkı karşılaştırmaya döner."
        fi
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
    if [ "${BENCHMARK_ENABLE_COMPARE}" = "1" ] && [ "${benchmark_compare_target_found}" = "0" ]; then
      if resolve_benchmark_compare_target "${BENCHMARK_COMPARE_NAME}"; then
        echo "✅ Benchmark baseline kaydı hazır: ${BENCHMARK_COMPARE_FILE}"
        echo "ℹ️ Sonraki benchmark koşusunda --benchmark-compare=${BENCHMARK_COMPARE_SELECTOR} otomatik kullanılacak."
      else
        echo "⚠️ Benchmark JSON üretildi ancak .benchmarks altında '${BENCHMARK_COMPARE_NAME}' baseline kaydı doğrulanamadı."
      fi
    fi
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

FRONTEND_PLAYWRIGHT_SENTINEL="${FRONTEND_PLAYWRIGHT_SENTINEL:-.playwright-installed}"
FRONTEND_PLAYWRIGHT_PACKAGE_LOCK="${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK:-package-lock.json}"

frontend_playwright_package_lock_fingerprint() {
  [[ -f "${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK}" ]] || return 1
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK}" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK}" | awk '{print $1}'
  else
    cksum "${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK}" | awk '{print $1 ":" $2}'
  fi
}

frontend_playwright_sentinel_cache_ready() {
  local executable_path=""
  local recorded_lock_fingerprint=""
  local current_lock_fingerprint=""
  [[ -f "${FRONTEND_PLAYWRIGHT_SENTINEL}" ]] || return 1
  {
    IFS= read -r executable_path || true
    IFS= read -r recorded_lock_fingerprint || true
  } < "${FRONTEND_PLAYWRIGHT_SENTINEL}"
  current_lock_fingerprint="$(frontend_playwright_package_lock_fingerprint || true)"
  if [[ -n "${executable_path}" \
    && -f "${executable_path}" \
    && -n "${recorded_lock_fingerprint}" \
    && "${recorded_lock_fingerprint}" == "${current_lock_fingerprint}" ]]; then
    return 0
  fi

  rm -f "${FRONTEND_PLAYWRIGHT_SENTINEL}"
  return 1
}

frontend_playwright_chromium_cache_ready() {
  local executable_path=""
  executable_path="$(node - <<'NODE_PLAYWRIGHT_CACHE_CHECK' 2>/dev/null
const fs = require("node:fs");
const { chromium } = require("@playwright/test");
const executablePath = chromium.executablePath();
if (!fs.existsSync(executablePath)) process.exit(1);
process.stdout.write(executablePath);
NODE_PLAYWRIGHT_CACHE_CHECK
)" || return 1
  local lock_fingerprint=""
  [[ -n "${executable_path}" && -f "${executable_path}" ]] || return 1
  lock_fingerprint="$(frontend_playwright_package_lock_fingerprint)" || return 1
  printf '%s\n%s\n' "${executable_path}" "${lock_fingerprint}" > "${FRONTEND_PLAYWRIGHT_SENTINEL}" || true
}

PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER="${PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER:-${SCRIPT_DIR:-$(pwd)}/scripts/install_modules/utils/playwright_ubuntu_override.sh}"
# shellcheck source=scripts/install_modules/utils/playwright_ubuntu_override.sh
source "${PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER}"

install_local_frontend_playwright_chromium_cache() {
  if [ "${RUN_FRONTEND_E2E_AUTO_INSTALL}" != "1" ]; then
    return 1
  fi
  if ! command -v npx >/dev/null 2>&1; then
    echo "⚠️ Node Playwright Chromium cache'i otomatik kurulamadı: npx bulunamadı."
    return 1
  fi

  echo "📦 Node Playwright Chromium cache'i bulunamadı; yerel frontend smoke testleri için otomatik kuruluyor..."
  (
    unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
    local os_release_path="${OS_RELEASE_PATH:-/etc/os-release}"
    local playwright_timeout_ms="${PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT:-120000}"
    if is_playwright_ubuntu_override_recommended "${os_release_path}"; then
      echo "ℹ️ Ubuntu 25+ algılandı; Node Playwright Chromium cache'i ubuntu24.04-x64 OS override ile hazırlanıyor."
      run_playwright_ubuntu_override_install "${os_release_path}" "${playwright_timeout_ms}" \
        npx --no-install playwright install chromium
    else
      npx --no-install playwright install chromium
    fi
  )
}

run_frontend_e2e_with_retry() {
  local e2e_exit_code=0
  local frontend_e2e_script="${FRONTEND_E2E_NPM_SCRIPT:-test:e2e:smoke}"

  echo "🎭 Frontend Playwright smoke testleri çalıştırılıyor (${frontend_e2e_script})..."
  if npm run "${frontend_e2e_script}"; then
    return 0
  else
    e2e_exit_code=$?
  fi

  if [ "${FRONTEND_E2E_RETRY_ON_FAIL}" != "1" ]; then
    return "${e2e_exit_code}"
  fi

  echo "⚠️ Frontend Playwright smoke testleri başarısız oldu (çıkış=${e2e_exit_code}); flake elemek için bir kez yeniden deneniyor..."
  if npm run "${frontend_e2e_script}"; then
    echo "✅ Frontend Playwright smoke testleri ikinci denemede geçti. İlk hata flake olarak raporlandı."
    return 0
  else
    e2e_exit_code=$?
  fi

  echo "❌ Frontend Playwright smoke testleri retry sonrasında da başarısız (çıkış=${e2e_exit_code})."
  echo "ℹ️ Aynı smoke testi ikinci denemede de kaldığı için sonuç flake yerine deterministik kabul edilir."
  echo "   Chat WebSocket smoke için öncelikli kontroller: Vite /ws proxy upgrade, mock backend subprotocol negotiation ve StatusBar data-state."
  return "${e2e_exit_code}"
}

resolve_local_frontend_e2e_mode() {
  if [ "${RUN_FRONTEND_E2E}" != "auto" ]; then
    return 0
  fi

  if frontend_playwright_sentinel_cache_ready; then
    RUN_FRONTEND_E2E=1
    echo "✅ Node Playwright Chromium sentinel cache'i hazır; yerel frontend smoke testleri otomatik etkinleştirildi."
    return 0
  fi

  if frontend_playwright_chromium_cache_ready; then
    RUN_FRONTEND_E2E=1
    echo "✅ Node Playwright Chromium cache'i hazır; sentinel güncellendi ve yerel frontend smoke testleri otomatik etkinleştirildi."
    return 0
  fi

  if install_local_frontend_playwright_chromium_cache && frontend_playwright_chromium_cache_ready; then
    RUN_FRONTEND_E2E=1
    echo "✅ Node Playwright Chromium cache'i otomatik kuruldu; yerel frontend smoke testleri etkinleştirildi."
    return 0
  fi

  RUN_FRONTEND_E2E=0
  echo "⚠️ Frontend Playwright smoke testleri atlandı: Node Playwright Chromium cache'i hazırlanamadı (RUN_FRONTEND_E2E=auto)."
  if [ "${RUN_FRONTEND_E2E_AUTO_INSTALL}" != "1" ]; then
    echo "   Otomatik cache kurulumu RUN_FRONTEND_E2E_AUTO_INSTALL=${RUN_FRONTEND_E2E_AUTO_INSTALL} ile kapalı."
  fi
  echo "   Manuel kurulum için: cd web_ui_react && npx playwright install chromium"
  echo "   Ardından: RUN_FRONTEND_E2E=1 bash run_tests.sh"
}

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
        resolve_local_frontend_e2e_mode
        echo "🔐 Frontend dependency audit kalite kapısı çalıştırılıyor: npm run audit:high"
        FRONTEND_NPM_AUDIT_RAN=1
        npm run audit:high
        FRONTEND_NPM_AUDIT_EXIT_CODE=$?
        if [ "${FRONTEND_NPM_AUDIT_EXIT_CODE}" -ne 0 ]; then
          FRONTEND_EXIT_CODE=${FRONTEND_NPM_AUDIT_EXIT_CODE}
        else
          echo "🧹 Frontend lint kalite kapısı çalıştırılıyor: npm run lint"
          FRONTEND_LINT_RAN=1
          npm run lint
          FRONTEND_LINT_EXIT_CODE=$?
          if [ "${FRONTEND_LINT_EXIT_CODE}" -ne 0 ]; then
            FRONTEND_EXIT_CODE=${FRONTEND_LINT_EXIT_CODE}
          else
            echo "📊 Frontend coverage kalite kapısı çalıştırılıyor: npm run test:coverage"
            FRONTEND_COVERAGE_RAN=1
            npm run test:coverage
            FRONTEND_COVERAGE_EXIT_CODE=$?
            FRONTEND_EXIT_CODE=${FRONTEND_COVERAGE_EXIT_CODE}
            if [ "${FRONTEND_COVERAGE_EXIT_CODE}" -eq 0 ] && [ ! -f "coverage/index.html" ]; then
              echo "❌ Frontend coverage testi geçti ancak HTML artefaktı üretilemedi: web_ui_react/coverage/index.html"
              FRONTEND_COVERAGE_EXIT_CODE=1
              FRONTEND_EXIT_CODE=1
            fi
            if [ "${FRONTEND_EXIT_CODE}" -eq 0 ]; then
              if [ "${RUN_FRONTEND_E2E}" = "1" ]; then
                FRONTEND_E2E_RAN=1
                run_frontend_e2e_with_retry
                FRONTEND_E2E_EXIT_CODE=$?
              else
                echo "ℹ️ Frontend Playwright smoke testleri atlandı (RUN_FRONTEND_E2E=${RUN_FRONTEND_E2E})."
              fi
            fi
          fi
        fi
      fi

      if [ -f "coverage/base.css" ]; then
        echo "Frontend test raporuna kalıcı karanlık tema (dark mode) uygulanıyor..."
        if ! apply_dark_mode_to_frontend_coverage_report "$PWD/coverage"; then
          echo "❌ Frontend coverage dark mode link doğrulaması başarısız oldu."
          FRONTEND_EXIT_CODE=1
        fi
      fi

      # coverage/lcov-report/index.html CI araçları (ör. SonarQube) için korunur,
      # ancak tarayıcıda mükerrer rapor açılmasını önlemek için sadece ana HTML raporu açılır.
      open_artifact "$PWD/coverage/index.html"

      popd > /dev/null || true
    else
      FRONTEND_EXIT_CODE=1
    fi
  fi
elif [ -d "web_ui_react" ]; then
  echo "⚠️ Frontend testleri atlandı: web_ui_react/package.json bulunamadı."
fi

print_frontend_quality_summary

echo "======================================================"

# 4) Final Durum Değerlendirmesi
FINAL_EXIT_CODE=0
if [ "${BACKEND_EXIT_CODE}" -ne 0 ] || [ "${FRONTEND_EXIT_CODE}" -ne 0 ]; then
  FINAL_EXIT_CODE=1
fi
if [ "${BENCHMARK_EXIT_CODE}" -ne 0 ]; then
  if [ "${BENCHMARK_ENFORCE_RESULT}" = "1" ]; then
    FINAL_EXIT_CODE=1
  else
    echo "⚠️ Benchmark fazı başarısız ancak BENCHMARK_ENFORCE_RESULT=0 ile rapor modunda; final çıkış kodu bloke edilmeyecek."
    echo "   Varsayılan sıkı kapıya dönmek için: BENCHMARK_ENFORCE_RESULT=1 bash run_tests.sh"
  fi
fi
if [ "${FRONTEND_E2E_EXIT_CODE}" -ne 0 ]; then
  if [ "${FRONTEND_E2E_ENFORCE_RESULT}" = "1" ]; then
    FINAL_EXIT_CODE=1
  else
    echo "⚠️ Frontend Playwright E2E fazı retry sonrasında başarısız ancak FRONTEND_E2E_ENFORCE_RESULT=0 ile rapor modunda; final çıkış kodu bloke edilmeyecek."
    echo "   Varsayılan sıkı kapıya dönmek için: FRONTEND_E2E_ENFORCE_RESULT=1 bash run_tests.sh"
  fi
fi

if [ "${FINAL_EXIT_CODE}" -ne 0 ]; then
  echo "❌ Bazı testler veya kalite kapıları (coverage) başarısız oldu!"
  echo "   Backend Çıkış Kodu: ${BACKEND_EXIT_CODE}"
  if [ "${BACKEND_EXIT_CODE}" -ne 0 ]; then
    echo "   Backend Hata Nedenleri: $(format_backend_failure_reasons)"
  fi
  echo "   Frontend Unit/Coverage Çıkış Kodu: ${FRONTEND_EXIT_CODE}"
  echo "   Frontend E2E Çıkış Kodu: ${FRONTEND_E2E_EXIT_CODE} (enforce=${FRONTEND_E2E_ENFORCE_RESULT})"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE} (enforce=${BENCHMARK_ENFORCE_RESULT})"
  exit 1
else
  echo "✅ Zorunlu Backend, Frontend ve Benchmark kalite kapıları BAŞARIYLA tamamlandı!"
  echo "   Frontend E2E Çıkış Kodu: ${FRONTEND_E2E_EXIT_CODE} (enforce=${FRONTEND_E2E_ENFORCE_RESULT})"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE} (enforce=${BENCHMARK_ENFORCE_RESULT})"
  exit 0
fi
