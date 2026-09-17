#!/usr/bin/env bash

# Helper functions sourced by run_tests.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

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

  echo "🛡️ Kaynak borç kapıları + SAST + bağımlılık güvenlik taraması çalıştırılıyor..."
  if ! uv run python scripts/ci/check_ruff_debt_baseline.py; then
    echo "❌ Ruff docstring/E501/ASYNC240 borç baseline kontrolü başarısız."
    record_backend_failure "security_failed"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if ! uv run python scripts/ci/check_source_debt_markers.py; then
    echo "❌ Üretim kaynaklarında TODO/FIXME/HACK/XXX teknik borç işareti bulundu."
    record_backend_failure "security_failed"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if ! uv run python scripts/ci/check_module_notes_inventory.py; then
    echo "❌ docs/module-notes/INDEX.md envanter sözleşmesi başarısız (eksik kaynak/not, orphan not veya dokümante edilmemiş modül ratchet'i)."
    record_backend_failure "security_failed"
    BACKEND_EXIT_CODE=1
    return 1
  fi

  if ! uv run python scripts/ci/check_bandit_suppression_baseline.py; then
    echo "❌ Bandit güvenlik taraması veya suppression ratchet başarısız."
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
