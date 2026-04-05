#!/bin/bash
set -uo pipefail

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-90}"
AUTO_OPEN_ARTIFACTS="${AUTO_OPEN_ARTIFACTS:-1}"

PYTEST_WORKERS="${PYTEST_WORKERS:-auto}"
RUN_BENCHMARKS="${RUN_BENCHMARKS:-auto}"

BACKEND_EXIT_CODE=0
FRONTEND_EXIT_CODE=0
BENCHMARK_EXIT_CODE=0
LINT_EXIT_CODE=0



# 0) Linting ve statik analiz
run_static_checks() {
  echo "🧹 Tüm dosyalar için linting ve statik analiz yapılıyor..."

  if command -v ruff >/dev/null 2>&1; then
    echo "   -> Python linter (ruff) çalışıyor..."
    ruff check . || return 1
  else
    echo "⚠️ Ruff bulunamadı, python lint adımı atlandı."
  fi

  if command -v mypy >/dev/null 2>&1; then
    echo "   -> Python tip kontrolü (mypy) çalışıyor..."
    if ! mypy .; then
      echo "⚠️ Mypy uyarıları/hataları bulundu, lütfen inceleyin."
    fi
  else
    echo "⚠️ Mypy bulunamadı, tip kontrol adımı atlandı."
  fi

  if command -v pip-audit >/dev/null 2>&1; then
    echo "   -> Bağımlılık güvenlik taraması (pip-audit) çalışıyor..."
    if ! pip-audit; then
      echo "⚠️ pip-audit güvenlik uyarıları raporladı, çıktı incelenmeli."
    fi
  else
    echo "ℹ️ pip-audit bulunamadı, güvenlik taraması atlandı."
  fi

  if command -v yamllint >/dev/null 2>&1; then
    echo "   -> YAML linter (yamllint) çalışıyor..."
    if ! yamllint .; then
      echo "⚠️ YAML format uyarıları bulundu, çıktı incelenmeli."
    fi
  else
    echo "ℹ️ yamllint bulunamadı, YAML lint adımı atlandı."
  fi

  if command -v shellcheck >/dev/null 2>&1; then
    echo "   -> Shell linter (shellcheck) çalışıyor..."
    if ! find . -type f -name "*.sh" -exec shellcheck {} +; then
      echo "⚠️ Shell script uyarıları bulundu, çıktı incelenmeli."
    fi
  else
    echo "ℹ️ shellcheck bulunamadı, shell lint adımı atlandı."
  fi
}

# 1) Önceki test artefaktlarını temizle
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

# 2) Statik analiz ve linting quality gate
if ! run_static_checks; then
  echo "❌ Statik analiz adımı başarısız oldu."
  LINT_EXIT_CODE=1
fi

# 3) Backend testleri + coverage (pyproject addopts ile) + quality gate
run_pytest_coverage_report

# 4) Kritik yol performans baseline testleri (pytest-benchmark)
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

# 5) Frontend React testleri ve coverage (web_ui_react varsa zorunlu quality gate)
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

# 6) Final Durum Değerlendirmesi
if [ "${LINT_EXIT_CODE}" -ne 0 ] || [ "${BACKEND_EXIT_CODE}" -ne 0 ] || [ "${FRONTEND_EXIT_CODE}" -ne 0 ] || [ "${BENCHMARK_EXIT_CODE}" -ne 0 ]; then
  echo "❌ Bazı testler veya kalite kapıları (coverage) başarısız oldu!"
  echo "   Lint Çıkış Kodu: ${LINT_EXIT_CODE}"
  echo "   Backend Çıkış Kodu: ${BACKEND_EXIT_CODE}"
  echo "   Frontend Çıkış Kodu: ${FRONTEND_EXIT_CODE}"
  echo "   Benchmark Çıkış Kodu: ${BENCHMARK_EXIT_CODE}"
  exit 1
else
  echo "✅ Tüm Backend, Frontend ve Benchmark testleri BAŞARIYLA tamamlandı!"
  exit 0
fi
