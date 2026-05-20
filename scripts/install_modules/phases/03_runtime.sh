#!/usr/bin/env bash

sidar_phase_runtime_prerequisites() {
    sidar_source_install_utils "gpu_utils.sh"
    ensure_prerequisites
    select_runtime_mode
    detect_gpu
    setup_nvidia_docker
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" != "local" ]]; then
        info "Tam Docker modu: lokal Python/uv ortam kurulumu workspace fazına bırakılmadan atlanacak."
    fi
}
