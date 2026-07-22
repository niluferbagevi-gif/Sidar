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

report_git_diff_state() {
  local label="$1"

  if ! command -v git >/dev/null 2>&1 || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ℹ️ ${label}: git çalışma ağacı durumu raporlanamadı (git repo değil)."
    return 0
  fi

  if git diff --exit-code --quiet; then
    echo "✅ ${label}: git diff --exit-code temiz."
  else
    echo "⚠️ ${label}: git diff --exit-code değişiklik görüyor."
    git diff --stat || true
  fi
}

run_precommit_autofix() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "⚠️ 'uv' bulunamadı; Ruff kalite kapısı atlanıyor."
    return 0
  fi

  if [ "${RUFF_AUTOFIX:-0}" != "1" ]; then
    echo "🔍 Ruff kalite kapısı: uv run ruff check ."
    if ! uv run ruff check .; then
      echo "❌ Ruff lint kontrolü başarısız. Düzeltmek için: RUFF_AUTOFIX=1 bash run_tests.sh --stage all"
      return 1
    fi
    echo "🔍 Ruff format kapısı: uv run ruff format --check ."
    if ! uv run ruff format --check .; then
      echo "❌ Ruff format kontrolü başarısız. Düzeltmek için: RUFF_AUTOFIX=1 bash run_tests.sh --stage all"
      return 1
    fi
    return 0
  fi

  report_git_diff_state "RUFF_AUTOFIX başlangıç durumu"

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

  echo "🧹 Ruff autofix opt-in: ${ruff_autofix_cmd[*]}"
  if ! "${ruff_autofix_cmd[@]}"; then
    echo "❌ Ruff autofix sonrası lint kontrolleri başarısız. Testler durduruldu."
    report_git_diff_state "RUFF_AUTOFIX bitiş durumu"
    return 1
  fi
  echo "🧹 Ruff format opt-in: uv run ruff format ."
  if ! uv run ruff format .; then
    echo "❌ Ruff format autofix başarısız. Testler durduruldu."
    report_git_diff_state "RUFF_AUTOFIX bitiş durumu"
    return 1
  fi

  report_git_diff_state "RUFF_AUTOFIX bitiş durumu"
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
  if install -m 600 "${template}" "${target}"; then
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

COVERAGE_RATCHET_STATE_FILE="${COVERAGE_RATCHET_STATE_FILE:-pyproject.toml}"
COVERAGE_RATCHET_MIN_EXISTING_GATE="${COVERAGE_RATCHET_MIN_EXISTING_GATE:-5}"

validate_coverage_ratchet_state() {
  if [ ! -f "${COVERAGE_RATCHET_STATE_FILE}" ]; then
    echo "❌ Coverage ratchet state dosyası bulunamadı: ${COVERAGE_RATCHET_STATE_FILE}" >&2
    echo "   Bu dosya repo'ya commit edilmeli ve .gitignore kapsamına alınmamalıdır." >&2
    echo "   Baseline kaybı, coverage gate'in %0'dan yeniden başlamasına neden olabilir." >&2
    return 1
  fi

  python - "${COVERAGE_RATCHET_STATE_FILE}" "${COVERAGE_RATCHET_MIN_EXISTING_GATE}" <<'PY_RATCHET_STATE'
from pathlib import Path
import sys
import tomllib

state_path = Path(sys.argv[1])
min_gate = float(sys.argv[2])
data = tomllib.loads(state_path.read_text(encoding="utf-8"))
try:
    raw_gate = data["tool"]["coverage"]["report"]["fail_under"]
except KeyError as exc:
    raise SystemExit(f"{state_path} içinde [tool.coverage.report] fail_under bulunamadı") from exc
try:
    gate = float(raw_gate)
except (TypeError, ValueError) as exc:
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

is_truthy_env() {
  local value="${1:-}"
  value="${value,,}"
  value="${value//[[:space:]]/}"
  case "${value}" in
    1|true|yes|y|evet|e) return 0 ;;
    *) return 1 ;;
  esac
}

production_readiness_gate_active() {
  stage_all_selected \
    && [ "${TEST_PROFILE}" = "ci" ] \
    && [ "${RUN_BENCHMARKS}" = "required" ] \
    && [ "${RUN_FRONTEND_E2E}" = "1" ] \
    && [ "${BENCHMARK_ENFORCE_RESULT}" = "1" ] \
    && [ "${FRONTEND_E2E_ENFORCE_RESULT}" = "1" ]
}

assert_production_readiness_request() {
  if ! is_truthy_env "${SIDAR_PRODUCTION_READINESS:-${PRODUCTION_READINESS:-}}"; then
    return 0
  fi

  if production_readiness_gate_active; then
    echo "✅ Production readiness gate aktif: ${PRODUCTION_READINESS_COMMAND}"
    return 0
  fi

  echo "❌ SIDAR_PRODUCTION_READINESS=1 verildi ancak run_tests.sh tam production gate koşullarında çalışmıyor." >&2
  echo "   Zorunlu komut: ${PRODUCTION_READINESS_COMMAND}" >&2
  echo "   Mevcut: TEST_PROFILE=${TEST_PROFILE}, RUN_BENCHMARKS=${RUN_BENCHMARKS}, RUN_FRONTEND_E2E=${RUN_FRONTEND_E2E}, stage=${RUN_TESTS_STAGE}" >&2
  exit 2
}

check_production_readiness_system_dependencies() {
  if ! production_readiness_gate_active; then
    return 0
  fi

  echo "🧰 Production-readiness sistem bağımlılığı ön kontrolü çalıştırılıyor..."
  if bash scripts/install_ci_system_deps.sh --check; then
    echo "✅ Production-readiness sistem bağımlılıkları hazır (portaudio/shellcheck/bats)."
    return 0
  fi

  echo "❌ Production-readiness sistem bağımlılıkları eksik." >&2
  echo "   Önce şunu çalıştırın: bash scripts/install_ci_system_deps.sh" >&2
  echo "   Ardından tekrar deneyin: make production-readiness" >&2
  echo "   Bu erken ön kontrol, pyaudio derleme hatasının bandit/pytest gibi ikincil eksik araç hatalarına zincirlenmesini engeller." >&2
  exit 2
}

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

record_backend_failure() {
  local reason="$1"
  local joined_reasons
  [[ -n "$reason" ]] || return 0
  local IFS=,
  joined_reasons="${BACKEND_FAILURE_REASONS[*]}"
  case ",${joined_reasons}," in
    *,"$reason",*) return 0 ;;
    *) BACKEND_FAILURE_REASONS+=("$reason") ;;
  esac
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

print_failed_backend_nodeids() {
  if [ ! -f "${TEST_SUMMARY_JSON}" ]; then
    return 0
  fi

  if ! command -v python >/dev/null 2>&1; then
    return 0
  fi

  python - "${TEST_SUMMARY_JSON}" <<'PY_FAILED_NODEIDS'
from __future__ import annotations

import json
import sys
from pathlib import Path

summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
failed_tests = summary.get("backend_failed_tests", [])

if failed_tests:
    print("❌ Başarısız backend testleri:")
    for nodeid in failed_tests:
        print(f"   - {nodeid}")
PY_FAILED_NODEIDS
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

quality_summary_status() {
  local ran="$1"
  local exit_code="$2"
  if [ "${ran}" != "1" ]; then
    printf 'skipped'
  elif [ "${exit_code}" = "0" ]; then
    printf 'passed'
  else
    printf 'failed'
  fi
}

backend_stage_summary_status() {
  local stage="$1"
  local ran=0
  local exit_code=0

  case "${stage}" in
    unit)
      ran="${BACKEND_UNIT_RAN}"
      exit_code="${BACKEND_UNIT_EXIT_CODE}"
      ;;
    integration)
      ran="${BACKEND_INTEGRATION_RAN}"
      exit_code="${BACKEND_INTEGRATION_EXIT_CODE}"
      ;;
    smoke)
      ran="${BACKEND_SMOKE_RAN}"
      exit_code="${BACKEND_SMOKE_EXIT_CODE}"
      ;;
    e2e)
      ran="${BACKEND_E2E_RAN}"
      exit_code="${BACKEND_E2E_EXIT_CODE}"
      ;;
    *)
      printf 'skipped'
      return 0
      ;;
  esac

  quality_summary_status "${ran}" "${exit_code}"
}

write_test_summary_json() {
  local production_ready="$1"
  local benchmark_ran=1
  local smoke_status=""
  local integration_status=""
  local e2e_status=""
  local frontend_lint_status=""
  local frontend_typecheck_status=""
  local frontend_coverage_status=""
  local frontend_bundle_budget_status=""
  local frontend_e2e_status=""
  local benchmark_status=""
  local benchmark_compare_status="${BENCHMARK_COMPARE_STATUS:-not_run}"
  local benchmark_baseline_name="${BENCHMARK_COMPARE_NAME:-${BENCHMARK_BASELINE_NAME:-baseline}}"
  local benchmark_baseline_file="${BENCHMARK_COMPARE_FILE:-}"
  local benchmark_compare_selector="${BENCHMARK_COMPARE_SELECTOR:-}"
  local benchmark_compare_required="${BENCHMARK_COMPARE_REQUIRED:-0}"
  local benchmark_enforce_compare="${BENCHMARK_ENFORCE_COMPARE:-0}"
  local benchmark_enable_compare="${BENCHMARK_ENABLE_COMPARE:-1}"
  local benchmark_compare_fail="${BENCHMARK_COMPARE_FAIL:-}"
  local benchmark_json_output="${BENCHMARK_JSON_OUTPUT:-artifacts/benchmark/benchmark.json}"
  local frontend_e2e_scope="skipped"
  local frontend_e2e_script="${FRONTEND_E2E_NPM_SCRIPT:-test:e2e:smoke}"
  local production_readiness_status="not_requested"
  local production_readiness_summary="not_run"
  local production_readiness_reason="production readiness gate was not requested"
  local validation_class="partial"
  local release_blocking="true"
  local release_gate_exit_code="20"
  local installer_mode="${SIDAR_INSTALLER_MODE:-development_local}"
  local junit_dir="${TEST_SUMMARY_JUNIT_DIR:-artifacts/pytest}"
  local backend_failed_tests_enabled="false"

  smoke_status="$(backend_stage_summary_status smoke)"
  integration_status="$(backend_stage_summary_status integration)"
  e2e_status="$(backend_stage_summary_status e2e)"
  frontend_lint_status="$(quality_summary_status "${FRONTEND_LINT_RAN}" "${FRONTEND_LINT_EXIT_CODE}")"
  frontend_typecheck_status="$(quality_summary_status "${FRONTEND_TYPECHECK_RAN}" "${FRONTEND_TYPECHECK_EXIT_CODE}")"
  frontend_coverage_status="$(quality_summary_status "${FRONTEND_COVERAGE_RAN}" "${FRONTEND_COVERAGE_EXIT_CODE}")"
  frontend_bundle_budget_status="$(quality_summary_status "${FRONTEND_BUNDLE_BUDGET_RAN:-0}" "${FRONTEND_BUNDLE_BUDGET_EXIT_CODE:-0}")"
  frontend_e2e_status="$(quality_summary_status "${FRONTEND_E2E_RAN}" "${FRONTEND_E2E_EXIT_CODE}")"
  if [ "${FRONTEND_E2E_RAN}" = "1" ]; then
    if [ "${frontend_e2e_script}" = "test:e2e:smoke" ]; then
      frontend_e2e_scope="smoke"
    else
      frontend_e2e_scope="full"
    fi
  fi

  if [ "${production_ready}" = "true" ]; then
    production_readiness_status="passed"
    production_readiness_summary="passed"
    production_readiness_reason="production readiness gate passed"
    validation_class="production_readiness"
    release_blocking="false"
    release_gate_exit_code="0"
    installer_mode="production_readiness"
  elif production_readiness_gate_active; then
    production_readiness_status="failed"
    production_readiness_summary="failed"
    production_readiness_reason="production readiness gate was active but at least one required quality gate failed"
    validation_class="production_readiness_failed"
    release_blocking="true"
    release_gate_exit_code="1"
    installer_mode="production_readiness"
  elif stage_all_selected; then
    production_readiness_status="development_only"
    production_readiness_summary="not_run"
    production_readiness_reason="stage all completed outside the required CI production readiness profile"
    validation_class="development_full"
    release_blocking="true"
    release_gate_exit_code="10"
  else
    production_readiness_status="partial_stage"
    production_readiness_summary="not_run"
    production_readiness_reason="selected stage set does not cover the full production readiness gate"
  fi

  if [ "${installer_mode}" = "development_local" ] && [ "${TEST_PROFILE:-local}" = "ci" ]; then
    installer_mode="ci"
  fi

  if [ "${BACKEND_UNIT_RAN}" = "1" ] \
    || [ "${BACKEND_INTEGRATION_RAN}" = "1" ] \
    || [ "${BACKEND_SMOKE_RAN}" = "1" ] \
    || [ "${BACKEND_E2E_RAN}" = "1" ]; then
    backend_failed_tests_enabled="true"
  fi

  if [ "${RUN_BENCHMARKS}" = "0" ]; then
    benchmark_ran=0
  fi
  benchmark_status="$(quality_summary_status "${benchmark_ran}" "${BENCHMARK_EXIT_CODE}")"

  mkdir -p "$(dirname "${TEST_SUMMARY_JSON}")"
  if command -v python >/dev/null 2>&1; then
    if python scripts/test_gates/summary.py "${TEST_SUMMARY_JSON}" \
      "${smoke_status}" \
      "${integration_status}" \
      "${e2e_status}" \
      "${frontend_lint_status}" \
      "${frontend_typecheck_status}" \
      "${frontend_coverage_status}" \
      "${frontend_bundle_budget_status}" \
      "${frontend_e2e_status}" \
      "${benchmark_status}" \
      "${production_ready}" \
      "${junit_dir}" \
      "${backend_failed_tests_enabled}" \
      "${SIDAR_INSTALLER_BOOTSTRAP_MODE:-unknown}" \
      "${SIDAR_INSTALL_MODULES_DOWNLOADED_COUNT:-0}" \
      "${SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS:-0}" \
      "${SIDAR_INSTALL_MODULE_HTTP_429_RETRIES:-0}" \
      "${SIDAR_INSTALL_MODULE_CACHE_HITS:-0}" \
      "${SIDAR_INSTALL_MODULE_BASE_URL:-}" \
      "${production_readiness_summary}" \
      "${production_readiness_status}" \
      "${production_readiness_reason}" \
      "${validation_class}" \
      "${release_blocking}" \
      "${release_gate_exit_code}" \
      "${installer_mode}" \
      "${benchmark_compare_status}" \
      "${benchmark_baseline_name}" \
      "${benchmark_baseline_file}" \
      "${benchmark_compare_selector}" \
      "${benchmark_compare_required}" \
      "${benchmark_enforce_compare}" \
      "${benchmark_enable_compare}" \
      "${benchmark_compare_fail}" \
      "${benchmark_json_output}" \
      "${frontend_e2e_scope}" \
      "${frontend_e2e_script}"
    then
      echo "🧾 Makinece okunabilir test özeti yazıldı: ${TEST_SUMMARY_JSON}"
    else
      echo "⚠️ Makinece okunabilir test özeti yazılamadı: ${TEST_SUMMARY_JSON}"
    fi
  else
    echo "⚠️ python bulunamadı; makinece okunabilir test özeti yazılamadı: ${TEST_SUMMARY_JSON}"
  fi
}

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

echo "ℹ️ Coverage quality gate eşiği: ${COVERAGE_FAIL_UNDER} (profile=${COVERAGE_FAIL_UNDER_SOURCE}, pyproject.toml baseline=${DEFAULT_COVERAGE_FAIL_UNDER}, minimum unit floor=${MIN_UNIT_COVERAGE_FAIL_UNDER}, ratchet cap=${COVERAGE_RATCHET_MAX_GATE}); açık COVERAGE_FAIL_UNDER verilirse final coverage report --fail-under ile override edilir."
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
    record_backend_failure "static_failed"
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
    if uv run mypy --strict core/ agent/ web/ managers/ launcher/ 2>&1 | tee "${AUTO_HEAL_LOG_PATH}" "${mypy_attempt_log}"; then
      return 0
    fi
    if [ "${AUTO_HEAL_ON_FAILURE}" != "1" ] || [ "${attempt}" -ge "${AUTO_HEAL_MAX_ATTEMPTS}" ]; then
      record_backend_failure "static_failed"
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
          record_backend_failure "static_failed"
          BACKEND_EXIT_CODE=1
          return 1
          ;;
      esac
      auto_heal_prompt_done=1
    fi
    echo "⚠️ Mypy hataları tespit edildi. Otonom iyileştirme döngüsü başlatılıyor... (deneme $((attempt + 1))/${AUTO_HEAL_MAX_ATTEMPTS})"
    if ! uv run python -m scripts.auto_heal --log "${AUTO_HEAL_LOG_PATH}" --source mypy --batch-retries "${AUTO_HEAL_BATCH_RETRIES}" --output "${AUTO_HEAL_RESULT_PATH}"; then
      echo "❌ Otonom ajan düzeltme planını uygulayamadı. Sonuç artefaktı: ${AUTO_HEAL_RESULT_PATH}"
      record_backend_failure "static_failed"
      BACKEND_EXIT_CODE=1
      return 1
    fi
    echo "✅ Otonom iyileştirme tamamlandı. Sonuç artefaktı: ${AUTO_HEAL_RESULT_PATH}. Mypy yeniden çalıştırılıyor..."
    attempt=$((attempt + 1))
  done
}

ensure_benchmark_tool_dependencies() {
  if uv run python - <<'PY' >/dev/null 2>&1
import pytest  # noqa: F401
import pytest_benchmark  # noqa: F401
PY
  then
    return 0
  fi

  echo "⚠️ Benchmark kalite araçları eksik (pytest/pytest-benchmark)."
  echo "ℹ️ Benchmark/dev araçları için full extras öncesi CI sistem bağımlılıkları hazırlanıyor..."
  if ! bash scripts/install_ci_system_deps.sh; then
    echo "❌ CI sistem bağımlılıkları hazırlanamadı; pytest/pytest-benchmark kurulumu full uv sync pyaudio/portaudio.h aşamasında kesildiği için eksik kalabilir."
    echo "   Manuel hazırlık: bash scripts/install_ci_system_deps.sh && uv sync --frozen --all-extras"
    echo "   İlk yerel baseline için ardından: make benchmark-seed && make production-readiness"
    BENCHMARK_EXIT_CODE=1
    return 1
  fi

  echo "ℹ️ Benchmark kalite araçları uv ile senkronize ediliyor (uv sync --frozen --all-extras)..."
  if ! uv sync --frozen --all-extras; then
    echo "❌ Benchmark kalite araçları kurulamadı; python -m pytest benchmark fazı çalıştırılamaz."
    BENCHMARK_EXIT_CODE=1
    return 1
  fi

  if ! uv run python - <<'PY' >/dev/null 2>&1
import pytest  # noqa: F401
import pytest_benchmark  # noqa: F401
PY
  then
    echo "❌ Pytest/pytest-benchmark doğrulaması başarısız; dev extra ortamda kullanılabilir değil."
    BENCHMARK_EXIT_CODE=1
    return 1
  fi
}

ensure_security_tool_dependencies() {
  if uv run python - <<'PY' >/dev/null 2>&1
import bandit  # noqa: F401
PY
  then
    return 0
  fi

  echo "⚠️ Güvenlik kalite araçları eksik (bandit)."
  echo "ℹ️ Bandit/dev araçları için full extras öncesi CI sistem bağımlılıkları hazırlanıyor..."
  if ! bash scripts/install_ci_system_deps.sh; then
    echo "❌ CI sistem bağımlılıkları hazırlanamadı; bandit kurulumu full uv sync pyaudio/portaudio.h aşamasında kesildiği için eksik kalabilir."
    echo "   Manuel hazırlık: bash scripts/install_ci_system_deps.sh && uv sync --frozen --all-extras"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  echo "ℹ️ Güvenlik kalite araçları uv ile senkronize ediliyor (uv sync --frozen --all-extras)..."
  if ! uv sync --frozen --all-extras; then
    echo "❌ Güvenlik kalite araçları kurulamadı; bandit çalıştırılamaz."
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if ! uv run python - <<'PY' >/dev/null 2>&1
import bandit  # noqa: F401
PY
  then
    echo "❌ Bandit doğrulaması başarısız; dev extra ortamda kullanılabilir değil."
    BACKEND_EXIT_CODE=1
    return 1
  fi
}

run_security_analysis_gates() {
  if [ "${RUN_SECURITY_ANALYSIS:-1}" != "1" ]; then
    echo "ℹ️ Güvenlik analizi adımı atlandı (RUN_SECURITY_ANALYSIS=${RUN_SECURITY_ANALYSIS:-1})."
    return 0
  fi

  if ! ensure_uv_available || ! ensure_security_tool_dependencies; then
    echo "❌ Güvenlik analizi önkoşulları hazırlanamadı."
    record_backend_failure "security_failed"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  echo "🛡️ Ruff borç ratchet + SAST + bağımlılık güvenlik taraması çalıştırılıyor..."
  if ! uv run python scripts/ci/check_ruff_debt_baseline.py; then
    echo "❌ Ruff docstring/E501/ASYNC240 borç baseline kontrolü başarısız."
    record_backend_failure "security_failed"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if ! uv run bandit -r . -c pyproject.toml; then
    echo "❌ Bandit güvenlik taraması başarısız."
    record_backend_failure "security_failed"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  local pip_audit_timeout="${PIP_AUDIT_TIMEOUT:-30}"
  local pip_audit_max_retries="${PIP_AUDIT_MAX_RETRIES:-3}"
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
    record_backend_failure "security_failed"
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
  record_backend_failure "security_failed"
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
  echo "ℹ️ Tam extras senkronizasyonu öncesi CI sistem bağımlılıkları hazırlanıyor (PortAudio/shellcheck/bats)..."
  if ! bash scripts/install_ci_system_deps.sh; then
    echo "❌ CI sistem bağımlılıkları hazırlanamadı; pyaudio derlemesi portaudio.h eksikliğiyle başarısız olabilir."
    echo "   Manuel hazırlık: bash scripts/install_ci_system_deps.sh && uv sync --frozen --all-extras"
    BACKEND_EXIT_CODE=1
    return 1
  fi
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
    echo "❌ bats yok — shell testleri çalıştırılamadı. CI paritesi için: bash scripts/install_ci_system_deps.sh"
    echo "   Parolasız sudo kullanılabiliyorsa opt-in otomatik kurulum: AUTO_INSTALL_CI_SYSTEM_DEPS=1 bash run_tests.sh"
    record_backend_failure "bats_missing"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  echo "🐚 BATS shell testleri çalıştırılıyor..."
  mkdir -p "${BATS_REPORT_DIR}"
  if env -u DATABASE_URL -u TEST_DATABASE_URL -u POSTGRES_PASSWORD \
    bats --report-formatter junit --output "${BATS_REPORT_DIR}" tests/shell; then
    echo "✅ BATS shell testleri geçti. JUnit raporu: ${BATS_REPORT_DIR}/report.xml"
    return 0
  fi

  echo "❌ BATS shell testleri başarısız."
  record_backend_failure "bats_failed"
  BACKEND_EXIT_CODE=1
  return 1
}

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
  BENCHMARK_COMPARE_STATUS="skipped"
  echo "⚠️ Benchmark testleri RUN_BENCHMARKS=0 ile atlandı."
  if gpu_hardware_available || [ "${USE_GPU:-0}" = "1" ]; then
    echo "⚠️ GPU/hızlandırıcı algılandı; performans regresyonlarını erken yakalamak için benchmark fazını kapatmayın."
    echo "ℹ️ Öneri (lokal GPU): RUN_BENCHMARKS=required bash run_tests.sh"
  fi
  echo "⚠️ Performans regresyonlarının erken tespiti için CI/local pipeline'larda benchmark fazını düzenli çalıştırın."
  echo "ℹ️ Öneri (lokal): RUN_BENCHMARKS=required bash run_tests.sh"
  echo "ℹ️ Öneri (hedefli): uv run pytest -q ${PERFORMANCE_TEST_DIR} --benchmark-json=${BENCHMARK_JSON_OUTPUT}"
elif [ -d "${PERFORMANCE_TEST_DIR}" ]; then
  BENCHMARK_COMPARE_STATUS="not_requested"
  if ! ensure_uv_available || ! ensure_benchmark_tool_dependencies; then
    echo "❌ Benchmark önkoşulları hazırlanamadı."
    echo "   Bağımlılık kurulumu tamamlandıktan sonra yerel ilk baseline için: make benchmark-seed"
    BENCHMARK_EXIT_CODE=1
  fi
  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ]; then
    echo "📊 Aşama 2: Performans benchmark testleri tek çekirdek üzerinde koşturuluyor..."
  else
    echo "⚠️ Benchmark komutu önkoşul hatası nedeniyle çalıştırılmayacak."
  fi
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
      benchmark_baseline_age_days_value="$(benchmark_baseline_age_days "${BENCHMARK_COMPARE_FILE}" 2>/dev/null || true)"
      if [ -n "${benchmark_baseline_age_days_value}" ] \
        && [ "${benchmark_baseline_age_days_value}" -ge "${BENCHMARK_BASELINE_MAX_AGE_DAYS}" ]; then
        if [ "${BENCHMARK_ENFORCE_COMPARE}" = "1" ]; then
          BENCHMARK_COMPARE_STATUS="stale_required"
          BENCHMARK_EXIT_CODE=1
          echo "❌ Benchmark baseline ${benchmark_baseline_age_days_value} gündür yenilenmedi (eşik: ${BENCHMARK_BASELINE_MAX_AGE_DAYS} gün): ${BENCHMARK_COMPARE_FILE}"
          echo "ℹ️ Sıkı karşılaştırma bayat baseline ile devam edemez; 'make benchmark-seed' ile yenileyin."
        else
          echo "⚠️ Benchmark baseline ${benchmark_baseline_age_days_value} gündür yenilenmedi (eşik: ${BENCHMARK_BASELINE_MAX_AGE_DAYS} gün): ${BENCHMARK_COMPARE_FILE}"
          echo "ℹ️ Bayat bir baseline'a karşı rapor karşılaştırması yanıltıcı olabilir; 'make benchmark-seed' ile yenileyin."
        fi
      fi
      if [ "${BENCHMARK_ENFORCE_COMPARE}" = "1" ]; then
        if [ "${BENCHMARK_COMPARE_STATUS}" != "stale_required" ]; then
          BENCHMARK_COMPARE_STATUS="compared_enforced"
          echo "📈 Benchmark karşılaştırma kapısı etkin (--benchmark-compare=${BENCHMARK_COMPARE_SELECTOR}; baseline=${BENCHMARK_COMPARE_FILE}; regresyon_eşiği=${BENCHMARK_COMPARE_FAIL})."
          benchmark_cmd+=(--benchmark-compare-fail="${BENCHMARK_COMPARE_FAIL}")
        fi
      else
        BENCHMARK_COMPARE_STATUS="compared_report_only"
        echo "⚠️ Benchmark karşılaştırması rapor modunda (--benchmark-compare=${BENCHMARK_COMPARE_SELECTOR}; baseline=${BENCHMARK_COMPARE_FILE})."
        echo "ℹ️ Varsayılan sıkı kapıyı geçici rapor moduna almak için BENCHMARK_ENFORCE_COMPARE=0 kullanın."
      fi
    else
      BENCHMARK_COMPARE_STATUS="missing_baseline"
      echo "⚠️ Benchmark karşılaştırması atlandı: '.benchmarks' altında '${BENCHMARK_COMPARE_NAME}' etiketiyle eşleşen kayıt bulunamadı."
      echo "ℹ️ İlk benchmark koşusu --benchmark-save=${BENCHMARK_BASELINE_NAME} ile baseline kaydedecek; sonraki koşularda otomatik karşılaştırma yapılacak."
      echo "ℹ️ İlk makine/bootstrap istisnası: BENCHMARK_COMPARE_REQUIRED=0 RUN_BENCHMARKS=required ./run_tests.sh"
      echo "ℹ️ Sıkı karşılaştırma: BENCHMARK_COMPARE_REQUIRED=1 BENCHMARK_ENFORCE_COMPARE=1 RUN_BENCHMARKS=required ./run_tests.sh"
      echo "ℹ️ CI, .benchmarks baseline'ını repo commit'i yerine GitHub Actions cache/artifact üzerinden seed/restore eder."
      if [ "${BENCHMARK_COMPARE_REQUIRED}" = "1" ]; then
        if [ "${IS_CI_ENV}" -eq 1 ]; then
          BENCHMARK_COMPARE_STATUS="missing_required"
          echo "❌ BENCHMARK_COMPARE_REQUIRED=1 iken karşılaştırma için baseline bulunamadı."
          echo "ℹ️ CI bootstrap için cache/artifact baseline restore edin veya seed job'ında BENCHMARK_COMPARE_REQUIRED=0 kullanın."
          BENCHMARK_EXIT_CODE=1
        elif production_readiness_gate_active; then
          BENCHMARK_COMPARE_STATUS="missing_required"
          echo "❌ Local production-readiness için benchmark baseline bulunamadı."
          echo "➡️ Önerilen tek aksiyon: make benchmark-seed && make production-readiness"
          echo "   İlk komut .benchmarks baseline'ını üretir; ikinci komut release/merge kapısını karşılaştırmalı yeniden koşar."
          BENCHMARK_EXIT_CODE=1
        else
          echo "⚠️ Yerel bootstrap: BENCHMARK_COMPARE_REQUIRED=1 olsa da baseline bulunamadığı için ilk benchmark koşusu karşılaştırmasız çalıştırılacak."
          echo "ℹ️ Bu koşu --benchmark-save=${BENCHMARK_BASELINE_NAME} ile baseline seed eder; sonraki yerel koşular tekrar sıkı karşılaştırmaya döner."
        fi
      fi
    fi
  else
    BENCHMARK_COMPARE_STATUS="disabled"
    echo "ℹ️ Benchmark karşılaştırması devre dışı (BENCHMARK_ENABLE_COMPARE=0)."
  fi

  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ]; then
    echo "➡️ Çalıştırılan komut: ${benchmark_cmd[*]}"
    run_checked "${benchmark_cmd[@]}"
    BENCHMARK_EXIT_CODE=$?
  fi

  if [ "${BENCHMARK_EXIT_CODE}" -eq 0 ] && [ -f "${BENCHMARK_JSON_OUTPUT}" ]; then
    echo "✅ Benchmark JSON raporu oluşturuldu: ${BENCHMARK_JSON_OUTPUT}"
    if [ "${BENCHMARK_ENABLE_COMPARE}" = "1" ] && [ "${benchmark_compare_target_found}" = "0" ]; then
      if resolve_benchmark_compare_target "${BENCHMARK_COMPARE_NAME}"; then
        BENCHMARK_COMPARE_STATUS="seeded_not_compared"
        echo "✅ Benchmark baseline kaydı hazır: ${BENCHMARK_COMPARE_FILE}"
        echo "ℹ️ Sonraki benchmark koşusunda --benchmark-compare=${BENCHMARK_COMPARE_SELECTOR} otomatik kullanılacak."
      else
        BENCHMARK_COMPARE_STATUS="seed_missing"
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
  BENCHMARK_COMPARE_STATUS="benchmark_dir_missing"
  echo "⚠️ Benchmark testi atlandı: ${PERFORMANCE_TEST_DIR} bulunamadı."
  if [ "${RUN_BENCHMARKS}" = "required" ]; then
    echo "❌ RUN_BENCHMARKS=required iken benchmark dizini bulunamadı."
    BENCHMARK_EXIT_CODE=1
  fi
fi

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

        echo "🧪 Frontend typecheck kalite kapısı çalıştırılıyor: npm run typecheck"
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
print_release_scope_warning_once() {
  if [ "${RELEASE_SCOPE_WARNING_PRINTED}" = "1" ]; then
    return 0
  fi
  RELEASE_SCOPE_WARNING_PRINTED=1

  echo "ℹ️ GPU Inference Quality Gate (TTFT<=200ms, latency<=250ms) bu koşuya dahil değildir."
  echo "   Lokal production_ready=true bu donanım gate'inin geçtiği anlamına gelmez. CI'daki"
  echo "   GPU Inference Required Evidence Gate, ENABLE_GPU_BENCH_GATE=true ve başarılı self-hosted"
  echo "   GPU sonucu olmadan fail-closed çalışır; production-readiness aggregate buna bağlıdır."

  if production_readiness_gate_active; then
    echo "✅ Production readiness kapsamı aktif: ${PRODUCTION_READINESS_COMMAND}"
  elif stage_all_selected; then
    if [ "${FINAL_EXIT_CODE}" -eq 0 ]; then
      echo "✅ Development full validation başarıyla tamamlandı."
    fi
    cat <<RELEASE_SCOPE_WARNING

🚨 RELEASE / MERGE ONAYI VERMEYİN [summary-code=10]
   Bu çalışma --stage all kapsamını development/local profilinde tamamladı;
   artifacts/test-summary.json içinde production_ready=false kalır.
   PR template ve merge checklist üzerinde bu alan zorunlu kontrol edilmelidir.
   Production readiness için kanonik komut:
   ${PRODUCTION_READINESS_MAKE_COMMAND}
   Eşdeğer doğrudan komut:
   ${PRODUCTION_READINESS_COMMAND}
RELEASE_SCOPE_WARNING
    if [ "${TEST_PROFILE:-local}" = "local" ] && [ "${FRONTEND_BUNDLE_BUDGET}" != "1" ]; then
      echo "⚠️ Frontend bundle budget local/dev-full akışında kapalı. CI paritesi için: FRONTEND_BUNDLE_BUDGET_LOCAL_FULL=1 bash run_tests.sh --stage all"
    fi
  else
    cat <<RELEASE_SCOPE_WARNING

🚨 RELEASE / MERGE ONAYI VERMEYİN [summary-code=20]
   Bu çalışma production readiness gate değildir. Smoke/unit/build gibi seçili
   kapılar geçse bile integration, frontend E2E ve benchmark tam koşullarda
   çalışmadıysa projeyi production-ready kabul etmeyin.
   Production readiness için kanonik komut:
   ${PRODUCTION_READINESS_MAKE_COMMAND}
   Eşdeğer doğrudan komut:
   ${PRODUCTION_READINESS_COMMAND}
RELEASE_SCOPE_WARNING
  fi
}

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
