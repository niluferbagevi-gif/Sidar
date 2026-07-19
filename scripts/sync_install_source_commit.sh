#!/usr/bin/env bash
set -Eeuo pipefail

# SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT'i, verilen (varsayılan: HEAD) commit'e
# ilerletir. Bu pin, raw tek dosya kurulumun (curl .../main/install_sidar.sh)
# scripts/install_modules/* dosyalarını hangi commit'ten indireceğini belirler;
# gömülü hash manifestiyle (bkz. scripts/sync_install_module_hashes.sh) senkron
# olmayan bir pin, kurulumun hash doğrulama adımında sert şekilde başarısız
# olmasına yol açar (bkz. scripts/tools/verify_install_source_commit_pin.py).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="install_sidar.sh"
COMMIT="${1:-$(git -C "$REPO_ROOT" rev-parse HEAD)}"

cd "$REPO_ROOT"

if ! [[ "$COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '❌  Geçersiz commit SHA: %s (40 haneli hex bekleniyor)\n' "$COMMIT" >&2
    exit 1
fi

current="$(sed -nE 's/^SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="([0-9a-fA-F]{40}|unknown)"$/\1/p' "$TARGET")"
if [[ "$current" == "$COMMIT" ]]; then
    printf '✅  %s zaten %s commit''ine pinli; değişiklik yok.\n' "$TARGET" "$COMMIT"
    exit 0
fi

sed -i.bak -E "s/^SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT=\"([0-9a-fA-F]{40}|unknown)\"\$/SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT=\"${COMMIT}\"/" "$TARGET"
rm -f "${TARGET}.bak"

printf '✏️   %s: SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT %s -> %s olarak güncellendi.\n' "$TARGET" "${current:-<yok>}" "$COMMIT"

if ! bash -n "$TARGET"; then
    printf '❌  %s syntax kontrolü başarısız oldu. Düzeltmeden push etmeyin.\n' "$TARGET" >&2
    exit 1
fi
printf '✅  bash -n %s syntax kontrolü temiz.\n' "$TARGET"

if ! uv run python scripts/tools/verify_install_source_commit_pin.py --target "$TARGET"; then
    printf '⚠️   Pin güncellendi ama doğrulama hâlâ drift gösteriyor. Hedef commit''in\n' >&2
    printf '    scripts/install_modules ağacının gömülü manifestle eşleştiğinden emin olun\n' >&2
    printf '    (genellikle bu değişikliği içeren merge commit''ini hedefleyin).\n' >&2
    exit 1
fi
printf '✅  Pin, gömülü modül hash manifestiyle uyumlu.\n'
