#!/usr/bin/env bash
set -euo pipefail

root="${1:-.}"
format="${2:-markdown}"  # markdown | json

exts=(py js css html md)

count_files() {
  local ext="$1"
  find "$root" -type f -name "*.${ext}" -not -path "*/.git/*" | wc -l | tr -d ' '
}

count_lines() {
  local ext="$1"
  local files
  files=$(find "$root" -type f -name "*.${ext}" -not -path "*/.git/*")
  if [[ -z "$files" ]]; then
    echo 0
    return
  fi
  # shellcheck disable=SC2086
  wc -l $files | tail -n 1 | awk '{print $1}'
}

if [[ "$format" == "json" ]]; then
  printf '{"root":"%s","generated_at":%s,"metrics":{' "$root" "$(date +%s)"
  first=1
  total_files=0
  total_lines=0
  for ext in "${exts[@]}"; do
    files=$(count_files "$ext")
    lines=$(count_lines "$ext")
    total_files=$((total_files + files))
    total_lines=$((total_lines + lines))
    if [[ $first -eq 0 ]]; then printf ','; fi
    first=0
    printf '"%s":{"files":%s,"lines":%s}' "$ext" "$files" "$lines"
  done
  printf '},"totals":{"files":%s,"lines":%s}}\n' "$total_files" "$total_lines"
  exit 0
fi

echo "# Audit Metrics"
echo
echo "| Uzantı | Dosya Sayısı | Satır Sayısı |"
echo "|---|---:|---:|"
total_files=0
total_lines=0
for ext in "${exts[@]}"; do
  files=$(count_files "$ext")
  lines=$(count_lines "$ext")
  total_files=$((total_files + files))
  total_lines=$((total_lines + lines))
  echo "| .$ext | $files | $lines |"
done
echo "| **Toplam** | **$total_files** | **$total_lines** |"