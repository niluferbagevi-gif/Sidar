#!/usr/bin/env bash

# Playwright upstream yeni Ubuntu sürümlerini tanımadan önce Chromium indirmesi
# başarısız olabilir. Ubuntu 25-30 aralığındaki hostlarda Playwright
# paketinin bildiği en yeni Ubuntu LTS fallback build'ini seç; diğer distro,
# mimari ve belirsiz gelecek sürümleri koşulsuz override etme.
is_playwright_ubuntu_override_recommended() {
    local os_release_file="${1:-/etc/os-release}"
    local distro_id=""
    local distro_like=""
    local version_id=""
    local key value

    [[ -r "$os_release_file" ]] || return 1
    while IFS='=' read -r key value; do
        value="${value%\"}"
        value="${value#\"}"
        case "$key" in
            ID) distro_id="$value" ;;
            ID_LIKE) distro_like="$value" ;;
            VERSION_ID) version_id="$value" ;;
        esac
    done < "$os_release_file"

    [[ " ${distro_id,,} ${distro_like,,} " == *"ubuntu"* ]] || return 1
    local ubuntu_major="${version_id%%.*}"
    [[ "$ubuntu_major" =~ ^[0-9]+$ ]] || return 1
    (( ubuntu_major >= 25 && ubuntu_major <= 30 ))
}

# Ubuntu 25+ için override yalnız upstream Playwright host matrisi henüz bu
# sürümü resmi olarak tanımıyorsa kullanılmalı. Python Playwright paketinin
# bundled Node runtime'ı aynı hostPlatform modülünü kullanır; böylece yeni
# Ubuntu desteği geldiğinde sabit ubuntu24.04 override otomatik devreden çıkar.
playwright_host_platform_is_officially_supported() {
    local source_os_release="${1:-/etc/os-release}"
    shift || true
    [[ "$#" -gt 0 ]] || return 1

    env -u PLAYWRIGHT_HOST_PLATFORM_OVERRIDE OS_RELEASE_PATH="$source_os_release" "$@" - <<'PY_PLAYWRIGHT_HOST_SUPPORT' >/dev/null 2>&1
from pathlib import Path
import json
import subprocess

import playwright


driver_dir = Path(playwright.__file__).resolve().parent / "driver"
node_bin = driver_dir / "node"
host_platform_module = driver_dir / "package" / "lib" / "server" / "utils" / "hostPlatform.js"
if not node_bin.is_file() or not host_platform_module.is_file():
    raise SystemExit(1)
probe = subprocess.run(
    [
        str(node_bin),
        "-e",
        f"const platform = require({json.dumps(str(host_platform_module))}); process.exit(platform.isOfficiallySupportedPlatform ? 0 : 1);",
    ],
    check=False,
)
raise SystemExit(probe.returncode)
PY_PLAYWRIGHT_HOST_SUPPORT
}

playwright_latest_supported_ubuntu_version() {
    local fallback_version="24.04"
    local probe_output=""
    shift || true

    if [[ "$#" -eq 0 ]]; then
        echo "$fallback_version"
        return 0
    fi

    probe_output="$(
        "$@" - <<'PY_PLAYWRIGHT_SUPPORTED_UBUNTU' 2>/dev/null
from pathlib import Path
import re

try:
    import playwright
except Exception:
    raise SystemExit(1)

host_platform_module = (
    Path(playwright.__file__).resolve().parent
    / "driver"
    / "package"
    / "lib"
    / "server"
    / "utils"
    / "hostPlatform.js"
)
try:
    source = host_platform_module.read_text(encoding="utf-8")
except OSError:
    raise SystemExit(1)

versions = sorted(
    set(re.findall(r"ubuntu(\d+\.\d+)-x64", source)),
    key=lambda value: tuple(map(int, value.split("."))),
)
if not versions:
    raise SystemExit(1)
print(versions[-1])
PY_PLAYWRIGHT_SUPPORTED_UBUNTU
    )" || probe_output=""

    if [[ "$probe_output" =~ ^[0-9]+\.[0-9]+$ ]]; then
        echo "$probe_output"
    else
        echo "$fallback_version"
    fi
}

playwright_ubuntu_override_platform() {
    local supported_version="${1:-24.04}"
    echo "ubuntu${supported_version}-x64"
}

resolve_playwright_python_spec() {
    local pyproject_file="${1:-${SCRIPT_DIR}/pyproject.toml}"
    local resolved_spec=""

    if [[ -r "$pyproject_file" ]]; then
        resolved_spec="$(awk '
            /^\[dependency-groups\]$/ { in_dependency_groups=1; next }
            in_dependency_groups && /^\[/ { exit }
            in_dependency_groups && /"playwright[<>=!~]/ {
                line=$0
                sub(/^[^"]*"/, "", line)
                sub(/".*$/, "", line)
                print line
                exit
            }
        ' "$pyproject_file")"
    fi
    echo "${resolved_spec:-playwright>=1.60,<1.62}"
}

prepare_playwright_ubuntu_override_file() {
    local source_os_release="${1:-/etc/os-release}"
    local target_os_release="$2"
    local supported_ubuntu_version="${3:-24.04}"
    local normalized_os_release=""

    if [[ -r "$source_os_release" ]]; then
        cp "$source_os_release" "$target_os_release"
    fi
    if [[ -s "$target_os_release" ]]; then
        if grep -q '^VERSION_ID=' "$target_os_release"; then
            normalized_os_release="$(mktemp)"
            awk -v supported_ubuntu_version="$supported_ubuntu_version" 'BEGIN { replaced=0 }
                /^VERSION_ID=/ && !replaced { print "VERSION_ID=\"" supported_ubuntu_version "\""; replaced=1; next }
                { print }
            ' "$target_os_release" > "$normalized_os_release"
            mv "$normalized_os_release" "$target_os_release"
        else
            echo "VERSION_ID=\"${supported_ubuntu_version}\"" >> "$target_os_release"
        fi
    else
        cat > "$target_os_release" <<OS_RELEASE_EOF
ID=ubuntu
VERSION_ID="${supported_ubuntu_version}"
OS_RELEASE_EOF
    fi
}

run_playwright_ubuntu_override_install() {
    local source_os_release="${1:-/etc/os-release}"
    local download_timeout_ms="${2:-120000}"
    local override_os_release=""
    local install_rc=0
    local supported_ubuntu_version=""
    local override_platform=""
    local -a python_probe_cmd=()
    local arg=""
    shift 2

    for arg in "$@"; do
        [[ "$arg" == "-m" ]] && break
        python_probe_cmd+=("$arg")
    done
    supported_ubuntu_version="$(playwright_latest_supported_ubuntu_version "$source_os_release" "${python_probe_cmd[@]:-$@}")"
    override_platform="$(playwright_ubuntu_override_platform "$supported_ubuntu_version")"
    override_os_release="$(mktemp)"
    prepare_playwright_ubuntu_override_file "$source_os_release" "$override_os_release" "$supported_ubuntu_version"
    env PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT="$download_timeout_ms" \
        PLAYWRIGHT_HOST_PLATFORM_OVERRIDE="$override_platform" \
        OS_RELEASE_PATH="$override_os_release" \
        "$@" || install_rc=$?
    rm -f "$override_os_release"
    return "$install_rc"
}

playwright_linux_dependencies_ready() {
    local package_name=""
    local ldconfig_cache=""

    if command -v apt >/dev/null 2>&1 || command -v apt-cache >/dev/null 2>&1 || command -v dpkg-query >/dev/null 2>&1; then
        for package_name in libnss3 libnspr4 libxshmfence1; do
            playwright_package_installed "$package_name" || return 1
        done
        for package_name in libgtk-3-0t64 libgtk-3-0; do
            playwright_package_installed "$package_name" && return 0
        done
        return 1
    fi

    if command -v ldconfig >/dev/null 2>&1; then
        ldconfig_cache="$(ldconfig -p 2>/dev/null || true)"
        [[ "$ldconfig_cache" == *"libnss3.so"* && "$ldconfig_cache" == *"libnspr4.so"* && "$ldconfig_cache" == *"libgtk-3.so"* && "$ldconfig_cache" == *"libXshmfence.so"* ]]
        return
    fi

    return 1
}

playwright_package_installed() {
    local package_name="$1"
    local package_status=""

    if command -v apt >/dev/null 2>&1; then
        if apt list --installed "$package_name" 2>/dev/null | awk -F/ 'NR > 1 {print $1}' | grep -Fxq "$package_name"; then
            return 0
        fi
    fi

    if command -v dpkg-query >/dev/null 2>&1; then
        package_status="$(dpkg-query -W -f='${db:Status-Abbrev}' "$package_name" 2>/dev/null || true)"
        [[ "$package_status" == ii* ]] && return 0
    fi

    return 1
}

playwright_ubuntu_dependency_packages() {
    local gtk_package="libgtk-3-0"
    # Ubuntu 24.04+ t64 geçişinde paket adı libgtk-3-0t64 oldu; Ubuntu
    # 26.04 (resolute) için de resmi Sidar fallback listesinde bu paket
    # tercih edilir. Eski Ubuntu sürümleri için libgtk-3-0 fallback kalır.
    if command -v apt-cache >/dev/null 2>&1 && apt-cache show libgtk-3-0t64 >/dev/null 2>&1; then
        gtk_package="libgtk-3-0t64"
    fi
    printf '%s\n' \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libxshmfence1 \
        libgbm1 \
        "$gtk_package" \
        libpango-1.0-0 \
        libcairo2 \
        libasound2t64
}

playwright_missing_ubuntu_dependencies() {
    local package_name=""
    local -a missing_packages=()

    while IFS= read -r package_name; do
        [[ -n "$package_name" ]] || continue
        playwright_package_installed "$package_name" || missing_packages+=("$package_name")
    done < <(playwright_ubuntu_dependency_packages)

    printf '%s\n' "${missing_packages[@]}"
}

install_playwright_linux_dependencies_fallback() {
    local -a playwright_linux_dependencies=()
    mapfile -t playwright_linux_dependencies < <(playwright_ubuntu_dependency_packages)

    if ! command -v apt-get >/dev/null 2>&1; then
        warn "Playwright Chromium sistem bağımlılıkları otomatik kurulamadı: apt-get bulunamadı."
        return 1
    fi
    if ! command -v sudo >/dev/null 2>&1; then
        warn "Playwright Chromium sistem bağımlılıkları otomatik kurulamadı: sudo bulunamadı."
        return 1
    fi

    sudo DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y \
        "${playwright_linux_dependencies[@]}"
}
