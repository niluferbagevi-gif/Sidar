# shellcheck shell=bash
# shellcheck disable=SC2034
# This file is sourced by run_tests.sh and expects its functions/variables in scope.
if [ -z "${SIDAR_RUN_TESTS_CONTEXT:-}" ]; then
  echo "❌ scripts/test_stages faz dosyaları doğrudan çalıştırılmaz; repo kökünden bash run_tests.sh kullanın."
  exit 2
fi

# 2) Backend unit/integration pytest + coverage fazı:
#    Ağır altyapı (Redis/PostgreSQL) + DB hazırlık + pytest coverage
if [ "${BACKEND_PREREQUISITES_READY:-0}" = "1" ] && load_test_database_password_env && ensure_test_services && prepare_test_database; then
  BACKEND_TESTS_READY=1
  run_pytest_coverage_report
else
  echo "❌ Backend pytest coverage fazı atlandı: önkoşul veya test veritabanı hazırlığı başarısız."
  BACKEND_EXIT_CODE=1
fi
