#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Sidar — Env template parity checker
#
# config.py + agent/ + core/ + managers/ + scripts/ altında kullanılan
# os.getenv(...), os.environ.get(...), environ.get(...) ve get_*_env(...)
# anahtarlarının sürüm kontrollü env şablonlarında tanımlı olduğunu doğrular.
#
# Çıkış kodları:
#   0 → Tüm anahtarlar eşleşiyor (parite tamam)
#   1 → Bir veya daha fazla anahtar eksik (CI'da hata)
#
# Kullanım:
#   ./scripts/check_env_parity.sh
#   ./scripts/check_env_parity.sh --warn-only
#   ./scripts/check_env_parity.sh --ignore PYTEST_CURRENT_TEST --ignore CI,GITHUB_ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

usage() {
  cat <<'EOF_USAGE'
Sidar env parity checker

Kullanım:
  ./scripts/check_env_parity.sh [--warn-only] [--ignore KEY[,KEY...]] [--help]

Seçenekler:
  --warn-only        Eksik anahtarları uyarı olarak göster, exit 0 dön.
  --ignore KEY      Runtime/CI tarafından üretilen anahtarı parite dışı bırak.
                    Virgülle ayrılmış liste veya tekrar eden --ignore kabul edilir.
  --help            Bu yardım metnini göster.

Varsayılan ignore listesi:
  PYTEST_CURRENT_TEST, VIRTUAL_ENV, CONDA_PREFIX, CI, GITHUB_ACTIONS, MODE_ENV
EOF_USAGE
}

WARN_ONLY=0
IGNORE_KEYS=(
  PYTEST_CURRENT_TEST
  VIRTUAL_ENV
  CONDA_PREFIX
  CI
  GITHUB_ACTIONS
  MODE_ENV
  SIDAR_ENV_PARITY_IGNORE
)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --warn-only)
      WARN_ONLY=1
      shift
      ;;
    --ignore)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "HATA: --ignore için KEY veya KEY,KEY listesi verilmelidir." >&2
        exit 1
      fi
      IFS=',' read -r -a _extra_ignores <<< "$2"
      IGNORE_KEYS+=("${_extra_ignores[@]}")
      shift 2
      ;;
    --ignore=*)
      _ignore_value="${1#--ignore=}"
      IFS=',' read -r -a _extra_ignores <<< "$_ignore_value"
      IGNORE_KEYS+=("${_extra_ignores[@]}")
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "HATA: bilinmeyen argüman → $1" >&2
      echo >&2
      usage >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

SCAN_PATHS=(
  "$PROJECT_ROOT/config.py"
  "$PROJECT_ROOT/agent"
  "$PROJECT_ROOT/core"
  "$PROJECT_ROOT/managers"
  "$PROJECT_ROOT/scripts"
)

ENV_TEMPLATES=(
  "$PROJECT_ROOT/.env.example"
  "$PROJECT_ROOT/.env.advanced.example"
  "$PROJECT_ROOT/.env.development.example"
  "$PROJECT_ROOT/.env.test.example"
)

for path in "${SCAN_PATHS[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "HATA: tarama hedefi bulunamadı → $path" >&2
    exit 1
  fi
done

for path in "${ENV_TEMPLATES[@]}"; do
  if [[ ! -f "$path" ]]; then
    echo "HATA: env şablonu bulunamadı → $path" >&2
    exit 1
  fi
done

SIDAR_ENV_PARITY_SCAN_PATHS="$(printf '%s\n' "${SCAN_PATHS[@]}")"
SIDAR_ENV_PARITY_TEMPLATES="$(printf '%s\n' "${ENV_TEMPLATES[@]}")"
SIDAR_ENV_PARITY_IGNORE="$(printf '%s\n' "${IGNORE_KEYS[@]}" | sed '/^$/d' | sort -u)"
export SIDAR_ENV_PARITY_PROJECT_ROOT="$PROJECT_ROOT"
export SIDAR_ENV_PARITY_SCAN_PATHS
export SIDAR_ENV_PARITY_TEMPLATES
export SIDAR_ENV_PARITY_IGNORE

python3 <<'PY_ENV_PARITY'
from __future__ import annotations

import os
import re
from pathlib import Path

project_root = Path(os.environ["SIDAR_ENV_PARITY_PROJECT_ROOT"])
scan_roots = [Path(item) for item in os.environ["SIDAR_ENV_PARITY_SCAN_PATHS"].splitlines() if item]
template_paths = [Path(item) for item in os.environ["SIDAR_ENV_PARITY_TEMPLATES"].splitlines() if item]
ignore_keys = {item.strip() for item in os.environ.get("SIDAR_ENV_PARITY_IGNORE", "").splitlines() if item.strip()}

KEY_RE = r"[A-Z_][A-Z0-9_]*"
ENV_PATTERNS = [
    re.compile(rf"os\.getenv\(\s*['\"]({KEY_RE})['\"]"),
    re.compile(rf"os\.environ\.get\(\s*['\"]({KEY_RE})['\"]"),
    re.compile(rf"(?<![A-Za-z0-9_])environ\.get\(\s*['\"]({KEY_RE})['\"]"),
]
HELPER_CALL_RE = re.compile(r"\bget_[A-Za-z0-9_]*env\(([^)]*)\)", re.DOTALL)
STRING_KEY_RE = re.compile(rf"['\"]({KEY_RE})['\"]")
TEMPLATE_KEY_RE = re.compile(rf"^({KEY_RE})=", re.MULTILINE)

EXCLUDED_SCAN_DIRS = {
    ".git",
    ".venv",
    ".venv-container",
    "__pycache__",
    "htmlcov",
    "node_modules",
    "dist",
    "build",
    "artifacts",
    "logs",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".db", ".sqlite3"}


def iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = set(path.relative_to(project_root).parts)
        if relative_parts & EXCLUDED_SCAN_DIRS:
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        yield path


def strip_comment_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)

code_keys: set[str] = set()
scanned_files: list[Path] = []
for root in scan_roots:
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        text = strip_comment_lines(text)
        before_count = len(code_keys)
        for pattern in ENV_PATTERNS:
            code_keys.update(pattern.findall(text))
        for call_args in HELPER_CALL_RE.findall(text):
            code_keys.update(STRING_KEY_RE.findall(call_args))
        if len(code_keys) != before_count:
            scanned_files.append(path)

template_keys: set[str] = set()
for path in template_paths:
    text = path.read_text(encoding="utf-8", errors="ignore")
    template_keys.update(TEMPLATE_KEY_RE.findall(text))

missing = sorted(code_keys - template_keys - ignore_keys)

print("=== Sidar Env Parite Kontrolü ===")
print("Tarama kapsamı:")
for root in scan_roots:
    print(f"  - {root.relative_to(project_root)}")
print("Env şablonları:")
for path in template_paths:
    print(f"  - {path.relative_to(project_root)}")
print(f"Koddan çıkarılan anahtar: {len(code_keys)}")
print(f"Şablonlardan çıkarılan anahtar: {len(template_keys)}")
print(f"Yoksayılan anahtar: {len(ignore_keys)}")
print("")

if not missing:
    print("✅  Parite tamam — tüm taranan env anahtarları şablonlarda mevcut veya ignore listesinde.")
    raise SystemExit(0)

print(f"❌  Env şablonlarında eksik anahtarlar ({len(missing)} adet):")
for key in missing:
    print(f"    - {key}")
print("")
print("Düzeltmek için anahtarı uygun env şablonuna ekleyin veya runtime-only ise --ignore KEY kullanın.")
raise SystemExit(1)
PY_ENV_PARITY
status=$?

if [[ "$status" -ne 0 && "$WARN_ONLY" -eq 1 ]]; then
  echo "(--warn-only modu: hata olarak çıkılmıyor)"
  exit 0
fi

exit "$status"
