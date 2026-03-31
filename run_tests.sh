#!/bin/bash
set -euo pipefail

echo "🚀 Sidar AI - Otomatik Kalite Güvence Testleri Başlıyor..."

# .coveragerc fail_under = 90 ve ci.yml --cov-fail-under=90 ile uyumlu varsayılan.
# Daha katı bir eşik için: COVERAGE_FAIL_UNDER=95 bash run_tests.sh
COVERAGE_FAIL_UNDER="${COVERAGE_FAIL_UNDER:-90}"
AUTO_OPEN_ARTIFACTS="${AUTO_OPEN_ARTIFACTS:-1}"

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

# ─── 1) Backend: Tüm testler — tek seferlik çalıştırma ───────────────────────
# pyproject.toml addopts'ta zaten şunlar var:
#   --cov=. --cov-report=term-missing --cov-report=html --cov-report=xml
# Buraya sadece --cov-fail-under ekliyoruz; testler iki kez koşmaz.
echo "📊 Backend testleri çalıştırılıyor (coverage fail-under=${COVERAGE_FAIL_UNDER}%)..."
pytest --cov-fail-under="${COVERAGE_FAIL_UNDER}"

# parallel=True (.coveragerc) ile .coverage.* dosyaları oluşur; birleştir.
if python -m coverage combine --quiet 2>/dev/null; then
  echo "ℹ️ Coverage dosyaları birleştirildi."
fi

if [ -f "htmlcov/index.html" ]; then
  echo "✅ Coverage HTML raporu oluşturuldu: htmlcov/index.html"
  open_artifact "htmlcov/index.html"
else
  echo "⚠️ Coverage raporu oluşturulamadı: htmlcov/index.html bulunamadı."
fi

# ─── 2) Benchmark testleri ────────────────────────────────────────────────────
# Adım 5 güvenliği: dosya silinmiş veya yeniden adlandırılmışsa süreci kırmaz.
if [ -f "tests/test_benchmark.py" ]; then
  echo "⏱️ Benchmark testleri çalıştırılıyor..."
  python -m pytest -v tests/test_benchmark.py \
    --benchmark-disable-gc \
    --benchmark-sort=mean \
    --no-cov
else
  echo "⚠️ tests/test_benchmark.py bulunamadı — benchmark adımı atlanıyor."
fi

# ─── 3) Frontend React testleri ──────────────────────────────────────────────
# web_ui_react dizini varsa Node.js quality gate zorunludur.
if [ -d "web_ui_react" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "❌ web_ui_react dizini var ama npm bulunamadı — React testleri çalıştırılamıyor."
    exit 1
  fi

  echo "🚀 Frontend (React) Testleri Başlıyor..."
  pushd web_ui_react > /dev/null
  # npm ci: package-lock.json'a göre deterministik kurulum (npm install'dan hızlı ve güvenli).
  npm ci
  npm run test:coverage
  for report in coverage/lcov-report/index.html coverage/index.html; do
    open_artifact "$PWD/$report"
  done
  popd > /dev/null
fi

echo "✅ Tüm Backend ve Frontend testleri başarıyla tamamlandı!"
