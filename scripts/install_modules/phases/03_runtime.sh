#!/usr/bin/env bash

sidar_phase_runtime_prerequisites() {
    ensure_prerequisites
    select_runtime_mode_early
    detect_gpu
    setup_nvidia_docker
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        # uv-venv akışı: önce uv kur/güncelle, sonra venv oluştur
        setup_uv
        setup_python_env
        install_python_deps
        install_pyright_lsp_tool
        verify_torch_cuda
    else
        info "Tam Docker modu: lokal Python/Conda ortam kurulumu atlanıyor."
    fi
}
