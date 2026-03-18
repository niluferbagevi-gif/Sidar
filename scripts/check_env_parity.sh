#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Sidar — .env.example ↔ config.py Parite Kontrolü
#
# config.py'deki tüm os.getenv(...) çağrılarını tarar ve karşılığının
# .env.example'da tanımlı olup olmadığını doğrular.
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

# ─── Argümanlar ───────────────────────────────────────────────────────────────
WARN_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --warn-only) WARN_ONLY=1 ;;
  esac
done

# ─── Proje kökünü bul ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONFIG_FILE="$PROJECT_ROOT/config.py"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "HATA: config.py bulunamadı → $CONFIG_FILE" >&2
  exit 1
fi

if [[ ! -f "$ENV_EXAMPLE" ]]; then
  echo "HATA: .env.example bulunamadı → $ENV_EXAMPLE" >&2
  exit 1
fi

# ─── config.py'den env anahtarlarını çıkar ────────────────────────────────────
# os.getenv("KEY") ve os.getenv("KEY", ...) kalıplarını yakala
# Ayrıca özel get_*_env("KEY") yardımcı fonksiyonlarını da yakala
CONFIG_KEYS=$(
  grep -oP '(?<=os\.getenv\()["\x27][A-Z_][A-Z0-9_]+["\x27]' "$CONFIG_FILE" \
    | tr -d "'\"" | sort -u
)

# ─── .env.example'daki anahtarları çıkar ─────────────────────────────────────
EXAMPLE_KEYS=$(
  grep -oP '^[A-Z_][A-Z0-9_]+(?==)' "$ENV_EXAMPLE" | sort -u
)

# ─── Karşılaştır ──────────────────────────────────────────────────────────────
MISSING=()
while IFS= read -r key; do
  [[ -z "$key" ]] && continue
  if ! echo "$EXAMPLE_KEYS" | grep -qx "$key"; then
    MISSING+=("$key")
  fi
done <<< "$CONFIG_KEYS"

# ─── Sonuç raporu ─────────────────────────────────────────────────────────────
echo "=== Sidar Env Parite Kontrolü ==="
echo "config.py tarandı  : $(echo "$CONFIG_KEYS" | wc -l | tr -d ' ') anahtar"
echo ".env.example tarandı: $(echo "$EXAMPLE_KEYS" | wc -l | tr -d ' ') anahtar"
echo ""

if [[ ${#MISSING[@]} -eq 0 ]]; then
  echo "✅  Parite tamam — tüm anahtarlar .env.example'da mevcut."
  exit 0
fi

echo "❌  .env.example'da eksik anahtarlar (${#MISSING[@]} adet):"
for key in "${MISSING[@]}"; do
  echo "    - $key"
done
echo ""
echo "Düzeltmek için .env.example dosyasına yukarıdaki anahtarları ekleyin."

if [[ "$WARN_ONLY" -eq 1 ]]; then
  echo "(--warn-only modu: hata olarak çıkılmıyor)"
  exit 0
fi

exit 1
