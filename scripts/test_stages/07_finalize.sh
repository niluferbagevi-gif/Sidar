# shellcheck shell=bash
# shellcheck disable=SC2034
# This file is sourced by run_tests.sh and expects its functions/variables in scope.
if [ -z "${SIDAR_RUN_TESTS_CONTEXT:-}" ]; then
  echo "❌ scripts/test_stages faz dosyaları doğrudan çalıştırılmaz; repo kökünden bash run_tests.sh kullanın."
  exit 2
fi

# 7) Final Durum Değerlendirmesi
FINAL_EXIT_CODE=0
if [ "${BACKEND_EXIT_CODE}" -ne 0 ] || [ "${FRONTEND_EXIT_CODE}" -ne 0 ]; then
  FINAL_EXIT_CODE=1
fi
if [ "${BENCHMARK_EXIT_CODE}" -ne 0 ]; then
  if [ "${BENCHMARK_ENFORCE_RESULT}" = "1" ]; then
    FINAL_EXIT_CODE=1
  else
    echo "⚠️ Benchmark fazı başarısız ancak TEST_PROFILE=${TEST_PROFILE} için flake-soft-fail modunda; final çıkış kodu bloke edilmeyecek."
    echo "   Sıkı yerel doğrulama için: BENCHMARK_ENFORCE_RESULT=1 bash run_tests.sh"
  fi
fi
if [ "${FRONTEND_E2E_EXIT_CODE}" -ne 0 ]; then
  if [ "${FRONTEND_E2E_ENFORCE_RESULT}" = "1" ]; then
    FINAL_EXIT_CODE=1
  else
    echo "⚠️ Frontend Playwright E2E fazı retry sonrasında başarısız ancak TEST_PROFILE=${TEST_PROFILE} için flake-soft-fail modunda; final çıkış kodu bloke edilmeyecek."
    echo "   Sıkı yerel doğrulama için: FRONTEND_E2E_ENFORCE_RESULT=1 bash run_tests.sh"
  fi
fi

if [ "${FINAL_EXIT_CODE}" -ne 0 ]; then
  echo "❌ Bazı testler veya kalite kapıları (coverage) başarısız oldu!"
  echo "   Backend Çıkış Kodu: ${BACKEND_EXIT_CODE}"
  if [ "${BACKEND_EXIT_CODE}" -ne 0 ]; then
    echo "   Backend Hata Nedenleri: $(format_backend_failure_reasons)"
  fi
  echo "   Frontend Unit/Coverage Çıkış Kodu: ${FRONTEND_EXIT_CODE}"
  echo "   Frontend E2E Çıkış Kodu: ${FRONTEND_E2E_EXIT_CODE} (enforce=${FRONTEND_E2E_ENFORCE_RESULT})"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE} (enforce=${BENCHMARK_ENFORCE_RESULT})"
  exit 1
else
  echo "✅ Zorunlu Backend, Frontend ve Benchmark kalite kapıları BAŞARIYLA tamamlandı!"
  echo "   Frontend E2E Çıkış Kodu: ${FRONTEND_E2E_EXIT_CODE} (enforce=${FRONTEND_E2E_ENFORCE_RESULT})"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE} (enforce=${BENCHMARK_ENFORCE_RESULT})"
  exit 0
fi