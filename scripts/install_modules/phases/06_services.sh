#!/usr/bin/env bash

sidar_phase_local_migrations_and_models() {
    sidar_source_install_utils "ollama_models.sh"
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        # DB migrasyonu öncesi servis hazırlığı: kullanıcı onayı bu aşamada alınır.
        prepare_docker_for_migrations
        # Önce DB migrasyonu: olası bağlantı/şema hataları sonraki adımlara geçmeden görülsün.
        run_migrations
        # Model indirme: fonksiyon sonunda cleanup_temp_ollama trap'i geçici 'ollama serve'
        # sürecini otomatik sonlandırır; hemen ardından gelen launch_docker_services'in
        # Docker Ollama servisiyle 11434 port çakışması bu şekilde önlenir.
        download_ollama_models
    else
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        MIGRATION_STATUS="tam_docker_modu_nedeniyle_atlandi"
        info "Tam Docker modu: lokal migrasyon/model indirme adımları atlanıyor."
    fi
}


sync_database_passwords_before_smoke_tests() {
    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
        return 0
    fi

    if [[ ! -f "$SCRIPT_DIR/scripts/sync_database_passwords.py" ]]; then
        warn "scripts/sync_database_passwords.py bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
        return 0
    fi

    info "Smoke test öncesi PostgreSQL dotenv profilleri eşitleniyor (.env.test dahil)..."
    if (cd "$SCRIPT_DIR" && uv run python scripts/sync_database_passwords.py --all-envs >/dev/null 2>&1); then
        ok "Smoke test öncesi PostgreSQL dotenv profilleri eşitlendi."
    else
        warn "Smoke test öncesi PostgreSQL dotenv senkronizasyonu tamamlanamadı; smoke testler mevcut ortamla devam edecek."
    fi

    if [[ ! -f "$SCRIPT_DIR/scripts/sync_postgres_password.py" ]]; then
        warn "scripts/sync_postgres_password.py bulunamadı; canlı PostgreSQL parola senkronizasyonu atlandı."
        return 0
    fi

    info "Smoke test öncesi canlı PostgreSQL kullanıcı parolası doğrulanıyor..."
    if (cd "$SCRIPT_DIR" && uv run python scripts/sync_postgres_password.py >/dev/null 2>&1); then
        ok "Canlı PostgreSQL kullanıcı parolası smoke test öncesi eşitlendi."
    else
        warn "Canlı PostgreSQL parola senkronizasyonu tamamlanamadı; smoke testler mevcut veritabanı durumu ile devam edecek."
    fi
}

sidar_phase_services_and_validation() {
    # Tüm altyapı (jaeger/prometheus/grafana dahil) smoke testlerden önce hazır olsun.
    launch_docker_services
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
        sync_database_passwords_before_smoke_tests
        run_smoke_tests
        run_test_artifact_audit
    else
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        SMOKE_TEST_STATUS="tam_docker_modu_nedeniyle_atlandi"
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        AUDIT_STATUS="tam_docker_modu_nedeniyle_atlandi"
        info "Tam Docker modu: lokal smoke-test/audit adımları atlanıyor."
    fi
}
