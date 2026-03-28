#!/bin/bash
set -euo pipefail

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-100}"

# 1) Genel proje kapsam eşiği (quality gate)
python -m pytest -v --cov=. --cov-report=term-missing --cov-fail-under="${COVERAGE_FAIL_UNDER}"

# 2) Kritik çekirdek dosyalar için hedef kapsam
python -m pytest -v \
  --cov=managers.security \
  --cov=core.memory \
  --cov=core.rag \
  --cov-report=term-missing \
  --cov-fail-under="${COVERAGE_FAIL_UNDER}"

# 3) Kritik yol performans baseline testleri (pytest-benchmark)
python -m pytest -v tests/test_benchmark.py

# 4) Frontend React testleri ve coverage (opsiyonel — npm kuruluysa)
if [ -d "web_ui_react" ] && command -v npm >/dev/null 2>&1; then
  echo "🚀 Frontend (React) Testleri Başlıyor..."
  pushd web_ui_react > /dev/null
  if ! npm install; then
    echo "⚠️ npm install başarısız, React testleri atlanıyor."
    popd > /dev/null
  else
    npm run test:coverage
    popd > /dev/null
  fi
elif [ -d "web_ui_react" ]; then
  echo "⚠️ web_ui_react dizini var ama npm bulunamadı — React testleri atlanıyor."
fi

echo "✅ Tüm Backend ve Frontend testleri başarıyla tamamlandı!"