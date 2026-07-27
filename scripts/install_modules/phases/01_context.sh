#!/usr/bin/env bash
set -Eeuo pipefail

normalize_bool() {
    local value="${1:-}"
    value=$(echo "$value" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    case "$value" in
        1|true|yes|y|evet|e) echo "true" ;;
        0|false|no|n|hayir|h|hayır) echo "false" ;;
        *) echo "" ;;
    esac
}

resolve_runtime_mode_choice() {
    local raw="${1:-}"
    raw=$(echo "$raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    case "$raw" in
        1|local|dev|developer|gelistirici|geliştirici) echo "local" ;;
        2|docker|full|full-docker|tam-docker) echo "docker" ;;
        *) echo "ask" ;;
    esac
}

resolve_env_type_choice() {
    local raw="${1:-}"
    raw=$(echo "$raw" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
    case "$raw" in
        1|dev|development|gelistirme|geliştirme) echo "development" ;;
        2|prod|production|canli|canlı) echo "production" ;;
        *) echo "ask" ;;
    esac
}

_visible_width() {
    local value="${1-}"
    python3 - "$value" <<'PY'
import sys
import unicodedata

text = sys.argv[1] if len(sys.argv) > 1 else ""
width = 0
for ch in text:
    if unicodedata.combining(ch):
        continue
    width += 2 if unicodedata.east_asian_width(ch) in {"F", "W"} else 1
print(width)
PY
}

_pad_visible() {
    local value="${1-}" target_width="${2:-0}"
    local current_width pad_len
    current_width="$(_visible_width "$value")"
    pad_len=$(( target_width - current_width ))
    if (( pad_len < 0 )); then
        pad_len=0
    fi
    printf '%s%*s' "$value" "$pad_len" ""
}

_center_visible() {
    local value="${1-}" target_width="${2:-60}"
    local current_width left_pad right_pad
    current_width="$(_visible_width "$value")"
    left_pad=$(( (target_width - current_width) / 2 ))
    (( left_pad < 0 )) && left_pad=0
    right_pad=$(( target_width - current_width - left_pad ))
    (( right_pad < 0 )) && right_pad=0
    printf '%*s%s%*s' "$left_pad" "" "$value" "$right_pad" ""
}

banner() {

    local version_suffix=""
    local banner_text=""
    local centered_banner=""
    if [[ "$INSTALL_SIDAR_VERSION" != "0.0.0" ]]; then
        version_suffix=" (v$INSTALL_SIDAR_VERSION)"
    fi
    banner_text="$(sidar_t banner_title)${version_suffix}"
    centered_banner="$(_center_visible "$banner_text" 60)"

    echo -e "${BOLD}${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    printf "║%s║\n" "$(_pad_visible "$centered_banner" 60)"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

ensure_noninteractive_sudo_ready() {
    if [[ "$EUID" -eq 0 ]]; then
        info "$(sidar_t root_install)"
        return 0
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        if [[ "$NO_INTERACTION" == true || "$SILENT_MODE" == true || "$AUTO_INSTALL" == true ]]; then
            fail "$(sidar_t sudo_missing_noninteractive)"
        fi
        return 0
    fi

    if [[ "$NO_INTERACTION" == true || "$SILENT_MODE" == true || "$AUTO_INSTALL" == true ]]; then
        if sudo -n -v >/dev/null 2>&1; then
            ok "$(sidar_t sudo_ready)"
        else
            fail "$(sidar_t sudo_blocked)"
        fi
    fi
}



sidar_warn_if_repo_on_windows_mount() {
    [[ "$WSL2" == true ]] || return 0
    case "${SCRIPT_DIR:-}" in
        /mnt/*)
            warn "Repo, Windows dosya sisteminde çalışıyor gibi görünüyor (${SCRIPT_DIR})."
            warn "Docker'ın resmi WSL önerisi kaynak kodun WSL'nin kendi Linux dosya sisteminde (örn. \$HOME altında) tutulmasıdır;"
            warn "/mnt/c gibi Windows sürücüleri 9p/DrvFs üzerinden erişildiği için kayda değer ölçüde yavaş olabilir ve dosya"
            warn "izni/symlink davranışı farklılık gösterebilir."
            info "Önerilen: cd \"\$HOME\" && git clone https://github.com/niluferbagevi-gif/Sidar.git && cd Sidar && ./install_sidar.sh"
            ;;
    esac
}

sidar_fail_if_wsl_integration_autofix_applied_current_session() {
    if [[ "$WSL2" == true && ("${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "${TMPDIR:-/tmp}/sidar_wsl_integration_applied") ]]; then
        fail "WSL integration ilk defa açıldı. Lütfen Windows'tan wsl --shutdown çalıştırın, Ubuntu'ya yeniden girin ve ./install_sidar.sh komutunu tekrar başlatın."
    fi
}

sidar_phase_initialize_context() {
    banner
    report_repo_lookup_context
    detect_environment
    sidar_warn_if_repo_on_windows_mount
    sidar_source_install_utils "wsl_gpu_preflight.sh"
    sidar_source_install_utils "wsl_integration_autofix.sh"
    run_wsl2_gpu_preflight
    sidar_fail_if_wsl_integration_autofix_applied_current_session
    if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "${TMPDIR:-/tmp}/sidar_wsl_integration_applied" ]]; then
        info "Docker Desktop WSL Integration preflight tekrar çağrısı atlandı (oturum içinde otomatik düzeltme daha önce uygulandı)."
    else
        ( docker_desktop_wsl_integration_preflight ) || warn "Docker Desktop WSL Integration raporu alınamadı; kurulum non-critical bilgi fazında devam ediyor."
        if [[ "${WSL_INTEGRATION_AUTOFIX_ELIGIBLE:-false}" == "true" ]]; then
            local current_distro="${WSL_DISTRO_NAME:-}"
            if [[ -z "$current_distro" ]] && command -v wsl.exe &>/dev/null; then
                current_distro="$(wsl.exe -l -q 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}' || true)"
            fi
            if docker info >/dev/null 2>&1 || [[ -S /var/run/docker.sock ]]; then
                ok "Docker daemon zaten yanıt veriyor; preflight sonrası ikinci WSL Integration autofix denemesi atlandı."
                export WSL_INTEGRATION_AUTOFIX_ELIGIBLE=false
            elif [[ -n "$current_distro" ]] && declare -F apply_wsl_integration_autofix >/dev/null 2>&1; then
                info "Preflight sonrası otomatik WSL Integration düzeltmesi deneniyor: '${current_distro}'."
                if ! apply_wsl_integration_autofix "$current_distro"; then
                    if [[ "${WSL_INTEGRATION_RESTART_REQUIRED:-false}" == "true" || -f "${TMPDIR:-/tmp}/sidar_wsl_integration_restart_required" ]]; then
                        fail "Docker Desktop WSL Integration ayarı yazıldı; socket mount'un yeni oturuma enjekte edilmesi için Windows PowerShell'de 'wsl --shutdown' çalıştırın, Ubuntu'yu yeniden açın ve install_sidar.sh komutunu tekrar başlatın."
                    fi
                    warn "Preflight sonrası WSL Integration otomatik düzeltmesi başarısız oldu; kullanıcı onayı istenmeden kurulum devam edecek."
                    warn "Manuel adım gerekli: Docker Desktop > Settings > Resources > WSL Integration > '${current_distro}' toggle'ını açın."
                    warn "Ardından install_sidar.sh komutunu yeniden çalıştırın."
                fi
            else
                warn "WSL Integration autofix için geçerli distro tespit edilemedi; manuel kontrol önerilir."
            fi
        fi
    fi
    sidar_fail_if_wsl_integration_autofix_applied_current_session
    if [[ "$OFFLINE_MODE" == true ]]; then
        OFFLINE_PACKAGES_DIR="$(resolve_offline_packages_dir || true)"
        if [[ -n "$OFFLINE_PACKAGES_DIR" ]]; then
            info "Çevrimdışı/air-gapped mod etkin. Paket kaynağı: $OFFLINE_PACKAGES_DIR"
            verify_offline_bundle_manifest "$OFFLINE_PACKAGES_DIR"
        else
            fail "Çevrimdışı mod etkin ancak offline_packages dizini bulunamadı."
        fi
    fi
}

sidar_phase_handle_early_exit() {
    if [[ "$INSTALL_SUBCOMMAND" == "doctor" ]]; then
        run_doctor_phase
        return 0
    fi

    ensure_noninteractive_sudo_ready

    if run_install_subcommand_if_requested; then
        relocate_log_file_if_needed
        cleanup_bootstrap_script_copy
        return 0
    fi

    if [[ "$INSTALL_KUBERNETES" == true ]]; then
        info "--kubernetes/--helm modu aktif: yerel bağımlılık kurulumu atlanacak, Helm dağıtımı yapılacak."
        deploy_with_helm
        return 0
    fi

    return 1
}
