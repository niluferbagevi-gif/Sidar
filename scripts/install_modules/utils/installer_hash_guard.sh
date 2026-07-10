#!/usr/bin/env bash

installer_hash_guard_git_root_for_script() {
    local script_path="$1"
    local script_dir=""

    [[ -n "$script_path" ]] || return 1
    script_dir="$(cd "$(dirname "$script_path")" 2>/dev/null && pwd -P)" || return 1
    git -C "$script_dir" rev-parse --show-toplevel 2>/dev/null
}

log_installer_hash_drift_git_context() {
    local label="$1"
    local script_path="$2"
    local repo_root=""
    local repo_head=""
    local status_output=""

    command -v git >/dev/null 2>&1 || return 0
    repo_root="$(installer_hash_guard_git_root_for_script "$script_path" || true)"
    [[ -n "$repo_root" ]] || return 0

    repo_head="$(git -C "$repo_root" rev-parse --short HEAD 2>/dev/null || echo bilinmiyor)"
    status_output="$(git -C "$repo_root" status --short 2>/dev/null || true)"
    warn "${label} git bağlamı: repo=${repo_root}, HEAD=${repo_head}"
    if [[ -n "$status_output" ]]; then
        warn "${label} git status --short:"
        while IFS= read -r status_line; do
            warn "  ${status_line}"
        done <<< "$status_output"
    else
        info "${label} git status --short: temiz"
    fi
}

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
        log_installer_hash_drift_git_context "Mevcut installer" "$current_script"
        log_installer_hash_drift_git_context "Hedef installer" "$next_script"
        fail "${reexec_label} install_sidar.sh SHA256 farklı (mevcut=${current_sha}, hedef=${next_sha}). Yanlış/eski installer çalıştırma riskini önlemek için re-exec durduruldu. NEXT STEP → hash drift kaynağını temizleyin: \$HOME/Sidar/install_sidar.sh eskiyse 'rm -f \"\$HOME/Sidar/install_sidar.sh\"' komutuyla kaldırıp güncel install_sidar.sh ile yeniden deneyin; hedef repo driftliyse git pull --ff-only veya temiz clone kullanın. Yalnız bilinçli/incelemesi yapılmış durumda SIDAR_INSTALL_ALLOW_STALE_REEXEC=1 ile tekrar deneyin."
    fi
}

verify_reexec_installer_or_fail() {
    local next_script="$1"
    local reexec_label="$2"

    check_installer_hash "$ORIGINAL_SCRIPT_PATH" "$next_script" "$reexec_label"
}


sidar_resolve_resume_installer_path() {
    local repo_script="${SCRIPT_DIR:-}/install_sidar.sh"

    if [[ -n "${SCRIPT_DIR:-}" && -f "$repo_script" ]]; then
        printf '%s\n' "$repo_script"
        return 0
    fi

    if [[ -n "${ORIGINAL_SCRIPT_PATH:-}" && -f "$ORIGINAL_SCRIPT_PATH" ]]; then
        printf '%s\n' "$ORIGINAL_SCRIPT_PATH"
        return 0
    fi

    fail "Auto-heal resume için çalıştırılabilir install_sidar.sh bulunamadı. Denenenler: SCRIPT_DIR=${SCRIPT_DIR:-boş}, ORIGINAL_SCRIPT_PATH=${ORIGINAL_SCRIPT_PATH:-boş}. Repo içindeki install_sidar.sh ile kurulumu yeniden başlatın."
}

sidar_verify_resume_installer_or_fail() {
    local resume_script="$1"
    local current_script="${ORIGINAL_SCRIPT_PATH:-}"

    [[ -n "$resume_script" ]] || fail "Auto-heal resume hedefi boş."
    [[ -f "$resume_script" ]] || fail "Auto-heal resume hedef install_sidar.sh bulunamadı: $resume_script"

    if [[ -z "$current_script" || ! -f "$current_script" ]]; then
        current_script="$resume_script"
    fi
    check_installer_hash "$current_script" "$resume_script" "Auto-heal resume re-exec"
}


verify_home_reexec_candidate_if_present() {
    local home_script="$HOME/Sidar/install_sidar.sh"

    [[ -d "$HOME/Sidar/.git" && -f "$home_script" ]] || return 0
    if [[ "${SIDAR_INSTALL_TEST_MODE:-0}" == "1" && "${SIDAR_INSTALL_ALLOW_HOME_REEXEC_IN_TEST_MODE:-0}" != "1" ]]; then
        return 0
    fi

    verify_reexec_installer_or_fail "$home_script" "Mevcut $HOME/Sidar re-exec"
}
