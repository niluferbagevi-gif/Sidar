#!/usr/bin/env bash
set -Eeuo pipefail

# install_sidar.sh downloads scripts/install_modules/* from a pinned commit
# (SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT) when the raw single-file installer
# runs before any local repo exists. That pin has to point at a commit whose
# scripts/install_modules tree matches the embedded hash manifest, or the raw
# installer fallback downloads stale files that fail their own hash check.
#
# Run this after committing a change under scripts/install_modules/ (and
# after scripts/sync_install_module_hashes.sh has already updated the
# embedded manifest in that same commit): it stamps the pin to the commit you
# just made, then verifies the result.
#
# Usage: scripts/sync_installer_source_commit_pin.sh [commit-sha]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="install_sidar.sh"

cd "$REPO_ROOT"

commit="${1:-$(git rev-parse HEAD)}"
if ! [[ "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    printf '❌  Geçersiz commit SHA: %s (40 karakter hex olmalı)\n' "$commit" >&2
    exit 1
fi

current="$(sed -nE 's/^SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT="([0-9a-f]{40})"$/\1/p' "$TARGET")"
if [[ "$current" == "$commit" ]]; then
    printf 'ℹ️   %s zaten %s commit'"'"'ine pinlenmiş; değişiklik yok.\n' "$TARGET" "$commit"
else
    sed -i.bak -E "s/^SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT=\"[0-9a-f]{40}\"$/SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT=\"${commit}\"/" "$TARGET"
    rm -f "${TARGET}.bak"
    printf '✏️   %s -> SIDAR_INSTALLER_EMBEDDED_SOURCE_COMMIT=%s olarak güncellendi.\n' "$TARGET" "$commit"
fi

uv run python scripts/tools/check_installer_source_commit_pin.py

printf '\nGözden geçirip commit edin:\n'
printf '    git add %s\n' "$TARGET"
printf '    git commit -m "Sync install_sidar.sh source commit pin"\n'
