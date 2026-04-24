#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_SCRIPT="${ROOT_DIR}/install_sidar.sh"
MODULE_DIR="${ROOT_DIR}/scripts/install_modules"
OUTPUT_SCRIPT="${ROOT_DIR}/dist/install_sidar.sh"

mkdir -p "${ROOT_DIR}/dist"

if [[ ! -f "$SOURCE_SCRIPT" ]]; then
    echo "Kaynak betik bulunamadı: $SOURCE_SCRIPT" >&2
    exit 1
fi

if [[ ! -d "$MODULE_DIR" ]]; then
    echo "Modül dizini bulunamadı: $MODULE_DIR" >&2
    exit 1
fi

awk -v module_dir="$MODULE_DIR" '
BEGIN { in_block = 0 }
/^# BEGIN_BUNDLE_MODULES$/ {
    print "# BEGIN_BUNDLE_MODULES"
    print "# Bundled by scripts/tools/bundle_install_sidar.sh"
    while ((("find \"" module_dir "\" -maxdepth 1 -type f -name \"*.sh\" | sort") | getline f) > 0) {
        print ""
        print "# --- MODULE: " f " ---"
        while ((getline line < f) > 0) {
            print line
        }
        close(f)
    }
    close("find \"" module_dir "\" -maxdepth 1 -type f -name \"*.sh\" | sort")
    print "# END_BUNDLE_MODULES"
    in_block = 1
    next
}
/^# END_BUNDLE_MODULES$/ {
    in_block = 0
    next
}
in_block == 0 { print }
' "$SOURCE_SCRIPT" > "$OUTPUT_SCRIPT"

chmod +x "$OUTPUT_SCRIPT"
echo "Bundle oluşturuldu: $OUTPUT_SCRIPT"
