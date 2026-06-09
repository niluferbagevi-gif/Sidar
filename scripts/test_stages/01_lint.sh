# shellcheck shell=bash
# shellcheck disable=SC2034
# This file is sourced by run_tests.sh and expects its functions/variables in scope.
if [ -z "${SIDAR_RUN_TESTS_CONTEXT:-}" ]; then
  echo "❌ scripts/test_stages faz dosyaları doğrudan çalıştırılmaz; repo kökünden bash run_tests.sh kullanın."
  exit 2
fi

# 1) Backend lint/type-check ve ortak önkoşul fazı:
#    Faz-1: uv/runtime doğrulaması + Ollama model senkronizasyonu
#    Faz-2: Statik analiz + otonom iyileştirme
BACKEND_PREREQUISITES_READY=0
BACKEND_TESTS_READY=0
if ensure_uv_available && prepare_docker_test_image && ensure_runtime_dependencies && sync_ollama_models && run_static_analysis_gates; then
  BACKEND_PREREQUISITES_READY=1
else
  echo "❌ Backend lint/type-check önkoşulları başarısız; pytest ve BATS fazları atlanacak."
  BACKEND_EXIT_CODE=1
fi
