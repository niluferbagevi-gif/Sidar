#!/usr/bin/env bash
# Sidar installer phase: post-install service launch, runtime mode and subcommand helpers.

# ── Docker Servislerini Başlatma ──────────────────────────────────────────────
launch_docker_services() {
    local docker_compose_cmd=()
    local compose_profiles=""
    local env_file="$SCRIPT_DIR/.env"
    local runtime_mode="${APP_RUNTIME_MODE_SELECTED:-${APP_RUNTIME_MODE:-docker}}"
    local include_observability="${SIDAR_START_OBSERVABILITY_STACK:-false}"
    local -a infra_services=(postgres redis)

    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        docker_compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        docker_compose_cmd=(docker-compose)
    else
        warn "Sistemde Docker veya Docker Compose bulunamadı, servisler otomatik başlatılamıyor."
        return
    fi

    if [[ -f "$env_file" ]]; then
        compose_profiles=$(read_env_value_from_file "COMPOSE_PROFILES" "$env_file" | tr -d '[:space:]')
    fi
    if [[ -z "$compose_profiles" ]]; then
        if [[ "$GPU_AVAILABLE" == true ]]; then
            compose_profiles="gpu"
        else
            compose_profiles="cpu"
        fi
    fi
    if [[ "$include_observability" == "true" && ",$compose_profiles," != *",observability,"* ]]; then
        compose_profiles="${compose_profiles},observability"
    fi

    if [[ "$runtime_mode" == "ask" ]]; then
        runtime_mode="docker"
        APP_RUNTIME_MODE="$runtime_mode"
        APP_RUNTIME_MODE_SELECTED="$runtime_mode"
        warn "Çalışma modu daha önce seçilmemiş; tekrar menü göstermeden varsayılan 'docker' kullanılacak."
    fi

    echo ""
    local start_prompt="Docker servisleri başlatılsın mı? [E/h] "
    local start_default="E"
    local start_docker=""
    if [[ "$AUTO_START_DOCKER_SERVICES" == "true" ]]; then
        start_docker="E"
        info "AUTO_INSTALL: START_DOCKER_SERVICES=true olduğu için Docker servisleri otomatik başlatılacak."
    elif [[ "$AUTO_START_DOCKER_SERVICES" == "false" ]]; then
        start_docker="H"
        info "AUTO_INSTALL: START_DOCKER_SERVICES=false olduğu için Docker servis başlatma adımı atlanacak."
    elif [[ "$DOCKER_DB_SERVICES_STARTED" == true ]]; then
        info "PostgreSQL/Redis migrasyon adımında zaten başlatıldı; kalan Docker servisleri otomatik başlatılacak."
        start_docker="E"
    elif [[ "$NO_INTERACTION" == true ]]; then
        start_docker="E"
    else
        start_docker=$(prompt_yes_no_with_timeout_default_yes "$start_prompt")
    fi

    case "${start_docker:-$start_default}" in
        [EeYy]*)
            echo "── Docker Servis Kontrolü ──"
            if ensure_docker_daemon_running; then
                echo "✅ Docker motoru erişilebilir."
            else
                warn "Docker motoruna erişilemediği için arka plan servis başlatma adımı atlandı."
                if [[ "$WSL2" == true ]]; then
                    info "$(wsl_integration_remediation_message "${WSL_DISTRO_NAME:-Ubuntu}")"
                fi
                info "Entegrasyon tamamlandıktan sonra manuel çalıştırın: COMPOSE_PROFILES=$compose_profiles ${docker_compose_cmd[*]} up -d"
                return
            fi

            info "Docker Compose servisleri başlatılıyor..."
            if [[ "$include_observability" == "true" ]]; then
                infra_services+=(jaeger prometheus grafana)
                info "Monitoring konfigürasyon dosyaları için bind-mount sanity check çalıştırılıyor..."
                validate_monitoring_mount_paths
            else
                info "Gözlemlenebilirlik yığını varsayılan kurulumda başlatılmayacak. Etkinleştirmek için SIDAR_START_OBSERVABILITY_STACK=true kullanın."
            fi
            if [[ "$runtime_mode" == "local" ]]; then
                info "Seçilen çalışma modu: local (uygulama local + altyapı Docker)"
                if ! check_host_ollama_healthy "$env_file"; then
                    infra_services+=(ollama)
                    info "Host Ollama bulunamadı veya healthy değil; Docker Ollama konteyneri kullanılacak."
                else
                    info "Host Ollama healthy tespit edildi; Docker Ollama konteyneri başlatılmayacak."
                    log_host_ollama_runtime_diagnostics "$env_file"
                fi
                if COMPOSE_PROFILES="$compose_profiles" "${docker_compose_cmd[@]}" up -d "${infra_services[@]}"; then
                    ok "Altyapı Docker servisleri başarıyla başlatıldı (${infra_services[*]})."
                else
                    warn "Altyapı Docker servisleri başlatılamadı. Port çakışması veya Docker kapalı olabilir."
                fi
            else
                info "Seçilen çalışma modu: docker (tüm servisler Docker)"
                info "Docker Compose profili: $compose_profiles"
                if COMPOSE_PROFILES="$compose_profiles" "${docker_compose_cmd[@]}" up -d; then
                    ok "Docker servisleri başarıyla başlatıldı."
                else
                    warn "Docker servisleri başlatılamadı. Port çakışması veya Docker kapalı olabilir."
                fi
            fi
            ;;
        *)
            if [[ "$runtime_mode" == "local" ]]; then
                info "Docker servislerinin başlatılması atlandı. (Manuel: docker compose up -d ${infra_services[*]}; gözlemlenebilirlik için: COMPOSE_PROFILES=observability docker compose up -d jaeger prometheus grafana)"
            else
                info "Docker servislerinin başlatılması atlandı. (Manuel: COMPOSE_PROFILES=$compose_profiles docker compose up -d; gözlemlenebilirlik için profile'a observability ekleyin)"
            fi
            ;;
    esac
}

# ── Çalışma Modu Seçimi ─────────────────────────────────────────────────────
select_runtime_mode() {
    local runtime_mode="${APP_RUNTIME_MODE:-ask}"
    local runtime_answer=""

    if [[ "$runtime_mode" == "ask" ]]; then
        if [[ "$NO_INTERACTION" == true ]]; then
            runtime_mode="docker"
            info "--ci/--no-interaction etkin: çalışma modu varsayılanı 'docker' seçildi."
        else
            echo ""
            info "Çalışma modu seçimi:"
            echo "  1) Geliştirici modu (önerilen): uygulama local, altyapı servisleri Docker"
            echo "  2) Tam Docker modu: web/agent dahil tüm servisler Docker"
            clear_stdin_buffer
            if read -r -t "$SIDAR_PROMPT_TIMEOUT" -p "Seçim [1/2, varsayılan=1]: " runtime_answer 2>/dev/tty; then
                :
            else
                warn "${SIDAR_PROMPT_TIMEOUT} saniye içinde seçim yapılmadı. Varsayılan seçim: 1 (geliştirici modu)."
                runtime_answer="1"
            fi
            case "${runtime_answer:-1}" in
                2) runtime_mode="docker" ;;
                *) runtime_mode="local" ;;
            esac
        fi
    fi

    APP_RUNTIME_MODE="$runtime_mode"
    APP_RUNTIME_MODE_SELECTED="$runtime_mode"

    if [[ "$runtime_mode" == "docker" ]]; then
        info "Seçilen çalışma modu: docker (tam docker akışı uygulanacak)."
    else
        info "Seçilen çalışma modu: local (uygulama local + altyapı Docker)."
    fi
}

# ── Kurulum Sonrası IDE Başlatma ─────────────────────────────────────────────
launch_ide() {
    local vscode_mode="none"
    local vscode_target_path="$SCRIPT_DIR"
    local vscode_exe_path="/mnt/c/Program Files/Microsoft VS Code/Code.exe"

    if [[ "$NO_INTERACTION" == true && "$AUTO_OPEN_VSCODE" != "true" ]]; then
        info "--ci/--no-interaction etkin: IDE açma adımı atlandı."
        return
    fi

    if command -v code &>/dev/null; then
        vscode_mode="code-cli"
    elif [[ "$WSL2" == true ]] && command -v cmd.exe &>/dev/null; then
        if cmd.exe /c "where code" >/dev/null 2>&1; then
            vscode_mode="windows-code-cli"
            if command -v wslpath &>/dev/null; then
                vscode_target_path=$(wslpath -w "$SCRIPT_DIR" 2>/dev/null || echo "$SCRIPT_DIR")
            fi
        else
            local localappdata_path=""
            localappdata_path="$(resolve_windows_localappdata_path 2>/dev/null || true)"
            if [[ -n "$localappdata_path" && -x "${localappdata_path}/Programs/Microsoft VS Code/Code.exe" ]]; then
                vscode_exe_path="${localappdata_path}/Programs/Microsoft VS Code/Code.exe"
            fi
        fi

        if [[ -x "$vscode_exe_path" ]]; then
            vscode_mode="windows-code-exe"
            if command -v wslpath &>/dev/null; then
                vscode_target_path=$(wslpath -w "$SCRIPT_DIR" 2>/dev/null || echo "$SCRIPT_DIR")
            fi
        fi
    fi

    if [[ "$vscode_mode" != "none" ]]; then
        echo ""
        if [[ "$AUTO_OPEN_VSCODE" == "true" ]]; then
            open_code="E"
            info "AUTO_INSTALL: OPEN_VSCODE=true olduğu için VS Code otomatik açılacak."
        elif [[ "$AUTO_OPEN_VSCODE" == "false" ]]; then
            open_code="H"
            info "AUTO_INSTALL: OPEN_VSCODE=false olduğu için VS Code açılmayacak."
        else
            open_code=$(prompt_yes_no_with_timeout_default_yes "Kurulum tamamlandı. Proje VS Code ile açılsın mı? [e/H] ")
        fi
        case "${open_code:-H}" in
            [EeYy]*)
                info "VS Code açılıyor..."
                case "$vscode_mode" in
                    code-cli)
                        code "$SCRIPT_DIR"
                        ;;
                    windows-code-cli)
                        cmd.exe /c code "$vscode_target_path" >/dev/null 2>&1 || warn "Windows code CLI ile VS Code başlatılamadı."
                        ;;
                    windows-code-exe)
                        "$vscode_exe_path" "$vscode_target_path" >/dev/null 2>&1 || warn "Code.exe ile VS Code başlatılamadı."
                        ;;
                esac
                ;;
            *)
                info "VS Code başlatılması atlandı."
                ;;
        esac
    else
        warn "Sistemde VS Code launcher bulunamadı (code PATH, Windows code CLI veya Code.exe)."
        info "WSL ile tam entegrasyon için Windows tarafına VS Code ve 'WSL' eklentisini kurmanız önerilir."
    fi
}


cleanup_bootstrap_script_copy() {
    if [[ "$ORIGINAL_SCRIPT_DIR" == "$TARGET_DIR" ]]; then
        return
    fi

    if [[ "$(basename "$ORIGINAL_SCRIPT_PATH")" != "install_sidar.sh" ]]; then
        return
    fi

    if [[ -d "$ORIGINAL_SCRIPT_DIR/.git" ]]; then
        info "Kurulum farklı bir repo kopyasından çalıştırıldığı için betik dosyası silinmedi: $ORIGINAL_SCRIPT_PATH"
        return
    fi

    local repo_installer="$TARGET_DIR/install_sidar.sh"

    if [[ -f "$ORIGINAL_SCRIPT_PATH" ]]; then
        if rm -f "$ORIGINAL_SCRIPT_PATH"; then
            ok "Geçici kurulum betiği kaldırıldı: $ORIGINAL_SCRIPT_PATH"
        else
            warn "Geçici kurulum betiği silinemedi: $ORIGINAL_SCRIPT_PATH"
        fi
    fi

    if [[ -f "$repo_installer" ]]; then
        ORIGINAL_SCRIPT_PATH="$repo_installer"
        ORIGINAL_SCRIPT_DIR="$TARGET_DIR"
        export ORIGINAL_SCRIPT_PATH ORIGINAL_SCRIPT_DIR
        info "Resume kaynağı repo installer'ına geçirildi: $ORIGINAL_SCRIPT_PATH"
    else
        warn "Repo installer bulunamadı; resume kaynağı güncellenemedi: $repo_installer"
    fi

    info "Kurulum bundan sonra $TARGET_DIR dizininden yönetilmelidir."
}

# ── Terminal kısayolu: Sidar ortamını hızlı aktive et ───────────────────────
setup_shell_activation_shortcut() {
    step "Terminal Kısayolu Yapılandırması"

    local -a rc_files=("$HOME/.bashrc" "$HOME/.zshrc")
    local marker_begin="# >>> Sidar shell helper >>>"
    local marker_end="# <<< Sidar shell helper <<<"
    local helper_body=""
    helper_body=$(cat <<EOF
${marker_begin}
sidar_env() {
  cd "$TARGET_DIR" || return 1
  # shellcheck disable=SC1091
  source "$TARGET_DIR/.venv/bin/activate"
}
alias sidar-env='sidar_env'
${marker_end}
EOF
)

    local rcfile
    for rcfile in "${rc_files[@]}"; do
        [[ -f "$rcfile" ]] || touch "$rcfile"
        if grep -qF "$marker_begin" "$rcfile" 2>/dev/null; then
            info "Sidar terminal kısayolu zaten mevcut: $rcfile"
            continue
        fi
        {
            echo ""
            echo "$helper_body"
        } >> "$rcfile"
        ok "Sidar terminal kısayolu eklendi: $rcfile (kullanım: sidar-env)"
    done
}


run_doctor_phase() {
    step "Sidar Doctor"
    cd "$SCRIPT_DIR" || return 1
    mkdir -p artifacts/install
    local -a doctor_cmd=()
    if command -v uv &>/dev/null; then
        doctor_cmd=(uv run python -m core.doctor artifacts/install/doctor.json)
    elif command -v python3 &>/dev/null; then
        doctor_cmd=(python3 -m core.doctor artifacts/install/doctor.json)
    else
        fail "Doctor çalıştırmak için python3 veya uv bulunamadı."
    fi

    if SIDAR_CONFIG_QUIET=1 "${doctor_cmd[@]}"; then
        ok "Doctor raporu üretildi: artifacts/install/doctor.json"
    else
        warn "Doctor raporu üretildi ancak bir veya daha fazla kontrol fail durumunda. Rapor: artifacts/install/doctor.json"
        return 1
    fi
}

run_prepare_system_phase() {
    install_system_dependencies
    sync_repo
    cd "$SCRIPT_DIR" || return 1
    ensure_prerequisites
    select_runtime_mode
    detect_gpu
    setup_nvidia_docker
    create_directories
    setup_env_file
    ok "prepare-system fazı tamamlandı."
}

run_sync_deps_phase() {
    cd "$SCRIPT_DIR" || return 1
    ensure_prerequisites
    select_runtime_mode
    detect_gpu
    install_uv_cli
    create_uv_venv
    install_python_deps
    install_pyright_lsp_tool
    verify_torch_cuda
    ok "sync-deps fazı tamamlandı."
}

run_provision_models_phase() {
    cd "$SCRIPT_DIR" || return 1
    ensure_prerequisites
    detect_gpu
    setup_env_file
    download_ollama_models
    ok "provision-models fazı tamamlandı."
}

run_smoke_phase() {
    cd "$SCRIPT_DIR" || return 1
    ensure_prerequisites
    detect_gpu
    prepare_docker_for_migrations
    run_migrations
    seed_rag_metadata_after_migrations
    run_smoke_tests
    run_install_integration_api_tests
    run_install_frontend_quality_validation
    run_test_artifact_audit
    run_install_ci_full_validation
    run_doctor_phase || true
    ok "smoke fazı tamamlandı."
}

run_install_subcommand_if_requested() {
    case "$INSTALL_SUBCOMMAND" in
        full) return 1 ;;
        doctor)
            run_doctor_phase
            return 0
            ;;
        prepare-system)
            run_prepare_system_phase
            return 0
            ;;
        sync-deps)
            run_sync_deps_phase
            return 0
            ;;
        provision-models)
            run_provision_models_phase
            return 0
            ;;
        smoke)
            run_smoke_phase
            return 0
            ;;
    esac
    return 1
}

sidar_fail_if_wsl_integration_autofix_applied_current_session_main() {
    if [[ "$WSL2" == true && ("${WSL_INTEGRATION_AUTOFIX_APPLIED:-false}" == "true" || -f "${TMPDIR:-/tmp}/sidar_wsl_integration_applied") ]]; then
        fail "WSL integration ilk defa açıldı. Lütfen Windows'tan wsl --shutdown çalıştırın, Ubuntu'ya yeniden girin ve ./install_sidar.sh komutunu tekrar başlatın."
    fi
}

