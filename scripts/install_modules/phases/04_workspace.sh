#!/usr/bin/env bash

sidar_precheck_workspace_ownership() {
    local expected_user="${USER:-$(id -un)}"
    local ownership_anomaly=""

    ownership_anomaly="$(find "$SCRIPT_DIR" -not -user "$expected_user" -print -quit 2>/dev/null || true)"
    if [[ -n "$ownership_anomaly" ]]; then
        warn "Sahiplik anomalisi tespit edildi: $ownership_anomaly"
        warn "Bu durum genellikle kurulumun daha önce sudo/root ile çalıştırılmasından kaynaklanır ve permission denied hatalarına yol açar."
        warn "Düzeltme: sudo chown -R \"$expected_user:$expected_user\" \"$SCRIPT_DIR\""
    fi
}

sidar_phase_workspace_config() {
    sidar_source_install_utils "python_env.sh" "db_credentials.sh" "env_utils.sh"
    sidar_precheck_workspace_ownership
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" == "local" ]]; then
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
