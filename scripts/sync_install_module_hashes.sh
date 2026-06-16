#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "$REPO_ROOT"

before_file="$(mktemp "${TMPDIR:-/tmp}/sidar_install_manifest_before.XXXXXX")"
cp install_sidar.sh "$before_file"

uv run python scripts/tools/update_install_module_hash_manifest.py --target install_sidar.sh

if diff -q "$before_file" install_sidar.sh >/dev/null; then
    echo "OK: install_sidar.sh gömülü modül manifesti zaten güncel."
else
    echo "Güncellendi: install_sidar.sh gömülü modül manifesti değişti."
    git diff -- install_sidar.sh || true
fi

rm -f "$before_file"
bash -n install_sidar.sh
echo "OK: install_sidar.sh söz dizimi geçerli."
