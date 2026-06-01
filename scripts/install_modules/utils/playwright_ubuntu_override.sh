#!/usr/bin/env bash

# Playwright upstream yeni Ubuntu sürümlerini tanımadan önce Chromium indirmesi
# başarısız olabilir. Yalnız Ubuntu 25+ hostlarda kararlı ubuntu24.04-x64 paketini
# seç; diğer distro ve mimarileri koşulsuz override etme.
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
    (( ubuntu_major >= 25 ))
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
    echo "${resolved_spec:-playwright>=1.60,<2.0}"
}

prepare_playwright_ubuntu_override_file() {
    local source_os_release="${1:-/etc/os-release}"
    local target_os_release="$2"
    local normalized_os_release=""

    if [[ -r "$source_os_release" ]]; then
        cp "$source_os_release" "$target_os_release"
    fi
    if [[ -s "$target_os_release" ]]; then
        if grep -q '^VERSION_ID=' "$target_os_release"; then
            normalized_os_release="$(mktemp)"
            awk 'BEGIN { replaced=0 }
                /^VERSION_ID=/ && !replaced { print "VERSION_ID=\"24.04\""; replaced=1; next }
                { print }
            ' "$target_os_release" > "$normalized_os_release"
            mv "$normalized_os_release" "$target_os_release"
        else
            echo 'VERSION_ID="24.04"' >> "$target_os_release"
        fi
    else
        cat > "$target_os_release" <<'OS_RELEASE_EOF'
ID=ubuntu
VERSION_ID="24.04"
OS_RELEASE_EOF
    fi
}

run_playwright_ubuntu_override_install() {
    local source_os_release="${1:-/etc/os-release}"
    local download_timeout_ms="${2:-120000}"
    local override_os_release=""
    local install_rc=0
    shift 2

    override_os_release="$(mktemp)"
    prepare_playwright_ubuntu_override_file "$source_os_release" "$override_os_release"
    env PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT="$download_timeout_ms" \
        PLAYWRIGHT_HOST_PLATFORM_OVERRIDE="ubuntu24.04-x64" \
        OS_RELEASE_PATH="$override_os_release" \
        "$@" || install_rc=$?
    rm -f "$override_os_release"
    return "$install_rc"
}

install_playwright_linux_dependencies_fallback() {
    local -a playwright_linux_dependencies=(
        libnss3
        libnspr4
        libatk1.0-0
        libatk-bridge2.0-0
        libcups2
        libdrm2
        libxkbcommon0
        libxcomposite1
        libxdamage1
        libxfixes3
        libxrandr2
        libgbm1
        libpango-1.0-0
        libcairo2
        libasound2t64
    )

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
