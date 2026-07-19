#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="install_sidar.sh"

cd "$REPO_ROOT"

uv run python scripts/tools/update_install_module_hash_manifest.py --target "$TARGET"

if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
    current_commit="$(git rev-parse HEAD)"
    uv run python scripts/tools/update_install_module_hash_manifest.py \
        --target "$TARGET" \
        --stamp-commit "$current_commit"
fi

# Wrapper sessiz çalışmasın: hangi satırlar değişti, hangi modül(ler) drift'ti
# bunu geliştiriciye göster ve install_sidar.sh hala syntax-clean mi doğrula.
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
    if git diff --quiet -- "$TARGET"; then
        printf '✅  %s gömülü modül manifesti zaten güncel; değişiklik yok.\n' "$TARGET"
    else
        printf '✏️   %s gömülü modül manifesti güncellendi. Drift satırları:\n' "$TARGET"
        git --no-pager diff --no-color -- "$TARGET" \
            | awk '/^[+-][0-9a-f]{64}  scripts\/install_modules\// { print "    " $0 }'
        printf '\nGözden geçirip commit edin:\n'
        printf '    git add %s\n' "$TARGET"
        printf '    git commit -m "Sync install_sidar.sh module hashes"\n'
    fi
else
    printf 'ℹ️   git deposu algılanmadı; diff özeti atlanıyor (manifest güncellendi).\n'
fi

# install_sidar.sh'ın hala syntax-temiz olduğundan emin ol; manifest yazarı
# heredoc içine kaymış hatalı bir bayt bıraksa burada erken yakalanır.
if ! bash -n "$TARGET"; then
    printf '❌  %s syntax kontrolü başarısız oldu. Düzeltmeden push etmeyin.\n' "$TARGET" >&2
    exit 1
fi
printf '✅  bash -n %s syntax kontrolü temiz.\n' "$TARGET"
