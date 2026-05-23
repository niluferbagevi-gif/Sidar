#!/usr/bin/env bash

verify_wsl_integration_listed() {
    [[ "$WSL2" == true ]] || return 0
    command -v powershell.exe &>/dev/null || return 0

    local current_distro="" default_distro="" enable_default="" integrated_csv="" integrated_norm=""
    local wsl_distros="" backend_registered=false
    local in_integrated=false default_covers=false
    local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"
    local docker_socket_ready=false
    if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null || docker info &>/dev/null; then
        docker_socket_ready=true
    fi

    current_distro="${WSL_DISTRO_NAME:-}"
    if [[ -z "$current_distro" ]]; then
        current_distro="$(powershell.exe -NoProfile -Command "wsl.exe -l -q | Select-Object -First 1" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}')"
    fi
    [[ -n "$current_distro" ]] || return 0

    default_distro="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; wsl.exe --status | Select-String 'Default Distribution' | ForEach-Object { (\$_.ToString() -split ':',2)[1].Trim() }" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}')"
    if [[ -z "$default_distro" ]]; then
        default_distro="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; wsl.exe -l -v | Select-String '\\*' | ForEach-Object { (\$_.ToString() -replace '\\*','').Trim() } | Select-Object -First 1" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}')"
    fi
    wsl_distros="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; wsl.exe -l -q" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r')"
    if printf '%s\n' "$wsl_distros" | awk 'NF {print}' | grep -Eq '^docker-desktop(-data)?$'; then
        backend_registered=true
    fi
    enable_default="$(wsl_powershell_read "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; if (\$null -eq \$cfg.EnableIntegrationWithDefaultWslDistro) { '' } else { [string]\$cfg.EnableIntegrationWithDefaultWslDistro } }")"
    integrated_csv="$(wsl_powershell_read "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; \$list=\$null; if (\$cfg.IntegratedWslDistros) { \$list=@(\$cfg.IntegratedWslDistros) } elseif (\$cfg.integratedWslDistros) { \$list=@(\$cfg.integratedWslDistros) } elseif (\$null -ne \$cfg.wsl -and \$null -ne \$cfg.wsl.distros) { if (\$cfg.wsl.distros -is [System.Array]) { \$list=@(\$cfg.wsl.distros) } else { \$list=@(\$cfg.wsl.distros.PSObject.Properties | Where-Object { \$_.Value -eq \$true } | Select-Object -ExpandProperty Name) } } elseif (\$null -ne \$cfg.integration -and \$null -ne \$cfg.integration.wslDistros) { if (\$cfg.integration.wslDistros -is [System.Array]) { \$list=@(\$cfg.integration.wslDistros) } else { \$list=@(\$cfg.integration.wslDistros.PSObject.Properties | Where-Object { \$_.Value -eq \$true } | Select-Object -ExpandProperty Name) } } elseif (\$null -ne \$cfg.wslIntegration -and \$null -ne \$cfg.wslIntegration.distros) { if (\$cfg.wslIntegration.distros -is [System.Array]) { \$list=@(\$cfg.wslIntegration.distros) } else { \$list=@(\$cfg.wslIntegration.distros.PSObject.Properties | Where-Object { \$_.Value -eq \$true } | Select-Object -ExpandProperty Name) } } elseif (\$null -ne \$cfg.wslEngine -and \$null -ne \$cfg.wslEngine.integratedDistros) { if (\$cfg.wslEngine.integratedDistros -is [System.Array]) { \$list=@(\$cfg.wslEngine.integratedDistros) } else { \$list=@(\$cfg.wslEngine.integratedDistros.PSObject.Properties | Where-Object { \$_.Value -eq \$true } | Select-Object -ExpandProperty Name) } } elseif (\$cfg.enabledIntegrations) { if (\$cfg.enabledIntegrations -is [System.Array]) { \$list=@(\$cfg.enabledIntegrations) } else { \$list=@(\$cfg.enabledIntegrations.PSObject.Properties | Where-Object { \$_.Value -eq \$true } | Select-Object -ExpandProperty Name) } }; if (\$list) { \$list | ForEach-Object { [string]\$_ } | Where-Object { \$_ } | Select-Object -Unique | Join-String -Separator ',' } }")"

    if [[ "$backend_registered" != true ]]; then
        fail "Docker Desktop backend distro (docker-desktop / docker-desktop-data) WSL2'de kayıtlı değil."
        warn "WSL Integration toggle açmak yeterli olmayabilir; backend dağıtımı manuel silinmiş olabilir."
        warn "Çözüm: Docker Desktop > Settings > Troubleshoot > Reset to factory defaults"
        warn "veya Docker Desktop'ı yeniden kurun. Sonra bu betiği tekrar çalıştırın."
        return 1
    fi

    integrated_norm=",${integrated_csv// /},"
    [[ "$integrated_norm" == *",$current_distro,"* ]] && in_integrated=true
    if [[ "${enable_default,,}" == "true" && -n "$default_distro" && "$default_distro" == "$current_distro" ]]; then
        default_covers=true
    fi

    if [[ "$in_integrated" == true ]]; then
        ok "WSL entegrasyonu '${current_distro}' için açık."
        return 0
    fi
    if [[ "$default_covers" == true ]]; then
        if [[ "${WSL_INTEGRATION_HARDEN_EXPLICIT:-true}" == "true" ]]; then
            export WSL_INTEGRATION_AUTOFIX_ELIGIBLE=true
            info "Default-distro toggle '${current_distro}' kapsıyor; explicit toggle eklenmesi için postcheck'e devredildi."
            return 1
        fi
        info "Docker Desktop default-distro toggle'u '${current_distro}' dağıtımını kapsıyor."
        warn "Öneri: WSL Integration listesinden '${current_distro}' için explicit toggle'ı da açın."
        return 0
    fi
    if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "$integration_autofix_sentinel" ]]; then
        if [[ "$docker_socket_ready" == true ]]; then
            ok "WSL Integration runtime doğrulandı: daemon socket erişilebilir (UI listesi '${current_distro}' için gecikmeli olabilir)."
            return 0
        fi
        warn "Docker Desktop WSL Integration hâlâ '${current_distro}' için kapalı görünüyor; daha önce bu oturumda otomatik düzeltme uygulandı, Docker Desktop senkronizasyonu bekleniyor."
        return 0
    fi
    if [[ "$docker_socket_ready" == true ]]; then
        info "Docker daemon socket erişilebilir; '${current_distro}' için WSL Integration UI listesi ile runtime durum farklı olabilir."
        return 0
    fi
    warn "Docker Desktop WSL Integration listesinde '${current_distro}' kapalı görünüyor."
    return 1
}

ensure_docker_daemon_running() {
    _docker_ready_with_socket() {
        if ! docker info &>/dev/null; then
            return 1
        fi

        if [[ "$WSL2" == true ]]; then
            DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Os}}' &>/dev/null || return 1
        else
            docker version --format '{{.Server.Os}}' &>/dev/null || return 1
        fi

        return 0
    }

    _detect_current_wsl_distro_name() {
        if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
            printf '%s\n' "$WSL_DISTRO_NAME"
            return 0
        fi
        if command -v powershell.exe &>/dev/null; then
            powershell.exe -NoProfile -Command "wsl.exe -l -q | Select-Object -First 1" 2>/dev/null \
                | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}'
            return 0
        fi
        printf '%s\n' ""
    }


    _wsl_integration_distro_listed() {
        local distro_name="$1"
        [[ "$WSL2" == true ]] || return 1
        command -v powershell.exe &>/dev/null || return 1
        [[ -n "$distro_name" ]] || return 1

        local integrated_csv integrated_norm
        integrated_csv="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; \$prop=\$cfg.PSObject.Properties | Where-Object { \$_.Name -ieq 'integratedWslDistros' } | Select-Object -First 1; if (\$null -ne \$prop -and \$null -ne \$cfg.(\$prop.Name)) { @(\$cfg.(\$prop.Name)) -join ',' } }" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | tail -n1)"
        integrated_norm=",${integrated_csv// /},"
        [[ "$integrated_norm" == *",$distro_name,"* ]]
    }

    _wsl_backend_docker_desktop_registered() {
        [[ "$WSL2" == true ]] || return 0
        command -v powershell.exe &>/dev/null || return 0

        local wsl_distros
        wsl_distros="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; wsl.exe -l -q" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r')"
        printf '%s\n' "$wsl_distros" | awk 'NF {print}' | grep -Fxq "docker-desktop"
    }

    _wait_for_docker_socket_mount_after_autofix() {
        local mount_wait_timeout="${WSL_INTEGRATION_SOCKET_WAIT_TIMEOUT:-30}"
        if ! [[ "$mount_wait_timeout" =~ ^[0-9]+$ ]] || (( mount_wait_timeout < 10 )); then
            mount_wait_timeout=30
        fi

        local elapsed=0
        while (( elapsed < mount_wait_timeout )); do
            if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null; then
                ok "Docker socket mount doğrulandı (autofix sonrası)."
                return 0
            fi
            sleep 2
            ((elapsed += 2))
        done
        return 1
    }

    _docker_wsl_integration_postcheck() {
        [[ "$WSL2" == true ]] || return 0
        command -v powershell.exe &>/dev/null || return 0

        local current_distro="" default_distro="" enable_default="" integrated_csv="" integrated_norm=""
        local in_integrated=false default_covers=false
        local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"

        current_distro="$(_detect_current_wsl_distro_name)"
        [[ -n "$current_distro" ]] || return 0

        default_distro="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; wsl.exe -l -q | Select-Object -First 1" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}')"
        enable_default="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; if (\$null -eq \$cfg.EnableIntegrationWithDefaultWslDistro) { '' } else { [string]\$cfg.EnableIntegrationWithDefaultWslDistro } }" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | tail -n1)"
        integrated_csv="$(powershell.exe -NoProfile -Command "[Console]::OutputEncoding=[Text.Encoding]::UTF8; \$p=Join-Path \$env:APPDATA 'Docker\\settings-store.json'; if (!(Test-Path \$p)) { \$p=Join-Path \$env:APPDATA 'Docker\\settings.json' }; if (Test-Path \$p) { \$cfg=Get-Content \$p -Raw | ConvertFrom-Json; \$found=\$false; \$keys=@('integratedWslDistros','IntegratedWslDistros','enabledWslIntegrations'); foreach (\$k in \$keys) { \$prop=\$cfg.PSObject.Properties | Where-Object { \$_.Name -ieq \$k } | Select-Object -First 1; if (\$null -ne \$prop -and \$null -ne \$cfg.(\$prop.Name)) { @(\$cfg.(\$prop.Name)) -join ','; \$found=\$true; break } }; if (-not \$found -and \$null -ne \$cfg.wsl) { \$nested=\$cfg.wsl.PSObject.Properties | Where-Object { \$_.Name -ieq 'integratedDistros' -or \$_.Name -ieq 'enabledWslIntegrations' } | Select-Object -First 1; if (\$null -ne \$nested -and \$null -ne \$cfg.wsl.(\$nested.Name)) { @(\$cfg.wsl.(\$nested.Name)) -join ',' } } }" 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | tail -n1)"

        integrated_norm=",${integrated_csv// /},"
        [[ "$integrated_norm" == *",$current_distro,"* ]] && in_integrated=true

        if [[ "${enable_default,,}" == "true" && -n "$default_distro" && "$default_distro" == "$current_distro" ]]; then
            default_covers=true
        fi

        if [[ "$in_integrated" == true ]]; then
            ok "WSL entegrasyonu '${current_distro}' için açık."
            if ! DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null; then
                warn "Docker socket WSL2 dağıtımında mount edilmemiş olabilir; Docker Desktop toggle'ı '${current_distro}' için kapalı olabilir."
            fi
            return 0
        fi

        if [[ "$default_covers" == true ]]; then
            if [[ "${WSL_INTEGRATION_HARDEN_EXPLICIT:-true}" == "true" \
                  && "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" != "true" \
                  && ! -f "$integration_autofix_sentinel" ]]; then
                info "Default-distro toggle '${current_distro}' kapsıyor; sertleştirme için explicit toggle ekleniyor."
                if apply_wsl_integration_autofix "$current_distro"; then
                    ok "Postcheck hardening: '${current_distro}' explicit toggle eklendi (Docker Desktop yeniden başlatıldı)."
                else
                    warn "Postcheck hardening başarısız; öneri olarak Settings > Resources > WSL Integration üzerinden manuel açın."
                fi
                return 0
            fi
            info "Docker Desktop default-distro toggle'u '${current_distro}' dağıtımını kapsıyor."
            warn "Öneri: WSL Integration listesinden '${current_distro}' için explicit toggle'ı da açın."
            if ! DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null; then
                warn "Docker socket WSL2 dağıtımında mount edilmemiş olabilir; Docker Desktop toggle'ı '${current_distro}' için explicit açılması gerekir."
            fi
            return 0
        fi

        if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "$integration_autofix_sentinel" ]]; then
            if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null; then
                if [[ "${_WSL_INTEGRATION_POSTFIX_NOTICE_SHOWN:-false}" != "true" ]]; then
                    ok "WSL Integration runtime doğrulandı: daemon socket erişilebilir (UI listesi henüz güncellenmemiş olabilir)."
                    _WSL_INTEGRATION_POSTFIX_NOTICE_SHOWN=true
                fi
                return 0
            fi
            warn "Docker Desktop WSL Integration hâlâ '${current_distro}' için kapalı görünüyor; daha önce bu oturumda otomatik düzeltme uygulandı, Docker Desktop senkronizasyonu bekleniyor."
            info "Autofix sonrası Docker socket mount doğrulaması başlatılıyor (maks. ${WSL_INTEGRATION_SOCKET_WAIT_TIMEOUT:-30}sn, 2sn aralıklarla)."
            if _wait_for_docker_socket_mount_after_autofix; then
                return 0
            fi
            warn "Autofix sonrası Docker socket mount doğrulanamadı; daemon hazırlanıyor olabilir."
            return 0
        fi

        local should_apply=false
        if [[ "${WSL_INTEGRATION_AUTOFIX_ELIGIBLE:-false}" == "true" ]]; then
            should_apply=true
            info "Preflight '${current_distro}' için autofix-eligible işareti verdi; aynı oturumda tekrar prompt göstermeden otomatik düzeltme uygulanacak."
        else
            if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null || docker info &>/dev/null; then
                info "Docker daemon socket erişilebilir; '${current_distro}' için WSL Integration UI listesi gecikmeli/yanıltıcı olabilir."
                return 0
            fi
            warn "Docker Desktop WSL Integration listesinde '${current_distro}' kapalı görünüyor."
        fi
        if [[ "$should_apply" != true && ( "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ) ]]; then
            should_apply=true
            info "NO_INTERACTION/AUTO_INSTALL etkin: '${current_distro}' için Docker Desktop WSL entegrasyonu otomatik etkinleştirilecek."
        elif [[ "$should_apply" != true ]]; then
            local reply
            reply=$(prompt_yes_no_with_timeout_default_yes "'${current_distro}' için Docker Desktop WSL Integration ayarı otomatik açılsın mı? [E/h]: ")
            reply="${reply^^}"
            if [[ "$reply" == "E" || "$reply" == "EVET" || "$reply" == "Y" || "$reply" == "YES" || -z "$reply" ]]; then
                should_apply=true
            fi
        fi

        if [[ "$should_apply" != true ]]; then
            warn "WSL Integration otomatik güncellemesi atlandı. Docker Desktop > Settings > Resources > WSL Integration bölümünden '${current_distro}' anahtarını açın."
            return 1
        fi

        if ! apply_wsl_integration_autofix "$current_distro"; then
            warn "Docker Desktop WSL Integration ayarı otomatik güncellenemedi."
            return 1
        fi

        info "Docker Desktop yeniden başlatıldı; WSL Integration ayarının uygulanması bekleniyor..."
        local attempt
        for attempt in $(seq 1 20); do
            sleep 3
            if _wsl_integration_distro_listed "$current_distro"; then
                ok "Docker Desktop WSL Integration: '${current_distro}' artık aktif."
                return 0
            fi
            if DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null || docker info &>/dev/null; then
                ok "WSL Integration runtime doğrulandı: daemon socket erişilebilir (UI listesi '${current_distro}' için henüz güncellenmemiş olabilir)."
                return 0
            fi
        done

        if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" ]] && (DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}' &>/dev/null || docker info &>/dev/null); then
            ok "Autofix sonrası daemon erişilebilir; WSL Integration runtime çalışıyor, UI senkronizasyonu bekleniyor."
            return 0
        fi
        warn "PowerShell autofix denendi fakat '${current_distro}' Docker Desktop tarafından hâlâ tanınmadı; Settings > Resources > WSL Integration üzerinden manuel açın."
        return 1
    }

    if ! docker_cli_healthy; then
        return 1
    fi

    if _docker_ready_with_socket; then return 0; fi

    warn "Docker daemon çalışmıyor görünüyor; otomatik başlatma denenecek."

    if [[ "$WSL2" != true ]] && command -v systemctl &>/dev/null; then
        sudo systemctl start docker >/dev/null 2>&1 || true
    fi

    if [[ "$WSL2" != true ]] && ! docker info &>/dev/null && command -v service &>/dev/null; then
        sudo service docker start >/dev/null 2>&1 || true
    fi

    if [[ "$WSL2" == true ]] && command -v powershell.exe &>/dev/null; then
        if ! _wsl_backend_docker_desktop_registered; then
            fail "Docker Desktop backend distro ('docker-desktop') WSL2'de kayıtlı değil."
            warn "Bu dağıtım manuel silinmiş olabilir ('wsl --unregister docker-desktop')."
            warn "Çözüm: Docker Desktop > Settings > Troubleshoot > Reset to factory defaults"
            warn "veya Docker Desktop'ı yeniden kurun. Sonra bu betiği tekrar çalıştırın."
            return 1
        fi
    fi

    if ! docker info &>/dev/null && command -v powershell.exe &>/dev/null; then
        local desktop_timeout
        desktop_timeout="${DOCKER_DESKTOP_READY_TIMEOUT:-240}"
        if ! [[ "$desktop_timeout" =~ ^[0-9]+$ ]] || (( desktop_timeout < 30 )); then
            desktop_timeout=240
        fi
        if [[ "${_DOCKER_DESKTOP_AUTOFIX_RESTARTED_AT:-}" =~ ^[0-9]+$ ]]; then
            local now_ts elapsed_since_autofix remaining_warmup
            now_ts="$(date +%s)"
            elapsed_since_autofix=$(( now_ts - _DOCKER_DESKTOP_AUTOFIX_RESTARTED_AT ))
            if (( elapsed_since_autofix < 0 )); then
                elapsed_since_autofix=0
            fi
            if (( elapsed_since_autofix < 300 )); then
                remaining_warmup=$(( 300 - elapsed_since_autofix ))
                desktop_timeout=$(( desktop_timeout + remaining_warmup ))
                info "Preflight autofix sonrası Docker Desktop hâlâ ısınma penceresinde (${elapsed_since_autofix}sn); bekleme süresi ${remaining_warmup}sn uzatıldı (toplam ${desktop_timeout}sn)."
            fi
        fi
        local integration_autofix_sentinel="${TMPDIR:-/tmp}/sidar_wsl_integration_applied"
        if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "$integration_autofix_sentinel" ]]; then
            local autofix_timeout=$(( ${DOCKER_DESKTOP_READY_TIMEOUT:-240} + 120 ))
            if ! [[ "$autofix_timeout" =~ ^[0-9]+$ ]] || (( autofix_timeout < 30 )); then
                autofix_timeout=360
            fi
            if (( autofix_timeout > desktop_timeout )); then
                desktop_timeout=$autofix_timeout
            fi
            info "WSL integration autofix bu oturumda uygulandığı için Docker Desktop bekleme süresi yeniden ayarlandı (${desktop_timeout}sn)."
        fi

        powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \
            "\$dockerProc = Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue; if (-not \$dockerProc) { \$cmd = Get-Command 'Docker Desktop.exe' -ErrorAction SilentlyContinue; \$dockerExe = if (\$cmd -and \$cmd.Source) { \$cmd.Source } else { Join-Path \$env:ProgramFiles 'Docker\\Docker\\Docker Desktop.exe' }; Start-Process \$dockerExe }" \
            >/dev/null 2>&1 || true
        info "Docker Desktop başlatıldı, WSL entegrasyonunun hazır olması bekleniyor (maks. ${desktop_timeout}sn)..."
        local startup_probe_timeout=45
        local startup_probe_elapsed=0
        local startup_probe_step=5
        local docker_desktop_started=false
        while (( startup_probe_elapsed < startup_probe_timeout )); do
            if tasklist.exe //FI "IMAGENAME eq Docker Desktop.exe" 2>/dev/null | tr -d '\r' | grep -q "Docker Desktop.exe"; then
                docker_desktop_started=true
                break
            fi
            if pgrep -af 'docker.*desktop' >/dev/null 2>&1; then
                docker_desktop_started=true
                break
            fi
            sleep "$startup_probe_step"
            ((startup_probe_elapsed += startup_probe_step))
        done
        if [[ "$docker_desktop_started" != "true" ]]; then
            warn "Docker Desktop süreci ilk ${startup_probe_timeout}sn içinde başlatılamadı; erken çıkılıyor."
            return 1
        fi
        local elapsed=0
        local sleep_step=3
        local progress_mark=10
        local no_signal_seconds=0
        local no_signal_limit=90
        while (( elapsed < desktop_timeout )); do
            if ! powershell.exe -NoProfile -Command "@(Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue).Count" 2>/dev/null | tr -d '\r' | grep -Eq '^[1-9][0-9]*$'; then
                warn "Docker Desktop süreci çalışmıyor görünüyor; erken çıkılıyor (bekleme: ${elapsed}/${desktop_timeout}sn)."
                break
            fi
            if _docker_ready_with_socket; then
                ok "Docker daemon erişilebilir duruma geldi."
                return 0
            fi
            if [[ -e /dev/dxg || -S /var/run/docker.sock ]]; then
                no_signal_seconds=0
            else
                no_signal_seconds=$(( no_signal_seconds + sleep_step ))
                if (( no_signal_seconds >= no_signal_limit )); then
                    warn "Docker Desktop hazırlığında ${no_signal_limit}sn boyunca /dev/dxg veya /var/run/docker.sock sinyali alınamadı; erken çıkılıyor."
                    return 1
                fi
            fi
            sleep "$sleep_step"
            ((elapsed += sleep_step))
            if (( elapsed >= progress_mark )); then
                info "Docker daemon hâlâ hazırlanıyor... (${elapsed}/${desktop_timeout}sn)"
                progress_mark=$(( progress_mark + 10 ))
            fi
            if (( sleep_step < 12 )); then
                sleep_step=$(( sleep_step * 2 ))
                (( sleep_step > 12 )) && sleep_step=12
            fi
        done
        warn "Docker Desktop belirtilen süre içinde hazır hale gelmedi (${desktop_timeout}sn)."
    fi

    if _docker_ready_with_socket; then return 0; fi

    if [[ "$STRICT_DOCKER" == "true" ]]; then
        fail "Docker daemon erişilemedi. --strict-docker / SIDAR_REQUIRE_DOCKER=1 etkin olduğu için kurulum fail-fast durduruldu."
    fi

    return 1
}

sidar_phase_runtime_prerequisites() {
    sidar_source_install_utils "gpu_utils.sh"
    ensure_prerequisites
    select_runtime_mode
    detect_gpu
    setup_nvidia_docker
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" != "local" ]]; then
        info "Tam Docker modu: lokal Python/uv ortam kurulumu workspace fazına bırakılmadan atlanacak."
    fi
}
