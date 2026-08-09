#!/usr/bin/env bash

# Helper functions sourced by run_tests.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

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
