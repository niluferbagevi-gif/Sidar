#!/bin/bash
set -euo pipefail

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-100}"
AUTO_OPEN_ARTIFACTS="${AUTO_OPEN_ARTIFACTS:-1}"
TEST_SCOPE="${TEST_SCOPE:-unit}" # unit|integration|e2e|all

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

build_pytest_target_args() {
  case "${TEST_SCOPE}" in
    unit)
      echo "--ignore=tests/integration --ignore=tests/e2e"
      ;;
    integration)
      echo "tests/integration"
      ;;
    e2e)
      echo "tests/e2e"
      ;;
    all)
      echo ""
      ;;
    *)
      echo "❌ Geçersiz TEST_SCOPE='${TEST_SCOPE}'. Desteklenen değerler: unit, integration, e2e, all" >&2
      exit 2
      ;;
  esac
}

run_pytest_coverage_report() {
  local target_args
  target_args="$(build_pytest_target_args)"

  echo "📊 Pytest Coverage Raporu oluşturuluyor..."
  echo "➡️ Çalıştırılan komut: pytest -v ${target_args} --cov=managers.security --cov=core.memory --cov=core.rag --cov-fail-under=${COVERAGE_FAIL_UNDER}"

  # shellcheck disable=SC2086
  pytest -v ${target_args} \
    --cov=managers.security \
    --cov=core.memory \
    --cov=core.rag \
    --cov-report=term-missing \
    --cov-report=html \
    --cov-report=xml \
    --cov-fail-under="${COVERAGE_FAIL_UNDER}"

  if [ -f "htmlcov/index.html" ]; then
    echo "✅ Coverage HTML raporu oluşturuldu: htmlcov/index.html"
    open_artifact "htmlcov/index.html"
  else
    echo "⚠️ Coverage raporu oluşturulamadı: htmlcov/index.html bulunamadı."
  fi
}

run_pytest_coverage_report

# Kritik yol performans baseline testleri (pytest-benchmark)
if [ "${TEST_SCOPE}" = "all" ] || [ "${TEST_SCOPE}" = "unit" ]; then
  python -m pytest -v tests/test_benchmark.py
fi

# Frontend React testleri ve coverage (web_ui_react varsa zorunlu quality gate)
if [ -d "web_ui_react" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "❌ web_ui_react dizini var ama npm bulunamadı — React testleri çalıştırılamıyor."
    exit 1
  fi

  echo "🚀 Frontend (React) Testleri Başlıyor..."
  pushd web_ui_react > /dev/null
  npm install
  npm run test:coverage
  for report in coverage/lcov-report/index.html coverage/index.html; do
    open_artifact "$PWD/$report"
  done
  popd > /dev/null
fi

echo "✅ Backend ve Frontend test akışı başarıyla tamamlandı!"
