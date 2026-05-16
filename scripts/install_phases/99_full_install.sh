#!/usr/bin/env bash
# Sidar installer phase: full installation orchestration
# shellcheck shell=bash

run_full_install_phase() {
    # Kritik sıra:
    # 1) Sistem bağımlılıkları (git/curl vb.)
    # 2) Repo senkronizasyonu (git clone/pull)
    # 3) Ön koşul doğrulaması (uv/Python/FFmpeg/Docker/Ollama)
    install_system_dependencies
    sync_repo
    cd "$SCRIPT_DIR"
    ensure_prerequisites
    select_runtime_mode
    detect_gpu
    setup_nvidia_docker
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" && -f "$SCRIPT_DIR/.env" ]]; then
        # Mevcut .env varsa Docker imajlarını uv sync ile paralel önceden çekebiliriz.
        start_docker_image_prefetch_async "$APP_RUNTIME_MODE_SELECTED"
    fi
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
    create_directories
    # VS Code ayarları, Python yorumlayıcı yolu belli olduktan sonra erken hazırlanabilir.
    setup_vscode_workspace
    setup_env_file
    start_docker_image_prefetch_async "$APP_RUNTIME_MODE_SELECTED"
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        setup_react_frontend
        install_playwright_browsers
    else
        info "Tam Docker modu: lokal React build ve Playwright kurulumu atlanıyor."
    fi
    setup_shell_activation_shortcut
    setup_wsl2_audio
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        # DB migrasyonu öncesinde paralel image prefetch sonuçlansın; compose up gerekirse kalanları tekrar çeker.
        wait_for_docker_image_prefetch
        # DB migrasyonu öncesi servis hazırlığı: kullanıcı onayı bu aşamada alınır.
        prepare_docker_for_migrations
        # Önce DB migrasyonu: olası bağlantı/şema hataları sonraki adımlara geçmeden görülsün.
        run_migrations
        # Model indirme: fonksiyon sonunda cleanup_temp_ollama trap'i geçici 'ollama serve'
        # sürecini otomatik sonlandırır; hemen ardından gelen launch_docker_services'in
        # Docker Ollama servisiyle 11434 port çakışması bu şekilde önlenir.
        download_ollama_models
    else
        MIGRATION_STATUS="tam_docker_modu_nedeniyle_atlandi"
        info "Tam Docker modu: lokal migrasyon/model indirme adımları atlanıyor."
    fi
    # Tüm altyapı (jaeger/prometheus/grafana dahil) smoke testlerden önce hazır olsun.
    wait_for_docker_image_prefetch
    launch_docker_services
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        run_smoke_tests
        run_test_artifact_audit
    else
        SMOKE_TEST_STATUS="tam_docker_modu_nedeniyle_atlandi"
        AUDIT_STATUS="tam_docker_modu_nedeniyle_atlandi"
        info "Tam Docker modu: lokal smoke-test/audit adımları atlanıyor."
    fi
    print_summary
    relocate_log_file_if_needed
    cleanup_bootstrap_script_copy
    prompt_post_install_sidar_env_mode
    # En son adım: IDE başlatma onayı
    launch_ide
}
