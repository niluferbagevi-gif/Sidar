#!/usr/bin/env bash
set -euo pipefail

root="${1:-.}"
format="${2:-markdown}"  # markdown | json

exts=(py js css html md)

list_files() {
  local ext="$1"
  if git -C "$root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$root" ls-files "*.${ext}"
  else
    find "$root" -type f -name "*.${ext}" -not -path "*/.git/*"
  fi
}

count_files() {
  local ext="$1"
  local count
  count=$(list_files "$ext" | sed '/^$/d' | wc -l | tr -d ' ')
  echo "$count"
}

count_lines() {
  local ext="$1"
  python - "$root" "$ext" <<'PY'
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
ext = sys.argv[2]
try:
    files = subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', f'*.{ext}'],
        text=True,
    ).splitlines()
except subprocess.CalledProcessError:
    files = [str(p.relative_to(root)) for p in root.rglob(f'*.{ext}') if '.git' not in p.parts]

total = 0
for rel in files:
    path = root / rel
    with path.open(encoding='utf-8') as fh:
        total += sum(1 for _ in fh)
print(total)
PY
}

if [[ "$format" == "json" ]]; then
  printf '{"root":"%s","generated_at":%s,"tracked":true,"metrics":{' "$root" "$(date +%s)"
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
echo "> Note: Git deposu içindeyse yalnızca takipli dosyalar ölçülür; aksi halde .git hariç tüm dosyalar sayılır."
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
