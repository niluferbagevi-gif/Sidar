#!/usr/bin/env bash

# ── 8. WSL2 Ses Desteği Kurulumu ─────────────────────────────────────────────
# WSLg (Windows 11 Build 22000+) PulseAudio soketi üzerinden gerçek zamanlı
# mikrofon/hoparlör erişimini etkinleştirir.
setup_wsl2_audio() {
    [[ "$WSL2" == true ]] || return 0

    step "WSL2 Ses Desteği"

    local pulse_socket=""
    local pulse_uid
    pulse_uid=$(id -u)
    local pulse_runtime_dir="/run/user/${pulse_uid}"

    # WSLg PulseAudio soket konumlarını sırayla dene
    for candidate in \
        "${pulse_runtime_dir}/pulse/native" \
        "/tmp/pulse-${pulse_uid}/native" \
        "/tmp/pulse-socket"; do
        if [[ -S "$candidate" ]]; then
            pulse_socket="$candidate"
            break
        fi
    done

    # ── WSLg soketi tespit edildi: tam ses kurulumu ────────────────────────────
    if [[ -n "$pulse_socket" ]]; then
        ok "WSLg PulseAudio soketi tespit edildi: $pulse_socket"
        info "Windows 11 WSLg üzerinde ses desteği yapılandırılıyor..."
        local audio_restart_needed=false

        # PulseAudio istemci araçları + ALSA→PulseAudio köprüsü
        info "PulseAudio istemci kütüphaneleri kontrol ediliyor..."
        local pa_pkgs_needed=()
        for pkg in pulseaudio-utils libpulse-dev libasound2-plugins; do
            dpkg -l "$pkg" &>/dev/null 2>&1 || pa_pkgs_needed+=("$pkg")
        done
        if [[ ${#pa_pkgs_needed[@]} -gt 0 ]]; then
            if sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${pa_pkgs_needed[@]}" >/dev/null 2>&1; then
                ok "PulseAudio paketleri kuruldu: ${pa_pkgs_needed[*]}"
            else
                warn "Bazı PulseAudio paketleri kurulamadı: ${pa_pkgs_needed[*]}"
            fi
            audio_restart_needed=true
        else
            ok "PulseAudio paketleri zaten kurulu."
        fi

        # ALSA → PulseAudio yönlendirmesi (~/.asoundrc)
        local asoundrc="$HOME/.asoundrc"
        if [[ ! -f "$asoundrc" ]] || ! grep -q "pcm.pulse" "$asoundrc" 2>/dev/null; then
            cat > "$asoundrc" <<'ASOUNDRC'
# Sidar: ALSA varsayılanını PulseAudio'ya yönlendir (WSL2/WSLg)
pcm.default pulse
ctl.default pulse

pcm.pulse {
    type pulse
}
ctl.pulse {
    type pulse
}
ASOUNDRC
            ok "ALSA → PulseAudio köprüsü yapılandırıldı (~/.asoundrc)."
            audio_restart_needed=true
        else
            ok "$HOME/.asoundrc zaten PulseAudio yapılandırması içeriyor."
        fi

        # PULSE_SERVER ortam değişkeni (yeni terminaller için kalıcı)
        local pulse_export="export PULSE_SERVER=unix:${pulse_socket}"
        for rcfile in "$HOME/.bashrc" "$HOME/.zshrc"; do
            if [[ -f "$rcfile" ]]; then
                if grep -Fxq "$pulse_export" "$rcfile" 2>/dev/null; then
                    ok "PULSE_SERVER zaten ${rcfile} içinde tanımlı."
                else
                    {
                        echo ""
                        echo "# Sidar WSL2 ses desteği"
                        echo "$pulse_export"
                    } >> "$rcfile"
                    ok "PULSE_SERVER → ${rcfile} dosyasına eklendi."
                    audio_restart_needed=true
                fi
            fi
        done
        if [[ "$audio_restart_needed" == true ]]; then
            AUDIO_SESSION_RESTART_RECOMMENDED=true
        fi
        # Mevcut oturum için de hemen ayarla
        export PULSE_SERVER="unix:${pulse_socket}"

        # PulseAudio bağlantısını doğrula
        if command -v pactl &>/dev/null && pactl info &>/dev/null 2>&1; then
            local pa_server
            pa_server=$(pactl info 2>/dev/null | grep -i "Server Name" | cut -d: -f2- | xargs || echo "aktif")
            ok "PulseAudio bağlantısı doğrulandı: ${pa_server}"

            # .env'de ENABLE_MULTIMODAL=true yap (ses çalışıyor)
            local env_file="$SCRIPT_DIR/.env"
            if [[ -f "$env_file" ]]; then
                if grep -q "^ENABLE_MULTIMODAL=" "$env_file"; then
                    sed_inplace 's/^ENABLE_MULTIMODAL=.*/ENABLE_MULTIMODAL=true/' "$env_file"
                else
                    echo "ENABLE_MULTIMODAL=true" >> "$env_file"
                fi
                ok ".env: ENABLE_MULTIMODAL=true — ses/mikrofon desteği aktif."
            fi
        else
            warn "PulseAudio soketi mevcut fakat pactl ile doğrulanamadı."
            info "Yeni bir terminal açtıktan sonra test edin: pactl info"
            info "Sorun devam ederse: wsl --shutdown && wsl (Windows PowerShell'de)"
        fi

    # ── WSLg soketi bulunamadı: yönlendirme ve otomatik WSLg etkinleştirme ────
    else
        # --enable-audio bayrağıyla çalışıyorsa aktif etkinleştirme girişimi yap
        if [[ "$ENABLE_AUDIO" == true ]]; then
            warn "WSLg PulseAudio soketi henüz mevcut değil."
            info "WSLg'yi etkinleştirmek için aşağıdaki adımları uygulayın:"
            echo ""
            echo "  Windows PowerShell / CMD (yönetici olarak):"
            echo "    1. wsl --update"
            echo "    2. wsl --shutdown"
            echo "    3. Dağıtımı yeniden başlatın: wsl -d Ubuntu"
            echo ""
            echo "  Gereksinimler:"
            echo "    • Windows 11 Build 22000+ (veya Windows 10 KB5004296+)"
            echo "    • WSL 2.0.0+ (wsl --update ile güncelleyin)"
            echo ""
            echo "  WSLg sonra kurulumu tamamlayın:"
            echo "    ./install_sidar.sh --enable-audio"
            echo ""
            info "Ses desteği olmadan devam edilecek (ENABLE_MULTIMODAL=false)."
            local env_file="$SCRIPT_DIR/.env"
            if [[ -f "$env_file" ]]; then
                if grep -q "^ENABLE_MULTIMODAL=" "$env_file"; then
                    sed_inplace 's/^ENABLE_MULTIMODAL=.*/ENABLE_MULTIMODAL=false/' "$env_file"
                fi
            fi
        else
            warn "WSL2 üzerinde ses donanımına erişim kısıtlıdır."
            info "Ses desteğini etkinleştirmek için:"
            echo "  1. Windows 11 Build 22000+ ile WSLg otomatik olarak ses desteği sağlar."
            echo "  2. 'wsl --update' ile WSL'yi güncelleyin, ardından 'wsl --shutdown' yapın."
            echo "  3. Kurulum betiğini --enable-audio bayrağıyla yeniden çalıştırın:"
            echo "       ./install_sidar.sh --enable-audio"
            echo ""
            info "Sesli özellik kullanmayacaksanız .env dosyanızda ENABLE_MULTIMODAL=false kalabilir."
        fi
    fi

    # ── RAM limiti kontrolü ve .wslconfig otomatik yapılandırma ──────────────
    local wslconfig_path=""
    local resolved_windows_home=""
    resolved_windows_home="$(resolve_windows_userprofile_path || true)"
    if [[ -n "$resolved_windows_home" ]]; then
        wslconfig_path="${resolved_windows_home}/.wslconfig"
    fi

    # Mevcut memory değerini GB cinsinden sayıya çevir (örn. "16GB" → 16)
    _parse_gb() {
        echo "${1:-0}" | grep -oP '^\d+' || echo "0"
    }

    _detect_host_ram_gb() {
        local total_bytes="0"
        local wmic_bytes=""
        local ps_bytes=""

        # Win11 24H2+ sürümlerde WMIC kaldırılabildiği için önce PowerShell/CIM yolunu dene.
        if command -v powershell.exe &>/dev/null; then
            ps_bytes=$(powershell.exe -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory" 2>/dev/null \
                | tr -d '\r' \
                | awk 'NF {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0); if ($0 ~ /^[0-9]+$/) {print $0; exit}}' || true)
            if [[ -n "$ps_bytes" ]]; then
                total_bytes="$ps_bytes"
            fi
        fi
        if [[ -z "$total_bytes" || "$total_bytes" -le 0 ]] \
            && command -v cmd.exe &>/dev/null \
            && command -v wmic.exe &>/dev/null; then
            wmic_bytes=$(cmd.exe /c "wmic ComputerSystem get TotalPhysicalMemory /value" 2>/dev/null \
                | tr -d '\r' \
                | awk -F= '/^TotalPhysicalMemory=/ {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); if ($2 ~ /^[0-9]+$/) {print $2; exit}}' || true)
            if [[ -n "$wmic_bytes" ]]; then
                total_bytes="$wmic_bytes"
            fi
        fi

        if [[ -z "$total_bytes" || "$total_bytes" -le 0 ]] && [[ -r /proc/meminfo ]]; then
            local total_kb="0"
            total_kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo "0")
            if [[ -n "$total_kb" && "$total_kb" -gt 0 ]]; then
                total_bytes=$((total_kb * 1024))
            fi
        fi
        if [[ -z "$total_bytes" || "$total_bytes" -le 0 ]]; then
            echo "16"
            return
        fi
        # Yukarı yuvarla: bytes -> GB
        echo $(((total_bytes + 1073741823) / 1073741824))
    }

    _clamp_int() {
        local val="$1"
        local min="$2"
        local max="$3"
        if [[ "$val" -lt "$min" ]]; then
            echo "$min"
            return
        fi
        if [[ "$val" -gt "$max" ]]; then
            echo "$max"
            return
        fi
        echo "$val"
    }

    _detect_host_processors() {
        local logical_processors=""
        if command -v powershell.exe &>/dev/null; then
            logical_processors=$(powershell.exe -NoProfile -Command "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors" 2>/dev/null \
                | tr -d '\r' \
                | awk 'NF {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0); if ($0 ~ /^[0-9]+$/) {print $0; exit}}' || true)
        fi
        if [[ -z "$logical_processors" ]] && command -v nproc &>/dev/null; then
            logical_processors=$(nproc 2>/dev/null || true)
        fi
        if [[ -z "$logical_processors" || ! "$logical_processors" =~ ^[0-9]+$ || "$logical_processors" -le 0 ]]; then
            logical_processors=4
        fi
        echo "$logical_processors"
    }

    local host_ram_gb
    local host_processors
    local target_memory_gb
    local target_swap_gb
    local target_processors
    host_ram_gb=$(_detect_host_ram_gb)
    host_processors=$(_detect_host_processors)
    target_memory_gb=$((host_ram_gb * 3 / 4))
    target_memory_gb=$(_clamp_int "$target_memory_gb" 4 32)
    target_swap_gb=$((host_ram_gb / 2))
    target_swap_gb=$(_clamp_int "$target_swap_gb" 2 16)
    target_processors=$(_clamp_int "$host_processors" 2 16)

    local target_memory="${target_memory_gb}GB"
    local target_swap="${target_swap_gb}GB"
    local target_kernel_command_line="cgroup_no_v1=all"
    local target_sparse_vhd="true"
    info "WSL2 için dinamik .wslconfig hedefleri: memory=${target_memory}, swap=${target_swap}, processors=${target_processors}, kernelCommandLine=${target_kernel_command_line}, sparseVhd=${target_sparse_vhd} (host RAM: ${host_ram_gb}GB, logical processors: ${host_processors})."

    # [wsl2] bölümünde bir anahtarın tekil olmasını sağlar; yoksa ekler.
    # Değer zaten varsa korur, yinelenen satırları temizler.
    _ensure_wsl2_key_once() {
        local cfg_file="$1"
        local cfg_key="$2"
        local cfg_value="$3"
        local tmp_file
        tmp_file=$(mktemp)

        awk -v key="$cfg_key" -v value="$cfg_value" '
            BEGIN { in_wsl2=0; seen_key=0 }
            {
                if ($0 ~ /^\[.*\]$/) {
                    if (in_wsl2 && !seen_key) {
                        print key "=" value
                        seen_key=1
                    }
                    in_wsl2 = ($0 == "[wsl2]")
                    print
                    next
                }

                if (in_wsl2 && $0 ~ ("^" key "=")) {
                    if (!seen_key) {
                        print
                        seen_key=1
                    }
                    next
                }

                print
            }
            END {
                if (in_wsl2 && !seen_key) {
                    print key "=" value
                }
            }
        ' "$cfg_file" > "$tmp_file"

        if ! cmp -s "$cfg_file" "$tmp_file"; then
            if mv "$tmp_file" "$cfg_file" 2>/dev/null || { cp "$tmp_file" "$cfg_file" && rm -f "$tmp_file"; }; then
                return 0
            fi
            rm -f "$tmp_file"
            return 2
        fi

        rm -f "$tmp_file"
        return 1
    }

    # Belirli bir INI bölümünde anahtarın tekil olmasını sağlar; yoksa ekler.
    _ensure_ini_key_once() {
        local cfg_file="$1"
        local cfg_section="$2"
        local cfg_key="$3"
        local cfg_value="$4"
        local tmp_file
        tmp_file=$(mktemp)

        awk -v section="$cfg_section" -v key="$cfg_key" -v value="$cfg_value" '
            BEGIN { in_section=0; seen_section=0; seen_key=0 }
            {
                if ($0 ~ /^\[.*\]$/) {
                    if (in_section && !seen_key) {
                        print key "=" value
                        seen_key=1
                    }
                    in_section = ($0 == "[" section "]")
                    if (in_section) { seen_section=1 }
                    print
                    next
                }

                if (in_section && $0 ~ ("^" key "=")) {
                    if (!seen_key) {
                        print
                        seen_key=1
                    }
                    next
                }

                print
            }
            END {
                if (in_section && !seen_key) {
                    print key "=" value
                    seen_key=1
                }
                if (!seen_section) {
                    print ""
                    print "[" section "]"
                    print key "=" value
                }
            }
        ' "$cfg_file" > "$tmp_file"

        if ! cmp -s "$cfg_file" "$tmp_file"; then
            if mv "$tmp_file" "$cfg_file" 2>/dev/null || { cp "$tmp_file" "$cfg_file" && rm -f "$tmp_file"; }; then
                return 0
            fi
            rm -f "$tmp_file"
            return 2
        fi

        rm -f "$tmp_file"
        return 1
    }

    # [wsl2] bölümünde anahtar değerini zorla günceller (ilkini değiştirir, tekrarları temizler).
    _set_wsl2_key_value() {
        local cfg_file="$1"
        local cfg_key="$2"
        local cfg_value="$3"
        local tmp_file
        tmp_file=$(mktemp)

        awk -v key="$cfg_key" -v value="$cfg_value" '
            BEGIN { in_wsl2=0; set_key=0 }
            {
                if ($0 ~ /^\[.*\]$/) {
                    if (in_wsl2 && !set_key) {
                        print key "=" value
                        set_key=1
                    }
                    in_wsl2 = ($0 == "[wsl2]")
                    print
                    next
                }
                if (in_wsl2 && $0 ~ ("^" key "=")) {
                    if (!set_key) {
                        print key "=" value
                        set_key=1
                    }
                    next
                }
                print
            }
            END {
                if (in_wsl2 && !set_key) {
                    print key "=" value
                }
            }
        ' "$cfg_file" > "$tmp_file"

        if ! cmp -s "$cfg_file" "$tmp_file"; then
            if mv "$tmp_file" "$cfg_file" 2>/dev/null || { cp "$tmp_file" "$cfg_file" && rm -f "$tmp_file"; }; then
                return 0
            fi
            rm -f "$tmp_file"
            return 2
        fi
        rm -f "$tmp_file"
        return 1
    }

    if [[ -n "$wslconfig_path" ]]; then
        if [[ ! -f "$wslconfig_path" ]]; then
            cat > "$wslconfig_path" <<'WSLCFG'
[wsl2]
memory=__SIDAR_WSL_MEMORY__
swap=__SIDAR_WSL_SWAP__
processors=__SIDAR_WSL_PROCESSORS__
kernelCommandLine=__SIDAR_WSL_KERNEL_COMMAND_LINE__

[experimental]
sparseVhd=__SIDAR_WSL_SPARSE_VHD__
WSLCFG
            sed_inplace "s/__SIDAR_WSL_MEMORY__/${target_memory}/g; s/__SIDAR_WSL_SWAP__/${target_swap}/g; s/__SIDAR_WSL_PROCESSORS__/${target_processors}/g; s/__SIDAR_WSL_KERNEL_COMMAND_LINE__/${target_kernel_command_line}/g; s/__SIDAR_WSL_SPARSE_VHD__/${target_sparse_vhd}/g" "$wslconfig_path"
            ok "WSL2: %UserProfile%/.wslconfig oluşturuldu (memory=${target_memory}, swap=${target_swap}, processors=${target_processors}, kernelCommandLine=${target_kernel_command_line}, sparseVhd=${target_sparse_vhd})."
            WSLCONFIG_CHANGED=true
            info "Değişiklik sonrası PowerShell'de 'wsl --shutdown' çalıştırıp dağıtımı yeniden başlatın."
        else
            local changed=false

            # [wsl2] bölümü yoksa dosyanın sonuna ekle
            if ! grep -q '^\[wsl2\]' "$wslconfig_path" 2>/dev/null; then
                printf '\n[wsl2]\n' >> "$wslconfig_path"
                ok "WSL2: .wslconfig içine [wsl2] bölümü eklendi."
                changed=true
            fi

            # [wsl2] altındaki memory= satırını tekilleştir; yoksa ekle
            local ensure_memory_rc=0
            _ensure_wsl2_key_once "$wslconfig_path" "memory" "$target_memory" || ensure_memory_rc=$?
            case $ensure_memory_rc in
                0)
                    ok "WSL2: .wslconfig içinde memory satırı düzenlendi/eklendi."
                    changed=true
                    ;;
                1)
                    : # no-op: zaten istenen durumda
                    ;;
                2)
                    warn "WSL2: .wslconfig memory satırı güncellenemedi (dosya yazma hatası)."
                    ;;
            esac

            local cur_mem cur_mem_gb
            cur_mem=$(awk '
                BEGIN { in_wsl2=0 }
                /^\[.*\]$/ { in_wsl2 = ($0 == "[wsl2]") }
                in_wsl2 && /^memory=/ { sub(/^memory=/, "", $0); print; exit }
            ' "$wslconfig_path")
            cur_mem_gb=$(_parse_gb "$cur_mem")
            if [[ "$cur_mem_gb" -lt "$target_memory_gb" ]]; then
                warn "WSL2: .wslconfig memory=${cur_mem} — bu makine için düşük olabilir (önerilen: ${target_memory})."
                local should_upgrade_mem=false
                if [[ "$SIDAR_WSL_AUTO_UPGRADE" == "true" || "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
                    should_upgrade_mem=true
                else
                    local upgrade_mem_reply
                    upgrade_mem_reply=$(prompt_yes_no_with_timeout_default_yes "WSL2 memory=${cur_mem} düşük görünüyor. ${target_memory} değerine otomatik yükseltelim mi? [E/h]: ")
                    upgrade_mem_reply="${upgrade_mem_reply^^}"
                    if [[ "$upgrade_mem_reply" == "E" || "$upgrade_mem_reply" == "EVET" || "$upgrade_mem_reply" == "Y" || "$upgrade_mem_reply" == "YES" || -z "$upgrade_mem_reply" ]]; then
                        should_upgrade_mem=true
                    fi
                fi
                if [[ "$should_upgrade_mem" == true ]]; then
                    local set_memory_rc=0
                    _set_wsl2_key_value "$wslconfig_path" "memory" "$target_memory" || set_memory_rc=$?
                    case $set_memory_rc in
                        0)
                            ok "WSL2: .wslconfig memory ${cur_mem} -> ${target_memory} olarak yükseltildi."
                            changed=true
                            cur_mem="$target_memory"
                            ;;
                        2)
                            warn "WSL2: .wslconfig memory yazılamadı (${cur_mem} -> ${target_memory}). Lütfen dosya izinlerini kontrol edin."
                            ;;
                        *)
                            warn "WSL2: .wslconfig memory düşük kaldı (${cur_mem}). İsterseniz daha sonra ${target_memory} olarak güncelleyebilirsiniz."
                            ;;
                    esac
                else
                    warn "WSL2: .wslconfig memory düşük kaldı (${cur_mem}). İsterseniz daha sonra ${target_memory} olarak güncelleyebilirsiniz."
                fi
            elif [[ "$cur_mem_gb" -ge "$host_ram_gb" ]]; then
                warn "WSL2: .wslconfig memory=${cur_mem} — Windows host RAM'i (${host_ram_gb}GB) ile aynı/üstü; host için RAM tamponu bırakmıyor olabilir."
            else
                ok "WSL2: .wslconfig memory=${cur_mem} — yeterli."
            fi

            # [wsl2] altındaki swap= satırını tekilleştir; yoksa ekle
            local ensure_swap_rc=0
            _ensure_wsl2_key_once "$wslconfig_path" "swap" "$target_swap" || ensure_swap_rc=$?
            case $ensure_swap_rc in
                0)
                    ok "WSL2: .wslconfig içinde swap satırı düzenlendi/eklendi."
                    changed=true
                    ;;
                1)
                    : # no-op: zaten istenen durumda
                    ;;
                2)
                    warn "WSL2: .wslconfig swap satırı güncellenemedi (dosya yazma hatası)."
                    ;;
            esac

            local cur_swap cur_swap_gb
            cur_swap=$(awk '
                BEGIN { in_wsl2=0 }
                /^\[.*\]$/ { in_wsl2 = ($0 == "[wsl2]") }
                in_wsl2 && /^swap=/ { sub(/^swap=/, "", $0); print; exit }
            ' "$wslconfig_path")
            cur_swap_gb=$(_parse_gb "$cur_swap")
            if [[ "$cur_swap_gb" -lt "$target_swap_gb" ]]; then
                warn "WSL2: .wslconfig swap=${cur_swap} — bu makine için düşük olabilir (önerilen: ${target_swap})."
                local should_upgrade_swap=false
                if [[ "$SIDAR_WSL_AUTO_UPGRADE" == "true" || "$NO_INTERACTION" == true || "$AUTO_INSTALL" == true ]]; then
                    should_upgrade_swap=true
                else
                    local upgrade_swap_reply
                    upgrade_swap_reply=$(prompt_yes_no_with_timeout_default_yes "WSL2 swap=${cur_swap} düşük görünüyor. ${target_swap} değerine otomatik yükseltelim mi? [E/h]: ")
                    upgrade_swap_reply="${upgrade_swap_reply^^}"
                    if [[ "$upgrade_swap_reply" == "E" || "$upgrade_swap_reply" == "EVET" || "$upgrade_swap_reply" == "Y" || "$upgrade_swap_reply" == "YES" || -z "$upgrade_swap_reply" ]]; then
                        should_upgrade_swap=true
                    fi
                fi
                if [[ "$should_upgrade_swap" == true ]]; then
                    local set_swap_rc=0
                    _set_wsl2_key_value "$wslconfig_path" "swap" "$target_swap" || set_swap_rc=$?
                    case $set_swap_rc in
                        0)
                            ok "WSL2: .wslconfig swap ${cur_swap} -> ${target_swap} olarak yükseltildi."
                            changed=true
                            cur_swap="$target_swap"
                            ;;
                        2)
                            warn "WSL2: .wslconfig swap yazılamadı (${cur_swap} -> ${target_swap}). Lütfen dosya izinlerini kontrol edin."
                            ;;
                        *)
                            warn "WSL2: .wslconfig swap düşük kaldı (${cur_swap}). İsterseniz daha sonra ${target_swap} olarak güncelleyebilirsiniz."
                            ;;
                    esac
                else
                    warn "WSL2: .wslconfig swap düşük kaldı (${cur_swap}). İsterseniz daha sonra ${target_swap} olarak güncelleyebilirsiniz."
                fi
            else
                ok "WSL2: .wslconfig swap=${cur_swap} — yeterli."
            fi

            local ensure_processors_rc=0
            _ensure_wsl2_key_once "$wslconfig_path" "processors" "$target_processors" || ensure_processors_rc=$?
            case $ensure_processors_rc in
                0)
                    ok "WSL2: .wslconfig içinde processors=${target_processors} satırı eklendi/tekilleştirildi."
                    changed=true
                    ;;
                1)
                    ok "WSL2: .wslconfig processors ayarı mevcut."
                    ;;
                2)
                    warn "WSL2: .wslconfig processors satırı güncellenemedi (dosya yazma hatası)."
                    ;;
            esac

            local ensure_kernel_rc=0
            _ensure_wsl2_key_once "$wslconfig_path" "kernelCommandLine" "$target_kernel_command_line" || ensure_kernel_rc=$?
            case $ensure_kernel_rc in
                0)
                    ok "WSL2: .wslconfig içinde kernelCommandLine=${target_kernel_command_line} satırı eklendi/tekilleştirildi."
                    changed=true
                    ;;
                1)
                    ok "WSL2: .wslconfig kernelCommandLine ayarı mevcut."
                    ;;
                2)
                    warn "WSL2: .wslconfig kernelCommandLine satırı güncellenemedi (dosya yazma hatası)."
                    ;;
            esac

            local ensure_sparse_vhd_rc=0
            _ensure_ini_key_once "$wslconfig_path" "experimental" "sparseVhd" "$target_sparse_vhd" || ensure_sparse_vhd_rc=$?
            case $ensure_sparse_vhd_rc in
                0)
                    ok "WSL2: .wslconfig içinde [experimental] sparseVhd=${target_sparse_vhd} satırı eklendi/tekilleştirildi."
                    changed=true
                    ;;
                1)
                    ok "WSL2: .wslconfig [experimental] sparseVhd ayarı mevcut."
                    ;;
                2)
                    warn "WSL2: .wslconfig [experimental] sparseVhd satırı güncellenemedi (dosya yazma hatası)."
                    ;;
            esac

            if [[ "$changed" == true ]]; then
                WSLCONFIG_CHANGED=true
                info "Değişiklik sonrası PowerShell'de 'wsl --shutdown' çalıştırıp dağıtımı yeniden başlatın."
            fi
        fi
    else
        warn "WSL2: %UserProfile% yolu çözümlenemedi. .wslconfig dosyasını manuel yapılandırın:"
        echo "       %UserProfile%\\.wslconfig içeriği:"
        echo "       [wsl2]"
        echo "       memory=${target_memory}"
        echo "       swap=${target_swap}"
        echo "       processors=${target_processors}"
        echo "       kernelCommandLine=${target_kernel_command_line}"
        echo ""
        echo "       [experimental]"
        echo "       sparseVhd=${target_sparse_vhd}"
    fi
}


sidar_phase_frontend_assets() {
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" == "local" ]]; then
        setup_react_frontend
        install_playwright_browsers
    else
        info "Tam Docker modu: lokal React build ve Playwright kurulumu atlanıyor."
    fi
    setup_shell_activation_shortcut
    setup_wsl2_audio
}
