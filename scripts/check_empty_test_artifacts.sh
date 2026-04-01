#!/usr/bin/env bash
set -euo pipefail

echo "🔍 Boş test dosyaları (artifacts) kontrol ediliyor..."

search_dirs=("tests")
if [[ -d "web_ui_react/src" ]]; then
  search_dirs+=("web_ui_react/src")
fi

empty_files=$(find "${search_dirs[@]}" -type f -size 0 \
  ! -name "__init__.py" \
  ! -path "*/__pycache__/*" \
  \( -path "*/tests/*" -o -path "*/test/*" -o -name "*.test.*" -o -name "*.spec.*" -o -name "test_*.py" \) \
  -print)

if [[ -n "$empty_files" ]]; then
  echo "❌ Boş test dosyası/dosyaları bulundu. Lütfen bu dosyaları silin veya içlerini doldurun:"
  echo "$empty_files"
  exit 1
fi

echo "✅ Hatalı (boş) test dosyası bulunamadı."