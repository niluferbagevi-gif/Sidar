#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_WSL_INTEGRATION_AUTOFIX_SH_LOADED=1

apply_wsl_integration_autofix() {
    local current_distro="${1:-}"
    local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"

    [[ "$WSL2" == true ]] || return 1
    command -v powershell.exe &>/dev/null || return 1
    [[ -n "$current_distro" ]] || return 1

    local script_dir script_path stderr_log
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    script_path="${script_dir}/wsl_integration_autofix.ps1"
    [[ -f "$script_path" ]] || return 1

    stderr_log="$(mktemp)"
    if ! powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$script_path")" -CurrentDistro "$current_distro" 2>"$stderr_log"; then
        warn "PowerShell WSL Integration autofix komutu başarısız oldu."
        if [[ -s "$stderr_log" ]]; then
            warn "PowerShell stderr (son 20 satır):"
            while IFS= read -r _line; do
                warn "$_line"
            done < <(tail -n 20 "$stderr_log")
        fi
        rm -f "$stderr_log"
        return 1
    fi
    rm -f "$stderr_log"

    WSL_INTEGRATION_AUTOFIX_APPLIED=true
    export WSL_INTEGRATION_AUTOFIX_APPLIED
    : > "$integration_autofix_sentinel"

    return 0
}
