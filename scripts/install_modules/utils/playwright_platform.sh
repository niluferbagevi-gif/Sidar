#!/usr/bin/env bash
# Shared Playwright platform fallback helpers for Python and Node browser installs.

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

prepare_playwright_ubuntu_override_file() {
    local source_os_release="${1:-/etc/os-release}"
    local target_os_release="$2"

    if [[ -r "$source_os_release" ]]; then
        cp "$source_os_release" "$target_os_release"
    fi
    if [[ -s "$target_os_release" ]]; then
        if grep -q '^VERSION_ID=' "$target_os_release"; then
            sed -i.bak 's/^VERSION_ID=.*/VERSION_ID="24.04"/' "$target_os_release"
            rm -f "${target_os_release}.bak"
        else
            echo 'VERSION_ID="24.04"' >> "$target_os_release"
        fi
    else
        cat >"$target_os_release" <<'PLAYWRIGHT_OS_RELEASE_EOF'
ID=ubuntu
VERSION_ID="24.04"
PLAYWRIGHT_OS_RELEASE_EOF
    fi
}
