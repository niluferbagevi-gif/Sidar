#!/usr/bin/env bash
set -Eeuo pipefail

sidar_run_or_warn() {
    local description="$1"
    shift
    local output=""
    if output="$("$@" 2>&1)"; then
        return 0
    fi
    warn "${description} başarısız oldu${output:+: ${output}}"
    return 1
}

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

# ── 9. Dizinleri oluştur ──────────────────────────────────────────────────────
create_directories() {
    step "Proje Dizinleri"
    for dir in "${REQUIRED_DIRS[@]}"; do
        mkdir -p "$SCRIPT_DIR/$dir"
        sidar_run_or_warn "chmod 755 \"$SCRIPT_DIR/$dir\"" chmod 755 "$SCRIPT_DIR/$dir" || true
    done

    # Tam Docker modunda container kullanıcı UID/GID (10001) bind-mount dizinlerine
    # yazabilmelidir; aksi halde /app/logs gibi yolarda Permission denied oluşur.
    local runtime_mode="${APP_RUNTIME_MODE_SELECTED:-${APP_RUNTIME_MODE:-${AUTO_RUNTIME_MODE:-ask}}}"
    if [[ "$runtime_mode" == "docker" ]]; then
        local -a docker_bind_dirs=(logs data temp sessions)
        local bind_dir=""
        for bind_dir in "${docker_bind_dirs[@]}"; do
            mkdir -p "$SCRIPT_DIR/$bind_dir"
            sidar_run_or_warn "chown 10001:10001 \"$SCRIPT_DIR/$bind_dir\"" chown 10001:10001 "$SCRIPT_DIR/$bind_dir" || true
            sidar_run_or_warn "chmod u+rwx,g+rx,o+rx \"$SCRIPT_DIR/$bind_dir\"" chmod u+rwx,g+rx,o+rx "$SCRIPT_DIR/$bind_dir" || true
            if command -v setfacl &>/dev/null; then
                sidar_run_or_warn "setfacl -m u:10001:rwx \"$SCRIPT_DIR/$bind_dir\"" setfacl -m u:10001:rwx "$SCRIPT_DIR/$bind_dir" || true
            fi
        done
    fi

    local log_file="$SCRIPT_DIR/logs/sidar_system.log"
    if [[ -f "$log_file" && ! -w "$log_file" ]]; then
        if [[ "${APP_RUNTIME_MODE_SELECTED:-${APP_RUNTIME_MODE:-${AUTO_RUNTIME_MODE:-ask}}}" == "docker" ]]; then
            sidar_run_or_warn "chown 10001:10001 \"$log_file\"" chown 10001:10001 "$log_file" || true
            if command -v setfacl &>/dev/null; then
                sidar_run_or_warn "setfacl -m u:10001:rw \"$log_file\"" setfacl -m u:10001:rw "$log_file" || true
            fi
        else
            sidar_run_or_warn "chown \"$(id -u):$(id -g)\" \"$log_file\"" chown "$(id -u):$(id -g)" "$log_file" || true
        fi
        sidar_run_or_warn "chmod u+rw \"$log_file\"" chmod u+rw "$log_file" || true
    fi

    if [[ -f "$SCRIPT_DIR/run_tests.sh" ]]; then
        chmod +x "$SCRIPT_DIR/run_tests.sh"
    fi
    ok "Dizinler hazır: ${REQUIRED_DIRS[*]}"
}

# ── VS Code Çalışma Alanı Hazırlığı ──────────────────────────────────────────
setup_vscode_workspace() {
    step "VS Code Çalışma Alanı Hazırlığı"
    local vscode_dir="$SCRIPT_DIR/.vscode"

    mkdir -p "$vscode_dir"

    local python_path="$SCRIPT_DIR/.venv/bin/python"

    cat > "$vscode_dir/settings.json" <<EOF
{
    "python.defaultInterpreterPath": "${python_path}",
    "python.terminal.activateEnvironment": true,
    "terminal.integrated.defaultProfile.linux": "bash"
}
EOF

    ok "VS Code çalışma alanı yapılandırıldı (.vscode/settings.json)."
}


sidar_phase_workspace_config() {
    sidar_source_install_utils "python_env.sh" "database_url.sh" "db_credentials.sh" "env_utils.sh"
    sidar_precheck_workspace_ownership
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" == "local" ]]; then
        # Modern paket yönetimi standardı: ortam kurulumu yalnızca uv venv + uv sync ile yapılır.
        install_uv_cli
        create_uv_venv
        install_python_deps
        install_pre_commit_hooks
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
