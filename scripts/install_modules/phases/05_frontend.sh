#!/usr/bin/env bash

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
