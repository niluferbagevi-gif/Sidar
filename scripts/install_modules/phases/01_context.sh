#!/usr/bin/env bash

sidar_phase_initialize_context() {
    banner
    report_repo_lookup_context
    detect_environment
    sidar_source_install_utils "wsl_gpu_preflight.sh"
    sidar_source_install_utils "wsl_integration_autofix.sh"
    run_wsl2_gpu_preflight
    if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "${TMPDIR:-/tmp}/sidar_wsl_integration_applied" ]]; then
        info "Docker Desktop WSL Integration preflight tekrar çağrısı atlandı (oturum içinde otomatik düzeltme daha önce uygulandı)."
    else
        ( docker_desktop_wsl_integration_preflight ) || warn "Docker Desktop WSL Integration raporu alınamadı; kurulum non-critical bilgi fazında devam ediyor."
        if [[ "${WSL_INTEGRATION_AUTOFIX_ELIGIBLE:-false}" == "true" ]]; then
            local current_distro="${WSL_DISTRO_NAME:-}"
            if [[ -z "$current_distro" ]] && command -v wsl.exe &>/dev/null; then
                current_distro="$(wsl.exe -l -q 2>/dev/null | iconv -f UTF-16LE -t UTF-8 2>/dev/null | tr -d '\0\r' | awk 'NF {print; exit}' || true)"
            fi
            if [[ -n "$current_distro" ]] && declare -F apply_wsl_integration_autofix >/dev/null 2>&1; then
                info "Preflight sonrası otomatik WSL Integration düzeltmesi deneniyor: '${current_distro}'."
                if ! apply_wsl_integration_autofix "$current_distro"; then
                    warn "Preflight sonrası WSL Integration otomatik düzeltmesi başarısız oldu; kullanıcı onayı istenmeden kurulum devam edecek."
                    warn "Manuel adım gerekli: Docker Desktop > Settings > Resources > WSL Integration > '${current_distro}' toggle'ını açın."
                    warn "Ardından install_sidar.sh komutunu yeniden çalıştırın."
                fi
            fi
        fi
    fi
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
