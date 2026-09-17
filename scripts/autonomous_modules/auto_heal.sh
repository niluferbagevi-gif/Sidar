#!/usr/bin/env bash

# Helper functions sourced by autonomous_loop.sh; do not execute directly.
# shellcheck disable=SC2034,SC2153  # Helpers consume/update orchestrator globals.

run_auto_heal_for_test_failure() {
  local source="${1:-pytest}"
  local log_path="${AUTONOMOUS_TEST_FAILURE_LOG}"

  if ! is_truthy_flag "${AUTONOMOUS_AUTO_HEAL_ENABLED}"; then
    echo "[HEAL] Auto-heal devre dışı (AUTONOMOUS_LOOP_AUTO_HEAL_ENABLED=${AUTONOMOUS_AUTO_HEAL_ENABLED})."
    return 1
  fi
  if [ ! -s "${log_path}" ]; then
    echo "[HEAL] Auto-heal log dosyası yok veya boş: ${log_path}"
    return 1
  fi

  mkdir -p "$(dirname "${AUTONOMOUS_AUTO_HEAL_RESULT_PATH}")"
  echo "[HEAL] Self-heal tetikleniyor: source=${source}, log=${log_path}, output=${AUTONOMOUS_AUTO_HEAL_RESULT_PATH}"
  local cmd=(
    uv run python -m scripts.auto_heal
    --log "${log_path}"
    --source "${source}"
    --output "${AUTONOMOUS_AUTO_HEAL_RESULT_PATH}"
  )
  if [ "${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}" = "prompt" ] || \
    [ "${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}" = "ask" ] || \
    [ "${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}" = "interactive" ]; then
    echo "[HEAL] HITL modu etkileşimli; scripts.auto_heal terminalden onay isteyecek."
  else
    cmd+=(--hitl-approve "${AUTONOMOUS_AUTO_HEAL_HITL_APPROVE}")
  fi
  "${cmd[@]}"
}
