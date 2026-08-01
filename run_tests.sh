#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}" || exit 1

# `set -e` bilinçli olarak KULLANILMIYOR: bu script birden çok bağımsız test/
# kalite fazını (unit, integration/smoke/e2e, benchmark, frontend lint/coverage/
# e2e) art arda çalıştırıp sonuçlarını sonda birleştirir; bir fazın başarısız
# olması sonraki fazların da çalışıp raporlanmasını engellememelidir. Bu yüzden
# sonucu final çıkış koduna dahil edilen her komut, çıkış kodunu tutarlı şekilde
# yakalayabilmek için run_checked ile çağrılır.
run_checked() {
  "$@"
  return $?
}

RUN_TESTS_STAGE="${RUN_TESTS_STAGE:-all}"
PRODUCTION_READINESS_MAKE_COMMAND="make production-readiness"
PRODUCTION_READINESS_COMMAND="TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
print_usage() {
  cat <<USAGE
Usage: bash run_tests.sh [--stage all|static|unit|integration|smoke|e2e|backend|frontend|bats[,..]]

Stage examples:
  bash run_tests.sh --stage static
  bash run_tests.sh --stage unit
  bash run_tests.sh --stage integration,smoke

Stage scopes:
  all          Full quality gate: static/security + backend unit/integration/smoke/e2e + frontend + benchmark + BATS (profile-dependent).
  integration  Backend integration main path: tests/integration/{api,cli,db,managers,web,workflow}.
  frontend     Frontend quality gate: npm audit:high, lint, typecheck, coverage and Playwright smoke.
  bats         Installer/shell quality gate: tests/shell via BATS.

Production readiness gate:
  ${PRODUCTION_READINESS_MAKE_COMMAND}
  # Equivalent direct command:
  ${PRODUCTION_READINESS_COMMAND}
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

# Runtime/bootstrap helpers are loaded before their first preflight call.
# shellcheck source=scripts/test_gates/environment_helpers.sh
source "${SCRIPT_DIR}/scripts/test_gates/environment_helpers.sh"



if ! assert_venv_writable; then
  exit 1
fi



ensure_project_venv

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."




check_python_version



# Test ortam değişken dosyasının (.env.test veya DOTENV_FILE ile belirtilen)
# var olduğundan emin olur; yoksa .env.test.example şablonundan otomatik
# olarak oluşturur. Böylece yeni klonlanan bir checkout'ta `bash run_tests.sh`
# elle hazırlık gerektirmeden çalışabilir.

ensure_test_dotenv


cleanup_zone_identifier_artifacts || exit 1

run_precommit_autofix || exit 1

COVERAGE_RATCHET_STATE_FILE="${COVERAGE_RATCHET_STATE_FILE:-pyproject.toml}"
COVERAGE_RATCHET_MIN_EXISTING_GATE="${COVERAGE_RATCHET_MIN_EXISTING_GATE:-5}"


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
#   - local profile  → COVERAGE_FAIL_UNDER_LOCAL    (varsayılan: pyproject.toml)
#   - ci profile     → COVERAGE_FAIL_UNDER_CI       (varsayılan: pyproject.toml)
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

# Ölçülen %100 kapsam artık local/CI merge tabanıdır; tüm profillerin varsayılan
# ratchet tavanı %100'dür. Böylece %100'den sonraki bir %99.x regresyonu günlük
# kapıda da fail-closed yakalanır. Açık COVERAGE_RATCHET_MAX_GATE atandıysa o
# değer geriye dönük uyumluluk için her profilin önüne geçer.
if [ -z "${COVERAGE_RATCHET_MAX_GATE:-}" ]; then
  COVERAGE_RATCHET_MAX_GATE="100"
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
  FRONTEND_BUNDLE_BUDGET="${FRONTEND_BUNDLE_BUDGET:-1}"
else
  AUTO_OPEN_ARTIFACTS="${AUTO_OPEN_ARTIFACTS:-1}"
  PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
  PYTEST_DIST_MODE="${PYTEST_DIST_MODE:-loadgroup}"
  RUN_BENCHMARKS="${RUN_BENCHMARKS:-required}"
  RUN_STATIC_ANALYSIS="${RUN_STATIC_ANALYSIS:-1}"
  RUN_BATS_TESTS="${RUN_BATS_TESTS:-auto}"
  RUN_FRONTEND_E2E="${RUN_FRONTEND_E2E:-auto}"
  if stage_all_selected; then
    # Kanonik local tam doğrulama, Makefile aracılığı olmadan çalıştırıldığında
    # da bundle boyutu regresyonlarını yakalamalıdır.
    FRONTEND_BUNDLE_BUDGET="${FRONTEND_BUNDLE_BUDGET:-${FRONTEND_BUNDLE_BUDGET_LOCAL_FULL:-1}}"
  else
    FRONTEND_BUNDLE_BUDGET="${FRONTEND_BUNDLE_BUDGET:-0}"
  fi
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
    FRONTEND_BUNDLE_BUDGET="${FRONTEND_BUNDLE_BUDGET:-0}"
  fi
fi

# Production-readiness validation must be loaded before its preflight calls.
# shellcheck source=scripts/test_gates/production_readiness_helpers.sh
source "${SCRIPT_DIR}/scripts/test_gates/production_readiness_helpers.sh"

assert_production_readiness_request
check_production_readiness_system_dependencies

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
BENCHMARK_GPU_TEST_FILE="${BENCHMARK_GPU_TEST_FILE:-${PERFORMANCE_TEST_DIR}/test_gpu_benchmark.py}"
BENCHMARK_GPU_JSON_OUTPUT="${BENCHMARK_GPU_JSON_OUTPUT:-artifacts/benchmark/gpu-benchmark.json}"
BENCHMARK_TREND_COMPARE="${BENCHMARK_TREND_COMPARE:-0}"
BENCHMARK_TREND_HISTORY="${BENCHMARK_TREND_HISTORY:-artifacts/benchmark/history.json}"
BENCHMARK_TREND_WINDOW="${BENCHMARK_TREND_WINDOW:-10}"
BENCHMARK_TREND_MAX_REGRESSION_PCT="${BENCHMARK_TREND_MAX_REGRESSION_PCT:-15}"
# Bir benchmark baseline'ı bu eşikten daha eskiyse (gün), karşılaştırma yine de
# rapor modunda uyarı verir; sıkı karşılaştırmada bayat baseline fail-closed olur.
BENCHMARK_BASELINE_MAX_AGE_DAYS="${BENCHMARK_BASELINE_MAX_AGE_DAYS:-14}"
AUTO_HEAL_ON_FAILURE="${AUTO_HEAL_ON_FAILURE:-0}"
AUTO_HEAL_MAX_ATTEMPTS="${AUTO_HEAL_MAX_ATTEMPTS:-2}"
AUTO_HEAL_BATCH_RETRIES="${AUTO_HEAL_BATCH_RETRIES:-0}"
AUTO_HEAL_LOG_PATH="${AUTO_HEAL_LOG_PATH:-artifacts/mypy_errors.log}"
AUTO_BUILD_DOCKER_TEST_IMAGE="${AUTO_BUILD_DOCKER_TEST_IMAGE:-0}"
AUTO_INSTALL_CI_SYSTEM_DEPS="${AUTO_INSTALL_CI_SYSTEM_DEPS:-0}"
DOCKER_TEST_IMAGE_BUILD_CONTEXT="${DOCKER_TEST_IMAGE_BUILD_CONTEXT:-.}"
AUTO_HEAL_RESULT_PATH="${AUTO_HEAL_RESULT_PATH:-artifacts/auto_heal_result.json}"
QUALITY_GATE_EXIT_AFTER_FIRST_FAIL="${QUALITY_GATE_EXIT_AFTER_FIRST_FAIL:-0}"
TEST_SUMMARY_JSON="${TEST_SUMMARY_JSON:-artifacts/test-summary.json}"
TEST_SUMMARY_JUNIT_DIR="${TEST_SUMMARY_JUNIT_DIR:-artifacts/pytest}"

# Stage-specific helper modules keep run_tests.sh focused on orchestration.
# shellcheck source=scripts/test_gates/benchmark_helpers.sh
source "${SCRIPT_DIR}/scripts/test_gates/benchmark_helpers.sh"
# shellcheck source=scripts/test_gates/coverage_helpers.sh
source "${SCRIPT_DIR}/scripts/test_gates/coverage_helpers.sh"
# shellcheck source=scripts/test_gates/frontend_helpers.sh
source "${SCRIPT_DIR}/scripts/test_gates/frontend_helpers.sh"
# shellcheck source=scripts/test_gates/service_helpers.sh
source "${SCRIPT_DIR}/scripts/test_gates/service_helpers.sh"
# shellcheck source=scripts/test_gates/summary_helpers.sh
source "${SCRIPT_DIR}/scripts/test_gates/summary_helpers.sh"
# shellcheck source=scripts/test_gates/backend_helpers.sh
source "${SCRIPT_DIR}/scripts/test_gates/backend_helpers.sh"
# shellcheck source=scripts/test_gates/bats_helpers.sh
source "${SCRIPT_DIR}/scripts/test_gates/bats_helpers.sh"

BACKEND_EXIT_CODE=0
BACKEND_UNIT_RAN=0
BACKEND_UNIT_EXIT_CODE=0
BACKEND_INTEGRATION_RAN=0
BACKEND_INTEGRATION_EXIT_CODE=0
BACKEND_SMOKE_RAN=0
BACKEND_SMOKE_EXIT_CODE=0
BACKEND_E2E_RAN=0
BACKEND_E2E_EXIT_CODE=0
FRONTEND_EXIT_CODE=0
FRONTEND_LINT_EXIT_CODE=0
FRONTEND_COVERAGE_EXIT_CODE=0
FRONTEND_NPM_AUDIT_EXIT_CODE=0
FRONTEND_BUNDLE_BUDGET_EXIT_CODE=0
FRONTEND_E2E_EXIT_CODE=0
FRONTEND_TYPECHECK_EXIT_CODE=0
FRONTEND_LINT_RAN=0
FRONTEND_TYPECHECK_RAN=0
FRONTEND_COVERAGE_RAN=0
FRONTEND_NPM_AUDIT_RAN=0
FRONTEND_BUNDLE_BUDGET_RAN=0
FRONTEND_E2E_RAN=0
BENCHMARK_EXIT_CODE=0
BENCHMARK_COMPARE_STATUS="not_run"
FRONTEND_COVERAGE_REPORT_PATH="web_ui_react/coverage/index.html"
FRONTEND_PLAYWRIGHT_REPORT_PATH="web_ui_react/playwright-report/index.html"
DOCKER_TEST_SERVICES_STARTED=0
DOCKER_COMPOSE_CMD=()
BACKEND_FAILURE_REASONS=()


MIN_UNIT_COVERAGE_FAIL_UNDER="${MIN_UNIT_COVERAGE_FAIL_UNDER:-5}"
if ! [[ "${MIN_UNIT_COVERAGE_FAIL_UNDER}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "⚠️ Geçersiz MIN_UNIT_COVERAGE_FAIL_UNDER değeri: '${MIN_UNIT_COVERAGE_FAIL_UNDER}'. Varsayılan 5 kullanılacak."
  MIN_UNIT_COVERAGE_FAIL_UNDER="5"
fi
if ! [[ "${COVERAGE_FAIL_UNDER}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "⚠️ Geçersiz COVERAGE_FAIL_UNDER değeri: '${COVERAGE_FAIL_UNDER}'. Varsayılan 5 kullanılacak."
  COVERAGE_FAIL_UNDER="5"
fi
COVERAGE_FAIL_UNDER="$(python - "${COVERAGE_FAIL_UNDER}" "${MIN_UNIT_COVERAGE_FAIL_UNDER}" <<'PY_COVERAGE_FLOOR'
import sys

resolved = float(sys.argv[1])
floor = float(sys.argv[2])
print(f"{max(resolved, floor):g}")
PY_COVERAGE_FLOOR
)"



echo "ℹ️ Coverage quality gate eşiği: ${COVERAGE_FAIL_UNDER} (profile=${COVERAGE_FAIL_UNDER_SOURCE}, pyproject.toml baseline=${DEFAULT_COVERAGE_FAIL_UNDER}, minimum unit floor=${MIN_UNIT_COVERAGE_FAIL_UNDER}, ratchet cap=${COVERAGE_RATCHET_MAX_GATE}); açık COVERAGE_FAIL_UNDER verilirse final coverage report --fail-under ile override edilir."
configure_local_bats_shell_tests
echo "ℹ️ Test profili: ${TEST_PROFILE} (CI=${IS_CI_ENV}, AUTO_OPEN_ARTIFACTS=${AUTO_OPEN_ARTIFACTS}, RUN_BENCHMARKS=${RUN_BENCHMARKS}, RUN_STATIC_ANALYSIS=${RUN_STATIC_ANALYSIS}, RUN_BATS_TESTS=${RUN_BATS_TESTS}, RUN_FRONTEND_E2E=${RUN_FRONTEND_E2E})"

# 0) Önceki test artefaktlarını temizle (idempotent başlangıç)
rm -rf .pytest_cache .coverage .coverage.* coverage.xml htmlcov tests/pytest.log web_ui_react/coverage web_ui_react/playwright-report web_ui_react/test-results "${BATS_REPORT_DIR}" sidar.egg-info build/







trap cleanup_test_services EXIT







# Global fail-under kalite kapısı yalnızca unit fazının çalıştığı stage
# kombinasyonlarında (all/backend/unit) anlamlıdır: pyproject.toml'daki
# fail_under eşiği repo genelindeki modül kapsamına göre kalibre edilmiştir.
# Yalnızca --stage integration/smoke/e2e gibi kısmi bir faz çalıştırıldığında
# üretilen kapsam repo genelini temsil etmez; bu durumda gate'i uygulamak
# integration testlerinin kendisi geçmişken sahte bir "coverage" başarısızlığı
# üretir.
# 1) Backend kalite akışı (3 faz):
#    Faz-1: Ollama model senkronizasyonu (otonom ajan beyni)
#    Faz-2: Statik analiz + otonom iyileştirme
#    Faz-3: Ağır altyapı (Redis/PostgreSQL) + DB hazırlık + pytest coverage
if [ "${SIDAR_RUN_BACKEND_PYTEST}" = "1" ]; then
  if backend_infra_required_for_stage; then
    if ensure_uv_available && prepare_docker_test_image && ensure_runtime_dependencies && sync_ollama_models && run_static_analysis_gates && sanitize_test_database_url_overrides && load_test_database_password_env && ensure_test_services && prepare_test_database; then
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
run_benchmark_quality_gate

FRONTEND_PLAYWRIGHT_SENTINEL="${FRONTEND_PLAYWRIGHT_SENTINEL:-.playwright-installed}"
FRONTEND_PLAYWRIGHT_PACKAGE_LOCK="${FRONTEND_PLAYWRIGHT_PACKAGE_LOCK:-package-lock.json}"

PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER="${PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER:-${SCRIPT_DIR:-$(pwd)}/scripts/install_modules/utils/playwright_ubuntu_override.sh}"
# shellcheck source=scripts/install_modules/utils/playwright_ubuntu_override.sh
source "${PLAYWRIGHT_UBUNTU_OVERRIDE_HELPER}"

# 3) Frontend React testleri ve coverage (web_ui_react varsa zorunlu quality gate)
if [ -d "web_ui_react" ] && [ -f "web_ui_react/package.json" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "❌ web_ui_react dizini var ama npm bulunamadı — React testleri çalıştırılamıyor."
    FRONTEND_EXIT_CODE=1
  else
    echo "🚀 Frontend (React) Testleri Başlıyor..."
    if pushd web_ui_react > /dev/null; then
      if [ -f "package-lock.json" ]; then
        echo "ℹ️ package-lock.json bulundu; local/CI paritesi için 'npm ci' çalıştırılıyor..."
        run_checked npm ci
      else
        echo "⚠️ package-lock.json bulunamadı; doğrulama için 'npm install' fallback olarak çalıştırılıyor."
        run_checked npm install
      fi
      local_npm_ci_exit=$?
      if [ "${local_npm_ci_exit}" -ne 0 ]; then
        FRONTEND_EXIT_CODE=${local_npm_ci_exit}
      else
        resolve_local_frontend_e2e_mode
        FRONTEND_E2E_MODE_EXIT_CODE=$?
        if [ "${FRONTEND_E2E_MODE_EXIT_CODE}" -ne 0 ]; then
          FRONTEND_EXIT_CODE=${FRONTEND_E2E_MODE_EXIT_CODE}
        fi
        echo "🔐 Frontend dependency audit kalite kapısı çalıştırılıyor: npm run audit:high"
        FRONTEND_NPM_AUDIT_RAN=1
        run_checked npm run audit:high
        FRONTEND_NPM_AUDIT_EXIT_CODE=$?
        if [ "${FRONTEND_NPM_AUDIT_EXIT_CODE}" -ne 0 ]; then
          FRONTEND_EXIT_CODE=${FRONTEND_NPM_AUDIT_EXIT_CODE}
        fi

        # Build, lint, typecheck, coverage ve browser E2E birbirinin yerine
        # geçmeyen kalite sinyalleridir. Bir kapının hatası sonraki sinyalleri
        # "skipped" durumuna düşürmemeli; tüm sonuçlar finalde birlikte toplanır.
        echo "🧹 Frontend lint kalite kapısı çalıştırılıyor: npm run lint"
        FRONTEND_LINT_RAN=1
        run_checked npm run lint
        FRONTEND_LINT_EXIT_CODE=$?
        if [ "${FRONTEND_LINT_EXIT_CODE}" -ne 0 ]; then
          FRONTEND_EXIT_CODE=${FRONTEND_LINT_EXIT_CODE}
        fi

        # NOT: web_ui_react/tsconfig.json içinde checkJs=false; ağaç neredeyse
        # tamamen .jsx/.js olduğundan bu kapı yalnızca tek .ts dosyasını ve TS
        # tarafı modül çözümlemesini denetler, .jsx/.js bileşen/hook mantığı
        # için gerçek bir tip güvencesi vermez (bkz. tsconfig.json).
        echo "🧪 Frontend typecheck kalite kapısı çalıştırılıyor: npm run typecheck (yalnız .ts + modül çözümleme; .jsx/.js tip denetlenmiyor)"
        FRONTEND_TYPECHECK_RAN=1
        run_checked npm run typecheck
        FRONTEND_TYPECHECK_EXIT_CODE=$?
        if [ "${FRONTEND_TYPECHECK_EXIT_CODE}" -ne 0 ]; then
          FRONTEND_EXIT_CODE=${FRONTEND_TYPECHECK_EXIT_CODE}
        fi

        echo "📊 Frontend coverage kalite kapısı çalıştırılıyor: npm run test:coverage"
        FRONTEND_COVERAGE_RAN=1
        run_checked npm run test:coverage
        FRONTEND_COVERAGE_EXIT_CODE=$?
        if [ "${FRONTEND_COVERAGE_EXIT_CODE}" -ne 0 ]; then
          FRONTEND_EXIT_CODE=${FRONTEND_COVERAGE_EXIT_CODE}
        elif [ ! -f "coverage/index.html" ]; then
          echo "❌ Frontend coverage testi geçti ancak HTML artefaktı üretilemedi: web_ui_react/coverage/index.html"
          FRONTEND_COVERAGE_EXIT_CODE=1
          FRONTEND_EXIT_CODE=1
        fi

        if [ "${FRONTEND_BUNDLE_BUDGET}" = "1" ]; then
          echo "📦 Frontend build/bundle budget kalite kapısı çalıştırılıyor: npm run build:budget"
          FRONTEND_BUNDLE_BUDGET_RAN=1
          run_checked npm run build:budget
          FRONTEND_BUNDLE_BUDGET_EXIT_CODE=$?
          if [ "${FRONTEND_BUNDLE_BUDGET_EXIT_CODE}" -ne 0 ]; then
            FRONTEND_EXIT_CODE=${FRONTEND_BUNDLE_BUDGET_EXIT_CODE}
          fi
        else
          echo "ℹ️ Frontend build/bundle budget atlandı (FRONTEND_BUNDLE_BUDGET=${FRONTEND_BUNDLE_BUDGET}). Etkinleştirmek için FRONTEND_BUNDLE_BUDGET=1 bash run_tests.sh --stage frontend"
        fi

        if [ "${RUN_FRONTEND_E2E}" = "1" ] && [ "${FRONTEND_E2E_MODE_EXIT_CODE}" -eq 0 ]; then
          FRONTEND_E2E_RAN=1
          run_checked run_frontend_e2e_with_retry
          FRONTEND_E2E_EXIT_CODE=$?
        elif [ "${RUN_FRONTEND_E2E}" != "1" ]; then
          echo "ℹ️ Frontend Playwright smoke testleri atlandı (RUN_FRONTEND_E2E=${RUN_FRONTEND_E2E})."
        else
          echo "❌ Frontend Playwright ortam hazırlığı başarısız; lint/typecheck/coverage/build sinyalleri yine de çalıştırıldı."
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

PRODUCTION_READY=false
if production_readiness_gate_active && [ "${FINAL_EXIT_CODE}" -eq 0 ]; then
  PRODUCTION_READY=true
fi
write_test_summary_json "${PRODUCTION_READY}"

RELEASE_SCOPE_WARNING_PRINTED=0

print_release_scope_warning_once

if [ "${FINAL_EXIT_CODE}" -ne 0 ]; then
  echo "❌ Bazı testler veya kalite kapıları (coverage) başarısız oldu!"
  echo "   Backend Çıkış Kodu: ${BACKEND_EXIT_CODE}"
  if [ "${BACKEND_EXIT_CODE}" -ne 0 ]; then
    echo "   Backend Hata Nedenleri: $(format_backend_failure_reasons)"
    print_failed_backend_nodeids
  fi
  echo "   Frontend Unit/Coverage Çıkış Kodu: ${FRONTEND_EXIT_CODE}"
  echo "   Frontend Bundle Budget Çıkış Kodu: ${FRONTEND_BUNDLE_BUDGET_EXIT_CODE} (ran=${FRONTEND_BUNDLE_BUDGET_RAN})"
  echo "   Frontend E2E Çıkış Kodu: ${FRONTEND_E2E_EXIT_CODE} (enforce=${FRONTEND_E2E_ENFORCE_RESULT})"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE} (enforce=${BENCHMARK_ENFORCE_RESULT})"
  exit 1
else
  if production_readiness_gate_active; then
    echo "✅ Zorunlu Backend, Frontend E2E ve Benchmark kalite kapıları BAŞARIYLA tamamlandı!"
  elif stage_all_selected; then
    print_release_scope_warning_once
  else
    echo "✅ Seçili kalite kapıları BAŞARIYLA tamamlandı."
    print_release_scope_warning_once
  fi
  echo "   Frontend E2E Çıkış Kodu: ${FRONTEND_E2E_EXIT_CODE} (enforce=${FRONTEND_E2E_ENFORCE_RESULT})"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE} (enforce=${BENCHMARK_ENFORCE_RESULT})"
  exit 0
fi
