# shellcheck shell=bash
# shellcheck disable=SC2034
# This file is sourced by run_tests.sh and expects its functions/variables in scope.
if [ -z "${SIDAR_RUN_TESTS_CONTEXT:-}" ]; then
  echo "❌ scripts/test_stages faz dosyaları doğrudan çalıştırılmaz; repo kökünden bash run_tests.sh kullanın."
  exit 2
fi

# 3) Backend BATS shell testleri + coverage ratchet fazı
if [ "${BACKEND_TESTS_READY:-0}" = "1" ]; then
  run_bats_shell_tests
  update_progressive_coverage_gate
else
  echo "⚠️ Backend test önkoşulları sağlanmadığı için BATS ve coverage ratchet fazı atlandı."
fi
