#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_SCRIPT="${ROOT_DIR}/install_sidar.sh"
MODULE_DIR="${ROOT_DIR}/scripts/install_modules"
OUTPUT_SCRIPT="${ROOT_DIR}/dist/install_sidar.sh"

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

    helper = module_dir "/install_helpers.sh"
    if (system("test -f \"" helper "\"") == 0) {
        emit_module(helper)
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
