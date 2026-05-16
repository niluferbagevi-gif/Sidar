#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Sidar — env şablonları ↔ runtime kaynak parite kontrolü
#
# Not: Bu dosya doğrudan çalıştırılabilir olmalıdır; test_env_parity bunu doğrular.
#
# config.py ile agent/, core/, managers/ ve scripts/ altındaki Python kaynaklarında
# okunan env anahtarlarını tarar ve karşılığının .env şablonlarında tanımlı olup
# olmadığını doğrular. Minimal .env.example bilerek kısa tutulur.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

usage() {
  cat <<'USAGE'
Sidar env parity checker

Kullanım:
  ./scripts/check_env_parity.sh [--warn-only] [--ignore KEY] [--help]

Seçenekler:
  --warn-only       Eksik anahtarları uyarı olarak göster, exit 0 dön.
  --ignore KEY      Runtime/internal bir env anahtarını bu koşuda yoksay.
                    Birden fazla kez kullanılabilir.
  --ignore=KEY      --ignore KEY ile aynı.
  --help            Bu yardım metnini göster.
USAGE
}

WARN_ONLY=0
EXTRA_IGNORE_KEYS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --warn-only)
      WARN_ONLY=1
      shift
      ;;
    --ignore)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "HATA: --ignore için anahtar gerekli" >&2
        exit 1
      fi
      EXTRA_IGNORE_KEYS+=("$2")
      shift 2
      ;;
    --ignore=*)
      EXTRA_IGNORE_KEYS+=("${1#--ignore=}")
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

TEMPLATES=(
  "$PROJECT_ROOT/.env.example"
  "$PROJECT_ROOT/.env.advanced.example"
  "$PROJECT_ROOT/.sidar_keys.env.example"
)
SCAN_TARGETS=(
  "$PROJECT_ROOT/config.py"
  "$PROJECT_ROOT/agent"
  "$PROJECT_ROOT/core"
  "$PROJECT_ROOT/managers"
  "$PROJECT_ROOT/scripts"
)

for target in "${SCAN_TARGETS[@]}"; do
  if [[ ! -e "$target" ]]; then
    echo "HATA: tarama hedefi bulunamadı → $target" >&2
    exit 1
  fi
done

for template in "${TEMPLATES[@]}"; do
  if [[ ! -f "$template" ]]; then
    echo "HATA: env şablonu bulunamadı → $template" >&2
    exit 1
  fi
done

DEFAULT_IGNORE_KEYS=(
  # Runtime/test harness variables: kullanıcı şablonlarında belgelenmez.
  CONDA_PREFIX
  DOTENV_FILE
  PYTEST_CURRENT_TEST
  VIRTUAL_ENV

  # Internal compatibility/derived database overrides.
  DATABASE_URL
  POSTGRES_DSN_SCHEME
  SIDAR_CONTAINER_DATABASE_URL
  SIDAR_CONTAINER_POSTGRES_HOST

  # Explicit runtime override/safety valves, not .env template surface area.
  SIDAR_ALLOW_FULL_ACCESS
  WEB_FETCH_MAX_CHARS
)

PY_OUTPUT=$(
  cd "$PROJECT_ROOT"
  python - "${DEFAULT_IGNORE_KEYS[@]}" -- "${EXTRA_IGNORE_KEYS[@]}" <<'PY'
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

separator_index = sys.argv.index("--")
ignored = set(sys.argv[1:separator_index]) | set(sys.argv[separator_index + 1 :])

template_paths = [
    Path(".env.example"),
    Path(".env.advanced.example"),
    Path(".sidar_keys.env.example"),
]
scan_roots = [Path("config.py"), Path("agent"), Path("core"), Path("managers"), Path("scripts")]

ENV_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
TEMPLATE_KEY_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=")
SIDAR_HELPERS = {
    "get_sidar_env",
    "get_sidar_optional_env",
    "get_sidar_int_env",
    "get_sidar_bool_env",
    "get_sidar_list_env",
}
DIRECT_HELPERS = {
    "get_bool_env",
    "get_int_env",
    "get_float_env",
    "get_list_env",
    "get_deprecated_int_env",
    "_get_bool_env",
}
ALL_HELPERS = SIDAR_HELPERS | DIRECT_HELPERS

@dataclass(frozen=True)
class EnvRef:
    key: str
    candidates: tuple[str, ...]
    source: str
    lineno: int


def template_keys() -> set[str]:
    keys: set[str] = set()
    for path in template_paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = TEMPLATE_KEY_RE.match(line)
            if match:
                keys.add(match.group(1))
    return keys


def source_files() -> list[Path]:
    files: list[Path] = []
    for target in scan_roots:
        if target.is_file():
            files.append(target)
            continue
        files.extend(
            p
            for p in target.rglob("*.py")
            if p.is_file()
            and ".git" not in p.parts
            and ".venv" not in p.parts
            and "__pycache__" not in p.parts
        )
    return sorted(files)


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr == "getenv"
        ):
            return "os.getenv"
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def literal_env_key(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and ENV_KEY_RE.match(node.value)
    ):
        return node.value
    return None


def refs_for_file(path: Path) -> list[EnvRef]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    refs: list[EnvRef] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node.func)
        if name not in ALL_HELPERS and name != "os.getenv":
            continue
        if not node.args:
            continue
        key = literal_env_key(node.args[0])
        if key is None:
            continue
        if name in SIDAR_HELPERS:
            prefixed = key if key.startswith("SIDAR_") else f"SIDAR_{key}"
            candidates = (prefixed, key)
        elif name in DIRECT_HELPERS and not key.startswith("SIDAR_"):
            # Several config values read SIDAR_<KEY> with a legacy KEY fallback, e.g.
            # get_float_env("SIDAR_FOO", get_float_env("FOO", default)). Do not force
            # legacy fallback names into templates when the preferred SIDAR_ name is documented.
            candidates = (key, f"SIDAR_{key}")
        else:
            candidates = (key,)
        refs.append(
            EnvRef(key=key, candidates=candidates, source=str(path), lineno=node.lineno)
        )
    return refs


examples = template_keys()
refs = [ref for path in source_files() for ref in refs_for_file(path)]
unique_keys = {ref.key for ref in refs}
missing: dict[str, EnvRef] = {}
for ref in refs:
    if ref.key in ignored or any(candidate in ignored for candidate in ref.candidates):
        continue
    if not any(candidate in examples for candidate in ref.candidates):
        missing.setdefault(ref.key, ref)

print(f"STAT\tSCANNED_FILES\t{len(source_files())}")
print(f"STAT\tCONFIG_KEYS\t{len(unique_keys)}")
print(f"STAT\tEXAMPLE_KEYS\t{len(examples)}")
print(f"STAT\tIGNORED_KEYS\t{len(ignored)}")
for key in sorted(missing):
    ref = missing[key]
    candidates = ",".join(ref.candidates)
    print(f"MISSING\t{key}\t{ref.source}:{ref.lineno}\t{candidates}")
PY
)

_get_stat() {
  local name="$1"
  printf '%s\n' "$PY_OUTPUT" | awk -F '\t' -v name="$name" '$1 == "STAT" && $2 == name { print $3 }'
}

MISSING=()
while IFS=$'\t' read -r kind key source candidates; do
  [[ "$kind" == "MISSING" ]] || continue
  MISSING+=("$key|$source|$candidates")
done <<< "$PY_OUTPUT"

echo "=== Sidar Env Parite Kontrolü ==="
echo "taranan kaynak dosya : $(_get_stat SCANNED_FILES)"
echo "kaynaklarda env anahtarı: $(_get_stat CONFIG_KEYS)"
echo "env şablonları anahtarı: $(_get_stat EXAMPLE_KEYS)"
echo "yoksayılan anahtar    : $(_get_stat IGNORED_KEYS)"
echo ""

if [[ ${#MISSING[@]} -eq 0 ]]; then
  echo "✅  Parite tamam — tüm kaynak env anahtarları env şablonlarında mevcut veya yoksayıldı."
  exit 0
fi

echo "❌  Env şablonlarında eksik anahtarlar (${#MISSING[@]} adet):"
for item in "${MISSING[@]}"; do
  IFS='|' read -r key source candidates <<< "$item"
  echo "    - $key ($source; kabul edilen şablon anahtarları: $candidates)"
done
echo ""
echo "Düzeltmek için uygun şablona (.env.example, .env.advanced.example veya .sidar_keys.env.example) yukarıdaki anahtarları ekleyin ya da runtime-only anahtarları --ignore ile yoksayın."

if [[ "$WARN_ONLY" -eq 1 ]]; then
  echo "(--warn-only modu: hata olarak çıkılmıyor)"
  exit 0
fi

exit 1
