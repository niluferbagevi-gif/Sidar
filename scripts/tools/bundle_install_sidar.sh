#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_SCRIPT="${ROOT_DIR}/install_sidar.sh"
MODULE_DIR="${ROOT_DIR}/scripts/install_modules"
OUTPUT_SCRIPT="${ROOT_DIR}/dist/install_sidar.sh"
OUTPUT_HASHES="${ROOT_DIR}/dist/MODULE_HASHES.txt"
OUTPUT_USAGE="${ROOT_DIR}/dist/INSTALLER_USAGE.md"
RELEASE_INSTALLER_URL="${SIDAR_RELEASE_INSTALLER_URL:-https://github.com/niluferbagevi-gif/Sidar/releases/latest/download/install_sidar.sh}"
RAW_INSTALLER_URL="${SIDAR_RAW_INSTALLER_URL:-https://raw.githubusercontent.com/niluferbagevi-gif/Sidar/main/install_sidar.sh}"

mkdir -p "${ROOT_DIR}/dist"

SIDAR_VERSION="$(uv run python -c 'from sidar_version import get_sidar_version; print(get_sidar_version())' 2>/dev/null || echo 'unknown')"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ ! -f "$SOURCE_SCRIPT" ]]; then
    echo "Kaynak betik bulunamadı: $SOURCE_SCRIPT" >&2
    exit 1
fi

if [[ ! -d "$MODULE_DIR" ]]; then
    echo "Modül dizini bulunamadı: $MODULE_DIR" >&2
    exit 1
fi

# Pre-bundle drift kontrolü: install_sidar.sh içindeki gömülü modül hash manifesti ile
# .sidar_manifest.txt / install_sidar.sh çekirdek heredoc'u, repo'daki gerçek dosyalarla
# uyumlu olmalı. Aksi halde GitHub raw üzerinden indirilen install_sidar.sh ile bundle
# arasında drift oluşur ve kullanıcı kurulumda hash hatası alır.
if ! uv run python "${ROOT_DIR}/scripts/tools/update_install_module_hash_manifest.py" \
        --target install_sidar.sh --check; then
    cat >&2 <<'DRIFT_EOF'
Bundle iptal edildi: install_sidar.sh içindeki gömülü modül hash manifesti
scripts/install_modules altındaki gerçek dosyalarla uyumsuz.
Bundle üretmeden önce şunu çalıştırın:
    scripts/sync_install_module_hashes.sh
DRIFT_EOF
    exit 1
fi

if ! uv run python "${ROOT_DIR}/scripts/tools/update_core_install_manifest.py" --check; then
    cat >&2 <<'CORE_DRIFT_EOF'
Bundle iptal edildi: çekirdek install manifesti (.sidar_manifest.txt ve install_sidar.sh
heredoc'u) core/memory.py veya core/multimodal.py ile uyumsuz.
Düzeltmek için: scripts/sync_install_manifest.sh
CORE_DRIFT_EOF
    exit 1
fi

{
    printf '#!/usr/bin/env bash\n# Sidar bundled installer\n# version: %s\n# bundled: %s\n# source: scripts/tools/bundle_install_sidar.sh\n\n' "$SIDAR_VERSION" "$BUILD_DATE"
    awk -v module_dir="$MODULE_DIR" '
function emit_module(file, line) {
    print ""
    print "# --- MODULE: " file " ---"
    while ((getline line < file) > 0) {
        print line
    }
    close(file)
}
BEGIN { in_block = 0 }
NR == 1 && /^#!/ { next }
/^# BEGIN_BUNDLE_MODULES$/ {
    print "# BEGIN_BUNDLE_MODULES"
    print "# Bundled by scripts/tools/bundle_install_sidar.sh"
    print "SIDAR_BUNDLE_MODE=1"
    print "export SIDAR_INSTALLER_BOOTSTRAP_MODE=\"${SIDAR_INSTALLER_BOOTSTRAP_MODE:-bundle}\""
    print "export SIDAR_INSTALL_MODULES_DOWNLOADED_COUNT=\"${SIDAR_INSTALL_MODULES_DOWNLOADED_COUNT:-0}\""
    print "export SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS=\"${SIDAR_INSTALL_MODULE_DOWNLOAD_ATTEMPTS:-0}\""
    print "export SIDAR_INSTALL_MODULE_HTTP_429_RETRIES=\"${SIDAR_INSTALL_MODULE_HTTP_429_RETRIES:-0}\""
    print "export SIDAR_INSTALL_MODULE_CACHE_HITS=\"${SIDAR_INSTALL_MODULE_CACHE_HITS:-0}\""

    helper = module_dir "/install_helpers.sh"
    if (system("test -f \"" helper "\"") == 0) {
        emit_module(helper)
    }

    cli = module_dir "/install_cli.sh"
    if (system("test -f \"" cli "\"") == 0) {
        emit_module(cli)
    }

    dispatcher = module_dir "/install_dispatcher.sh"
    if (system("test -f \"" dispatcher "\"") == 0) {
        emit_module(dispatcher)
    }

    while ((("find \"" module_dir "/utils\" -type f -name \"*.sh\" 2>/dev/null | sort") | getline f) > 0) {
        emit_module(f)
    }
    close("find \"" module_dir "/utils\" -type f -name \"*.sh\" 2>/dev/null | sort")

    while ((("find \"" module_dir "/phases\" -type f -name \"*.sh\" 2>/dev/null | sort") | getline f) > 0) {
        emit_module(f)
    }
    close("find \"" module_dir "/phases\" -type f -name \"*.sh\" 2>/dev/null | sort")

    print "# END_BUNDLE_MODULES"
    in_block = 1
    next
}
/^# END_BUNDLE_MODULES$/ {
    in_block = 0
    next
}
in_block == 0 { print }
' "$SOURCE_SCRIPT"
} > "$OUTPUT_SCRIPT"

chmod +x "$OUTPUT_SCRIPT"
echo "Bundle oluşturuldu: $OUTPUT_SCRIPT"

{
    echo "# Sidar installer module hashes"
    echo "# version: ${SIDAR_VERSION}"
    echo "# bundled: ${BUILD_DATE}"
    (
        cd "$ROOT_DIR"
        find scripts/install_modules -type f \( -name "*.sh" -o -name "*.ps1" \) | sort
    ) | while IFS= read -r module_path; do
        if command -v sha256sum >/dev/null 2>&1; then
            sha="$(sha256sum "${ROOT_DIR}/${module_path}" | awk '{print $1}')"
        else
            sha="$(shasum -a 256 "${ROOT_DIR}/${module_path}" | awk '{print $1}')"
        fi
        # sha256sum -c uyumluluğu için iki boşluk (gömülü manifest formatıyla aynı).
        printf '%s  %s\n' "$sha" "$module_path"
    done
} > "$OUTPUT_HASHES"

chmod +x "$OUTPUT_SCRIPT"

echo "Modül hash manifesti ayrıca yazıldı: $OUTPUT_HASHES"

cat > "$OUTPUT_USAGE" <<USAGE_EOF
# Sidar bundled installer usage

This release artifact is the preferred clean-install entry point for normal
online users and constrained networks because it is a single bundled
\`install_sidar.sh\` file. It avoids the bootstrap path that downloads each
\`scripts/install_modules/*\` file separately from GitHub raw URLs.

## Preferred release/bundle install

\`\`\`bash
curl -fsSL ${RELEASE_INSTALLER_URL} -o install_sidar.sh
# or: wget -O install_sidar.sh ${RELEASE_INSTALLER_URL}
chmod +x install_sidar.sh
./install_sidar.sh
\`\`\`

## Development checkout install

\`\`\`bash
git clone https://github.com/niluferbagevi-gif/Sidar.git
cd Sidar
uv sync --all-extras
./install_sidar.sh
\`\`\`

## Last-resort raw fallback

Use the raw \`main/install_sidar.sh\` URL only when a release bundle is not yet
available for the target ref. The raw path may need to download many module
files during bootstrap and can therefore be more exposed to transient GitHub raw
429/5xx throttling:

\`\`\`bash
curl -fsSL ${RAW_INSTALLER_URL} -o install_sidar.sh
# or: wget -O install_sidar.sh ${RAW_INSTALLER_URL}
chmod +x install_sidar.sh
./install_sidar.sh
\`\`\`
USAGE_EOF

echo "Installer kullanım rehberi yazıldı: $OUTPUT_USAGE"

# Post-bundle integrity: dist/MODULE_HASHES.txt'in kaynak install_sidar.sh'nin
# EMBEDDED_MODULE_HASHES_MANIFEST bloğuyla birebir aynı olmasını doğrula. Bundle
# sırasında ham modül blokları inline edildiği için bu, GitHub raw'dan indirilecek
# root install_sidar.sh ile release artefaktı arasında çelişki olmadığını garanti eder.
embedded_hashes="$(awk '
    /^SIDAR_MODULE_HASHES_EOF$/ { in_block = 0 }
    in_block { print }
    /<<.SIDAR_MODULE_HASHES_EOF./ { in_block = 1 }
' "$SOURCE_SCRIPT")"

manifest_hashes="$(grep -v '^#' "$OUTPUT_HASHES" | grep -v '^[[:space:]]*$')"

if [[ "$embedded_hashes" != "$manifest_hashes" ]]; then
    echo "Bundle integrity hatası: install_sidar.sh gömülü manifesti dist/MODULE_HASHES.txt ile uyumsuz." >&2
    diff -u <(printf '%s\n' "$embedded_hashes") <(printf '%s\n' "$manifest_hashes") >&2 || true
    exit 1
fi

echo "Bundle integrity doğrulandı: install_sidar.sh gömülü manifest == dist/MODULE_HASHES.txt"
cat <<GUIDANCE_EOF
Önerilen kullanıcı indirme yöntemi:
  curl -fsSL ${RELEASE_INSTALLER_URL} -o install_sidar.sh
  chmod +x install_sidar.sh
  ./install_sidar.sh

Not: raw main/install_sidar.sh yalnız release bundle mevcut değilse son çare
fallback olarak kullanılmalıdır; bundle bootstrap sırasında çoklu raw modül
isteklerini ortadan kaldırır.
GUIDANCE_EOF
