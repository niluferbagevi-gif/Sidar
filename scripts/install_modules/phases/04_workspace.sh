#!/usr/bin/env bash

sidar_phase_workspace_config() {
    sidar_source_install_utils "python_env.sh" "db_credentials.sh" "env_utils.sh"
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        # Modern paket yönetimi standardı: ortam kurulumu yalnızca uv venv + uv sync ile yapılır.
        install_uv_cli
        create_uv_venv
        install_python_deps
        install_pyright_lsp_tool
        verify_torch_cuda
    else
        info "Tam Docker modu: lokal Python/uv ortam kurulumu atlanıyor."
    fi
    create_directories
    # VS Code ayarları, Python yorumlayıcı yolu belli olduktan sonra erken hazırlanabilir.
    setup_vscode_workspace
    setup_env_file
}
