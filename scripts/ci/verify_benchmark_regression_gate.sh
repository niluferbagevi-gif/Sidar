#!/usr/bin/env bash
# Benchmark regression gate doğrulayıcı.
#
# pytest-benchmark `--benchmark-compare-fail=mean:X%` kapısının "sessiz" hale
# gelmediğini (yani gerçek bir yavaşlamada exit kodunu non-zero'a çevirdiğini)
# bağımsız bir canary üzerinde doğrular.
#
# Adımlar:
#   1) `tests/performance/test_regression_gate_canary.py` testini temiz baseline
#      olarak çalıştırır (`gate-canary-clean` etiketiyle saklar).
#   2) Aynı testi `SIDAR_BENCH_GATE_CANARY_SLOWDOWN_MS` enjekte ederek tekrar
#      çalıştırır ve `--benchmark-compare-fail` kapısının non-zero exit
#      ürettiğini bekler.
#   3) Üretilen canary JSON'larını temizler; gerçek `baseline` etkilenmez.
#
# Kullanım:
#   ./scripts/ci/verify_benchmark_regression_gate.sh
#   SIDAR_BENCH_GATE_CANARY_SLOWDOWN_MS=10 ./scripts/ci/verify_benchmark_regression_gate.sh
#   FAIL_THRESHOLD=mean:50% ./scripts/ci/verify_benchmark_regression_gate.sh
#
# Çevre değişkenleri:
#   SIDAR_BENCH_GATE_CANARY_SLOWDOWN_MS  Enjekte edilecek yavaşlatma (ms). default: 10
#   FAIL_THRESHOLD                       --benchmark-compare-fail eşiği.    default: mean:50%
#   PYTEST_CMD                           pytest çağrısı (uv kullanılmıyorsa).default: uv run python -m pytest
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

SLOWDOWN_MS="${SIDAR_BENCH_GATE_CANARY_SLOWDOWN_MS:-10}"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-mean:50%}"
PYTEST_CMD="${PYTEST_CMD:-uv run python -m pytest}"

# Yavaşlatma 0 olursa canary baseline ile aynı zamanı ölçer ve gate hiç
# tetiklenmez; bu durumda script "kapı sessiz" yanlış-pozitifi üretir.
# Kullanıcıyı erken uyaralım.
if ! [[ "${SLOWDOWN_MS}" =~ ^[0-9]+(\.[0-9]+)?$ ]] \
   || awk -v ms="${SLOWDOWN_MS}" 'BEGIN { exit (ms+0 > 0) ? 1 : 0 }'; then
  echo "❌ SIDAR_BENCH_GATE_CANARY_SLOWDOWN_MS pozitif bir sayı olmalı (alınan: '${SLOWDOWN_MS}')."
  echo "   Gate'i sessiz raporlamamak için en az birkaç ms gerçek yavaşlatma kullanın (öneri: 10)."
  exit 2
fi

CANARY_NODE="tests/performance/test_regression_gate_canary.py::test_regression_gate_canary"
BENCH_DIR=".benchmarks"
CLEAN_TAG="gate-canary-clean"
SLOW_TAG="gate-canary-slow"

# Tag ile eşleşen tüm canary baseline dosyalarını siler.
cleanup_canary_artifacts() {
  if [ ! -d "${BENCH_DIR}" ]; then
    return 0
  fi
  find "${BENCH_DIR}" -type f \
    \( -name "*_${CLEAN_TAG}.json" -o -name "*_${SLOW_TAG}.json" \) \
    -print -delete 2>/dev/null || true
}

trap cleanup_canary_artifacts EXIT

cleanup_canary_artifacts

echo "🔬 Benchmark regression gate doğrulanıyor..."
echo "   Canary node : ${CANARY_NODE}"
echo "   Slowdown    : ${SLOWDOWN_MS} ms"
echo "   Eşik        : ${FAIL_THRESHOLD}"

# Canary, projenin ağır conftest fixture'larından bağımsız bir CPU işidir;
# `--noconftest` ile çalıştırarak hem doğrulama hem de bağımlılık
# yüzeyini minimumda tutuyoruz. `--override-ini` ile addopts (coverage)
# ve `filterwarnings` zorunluluklarını boşaltıyoruz.
PYTEST_BASE_ARGS=(
  -c pyproject.toml
  -q
  --noconftest
  -p no:cacheprovider
  --override-ini=addopts=
  --override-ini=filterwarnings=
  --override-ini=asyncio_mode=strict
  -n 0
  --no-cov
  --benchmark-warmup=off
  --benchmark-min-rounds=5
  --benchmark-disable-gc
)

# Aşama 1: temiz canary baseline.
echo "➡️  Aşama 1/2: temiz canary baseline kaydediliyor (${CLEAN_TAG})..."
SIDAR_BENCH_GATE_CANARY=1 \
SIDAR_BENCH_GATE_CANARY_SLOWDOWN_MS=0 \
${PYTEST_CMD} "${PYTEST_BASE_ARGS[@]}" "${CANARY_NODE}" \
  --benchmark-save="${CLEAN_TAG}"

# Lokal yardımcı: baseline JSON yolunu bul.
find_latest() {
  local tag="$1"
  find "${BENCH_DIR}" -type f -name "*_${tag}.json" -print 2>/dev/null \
    | sort -V | tail -n 1
}

BASELINE_FILE="$(find_latest "${CLEAN_TAG}")"
if [ -z "${BASELINE_FILE}" ]; then
  echo "❌ Temiz canary baseline JSON dosyası bulunamadı (.benchmarks/**/*_${CLEAN_TAG}.json)."
  exit 1
fi
echo "   Baseline JSON: ${BASELINE_FILE}"

# Aşama 2: yapay yavaşlatma ile yeniden çalıştır ve gate'in fail etmesini bekle.
echo "➡️  Aşama 2/2: ${SLOWDOWN_MS} ms yavaşlatma enjekte ediliyor ve gate'in fail etmesi bekleniyor..."
set +e
SIDAR_BENCH_GATE_CANARY=1 \
SIDAR_BENCH_GATE_CANARY_SLOWDOWN_MS="${SLOWDOWN_MS}" \
${PYTEST_CMD} "${PYTEST_BASE_ARGS[@]}" "${CANARY_NODE}" \
  --benchmark-save="${SLOW_TAG}" \
  --benchmark-compare="${BASELINE_FILE}" \
  --benchmark-compare-fail="${FAIL_THRESHOLD}"
SLOW_EXIT=$?
set -e

echo "   pytest exit kodu: ${SLOW_EXIT}"

if [ "${SLOW_EXIT}" -eq 0 ]; then
  echo "❌ Regression gate SESSİZ: ${SLOWDOWN_MS} ms yapay yavaşlatma altında dahi exit=0 üretildi."
  echo "   Beklenen: ${FAIL_THRESHOLD} eşiği aşıldığı için non-zero exit."
  echo "   Çözüm önerisi: run_tests.sh içindeki --benchmark-compare ve --benchmark-compare-fail bayraklarının"
  echo "                  benchmark koşusuna gerçekten geçirildiğini ve BENCHMARK_ENFORCE_COMPARE=1 olduğunu doğrulayın."
  exit 1
fi

echo "✅ Regression gate canlı: yapay yavaşlatmada exit=${SLOW_EXIT} ile alarm tetiklendi."
exit 0
