#!/usr/bin/env bash

sidar_phase_runtime_pin_python_version() {
    local enforced_python_version="3.11"

    if [[ -n "${PYTHON_VERSION:-}" && "${PYTHON_VERSION}" != "${enforced_python_version}" ]]; then
        warn "PYTHON_VERSION=${PYTHON_VERSION} algılandı; runtime kararlılığı için ${enforced_python_version} zorunlu olarak uygulanacak."
    fi

    export PYTHON_VERSION="${enforced_python_version}"
    info "Runtime Python sürümü sabitlendi: ${PYTHON_VERSION} (uv venv --python ${PYTHON_VERSION})."
}

sidar_phase_runtime_prerequisites() {
    sidar_phase_runtime_pin_python_version
    sidar_source_install_utils "gpu_utils.sh"
    ensure_prerequisites
    select_runtime_mode
    detect_gpu
    setup_nvidia_docker
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" != "local" ]]; then
        info "Tam Docker modu: lokal Python/uv ortam kurulumu workspace fazına bırakılmadan atlanacak."
    fi
}
