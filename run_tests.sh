#!/bin/bash
set -uo pipefail

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

# Kademeli geçiş: mevcut backend coverage baseline'ı düşük olduğu için
# varsayılan eşik başlangıçta 14 tutulur. CI/CD veya local'de istenirse
# COVERAGE_FAIL_UNDER env ile daha yüksek hedef zorlanabilir.
COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-14}"
AUTO_OPEN_ARTIFACTS="${AUTO_OPEN_ARTIFACTS:-1}"
BASELINE_COVERAGE_FILE="${BASELINE_COVERAGE_FILE:-tests/coverage_baseline.txt}"

PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
RUN_BENCHMARKS="${RUN_BENCHMARKS:-auto}"

BACKEND_EXIT_CODE=0
FRONTEND_EXIT_CODE=0
BENCHMARK_EXIT_CODE=0

# 0) Önceki test artefaktlarını temizle
rm -rf .coverage .coverage.* htmlcov web_ui_react/coverage

open_artifact() {
  local target="$1"
  if [ ! -e "$target" ] || [ "${AUTO_OPEN_ARTIFACTS}" != "1" ]; then
    return 0
  fi

  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$target" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "$target" >/dev/null 2>&1 &
  elif command -v start >/dev/null 2>&1; then
    start "" "$target" >/dev/null 2>&1 &
  else
    echo "ℹ️ Otomatik açma için desteklenen komut bulunamadı: $target"
  fi
}

run_pytest_coverage_report() {
  echo "📊 Pytest + Coverage + Quality Gate çalıştırılıyor..."
  local pytest_cmd=(pytest --cov-fail-under="${COVERAGE_FAIL_UNDER}")

  if python -c "import xdist" >/dev/null 2>&1; then
    pytest_cmd+=(-n "${PYTEST_WORKERS}")
  fi

  echo "➡️ Çalıştırılan komut: ${pytest_cmd[*]}"

  "${pytest_cmd[@]}"
  BACKEND_EXIT_CODE=$?

  # parallel=True nedeniyle oluşan .coverage.* dosyalarını birleştir
  coverage combine >/dev/null 2>&1 || true

  # pytest başarısız olsa bile HTML raporunu üretmeyi dene
  coverage html >/dev/null 2>&1 || true

  if [ -f "htmlcov/index.html" ]; then
    echo "✅ Coverage HTML raporu oluşturuldu: htmlcov/index.html"
    open_artifact "htmlcov/index.html"
  else
    echo "⚠️ Coverage raporu oluşturulamadı: htmlcov/index.html bulunamadı."
  fi
}

enforce_coverage_non_regression() {
  if [ "${BACKEND_EXIT_CODE}" -ne 0 ]; then
    return 0
  fi

  if [ ! -f "coverage.xml" ]; then
    echo "⚠️ Non-regression coverage kontrolü atlandı: coverage.xml bulunamadı."
    return 0
  fi

  if [ ! -f "${BASELINE_COVERAGE_FILE}" ]; then
    echo "ℹ️ Coverage baseline dosyası bulunamadı (${BASELINE_COVERAGE_FILE}); non-regression kontrolü atlandı."
    return 0
  fi

  python - "$BASELINE_COVERAGE_FILE" <<'PY'
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

baseline_path = Path(sys.argv[1])
baseline = float(baseline_path.read_text(encoding="utf-8").strip())
root = ET.parse("coverage.xml").getroot()
line_rate = float(root.attrib.get("line-rate", "0") or 0.0)
current = round(line_rate * 100.0, 2)
print(f"ℹ️ Coverage non-regression kontrolü: current={current:.2f}% baseline={baseline:.2f}%")
if current + 1e-9 < baseline:
    raise SystemExit(1)
PY
  local baseline_exit=$?
  if [ "${baseline_exit}" -ne 0 ]; then
    echo "❌ Coverage baseline geriledi: ${BASELINE_COVERAGE_FILE} altına düşüldü."
    BACKEND_EXIT_CODE=1
  fi
}

# 1) Backend testleri + coverage (pyproject addopts ile) + quality gate
run_pytest_coverage_report
enforce_coverage_non_regression

# 2) Kritik yol performans baseline testleri (pytest-benchmark)
if [ "${RUN_BENCHMARKS}" = "0" ]; then
  echo "ℹ️ Benchmark testleri RUN_BENCHMARKS=0 ile atlandı."
elif [ -f "tests/test_benchmark.py" ]; then
  python -m pytest -v tests/test_benchmark.py --no-cov
  BENCHMARK_EXIT_CODE=$?
elif [ -f "tests/performance/test_benchmark.py" ]; then
  python -m pytest -v tests/performance/test_benchmark.py --no-cov
  BENCHMARK_EXIT_CODE=$?
else
  echo "⚠️ Benchmark testi atlandı: tests/test_benchmark.py veya tests/performance/test_benchmark.py bulunamadı."
fi

# 3) Frontend React testleri ve coverage (web_ui_react varsa zorunlu quality gate)
if [ -d "web_ui_react" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "❌ web_ui_react dizini var ama npm bulunamadı — React testleri çalıştırılamıyor."
    FRONTEND_EXIT_CODE=1
  else
    echo "🚀 Frontend (React) Testleri Başlıyor..."
    pushd web_ui_react > /dev/null || FRONTEND_EXIT_CODE=1

    if [ "${FRONTEND_EXIT_CODE}" -eq 0 ]; then
      npm ci
      local_npm_ci_exit=$?
      if [ "${local_npm_ci_exit}" -ne 0 ]; then
        FRONTEND_EXIT_CODE=${local_npm_ci_exit}
      else
        npm run test:coverage
        FRONTEND_EXIT_CODE=$?
      fi

      for report in coverage/lcov-report/index.html coverage/index.html; do
        open_artifact "$PWD/$report"
      done

      popd > /dev/null || true
    fi
  fi
fi

echo "======================================================"

# 4) Final Durum Değerlendirmesi
if [ "${BACKEND_EXIT_CODE}" -ne 0 ] || [ "${FRONTEND_EXIT_CODE}" -ne 0 ] || [ "${BENCHMARK_EXIT_CODE}" -ne 0 ]; then
  echo "❌ Bazı testler veya kalite kapıları (coverage) başarısız oldu!"
  echo "   Backend Çıkış Kodu: ${BACKEND_EXIT_CODE}"
  echo "   Frontend Çıkış Kodu: ${FRONTEND_EXIT_CODE}"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE}"
  exit 1
else
  echo "✅ Tüm Backend, Frontend ve Benchmark testleri BAŞARIYLA tamamlandı!"
  exit 0
fi
