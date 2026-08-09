#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="install_sidar.sh"
COMMIT_PIN=true

if [[ "${1:-}" == "--no-commit" ]]; then
    COMMIT_PIN=false
elif [[ -n "${1:-}" ]]; then
    printf 'Kullanım: %s [--no-commit]\n' "$0" >&2
    exit 2
fi

cd "$REPO_ROOT"

if ! git diff --quiet -- scripts/install_modules "$TARGET" \
    || ! git diff --cached --quiet -- scripts/install_modules "$TARGET"; then
    printf '❌ Önce installer modül/hash değişikliklerini commit edin; pin yalnız gerçek commit SHA üzerine damgalanabilir.\n' >&2
    exit 1
fi

uv run python scripts/tools/update_install_module_hash_manifest.py \
    --target "$TARGET" --check-manifest-only

# --check-pin only requires the pin to be internally consistent (the pinned
# commit's file contents must match the embedded hash manifest) — it does not
# require the pin to track current HEAD. If scripts/install_modules hasn't
# changed since the last pin, the existing pin already satisfies --check-pin,
# and re-stamping to a newer HEAD would only produce a no-op fixup commit.
if uv run python scripts/tools/update_install_module_hash_manifest.py \
    --target "$TARGET" --check-pin >/dev/null 2>&1; then
    printf '✅ Installer modül pini zaten geçerli (scripts/install_modules değişmedi); yeni damga gerekmiyor.\n'
    exit 0
fi

source_commit="$(git rev-parse HEAD)"
uv run python scripts/tools/update_install_module_hash_manifest.py \
    --target "$TARGET" --stamp-commit "$source_commit"
uv run python scripts/tools/update_install_module_hash_manifest.py \
    --target "$TARGET" --check-pin
bash -n "$TARGET"

if git diff --quiet -- "$TARGET"; then
    printf '✅ Installer modül pini zaten HEAD=%s ile uyumlu.\n' "$source_commit"
    exit 0
fi

printf '✅ Installer modül pini HEAD=%s commitine damgalandı ve doğrulandı.\n' "$source_commit"
if [[ "$COMMIT_PIN" == true ]]; then
    git add -- "$TARGET"
    git commit -m "Pin install_sidar.sh embedded module commit to ${source_commit}"
    printf '✅ Pin fixup commit oluşturuldu.\n'
else
    printf 'ℹ️  --no-commit seçildi; install_sidar.sh değişikliğini gözden geçirip commit edin.\n'
fi
