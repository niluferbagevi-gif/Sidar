#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_WSL_INTEGRATION_AUTOFIX_SH_LOADED=1

apply_wsl_integration_autofix() {
    local current_distro="${1:-}"
    local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"

    [[ "$WSL2" == true ]] || return 1
    command -v powershell.exe &>/dev/null || return 1
    [[ -n "$current_distro" ]] || return 1

    if ! powershell.exe -NoProfile -Command "\
        \$ErrorActionPreference='Stop'; \
        \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; \
        if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; \
        if (!(Test-Path \$p)) { throw 'Docker settings dosyası bulunamadı.' }; \
        Copy-Item \$p \"\$p.bak\" -Force; \
        if (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue) { \
            Start-Process 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe' -ArgumentList '--quit' -WindowStyle Hidden -ErrorAction SilentlyContinue; \
            \$stopped=\$false; \
            for (\$i=0; \$i -lt 10; \$i++) { \
                Start-Sleep -Seconds 1; \
                if (!(Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) { \$stopped=\$true; break }; \
            }; \
            if (-not \$stopped) { \
                Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force; \
                Start-Sleep -Seconds 3; \
            }; \
        }; \
        \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; \
        \$prop=\$cfg.PSObject.Properties | Where-Object { \$_.Name -ieq 'integratedWslDistros' } | Select-Object -First 1; \
        if (\$null -eq \$prop) { \
            \$cfg | Add-Member -NotePropertyName 'integratedWslDistros' -NotePropertyValue @() -Force; \
            \$propName='integratedWslDistros'; \
        } else { \
            \$propName=\$prop.Name; \
        }; \
        \$list=@(\$cfg.\$propName); \
        if (\$list -notcontains '$current_distro') { \$list += '$current_distro' }; \
        \$cfg.\$propName=\$list; \
        [System.IO.File]::WriteAllText(\$p, (\$cfg | ConvertTo-Json -Depth 100), (New-Object System.Text.UTF8Encoding \$false)); \
        Start-Process 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe' -WindowStyle Hidden; \
    " >/dev/null 2>&1; then
        return 1
    fi

    WSL_INTEGRATION_AUTOFIX_APPLIED=true
    export WSL_INTEGRATION_AUTOFIX_APPLIED
    : > "$integration_autofix_sentinel"

    return 0
}
