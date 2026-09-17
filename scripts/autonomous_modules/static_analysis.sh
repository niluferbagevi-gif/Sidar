#!/usr/bin/env bash

# Helper functions sourced by autonomous_loop.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

run_static_analysis_heal_phases() {
  local mypy_exit=0
  local bandit_exit=0

  if ! is_truthy_flag "${AUTONOMOUS_RUN_LINTER_PHASES}"; then
    echo "[LINTER] AUTONOMOUS_LOOP_RUN_LINTER_PHASES=${AUTONOMOUS_RUN_LINTER_PHASES}; mypy/bandit fazları atlandı."
    return 0
  fi

  mkdir -p "${AUTONOMOUS_REPORTS_DIR}"

  echo "[LINTER] Running Mypy Type Check..."
  uv run mypy . > "${AUTONOMOUS_MYPY_REPORT}" 2>&1
  mypy_exit=$?
  if [ "${mypy_exit}" -ne 0 ]; then
    echo "[LINTER] Mypy failed (exit=${mypy_exit}). Triggering Auto-Heal for type-check context..."
    cp "${AUTONOMOUS_MYPY_REPORT}" "${AUTONOMOUS_TEST_FAILURE_LOG}"
    run_auto_heal_for_test_failure mypy || true
  else
    echo "[LINTER] Mypy passed."
  fi

  echo "[SECURITY] Running Bandit Security Scan..."
  uv run bandit -r . -c pyproject.toml -f json -o "${AUTONOMOUS_BANDIT_REPORT}"
  bandit_exit=$?
  if [ "${bandit_exit}" -ne 0 ]; then
    echo "[SECURITY] Bandit found warnings (exit=${bandit_exit}). Triggering Auto-Heal for security context..."
    cp "${AUTONOMOUS_BANDIT_REPORT}" "${AUTONOMOUS_TEST_FAILURE_LOG}"
    run_auto_heal_for_test_failure bandit || true
  else
    echo "[SECURITY] Bandit passed."
  fi
}
