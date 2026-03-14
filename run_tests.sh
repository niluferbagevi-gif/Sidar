#!/bin/bash
# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

set -euo pipefail

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-95}"

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

echo "✅ Testler Tamamlandı!"