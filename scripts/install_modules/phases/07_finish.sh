#!/usr/bin/env bash

sidar_ensure_autonomy_scripts_executable() {
    local loop_script="${SCRIPT_DIR}/autonomous_loop.sh"
    local heal_script="${SCRIPT_DIR}/scripts/auto_heal.py"

    [[ -f "${loop_script}" ]] || fail "autonomous_loop.sh bulunamadı: ${loop_script}"
    [[ -f "${heal_script}" ]] || fail "auto_heal.py bulunamadı: ${heal_script}"

    chmod +x "${loop_script}" "${heal_script}"
    ok "Otonom döngü betikleri çalıştırılabilir olarak ayarlandı."
}

sidar_shell_single_quote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

sidar_configure_autonomous_cron() {
    local loop_script="${SCRIPT_DIR}/autonomous_loop.sh"
    local systemd_user_dir="${HOME}/.config/systemd/user"
    local service_file="${systemd_user_dir}/sidar-autonomous-loop.service"
    local timer_file="${systemd_user_dir}/sidar-autonomous-loop.timer"
    local cron_marker="# Sidar autonomous loop"
    local cron_line=""
    local quoted_script quoted_dir quoted_lock quoted_log

    if [[ "${ENABLE_AUTONOMOUS_CRON:-false}" != true ]]; then
        AUTONOMOUS_CRON_STATUS="atlandi_bayrak"
        info "Otonom döngü zamanlayıcısı opt-in kapalı. Etkinleştirmek için: ./install_sidar.sh --enable-autonomous-cron"
        return 0
    fi

    [[ -f "${loop_script}" ]] || fail "autonomous_loop.sh bulunamadı: ${loop_script}"
    mkdir -p "${SCRIPT_DIR}/logs"

    if command -v systemctl >/dev/null 2>&1 && systemctl --user is-system-running >/dev/null 2>&1; then
        mkdir -p "${systemd_user_dir}"
        cat > "${service_file}" <<EOF
[Unit]
Description=Sidar autonomous self-healing loop

[Service]
Type=oneshot
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${loop_script}
EOF
        cat > "${timer_file}" <<'EOF'
[Unit]
Description=Run Sidar autonomous self-healing loop hourly

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=5m

[Install]
WantedBy=timers.target
EOF
        systemctl --user daemon-reload
        systemctl --user enable --now sidar-autonomous-loop.timer
        AUTONOMOUS_CRON_STATUS="systemd_timer"
        ok "Otonom döngü systemd kullanıcı timer olarak kuruldu: sidar-autonomous-loop.timer"
        return 0
    fi

    if command -v crontab >/dev/null 2>&1; then
        quoted_dir="$(sidar_shell_single_quote "${SCRIPT_DIR}")"
        quoted_script="$(sidar_shell_single_quote "${loop_script}")"
        quoted_lock="$(sidar_shell_single_quote "${SCRIPT_DIR}/.sidar_autonomous_loop.lock")"
        quoted_log="$(sidar_shell_single_quote "${SCRIPT_DIR}/logs/autonomous_loop.cron.log")"
        cron_line="0 * * * * cd ${quoted_dir} && flock -n ${quoted_lock} ${quoted_script} >> ${quoted_log} 2>&1 ${cron_marker}"
        (crontab -l 2>/dev/null | sed "/${cron_marker}$/d"; printf '%s\n' "${cron_line}") | crontab -
        AUTONOMOUS_CRON_STATUS="crontab"
        ok "Otonom döngü kullanıcı crontab satırı olarak kuruldu."
        return 0
    fi

    # shellcheck disable=SC2034  # install_sidar.sh print_summary tarafından okunuyor.
    AUTONOMOUS_CRON_STATUS="manuel_gerekli"
    warn "Otonom döngü zamanlayıcısı kurulamadı: systemd user timer ve crontab kullanılamıyor. Manuel öneri: ${loop_script}"
}

sidar_phase_finish() {
    sidar_ensure_autonomy_scripts_executable
    sidar_configure_autonomous_cron
    print_summary
    relocate_log_file_if_needed
    cleanup_bootstrap_script_copy
    prompt_post_install_sidar_env_mode
    # En son adım: IDE başlatma onayı
    launch_ide
}
