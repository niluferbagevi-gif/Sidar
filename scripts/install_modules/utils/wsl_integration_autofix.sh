#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_WSL_INTEGRATION_AUTOFIX_SH_LOADED=1

apply_wsl_integration_autofix() {
    local current_distro="${1:-}"
    local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"

    [[ "$WSL2" == true ]] || return 1
    command -v powershell.exe &>/dev/null || return 1
    [[ -n "$current_distro" ]] || return 1

    local script_dir script_path stderr_log windows_script_path
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    script_path="${script_dir}/wsl_integration_autofix.ps1"
    [[ -f "$script_path" ]] || return 1

    stderr_log="$(mktemp)"
    windows_script_path="$(wslpath -w "$script_path")"
    powershell.exe -NoProfile -ExecutionPolicy Bypass \
        -File "$windows_script_path" \
        -CurrentDistro "$current_distro" \
        2>"$stderr_log"
    local ps_exit=$?
    if [[ "$ps_exit" -ne 0 ]]; then
        if [[ "$ps_exit" -eq 2 ]]; then
            warn "PowerShell autofix backend kaydını doğrulayamadı (exit=2). Docker Desktop reset/reinstall gerekli olabilir."
            warn "Öneri: Docker Desktop > Settings > Troubleshoot > Reset to factory defaults"
        else
            warn "PowerShell WSL Integration autofix komutu başarısız oldu (exit=${ps_exit})."
        fi
        if [[ -s "$stderr_log" ]]; then
            warn "PowerShell stderr (son 20 satır):"
            while IFS= read -r _line; do
                warn "${_line}"
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
