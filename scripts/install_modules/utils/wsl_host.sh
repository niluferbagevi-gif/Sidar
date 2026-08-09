#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils/phase modules.
SIDAR_INSTALL_UTIL_WSL_HOST_SH_LOADED=1

# WSL/Windows host interop helpers live here so Linux/macOS-oriented installer
# phases do not need to carry cmd.exe/powershell.exe path discovery details.

is_windows_interop_binary_path() {
    local bin_path="${1:-}"
    [[ -z "$bin_path" ]] && return 1

    # WSL üzerinde Windows binary'leri genellikle /mnt/<drive>/... altında ve .exe uzantılıdır.
    [[ "$bin_path" == /mnt/[A-Za-z]/* ]] && return 0
    [[ "$bin_path" == *.exe ]] && return 0
    return 1
}

resolve_native_binary_path() {
    local cmd_name="${1:-}"
    local resolved_path=""
    [[ -n "$cmd_name" ]] || return 1

    resolved_path="$(type -P "$cmd_name" 2>/dev/null || true)"
    [[ -n "$resolved_path" ]] || return 1

    if is_windows_interop_binary_path "$resolved_path"; then
        return 1
    fi

    echo "$resolved_path"
}

has_native_binary() {
    local cmd_name="${1:-}"
    resolve_native_binary_path "$cmd_name" >/dev/null
}

windows_path_to_wsl_path() {
    local windows_path="${1:-}"
    if [[ "$windows_path" =~ ^[A-Za-z]:\\ ]]; then
        local drive_letter path_rest
        drive_letter=$(echo "$windows_path" | cut -d: -f1 | tr '[:upper:]' '[:lower:]')
        path_rest=$(echo "$windows_path" | cut -d: -f2- | sed 's#\\#/#g')
        echo "/mnt/${drive_letter}${path_rest}"
        return 0
    fi
    return 1
}

resolve_windows_userprofile_path() {
    local win_userprofile=""
    local resolved_wsl_path=""

    # Birincil yöntem: cmd.exe interop
    if command -v cmd.exe &>/dev/null; then
        win_userprofile=$(cmd.exe /d /c "echo %UserProfile%" 2>/dev/null | tr -d '\r' | tail -n1 || true)
        resolved_wsl_path="$(windows_path_to_wsl_path "$win_userprofile" || true)"
        if [[ -n "$resolved_wsl_path" ]]; then
            echo "$resolved_wsl_path"
            return 0
        fi
    fi

    # Fallback: powershell.exe interop (kurumsal cmd policy kısıtlarında işe yarayabilir)
    if command -v powershell.exe &>/dev/null; then
        # shellcheck disable=SC2016  # PowerShell değişkeni; Bash tarafından genişletilmemeli.
        win_userprofile=$(powershell.exe -NoProfile -Command '$env:UserProfile' 2>/dev/null | tr -d '\r' | tail -n1 || true)
        resolved_wsl_path="$(windows_path_to_wsl_path "$win_userprofile" || true)"
        if [[ -n "$resolved_wsl_path" ]]; then
            echo "$resolved_wsl_path"
            return 0
        fi
    fi

    # Son fallback: yaygın varsayım (C:\Users\<username>)
    if [[ -n "${USER:-}" && -d "/mnt/c/Users/${USER}" ]]; then
        echo "/mnt/c/Users/${USER}"
        return 0
    fi

    return 1
}

resolve_windows_localappdata_path() {
    local win_localappdata=""
    local resolved_wsl_path=""

    if command -v cmd.exe &>/dev/null; then
        win_localappdata=$(cmd.exe /d /c "echo %LocalAppData%" 2>/dev/null | tr -d '\r' | tail -n1 || true)
        resolved_wsl_path="$(windows_path_to_wsl_path "$win_localappdata" || true)"
        if [[ -n "$resolved_wsl_path" ]]; then
            echo "$resolved_wsl_path"
            return 0
        fi
    fi

    if command -v powershell.exe &>/dev/null; then
        # shellcheck disable=SC2016  # PowerShell değişkeni; Bash tarafından genişletilmemeli.
        win_localappdata=$(powershell.exe -NoProfile -Command '$env:LocalAppData' 2>/dev/null | tr -d '\r' | tail -n1 || true)
        resolved_wsl_path="$(windows_path_to_wsl_path "$win_localappdata" || true)"
        if [[ -n "$resolved_wsl_path" ]]; then
            echo "$resolved_wsl_path"
            return 0
        fi
    fi

    local userprofile_path=""
    userprofile_path="$(resolve_windows_userprofile_path 2>/dev/null || true)"
    if [[ -n "$userprofile_path" && -d "${userprofile_path}/AppData/Local" ]]; then
        echo "${userprofile_path}/AppData/Local"
        return 0
    fi

    return 1
}
