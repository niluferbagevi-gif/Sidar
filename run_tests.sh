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

# 4) Frontend React testleri ve coverage (web_ui_react varsa zorunlu quality gate)
if [ -d "web_ui_react" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "❌ web_ui_react dizini var ama npm bulunamadı — React testleri çalıştırılamıyor."
    exit 1
  fi

  echo "🚀 Frontend (React) Testleri Başlıyor..."
  pushd web_ui_react > /dev/null
  npm install
  npm run test:coverage
  popd > /dev/null
fi

echo "✅ Tüm Backend ve Frontend testleri başarıyla tamamlandı!"
