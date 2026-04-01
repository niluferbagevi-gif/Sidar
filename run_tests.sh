#!/bin/bash
set -euo pipefail

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-90}"
AUTO_OPEN_ARTIFACTS="${AUTO_OPEN_ARTIFACTS:-1}"

PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
RUN_BENCHMARKS="${RUN_BENCHMARKS:-auto}"

open_artifact() {
  local target="$1"
  if [ ! -e "$target" ] || [ "${AUTO_OPEN_ARTIFACTS}" != "1" ]; then
    return 0
  fi

  if command -v xdg-open >/dev/null 2>&1; then
    nohup xdg-open "$target" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    nohup open "$target" >/dev/null 2>&1 || true
  elif command -v start >/dev/null 2>&1; then
    start "$target" >/dev/null 2>&1 || true
  else
    echo "ℹ️ Otomatik açma için desteklenen komut bulunamadı: $target"
  fi
}

run_pytest_coverage_report() {
  echo "📊 Pytest + Coverage + Quality Gate çalıştırılıyor..."
  PYTEST_CMD=(pytest --cov-fail-under="${COVERAGE_FAIL_UNDER}")
  if python -c "import xdist" >/dev/null 2>&1; then
    PYTEST_CMD+=( -n "${PYTEST_WORKERS}" )
  fi
  echo "➡️ Çalıştırılan komut: ${PYTEST_CMD[*]}"

  "${PYTEST_CMD[@]}"

  if [ -f "htmlcov/index.html" ]; then
    echo "✅ Coverage HTML raporu oluşturuldu: htmlcov/index.html"
    open_artifact "htmlcov/index.html"
  else
    echo "⚠️ Coverage raporu oluşturulamadı: htmlcov/index.html bulunamadı."
  fi
}

# 1) Backend testleri + coverage (pyproject addopts ile) + quality gate
run_pytest_coverage_report

# 2) Kritik yol performans baseline testleri (pytest-benchmark)
if [ "${RUN_BENCHMARKS}" = "0" ]; then
  echo "ℹ️ Benchmark testleri RUN_BENCHMARKS=0 ile atlandı."
elif [ -f "tests/test_benchmark.py" ]; then
  python -m pytest -v tests/test_benchmark.py --no-cov
else
  echo "⚠️ Benchmark testi atlandı: tests/test_benchmark.py bulunamadı."
fi

# 3) Frontend React testleri ve coverage (web_ui_react varsa zorunlu quality gate)
if [ -d "web_ui_react" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "❌ web_ui_react dizini var ama npm bulunamadı — React testleri çalıştırılamıyor."
    exit 1
  fi

  echo "🚀 Frontend (React) Testleri Başlıyor..."
  pushd web_ui_react > /dev/null
  npm ci
  npm run test:coverage
  for report in coverage/lcov-report/index.html coverage/index.html; do
    open_artifact "$PWD/$report"
  done
  popd > /dev/null
fi

echo "✅ Tüm Backend ve Frontend testleri başarıyla tamamlandı!"
