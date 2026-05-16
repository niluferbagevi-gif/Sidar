#!/usr/bin/env bash

sidar_phase_runtime_prerequisites() {
    sidar_source_install_utils "gpu_utils.sh"
    ensure_prerequisites
    select_runtime_mode
    detect_gpu
    setup_nvidia_docker
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        # uv akışı: önce CLI kur/güncelle, sonra venv oluştur
        install_uv_cli
        create_uv_venv
        install_python_deps
        install_pyright_lsp_tool
        verify_torch_cuda
    else
        info "Tam Docker modu: lokal Python/Conda ortam kurulumu atlanıyor."
    fi
}
