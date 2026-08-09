#!/usr/bin/env bash

# Helper functions sourced by run_tests.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

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
