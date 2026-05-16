#!/usr/bin/env bash

sidar_phase_workspace_config() {
    sidar_source_install_utils "db_credentials.sh" "env_utils.sh"
    create_directories
    # VS Code ayarları, Python yorumlayıcı yolu belli olduktan sonra erken hazırlanabilir.
    setup_vscode_workspace
    setup_env_file
}
