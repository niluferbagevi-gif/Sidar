#!/bin/bash
set -euo pipefail

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

# 1) Genel proje kapsam eşiği
python -m pytest -v --cov=. --cov-report=term-missing --cov-fail-under=70

# 2) Kritik çekirdek dosyalar için hedef kapsam
python -m pytest -v \
  --cov=managers.security \
  --cov=core.memory \
  --cov=core.rag \
  --cov-report=term-missing \
  --cov-fail-under=80

echo "✅ Testler Tamamlandı!"