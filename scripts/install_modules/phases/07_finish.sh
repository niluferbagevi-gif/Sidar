#!/usr/bin/env bash

sidar_ensure_autonomy_scripts_executable() {
    local loop_script="${SCRIPT_DIR}/autonomous_loop.sh"
    local heal_script="${SCRIPT_DIR}/scripts/auto_heal.py"

    [[ -f "${loop_script}" ]] || fail "autonomous_loop.sh bulunamadı: ${loop_script}"
    [[ -f "${heal_script}" ]] || fail "auto_heal.py bulunamadı: ${heal_script}"

    chmod +x "${loop_script}" "${heal_script}"
    ok "Otonom döngü betikleri çalıştırılabilir olarak ayarlandı."
}

sidar_phase_finish() {
    sidar_ensure_autonomy_scripts_executable
    print_summary
    relocate_log_file_if_needed
    cleanup_bootstrap_script_copy
    prompt_post_install_sidar_env_mode
    # En son adım: IDE başlatma onayı
    launch_ide
}
