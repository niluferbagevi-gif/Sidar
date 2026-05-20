#!/usr/bin/env bash

sidar_phase_initialize_context() {
    banner
    report_repo_lookup_context
    detect_environment
    sidar_source_install_utils "wsl_gpu_preflight.sh"
    run_wsl2_gpu_preflight
    if [[ "${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "${TMPDIR:-/tmp}/sidar_wsl_integration_applied" ]]; then
        info "Docker Desktop WSL Integration preflight tekrar çağrısı atlandı (oturum içinde otomatik düzeltme daha önce uygulandı)."
    else
        ( docker_desktop_wsl_integration_preflight ) || warn "Docker Desktop WSL Integration raporu alınamadı; kurulum non-critical bilgi fazında devam ediyor."
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
