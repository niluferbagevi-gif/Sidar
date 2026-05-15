#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Sidar — env şablonları ↔ config.py Parite Kontrolü
#
# Not: Bu dosya doğrudan çalıştırılabilir olmalıdır; test_env_parity bunu doğrular.
#
# config.py'deki tüm os.getenv(...) çağrılarını tarar ve karşılığının
# .env.example, .env.advanced.example veya .sidar_keys.env.example içinde
# tanımlı olup olmadığını doğrular. Minimal .env.example bilerek kısa tutulur.
#
# Çıkış kodları:
#   0 → Tüm anahtarlar eşleşiyor (parite tamam)
#   1 → Bir veya daha fazla anahtar eksik (CI'da hata)
#
# Kullanım:
#   ./scripts/check_env_parity.sh                    # proje kökünden
#   ./scripts/check_env_parity.sh --warn-only        # eksikler uyarı olarak çıkar, exit 0
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

usage() {
  cat <<'EOF'
Sidar env parity checker

Kullanım:
  ./scripts/check_env_parity.sh [--warn-only] [--help]

Seçenekler:
  --warn-only  Eksik anahtarları uyarı olarak göster, exit 0 dön.
  --help       Bu yardım metnini göster.
EOF
}

# ─── Argümanlar ───────────────────────────────────────────────────────────────
WARN_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --warn-only)
      WARN_ONLY=1
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "HATA: bilinmeyen argüman → $arg" >&2
      echo >&2
      usage >&2
      exit 1
      ;;
  esac
done

# ─── Proje kökünü bul ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONFIG_FILE="$PROJECT_ROOT/config.py"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"
ADVANCED_ENV_EXAMPLE="$PROJECT_ROOT/.env.advanced.example"
KEYS_ENV_EXAMPLE="$PROJECT_ROOT/.sidar_keys.env.example"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "HATA: config.py bulunamadı → $CONFIG_FILE" >&2
  exit 1
fi

for template in "$ENV_EXAMPLE" "$ADVANCED_ENV_EXAMPLE" "$KEYS_ENV_EXAMPLE"; do
  if [[ ! -f "$template" ]]; then
    echo "HATA: env şablonu bulunamadı → $template" >&2
    exit 1
  fi
done

# ─── config.py'den env anahtarlarını çıkar ────────────────────────────────────
# os.getenv("KEY") ve os.getenv("KEY", ...) kalıplarını yakala
# Ayrıca özel get_*_env("KEY") yardımcı fonksiyonlarını da yakala
CONFIG_KEYS=$(
  grep -oP '(?<=os\.getenv\()["\x27][A-Z_][A-Z0-9_]+["\x27]' "$CONFIG_FILE" \
    | tr -d "'\"" | sort -u
)

# ─── Env şablonlarındaki anahtarları çıkar ───────────────────────────────────
EXAMPLE_KEYS=$(
  cat "$ENV_EXAMPLE" "$ADVANCED_ENV_EXAMPLE" "$KEYS_ENV_EXAMPLE" \
    | grep -oP '^[A-Z_][A-Z0-9_]+(?==)' \
    | sort -u
)

# ─── Karşılaştır ──────────────────────────────────────────────────────────────
# Bilerek şablonlara yazılmayan runtime/internal/legacy override anahtarları.
# Örn. DATABASE_URL ve SIDAR_CONTAINER_DATABASE_URL, POSTGRES_* köklerinden
# türetildiği için kullanıcıdan istenmez.
IGNORE_KEYS=(
  CONDA_PREFIX
  DATABASE_URL
  DOTENV_FILE
  POSTGRES_DSN_SCHEME
  PYTEST_CURRENT_TEST
  SIDAR_ALLOW_FULL_ACCESS
  SIDAR_CONTAINER_DATABASE_URL
  SIDAR_CONTAINER_POSTGRES_HOST
  VIRTUAL_ENV
  WEB_FETCH_MAX_CHARS
)

_is_ignored_key() {
  local needle="$1"
  local ignored
  for ignored in "${IGNORE_KEYS[@]}"; do
    [[ "$needle" == "$ignored" ]] && return 0
  done
  return 1
}

MISSING=()
while IFS= read -r key; do
  [[ -z "$key" ]] && continue
  if _is_ignored_key "$key"; then
    continue
  fi
  if ! echo "$EXAMPLE_KEYS" | grep -qx "$key"; then
    MISSING+=("$key")
  fi
done <<< "$CONFIG_KEYS"

# ─── Sonuç raporu ─────────────────────────────────────────────────────────────
echo "=== Sidar Env Parite Kontrolü ==="
echo "config.py tarandı  : $(echo "$CONFIG_KEYS" | wc -l | tr -d ' ') anahtar"
echo "env şablonları tarandı: $(echo "$EXAMPLE_KEYS" | wc -l | tr -d ' ') anahtar"
echo ""

if [[ ${#MISSING[@]} -eq 0 ]]; then
  echo "✅  Parite tamam — tüm anahtarlar env şablonlarında mevcut."
  exit 0
fi

echo "❌  Env şablonlarında eksik anahtarlar (${#MISSING[@]} adet):"
for key in "${MISSING[@]}"; do
  echo "    - $key"
done
echo ""
echo "Düzeltmek için uygun şablona (.env.example, .env.advanced.example veya .sidar_keys.env.example) yukarıdaki anahtarları ekleyin."

if [[ "$WARN_ONLY" -eq 1 ]]; then
  echo "(--warn-only modu: hata olarak çıkılmıyor)"
  exit 0
fi

exit 1