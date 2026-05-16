#!/usr/bin/env bash

sidar_phase_local_migrations_and_models() {
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

sidar_phase_services_and_validation() {
    # Tüm altyapı (jaeger/prometheus/grafana dahil) smoke testlerden önce hazır olsun.
    launch_docker_services
    if [[ "$APP_RUNTIME_MODE_SELECTED" == "local" ]]; then
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
