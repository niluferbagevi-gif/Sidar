#!/usr/bin/env bash

check_installer_hash() {
    local current_script="$1"
    local next_script="$2"
    local reexec_label="$3"
    local current_sha="bilinmiyor"
    local next_sha="bilinmiyor"

    [[ -f "$next_script" ]] || fail "${reexec_label} hedef install_sidar.sh bulunamadı: $next_script"

    current_sha="$(compute_sha256 "$current_script" 2>/dev/null || echo bilinmiyor)"
    next_sha="$(compute_sha256 "$next_script" 2>/dev/null || echo bilinmiyor)"

    if [[ "$current_sha" == "bilinmiyor" || "$next_sha" == "bilinmiyor" ]]; then
        fail "${reexec_label} install_sidar.sh SHA256 doğrulaması yapılamadı (mevcut=${current_sha}, hedef=${next_sha}). Güvenli re-exec için sha256sum/shasum erişimini düzeltin."
    fi

    if [[ "$current_sha" != "$next_sha" ]]; then
        if [[ "${SIDAR_INSTALL_ALLOW_STALE_REEXEC:-0}" == "1" ]]; then
            warn "${reexec_label} install_sidar.sh SHA256 farklı (mevcut=${current_sha}, hedef=${next_sha}); SIDAR_INSTALL_ALLOW_STALE_REEXEC=1 nedeniyle devam ediliyor."
            return 0
        fi
        fail "${reexec_label} install_sidar.sh SHA256 farklı (mevcut=${current_sha}, hedef=${next_sha}). Yanlış/eski installer çalıştırma riskini önlemek için re-exec durduruldu. NEXT STEP → hash drift kaynağını temizleyin: \$HOME/Sidar/install_sidar.sh eskiyse 'rm -f \"\$HOME/Sidar/install_sidar.sh\"' komutuyla kaldırıp güncel install_sidar.sh ile yeniden deneyin; hedef repo driftliyse git pull --ff-only veya temiz clone kullanın. Yalnız bilinçli/incelemesi yapılmış durumda SIDAR_INSTALL_ALLOW_STALE_REEXEC=1 ile tekrar deneyin."
    fi
}

verify_reexec_installer_or_fail() {
    local next_script="$1"
    local reexec_label="$2"

    check_installer_hash "$ORIGINAL_SCRIPT_PATH" "$next_script" "$reexec_label"
}

verify_home_reexec_candidate_if_present() {
    local home_script="$HOME/Sidar/install_sidar.sh"

    [[ -d "$HOME/Sidar/.git" && -f "$home_script" ]] || return 0
    if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" && "${SIDAR_INSTALL_ALLOW_HOME_REEXEC_IN_TEST_MODE:-0}" != "1" ]]; then
        return 0
    fi

    verify_reexec_installer_or_fail "$home_script" "Mevcut $HOME/Sidar re-exec"
}
