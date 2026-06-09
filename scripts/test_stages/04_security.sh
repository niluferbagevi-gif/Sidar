# shellcheck shell=bash
# shellcheck disable=SC2034
# This file is sourced by run_tests.sh and expects its functions/variables in scope.
if [ -z "${SIDAR_RUN_TESTS_CONTEXT:-}" ]; then
  echo "❌ scripts/test_stages faz dosyaları doğrudan çalıştırılmaz; repo kökünden bash run_tests.sh kullanın."
  exit 2
fi

# 4) Güvenlik kapıları pytest yürütümünü bloke etmez; sonuç final çıkışta değerlendirilir.
if ! run_security_analysis_gates; then
  echo "⚠️ Güvenlik analizi başarısız oldu; pytest sonuçları üretildi, final çıkış kodu başarısız olarak işaretlenecek."
  BACKEND_EXIT_CODE=1
fi
