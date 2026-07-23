#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_ENV_UTILS_SH_LOADED=1

# Functional install helpers for the phase-based Sidar installer.
# These definitions intentionally override the legacy monolithic fallbacks in
# install_sidar.sh when sourced by the relevant phase module.

read_env_value_from_file() {
    local key="$1"
    local file_path="$2"
    [[ -f "$file_path" ]] || return 0

    awk -F= -v key="$key" '
        /^[[:space:]]*#/ { next }
        $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
            line = $0
            sub(/^[[:space:]]*[^=]+=[[:space:]]*/, "", line)
            sub(/[[:space:]]+#.*/, "", line)
            gsub(/\r/, "", line)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            gsub(/^"|"$/, "", line)
            gsub(/^'\''|'\''$/, "", line)
            print line
            exit
        }
    ' "$file_path"
}


sync_database_env_chain_after_setup() {
    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; PostgreSQL dotenv zinciri Python senkronizasyonu atlandı."
        return 0
    fi

    if [[ ! -f "$SCRIPT_DIR/scripts/sync_database_passwords.py" ]]; then
        warn "scripts.sync_database_passwords bulunamadı; PostgreSQL dotenv zinciri Python senkronizasyonu atlandı."
        return 0
    fi

    info "Ortam değişkenlerindeki PostgreSQL şifreleri tek Python helper ile eşitleniyor..."
    if (
        cd "$SCRIPT_DIR" && \
            uv run python -m scripts.sync_database_passwords --all-envs >/dev/null 2>&1 && \
            uv run python -m scripts.sync_database_passwords --remove-explicit-urls >/dev/null 2>&1
    ); then
        ok ".env zincirindeki PostgreSQL şifreleri kalıcı olarak eşitlendi."
    else
        warn "PostgreSQL dotenv zinciri Python senkronizasyonu tamamlanamadı; gerekirse manuel çalıştırın: "\
            "uv run python -m scripts.sync_database_passwords --all-envs && uv run python -m scripts.sync_database_passwords --remove-explicit-urls"
    fi
}

setup_env_file() {
    step ".env Yapılandırması"
    # umask sadece bu fonksiyonun ürettiği/dokunduğu secret içerikli dosyalarla
    # sınırlı tutulur; process genelinde kalıcı olarak değiştirilmez (önceki
    # davranışta modülün source edilmesi tüm sonraki dosya oluşturma
    # işlemlerini de etkiliyordu). Hassas dosyalar zaten explicit
    # install -m 600 / chmod 600 ile korunuyor; bu yalnız ek bir güvenlik ağı.
    local _sidar_prev_umask
    _sidar_prev_umask="$(umask)"
    umask 077
    trap 'umask "$_sidar_prev_umask"' RETURN

    ENV_FILE="$SCRIPT_DIR/.env"
    EXAMPLE_FILE="$SCRIPT_DIR/.env.example"

    ADVANCED_ENV_FILE="$SCRIPT_DIR/.env.advanced"
    ADVANCED_EXAMPLE_FILE="$SCRIPT_DIR/.env.advanced.example"

    # .env.advanced eksikse example üzerinden oluştur. Secret değerleri
    # ensure_auto_secrets sonrasında propagate_shared_secrets_to_env_variants
    # ile .env dosyasından senkronize edilir.
    if [[ ! -f "$ADVANCED_ENV_FILE" && -f "$ADVANCED_EXAMPLE_FILE" ]]; then
        install -m 600 "$ADVANCED_EXAMPLE_FILE" "$ADVANCED_ENV_FILE"
        ok ".env.advanced dosyası .env.advanced.example'dan oluşturuldu."
    fi

    if [[ -f "$ENV_FILE" ]]; then
        ok ".env dosyası zaten mevcut — varsayılanlar ve güvenlik anahtarları kontrol ediliyor."
        ensure_sidar_env_default "$ENV_FILE"
        ensure_database_url_defaults "$ENV_FILE"
        ensure_rag_vector_backend_pgvector "$ENV_FILE"
        harden_database_credentials "$ENV_FILE"
        sync_postgres_env_with_database_url "$ENV_FILE"
        ensure_local_service_host_defaults "$ENV_FILE"
        ensure_auto_secrets "$ENV_FILE"
        propagate_shared_secrets_to_env_variants "$ENV_FILE"
        validate_required_security_profile "$ENV_FILE"
        # collect_api_keys_interactive kendi içinde .env + runtime env varyantlarına
        # API anahtarlarını yazar; bu yüzden burada ikinci bir generic propagate gerekmez.
        collect_api_keys_interactive "$ENV_FILE"
        report_env_api_key_status "$ENV_FILE"
        sync_database_env_chain_after_setup
        validate_runtime_env_loading
        return
    fi

    if [[ ! -f "$EXAMPLE_FILE" ]]; then
        warn ".env.example bulunamadı — .env oluşturulamadı. Manuel olarak oluşturun."
        return
    fi

    install -m 600 "$EXAMPLE_FILE" "$ENV_FILE"
    ok ".env dosyası .env.example'dan oluşturuldu."
    ensure_sidar_env_default "$ENV_FILE"
    ensure_database_url_defaults "$ENV_FILE"
    ensure_rag_vector_backend_pgvector "$ENV_FILE"
    harden_database_credentials "$ENV_FILE"
    sync_postgres_env_with_database_url "$ENV_FILE"
    ensure_local_service_host_defaults "$ENV_FILE"

    # Güvenlik secret'larını üret/doğrula (her iki yolda da çalışan üst-düzey fonksiyon)
    ensure_auto_secrets "$ENV_FILE"
    propagate_shared_secrets_to_env_variants "$ENV_FILE"
    validate_required_security_profile "$ENV_FILE"

    # GPU tespitine göre USE_GPU/REQUIRE_GPU/GPU_MIXED_PRECISION değerlerini uyumlu hale getir
    if command -v sed &>/dev/null; then
        if [[ "$GPU_AVAILABLE" == true ]]; then
            sed_inplace 's/^USE_GPU=false/USE_GPU=true/' "$ENV_FILE"
            if grep -q '^REQUIRE_GPU=' "$ENV_FILE"; then
                sed_inplace 's/^REQUIRE_GPU=.*/REQUIRE_GPU=true/' "$ENV_FILE"
            else
                echo 'REQUIRE_GPU=true' >> "$ENV_FILE"
            fi
            sed_inplace 's/^GPU_MIXED_PRECISION=false/GPU_MIXED_PRECISION=true/' "$ENV_FILE"

            # Docker için GPU modunu ön tanımlı yap
            if grep -q '^COMPOSE_PROFILES=' "$ENV_FILE"; then
                sed_inplace 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=gpu/' "$ENV_FILE"
            else
                echo "COMPOSE_PROFILES=gpu" >> "$ENV_FILE"
            fi

            ok ".env: USE_GPU=true, REQUIRE_GPU=true, GPU_MIXED_PRECISION=true (GPU tespit edildi)"
            ok ".env: COMPOSE_PROFILES=gpu ayarlandı (Docker GPU modu artık varsayılan)."
        else
            sed_inplace 's/^USE_GPU=true/USE_GPU=false/' "$ENV_FILE"
            if grep -q '^REQUIRE_GPU=' "$ENV_FILE"; then
                sed_inplace 's/^REQUIRE_GPU=.*/REQUIRE_GPU=false/' "$ENV_FILE"
            else
                echo 'REQUIRE_GPU=false' >> "$ENV_FILE"
            fi
            sed_inplace 's/^GPU_MIXED_PRECISION=true/GPU_MIXED_PRECISION=false/' "$ENV_FILE"
            if grep -q '^COMPOSE_PROFILES=' "$ENV_FILE"; then
                sed_inplace 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=cpu/' "$ENV_FILE"
            else
                echo "COMPOSE_PROFILES=cpu" >> "$ENV_FILE"
            fi
            ok ".env: USE_GPU=false, REQUIRE_GPU=false, GPU_MIXED_PRECISION=false, COMPOSE_PROFILES=cpu ayarlandı."
        fi
    fi

    # Docker + GPU tespit edildiyse NVIDIA runtime'ı varsayılan yap
    if [[ "$GPU_AVAILABLE" == true ]] && command -v docker &>/dev/null && command -v sed &>/dev/null; then
        if grep -q '^DOCKER_RUNTIME=' "$ENV_FILE"; then
            sed_inplace 's/^DOCKER_RUNTIME=.*/DOCKER_RUNTIME=nvidia/' "$ENV_FILE"
        else
            echo 'DOCKER_RUNTIME=nvidia' >> "$ENV_FILE"
        fi

        if grep -q '^DOCKER_ALLOWED_RUNTIMES=' "$ENV_FILE"; then
            if ! grep -q '^DOCKER_ALLOWED_RUNTIMES=.*nvidia' "$ENV_FILE"; then
                sed_inplace 's/^DOCKER_ALLOWED_RUNTIMES=.*/DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime,nvidia/' "$ENV_FILE"
            fi
        else
            echo 'DOCKER_ALLOWED_RUNTIMES=runc,runsc,kata-runtime,nvidia' >> "$ENV_FILE"
        fi

        ok ".env: Docker GPU varsayılanları ayarlandı (DOCKER_RUNTIME=nvidia)."
    fi

    # collect_api_keys_interactive kendi içinde .env + runtime env varyantlarına
    # API anahtarlarını yazar; bu yüzden burada ikinci bir generic propagate gerekmez.
    collect_api_keys_interactive "$ENV_FILE"
    report_env_api_key_status "$ENV_FILE"
    sync_database_env_chain_after_setup
    validate_runtime_env_loading
}
