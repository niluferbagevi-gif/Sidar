#!/usr/bin/env bash
SIDAR_INSTALL_UTIL_DB_CREDENTIALS_SH_LOADED=1

# Database credential hardening helpers for the phase-based Sidar installer.
# These definitions intentionally override the legacy monolithic fallbacks in
# install_sidar.sh when sourced by the workspace phase.

harden_database_credentials() {
    local env_file="$1"
    local db_url=""
    local sidar_env="development"
    local safe_db_url=""
    local hardening_enabled="${ENABLE_DB_PASSWORD_HARDENING:-1}"

    [[ -f "$env_file" ]] || return

    db_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")
    sidar_env=$(read_env_value_from_file "SIDAR_ENV" "$env_file")
    sidar_env="${sidar_env:-development}"

    [[ -n "$db_url" ]] || return

    # Güvensiz bilinen varsayılan kimlik bilgileri (postgres:postgres vb.)
    if [[ "$db_url" =~ ^postgresql(\+asyncpg)?://([^:@/]+):([^@/]+)@(.+)$ ]]; then
        local db_user="${BASH_REMATCH[2]}"
        local db_password="${BASH_REMATCH[3]}"
        local db_host_and_name="${BASH_REMATCH[4]}"

        if is_weak_secret_value "$db_password"; then
            if [[ "$hardening_enabled" == "1" || "${FORCE_STRONG_DB_PASSWORD:-0}" == "1" ]]; then
                PRE_HARDEN_DB_PASSWORD="$db_password"
                local generated_password=""
                generated_password=$(generate_secure_token 24)
                if [[ -n "$generated_password" ]]; then
                    safe_db_url="postgresql+asyncpg://${db_user}:${generated_password}@${db_host_and_name}"
                    sed_inplace "s|^DATABASE_URL=.*|DATABASE_URL=${safe_db_url}|" "$env_file"
                    ok ".env: DATABASE_URL için güvenli bir veritabanı şifresi üretildi (SIDAR_ENV=${sidar_env})."

                    # Docker Compose ile çalışırken PostgreSQL container kimlik bilgileri
                    # DATABASE_URL ile senkron kalmalıdır.
                    if grep -q '^POSTGRES_PASSWORD=' "$env_file"; then
                        sed_inplace "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${generated_password}|" "$env_file"
                    else
                        echo "POSTGRES_PASSWORD=${generated_password}" >> "$env_file"
                    fi
                    if grep -q '^POSTGRES_USER=' "$env_file"; then
                        sed_inplace "s|^POSTGRES_USER=.*|POSTGRES_USER=${db_user}|" "$env_file"
                    else
                        echo "POSTGRES_USER=${db_user}" >> "$env_file"
                    fi
                    local db_name_for_container="${db_host_and_name#*/}"
                    db_name_for_container="${db_name_for_container%%\?*}"
                    [[ -n "$db_name_for_container" && "$db_name_for_container" != "$db_host_and_name" ]] || db_name_for_container="sidar"
                    local container_db_url="postgresql+asyncpg://${db_user}:${generated_password}@postgres:5432/${db_name_for_container}"
                    if grep -q '^SIDAR_CONTAINER_DATABASE_URL=' "$env_file"; then
                        sed_inplace "s|^SIDAR_CONTAINER_DATABASE_URL=.*|SIDAR_CONTAINER_DATABASE_URL=${container_db_url}|" "$env_file"
                    else
                        echo "SIDAR_CONTAINER_DATABASE_URL=${container_db_url}" >> "$env_file"
                    fi
                    DB_PASSWORD_HARDENED=true
                    ok ".env: POSTGRES_USER/POSTGRES_PASSWORD değerleri DATABASE_URL ile senkronize edildi."
                    info "PostgreSQL şifresi güçlendirildi. Mevcut bir volume varsa kurulum migrasyon aşamasında otomatik olarak sıfırlayacak — manuel işlem gerekmez."
                    if command -v docker &>/dev/null && docker info >/dev/null 2>&1; then
                        local detected_pg_volume=""
                        detected_pg_volume=$(docker volume ls --format '{{.Name}}' | grep -E '(^|_)postgres_data$' | head -n1 || true)
                        if [[ -n "$detected_pg_volume" ]]; then
                            info "Tespit edilen PostgreSQL volume: ${detected_pg_volume} (gerekirse kurulum tarafından otomatik sıfırlanacak)."
                        fi
                    fi
                else
                    warn ".env: Güçlü veritabanı şifresi otomatik üretilemedi. DATABASE_URL parolanızı manuel güncelleyin."
                fi
            else
                warn ".env: ENABLE_DB_PASSWORD_HARDENING=1 olmadığı için otomatik DB parola güçlendirme atlandı."
                warn ".env: DATABASE_URL varsayılan/zayıf parola içeriyor (${db_user}:****)."
                warn "Parolayı manuel güncellemek isterseniz DATABASE_URL ve POSTGRES_PASSWORD alanlarını birlikte değiştirin."
            fi
        fi
    fi
}

sync_postgres_env_with_database_url() {
    local env_file="$1"
    local db_url=""

    [[ -f "$env_file" ]] || return

    db_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")
    [[ -n "$db_url" ]] || return

    if [[ "$db_url" =~ ^postgresql(\+asyncpg)?://([^:@/]+):([^@/]+)@(.+)$ ]]; then
        local db_user="${BASH_REMATCH[2]}"
        local db_password="${BASH_REMATCH[3]}"
        local db_host_and_name="${BASH_REMATCH[4]}"
        local db_name="${db_host_and_name#*/}"

        # Host kısmında "/" yoksa varsayılan adı koru.
        if [[ "$db_name" == "$db_host_and_name" ]]; then
            db_name="sidar"
        fi

        # Olası query string'i temizle.
        db_name="${db_name%%\?*}"

        # Eski/çakışan satırları temizleyip en alta tek doğruluk kaynağını yaz.
        sed_inplace '/^POSTGRES_USER=/d' "$env_file"
        sed_inplace '/^POSTGRES_PASSWORD=/d' "$env_file"
        sed_inplace '/^POSTGRES_DB=/d' "$env_file"
        sed_inplace '/^DATABASE_URL=/d' "$env_file"

        local container_db_url="postgresql+asyncpg://${db_user}:${db_password}@postgres:5432/${db_name}"
        sed_inplace '/^SIDAR_CONTAINER_DATABASE_URL=/d' "$env_file"
        {
            echo "POSTGRES_USER=${db_user}"
            echo "POSTGRES_PASSWORD=${db_password}"
            echo "POSTGRES_DB=${db_name}"
            echo "DATABASE_URL=${db_url}"
            echo "SIDAR_CONTAINER_DATABASE_URL=${container_db_url}"
        } >> "$env_file"

        ok ".env: DATABASE_URL/POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB değerleri güvenli şekilde yeniden senkronize edildi."
    fi
}

ensure_database_url_defaults() {
    local env_file="$1"
    local current_db_url=""

    if [[ ! -f "$env_file" ]]; then
        return
    fi

    current_db_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")

    if [[ -z "$current_db_url" ]]; then
        write_generated_default_database_url "$env_file"
        ok ".env: DATABASE_URL güçlü rastgele PostgreSQL parolasıyla eklendi."
        return
    fi

    if [[ "$current_db_url" == sqlite* ]] && [[ "${ALLOW_SQLITE_DATABASE_URL:-0}" != "1" ]]; then
        warn ".env içinde SQLite DATABASE_URL tespit edildi: $current_db_url"
        write_generated_default_database_url "$env_file"
        ok ".env: DATABASE_URL güçlü rastgele PostgreSQL parolasıyla güncellendi."
        return
    fi

    if [[ "$current_db_url" == *lotus* ]]; then
        warn ".env içinde eski ürün adına ait DATABASE_URL tespit edildi; Sidar varsayılanına geçirilecek."
        write_generated_default_database_url "$env_file"
        ok ".env: DATABASE_URL güçlü rastgele Sidar PostgreSQL DSN değerine güncellendi."
    fi
}
