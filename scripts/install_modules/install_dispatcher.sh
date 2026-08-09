#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck shell=bash
# Phase dispatcher facade for install_sidar.sh.

sidar_dispatch_install_phases() {
    sidar_run_install_phase "01_context" sidar_phase_initialize_context
    sidar_fail_if_wsl_integration_autofix_applied_current_session_main
    if sidar_phase_handle_early_exit; then
        return
    fi

    sidar_run_install_phase "02_repo" sidar_phase_bootstrap_repo_system
    cleanup_bootstrap_script_copy
    sidar_run_install_phase "03_runtime" sidar_phase_runtime_prerequisites
    sidar_run_install_phase "04_workspace" sidar_phase_workspace_config
    sidar_run_install_phase "05_frontend" sidar_phase_frontend_assets
    sidar_run_install_phase "06_models" sidar_phase_local_migrations_and_models
    sidar_run_install_phase "06_services" sidar_phase_services_and_validation
    # Kurulum özeti gösterilmeden önce gerçek çalışma zamanı sağlığını raporla.
    # Doctor bulguları tanısaldır: rapor üretilir, ancak kurulum akışı kesilmez.
    run_doctor_phase || true
    sidar_run_install_phase "07_finish" sidar_phase_finish
}
