#!/usr/bin/env bash

sidar_ensure_autonomy_scripts_executable() {
    local loop_script="${SCRIPT_DIR}/autonomous_loop.sh"
    local heal_script="${SCRIPT_DIR}/scripts/auto_heal.py"

    [[ -f "${loop_script}" ]] || fail "autonomous_loop.sh bulunamadı: ${loop_script}"
    [[ -f "${heal_script}" ]] || fail "auto_heal.py bulunamadı: ${heal_script}"

    chmod +x "${loop_script}" "${heal_script}"
    ok "Otonom döngü betikleri çalıştırılabilir olarak ayarlandı."
}

sidar_shell_single_quote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

sidar_configure_autonomous_cron() {
    local loop_script="${SCRIPT_DIR}/autonomous_loop.sh"
    local systemd_user_dir="${HOME}/.config/systemd/user"
    local service_file="${systemd_user_dir}/sidar-autonomous-loop.service"
    local timer_file="${systemd_user_dir}/sidar-autonomous-loop.timer"
    local cron_marker="# Sidar autonomous loop"
    local cron_line=""
    local quoted_script quoted_dir quoted_lock quoted_log

    if [[ "${ENABLE_AUTONOMOUS_CRON:-false}" != true ]]; then
        AUTONOMOUS_CRON_STATUS="atlandi_bayrak"
        info "Otonom döngü zamanlayıcısı opt-in kapalı. Etkinleştirmek için: ./install_sidar.sh --enable-autonomous-cron"
        return 0
    fi

    [[ -f "${loop_script}" ]] || fail "autonomous_loop.sh bulunamadı: ${loop_script}"
    mkdir -p "${SCRIPT_DIR}/logs"

    if command -v systemctl >/dev/null 2>&1 && systemctl --user is-system-running >/dev/null 2>&1; then
        mkdir -p "${systemd_user_dir}"
        cat > "${service_file}" <<EOF
[Unit]
Description=Sidar autonomous self-healing loop

[Service]
Type=oneshot
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${loop_script}
EOF
        cat > "${timer_file}" <<'EOF'
[Unit]
Description=Run Sidar autonomous self-healing loop hourly

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=5m

[Install]
WantedBy=timers.target
EOF
        systemctl --user daemon-reload
        systemctl --user enable --now sidar-autonomous-loop.timer
        AUTONOMOUS_CRON_STATUS="systemd_timer"
        ok "Otonom döngü systemd kullanıcı timer olarak kuruldu: sidar-autonomous-loop.timer"
        return 0
    fi

    if command -v crontab >/dev/null 2>&1; then
        quoted_dir="$(sidar_shell_single_quote "${SCRIPT_DIR}")"
        quoted_script="$(sidar_shell_single_quote "${loop_script}")"
        quoted_lock="$(sidar_shell_single_quote "${SCRIPT_DIR}/.sidar_autonomous_loop.lock")"
        quoted_log="$(sidar_shell_single_quote "${SCRIPT_DIR}/logs/autonomous_loop.cron.log")"
        cron_line="0 * * * * cd ${quoted_dir} && flock -n ${quoted_lock} ${quoted_script} >> ${quoted_log} 2>&1 ${cron_marker}"
        (crontab -l 2>/dev/null | sed "/${cron_marker}$/d"; printf '%s\n' "${cron_line}") | crontab -
        AUTONOMOUS_CRON_STATUS="crontab"
        ok "Otonom döngü kullanıcı crontab satırı olarak kuruldu."
        return 0
    fi

    # shellcheck disable=SC2034 # AUTONOMOUS_CRON_STATUS bats testleri ve install özet raporu tarafından okunur.
    AUTONOMOUS_CRON_STATUS="manuel_gerekli"
    warn "Otonom döngü zamanlayıcısı kurulamadı: systemd user timer ve crontab kullanılamıyor. Manuel öneri: ${loop_script}"
}


sidar_install_summary_field_or_empty() {
    local field="$1"
    if declare -F read_install_test_summary_field >/dev/null 2>&1; then
        read_install_test_summary_field "$field" 2>/dev/null || true
    fi
}

sidar_install_summary_all_passed() {
    local field value
    for field in "$@"; do
        value="$(sidar_install_summary_field_or_empty "$field")"
        [[ "$value" == "passed" ]] || return 1
    done
    return 0
}

sidar_install_summary_any_failed() {
    local field value
    for field in "$@"; do
        value="$(sidar_install_summary_field_or_empty "$field")"
        [[ "$value" == "failed" ]] && return 0
    done
    return 1
}

print_install_summary_extended_test_statuses() {
    local summary_integration=""
    summary_integration="$(sidar_install_summary_field_or_empty integration)"
    if [[ "$summary_integration" == "passed" ]]; then
        echo "  Entegrasyon testleri: başarılı (run_tests.sh --stage all içinde doğrulandı)."
    elif [[ "$summary_integration" == "failed" ]]; then
        echo "  Entegrasyon testleri: hata var (run_tests.sh --stage all çıktısında doğrulandı). Tekrar için: bash run_tests.sh --stage integration"
    elif [[ "$INTEGRATION_TEST_STATUS" == "tamamlandi" ]]; then
        echo "  Entegrasyon testleri: başarılı (run_tests.sh --stage integration)."
    elif [[ "$INTEGRATION_TEST_STATUS" == "hata" ]]; then
        echo "  Entegrasyon testleri: hata var. Tekrar için: bash run_tests.sh --stage integration"
    else
        echo "  Entegrasyon testleri: atlandı (${INTEGRATION_TEST_STATUS}). Çalıştırmak için: ./install_sidar.sh --with-integration"
        echo "  Backend entegrasyon kapsamı için: bash run_tests.sh --stage integration"
        echo "  Frontend kalite kapısı ayrı stage'dir: bash run_tests.sh --stage frontend"
    fi

    local summary_e2e=""
    summary_e2e="$(sidar_install_summary_field_or_empty e2e)"
    if [[ "$summary_e2e" == "passed" ]]; then
        echo "  E2E testleri: başarılı (run_tests.sh --stage all içinde doğrulandı)."
    elif [[ "$summary_e2e" == "failed" ]]; then
        echo "  E2E testleri: hata var (run_tests.sh --stage all çıktısında doğrulandı). Tekrar için: bash run_tests.sh --stage e2e"
    elif [[ "$summary_e2e" == "skipped" ]]; then
        echo "  E2E testleri: atlandı (artifacts/test-summary.json). Çalıştırmak için: bash run_tests.sh --stage e2e"
    else
        echo "  E2E testleri: durum özeti yok. Doğrulamak için: bash run_tests.sh --stage e2e"
    fi

    if sidar_install_summary_all_passed frontend_lint frontend_typecheck frontend_coverage frontend_e2e; then
        echo "  Frontend kalite kapısı: başarılı (run_tests.sh --stage all içinde lint/typecheck/coverage/e2e doğrulandı)."
    elif sidar_install_summary_any_failed frontend_lint frontend_typecheck frontend_coverage frontend_e2e; then
        echo "  Frontend kalite kapısı: hata var (artifacts/test-summary.json). Tekrar için: RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend"
    elif [[ "$FRONTEND_QUALITY_STATUS" == "tamamlandi" ]]; then
        echo "  Frontend kalite kapısı: başarılı (run_tests.sh --stage frontend)."
    elif [[ "$FRONTEND_QUALITY_STATUS" == "hata" ]]; then
        echo "  Frontend kalite kapısı: hata var. Tekrar için: RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend"
    else
        echo "  Frontend kalite kapısı: atlandı (${FRONTEND_QUALITY_STATUS}). Çalıştırmak için: RUN_FRONTEND_E2E=1 bash run_tests.sh --stage frontend"
    fi
}

print_react_frontend_qa_status_block() {
    local frontend_status="${FRONTEND_QUALITY_STATUS:-atlandi_bayrak}"
    local frontend_quality_command="cd web_ui_react && npm run lint && npm run typecheck && npm run test:coverage && npm run test:e2e:smoke"

    if [[ "$frontend_status" == "tamamlandi" ]]; then
        echo -e "       ${GREEN}✅ Frontend QA: lint/typecheck/coverage/e2e smoke tamamlandı.${NC}"
        return
    fi

    echo ""
    if [[ "$frontend_status" == "hata" ]]; then
        echo -e "       ${RED}${BOLD}❌ FRONTEND QA BAŞARISIZ${NC}"
        echo -e "       ${RED}React build çıktısı oluşmuş olabilir; ancak build geçti ≠ frontend QA geçti.${NC}"
        echo -e "       ${RED}Başarısız kalite kapısını düzeltip tekrar çalıştırın:${NC}"
    else
        echo -e "       ${YELLOW}${BOLD}⚠️  FRONTEND QA ÇALIŞTIRILMADI${NC}"
        echo -e "       ${YELLOW}React build geçti ≠ frontend QA geçti.${NC}"
        echo -e "       ${YELLOW}Lint, typecheck, coverage ve e2e smoke henüz doğrulanmadı.${NC}"
        echo -e "       ${YELLOW}Ayrı frontend kalite kapısını çalıştırın:${NC}"
    fi
    echo "       ${frontend_quality_command}"
    echo ""
}

print_release_readiness_next_action() {
    local ci_status="${CI_FULL_VALIDATION_STATUS:-atlandi_bayrak}"
    local production_ready=""
    production_ready="$(sidar_install_summary_field_or_empty production_ready)"

    echo -e "  ${BOLD}🚦 Release / merge readiness:${NC}"
    if [[ "$production_ready" == "true" ]]; then
        echo -e "       ${GREEN}✅ Production readiness geçti.${NC}"
        echo "       Release/merge kapısı tamamlandı: make production-readiness"
        return
    fi

    if [[ "$ci_status" == "tamamlandi" ]]; then
        echo -e "       ${GREEN}✅ Development validation geçti.${NC}"
        echo -e "       ${YELLOW}${BOLD}⚠️  Bu sonuç yalnız yerel geliştirme ortamının sağlıklı olduğunu gösterir.${NC}"
    elif [[ "$ci_status" == "hata" ]]; then
        echo -e "       ${RED}❌ Development validation hata verdi; önce run_tests.sh çıktısını düzeltin.${NC}"
    else
        echo -e "       ${YELLOW}⏭️  Development validation çalıştırılmadı (${ci_status}).${NC}"
    fi

    echo -e "       ${YELLOW}${BOLD}⏭️  Production readiness: ÇALIŞTIRILMADI.${NC}"
    echo -e "       ${YELLOW}Development validation ≠ release/merge onayı.${NC}"
    echo -e "       ${BOLD}Release/merge için tek zorunlu kapı:${NC}"
    echo "       make production-readiness"
    echo "       # Eşdeğer: TEST_PROFILE=ci RUN_BENCHMARKS=required RUN_FRONTEND_E2E=1 SIDAR_PRODUCTION_READINESS=1 bash run_tests.sh --stage all"
}

# ── 15. Özet ─────────────────────────────────────────────────────────────────
print_summary() {
    local summary_banner=""
    summary_banner="$(_center_visible "Sidar AI Kurulumu Tamamlandı!" 60)"
    echo ""
    echo -e "${BOLD}${GREEN}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    printf "║%s║\n" "$(_pad_visible "$summary_banner" 60)"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    echo -e "${BOLD}Sonraki Adımlar:${NC}"
    echo ""
    echo -e "  1️⃣  .env dosyasını düzenle:"
    echo "       nano .env"
    echo ""
    echo -e "${BOLD}.env API anahtar durumu:${NC}"
    if [[ "$ENV_API_KEYS_TOTAL" -gt 0 && "$ENV_API_KEYS_FILLED" -eq "$ENV_API_KEYS_TOTAL" ]]; then
        echo -e "  ${GREEN}✅ .env dosyası API anahtarları açısından eksiksiz görünüyor (${ENV_API_KEYS_FILLED}/${ENV_API_KEYS_TOTAL}).${NC}"
    else
        echo -e "  ${YELLOW}⚠️  Dolu anahtar: ${ENV_API_KEYS_FILLED}/${ENV_API_KEYS_TOTAL}${NC}"
        if [[ "${#ENV_API_KEYS_MISSING[@]}" -gt 0 ]]; then
            echo "  Eksik / boş bırakılan anahtarlar:"
            local missing_key
            for missing_key in "${ENV_API_KEYS_MISSING[@]}"; do
                echo "    - ${missing_key}"
            done
        fi
        echo "  Not: Kullanmayacağınız servis anahtarlarını boş bırakabilirsiniz."
    fi
    verify_sidar_keys_file_permissions
    if declare -F print_runtime_key_source_summary >/dev/null 2>&1; then
        print_runtime_key_source_summary
    fi
    echo ""
    echo -e "  2️⃣  Sanal ortamı aktif et (yeni terminalde):"
    echo "       source .venv/bin/activate"
    echo ""
    echo -e "  3️⃣  Arka plan servisleri durumu:"
    if [[ "${APP_RUNTIME_MODE_SELECTED:-docker}" == "local" ]]; then
        echo "       Çalışma modu: Geliştirici (uygulama local, altyapı Docker)."
        echo "       Altyapı servisleri: docker compose up -d postgres redis"
        echo "       İzleme gerekiyorsa: COMPOSE_PROFILES=observability docker compose up -d jaeger prometheus grafana"
        echo "       (Host Ollama yoksa ayrıca: docker compose up -d ollama)"
        echo "       Durdurma: docker compose stop postgres redis jaeger prometheus grafana ollama"
    else
        echo "       Çalışma modu: Tam Docker (web/agent dahil)."
    echo "       Servisleri manuel yönetmek isterseniz: docker compose up -d / docker compose down"
    fi
    echo ""
    echo -e "  4️⃣  CLI ile başlat:"
    echo "       uv run python main.py"
    echo "       # veya: source .venv/bin/activate && python main.py"
    echo ""
    local web_url="http://localhost:7860"
    if [[ "${APP_RUNTIME_MODE_SELECTED:-docker}" == "docker" && "$GPU_AVAILABLE" == true ]]; then
        web_url="http://localhost:${WEB_GPU_PORT:-7861} (GPU profili)"
    fi
    echo -e "  5️⃣  Web arayüzü ile başlat (${web_url}):"
    echo "       uv run python main.py --quick web"
    echo "       # veya: source .venv/bin/activate && python main.py --quick web"
    if [[ "$REACT_UI_STATUS" == "hazır" || "$REACT_UI_STATUS" == "hazır_cache" ]]; then
        if [[ "$REACT_UI_STATUS" == "hazır_cache" ]]; then
            echo "       React UI build: cache kullanıldı, yeniden derleme atlandı (web_ui_react/dist)"
        else
            echo "       React UI build: tamamlandı (web_ui_react/dist)"
        fi
        print_react_frontend_qa_status_block
    elif [[ "$REACT_UI_STATUS" == "build_hata" ]]; then
        echo "       React UI build: başarısız (npm ci|npm install ve/veya npm run build hata verdi)"
        echo "       Logları kontrol edin ve manuel deneyin: cd web_ui_react && npm ci && npm run build"
    else
        echo "       React UI build: atlandı (${REACT_UI_STATUS})"
        echo "       Manuel build için: cd web_ui_react && npm ci && npm run build"
    fi
    echo ""
    echo -e "  6️⃣  Testleri çalıştır (varsayılan kurulumda hazır):"
    echo "       ./run_tests.sh"
    echo "       Test rehberi: docs/TESTING.md (PR/merge öncesi ana doğrulama yolu)"
    echo ""
    print_release_readiness_next_action
    echo ""
    print_install_validation_coverage

    if [[ "$GPU_AVAILABLE" == true ]]; then
        echo -e "  ${GREEN}🚀 GPU hızlandırma aktif — .env: USE_GPU=true${NC}"
        echo ""
    fi

    if [[ "$WSL2" == true ]]; then
        local multimodal_val=""
        [[ -f "$SCRIPT_DIR/.env" ]] && multimodal_val=$(read_env_value_from_file "ENABLE_MULTIMODAL" "$SCRIPT_DIR/.env" | tr -d '[:space:]')
        if [[ "$multimodal_val" == "true" ]]; then
            echo -e "  ${GREEN}🎙️  Ses/mikrofon desteği aktif (WSLg PulseAudio) — .env: ENABLE_MULTIMODAL=true${NC}"
            if [[ "$AUDIO_SESSION_RESTART_RECOMMENDED" == true ]]; then
                echo -e "  ${YELLOW}⚠️  Ses paketleri/yol değişkenleri güncellendi. Sağlıklı çalışması için kurulumdan sonra terminali kapatıp yeniden açın.${NC}"
            fi
        else
            echo -e "  ${YELLOW}🔇 Ses desteği kapalı. Etkinleştirmek için: ./install_sidar.sh --enable-audio${NC}"
        fi
        if [[ "$WSLCONFIG_CHANGED" == true ]]; then
            echo -e "  ${YELLOW}⚠️  ÖNEMLİ: .wslconfig değişti → memory/swap ayarlarının etkili olması için:${NC}"
            echo "       PowerShell'de: wsl --shutdown && wsl"
        fi
        echo ""
    fi

    echo -e "${BOLD}Faydalı Komutlar:${NC}"
    echo "  Terminoloji: smoke = hızlı sağlık kontrolü; dev-full = local tam doğrulama; production-readiness = merge/release kapısı."
    echo "  Test rehberi: docs/TESTING.md — smoke ile yetinmeyin; PR/merge öncesi production-readiness çalıştırın."
    echo "  dev-full (local tam doğrulama; backend + frontend + benchmark + BATS + security):"
    echo "    make dev-full"
    echo "    # Eşdeğer: bash run_tests.sh --stage all"
    echo "  production-readiness (merge/release kapısı):"
    echo "    make production-readiness"
    echo "  Backend entegrasyon ana yolu:"
    echo "    bash run_tests.sh --stage integration   # tests/integration/{api,cli,db,managers,web,workflow}"
    echo "  E2E odaklı doğrulama için:"
    echo "    bash run_tests.sh --stage e2e   # tests/e2e/{agents,cli,web}"
    echo "  Performans/benchmark doğrulaması için:"
    echo "    RUN_BENCHMARKS=required bash run_tests.sh"
    echo "  uv run python github_upload.py   — projeyi GitHub'a yükle"
    if [[ "$MIGRATION_STATUS" == "tamamlandi" ]]; then
        echo "  Alembic migrasyonları kurulum sırasında tamamlandı."
    else
        echo "  uv run alembic upgrade head  — DB hazır olduktan sonra migrasyonu çalıştırın"
    fi
    if [[ "$SMOKE_TEST_STATUS" == "tamamlandi" ]]; then
        echo "  Smoke testler: başarılı (tests/smoke)."
        echo "  Not: smoke = hızlı sağlık kontrolü; dev-full/local tam doğrulama veya production-readiness/merge-release kapısı değildir."
    elif [[ "$SMOKE_TEST_STATUS" == "hata" ]]; then
        echo "  Smoke testler: hata var. Tekrar için: uv run pytest tests/smoke --rootdir=\"$SCRIPT_DIR\" -v --no-cov"
        echo "  dev-full/local tam doğrulama için: make dev-full"
    else
        echo "  Smoke testler: atlandı (${SMOKE_TEST_STATUS}). Çalıştırmak için: uv run pytest tests/smoke --rootdir=\"$SCRIPT_DIR\" -v --no-cov"
        echo "  Kurulum sonrası dev-full/local tam doğrulama için: make dev-full"
    fi
    print_install_summary_extended_test_statuses
    if [[ "$AUDIT_STATUS" == "tamamlandi" ]]; then
        echo "  Test artifact audit: başarılı (scripts/check_empty_test_artifacts.sh)."
    elif [[ "$RUN_AUDIT" == true ]]; then
        echo "  Test artifact audit: ${AUDIT_STATUS}."
    else
        echo "  Test artifact audit: atlandı. Çalıştırmak için: ./install_sidar.sh --audit"
    fi
    if [[ "$AUTONOMOUS_CRON_STATUS" == "systemd_timer" ]]; then
        echo "  Otonom döngü zamanlayıcısı: systemd user timer aktif (sidar-autonomous-loop.timer)."
    elif [[ "$AUTONOMOUS_CRON_STATUS" == "crontab" ]]; then
        echo "  Otonom döngü zamanlayıcısı: kullanıcı crontab satırı aktif."
    elif [[ "$AUTONOMOUS_CRON_STATUS" == "manuel_gerekli" ]]; then
        echo "  Otonom döngü zamanlayıcısı: otomatik kurulamadı; autonomous_loop.sh için manuel systemd/crontab planı ekleyin."
    else
        echo "  Otonom döngü zamanlayıcısı: opt-in kapalı. Etkinleştirmek için: ./install_sidar.sh --enable-autonomous-cron"
    fi
    echo "  ollama serve              — Ollama servisini başlat"
    if [[ "$SKIP_MODELS" == true ]]; then
        echo "  ollama pull <model_adi>   — model indirmeleri atlandı, sonradan manuel indirin"
    fi
    echo "  docker compose up sidar-gpu     — Docker GPU modu"
    echo "  Not: Docker GPU için nvidia-container-toolkit kurulu olmalıdır."
    echo ""
    echo -e "${BOLD}Gözlemlenebilirlik (Telemetry)${NC}"
    echo "  İzleme servislerini başlat: COMPOSE_PROFILES=observability docker compose up -d jaeger prometheus grafana"
    echo "  Grafana paneli    : http://localhost:3000 (varsayılan: admin / admin)"
    echo "  Prometheus paneli : http://localhost:9090"
    echo "  Jaeger UI         : http://localhost:16686"
    echo "  Not: Bu servisler docker_setup/ altındaki hazır konfigürasyonları kullanır."
    echo "  Güvenlik notu: Üretimde ACCESS_LEVEL ayarını dikkatle yapılandırın."
    echo ""
}


sidar_phase_finish() {
    sidar_ensure_autonomy_scripts_executable
    sidar_configure_autonomous_cron
    run_install_ci_full_validation
    print_summary
    relocate_log_file_if_needed
    cleanup_bootstrap_script_copy
    prompt_post_install_sidar_env_mode
    # En son adım: IDE başlatma onayı
    launch_ide
}
