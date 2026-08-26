#!/usr/bin/env bash

# Helper functions sourced by run_tests.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

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
  # -u OLLAMA_NUM_CTX/_NUM_BATCH/_CODING_NUM_CTX: defense-in-depth alongside
  # the DATABASE_URL/POSTGRES_PASSWORD stripping above. install_sidar.sh's
  # own Ollama phase (sidar_ollama_export_runtime_defaults) exports these
  # into its own process before this step ever runs; when run_tests.sh runs
  # as a *child* of that same install_sidar.sh run (its end-of-install "CI
  # Tam Doğrulama" -> `make dev-full` prompt), that export otherwise leaks
  # into every bats subshell and shadows the isolated tmpdir/.env fixtures
  # tests/shell/ollama_ctx_batch_source_of_truth.bats and
  # tests/shell/ollama_coding_smoke.bats construct. Those test files also
  # unset these themselves now (belt-and-suspenders), but stripping here too
  # keeps this entry point correct for any future test with the same shape.
  if env -u DATABASE_URL -u TEST_DATABASE_URL -u POSTGRES_PASSWORD \
    -u OLLAMA_NUM_CTX -u OLLAMA_NUM_BATCH -u OLLAMA_CODING_NUM_CTX \
    bats --report-formatter junit --output "${BATS_REPORT_DIR}" tests/shell; then
    echo "✅ BATS shell testleri geçti. JUnit raporu: ${BATS_REPORT_DIR}/report.xml"
    return 0
  fi

  echo "❌ BATS shell testleri başarısız."
  record_backend_failure "bats_failed"
  BACKEND_EXIT_CODE=1
  return 1
}
