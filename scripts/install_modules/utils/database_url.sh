#!/usr/bin/env bash
# shellcheck disable=SC2034  # sentinel read indirectly by sidar_source_install_utils.
SIDAR_INSTALL_UTIL_DATABASE_URL_SH_LOADED=1

# DATABASE_URL and PostgreSQL dotenv synchronization helpers.

sidar_default_db_env_variant_specs() {
    printf '%s\n' \
        "$SCRIPT_DIR/.env.development:$SCRIPT_DIR/.env.development.example" \
        "$SCRIPT_DIR/.env.test:$SCRIPT_DIR/.env.test.example" \
        "$SCRIPT_DIR/.env.advanced:$SCRIPT_DIR/.env.advanced.example"
}

sidar_write_env_value() {
    local env_file="$1"
    local key="$2"
    local value="$3"

    sed_inplace "/^${key}=/d" "$env_file"
    echo "${key}=${value}" >> "$env_file"
}

sync_postgres_env_variants_with_source() {
    local source_env_file="$1"
    shift || true
    local -a variant_specs=("$@")
    local -a postgres_keys=(
        POSTGRES_USER
        POSTGRES_PASSWORD
        POSTGRES_DB
        DATABASE_URL
        SIDAR_CONTAINER_DATABASE_URL
    )

    [[ -f "$source_env_file" ]] || return 0

    if [[ "${#variant_specs[@]}" -eq 0 ]]; then
        mapfile -t variant_specs < <(sidar_default_db_env_variant_specs)
    fi

    local spec target example key value label
    for spec in "${variant_specs[@]}"; do
        target="${spec%%:*}"
        example=""
        if [[ "$spec" == *:* ]]; then
            example="${spec#*:}"
        fi
        [[ -n "$target" ]] || continue

        if [[ ! -f "$target" ]]; then
            if [[ -n "$example" && -f "$example" ]]; then
                cp "$example" "$target"
                ok "$(basename "$target") dosyası $(basename "$example") üzerinden oluşturuldu."
            else
                warn "$(basename "$target") bulunamadı; PostgreSQL credential senkronizasyonu atlandı."
                continue
            fi
        fi

        for key in "${postgres_keys[@]}"; do
            value=$(read_env_value_from_file "$key" "$source_env_file" | tr -d '\n')
            [[ -z "${value//[[:space:]]/}" ]] && continue
            sidar_write_env_value "$target" "$key" "$value"
        done

        label="$(basename "$target")"
        ok "${label}: PostgreSQL credential değerleri .env ile zorunlu olarak senkronize edildi."
    done
}

sync_postgres_env_with_database_url() {
    local env_file="$1"
    shift || true
    local -a variant_specs=("$@")
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
        sync_postgres_env_variants_with_source "$env_file" "${variant_specs[@]}"
    fi
}

write_generated_default_database_url() {
    local env_file="$1"
    local generated_password=""
    generated_password=$(generate_secure_token 24)
    [[ -n "$generated_password" ]] || fail "DATABASE_URL için güçlü parola üretilemedi."

    local local_db_url="postgresql+asyncpg://sidar:${generated_password}@127.0.0.1:5432/sidar"
    local container_db_url="postgresql+asyncpg://sidar:${generated_password}@postgres:5432/sidar"

    sed_inplace '/^POSTGRES_USER=/d' "$env_file"
    sed_inplace '/^POSTGRES_PASSWORD=/d' "$env_file"
    sed_inplace '/^POSTGRES_DB=/d' "$env_file"
    sed_inplace '/^DATABASE_URL=/d' "$env_file"
    sed_inplace '/^SIDAR_CONTAINER_DATABASE_URL=/d' "$env_file"
    {
        echo "POSTGRES_USER=sidar"
        echo "POSTGRES_PASSWORD=${generated_password}"
        echo "POSTGRES_DB=sidar"
        echo "DATABASE_URL=${local_db_url}"
        echo "SIDAR_CONTAINER_DATABASE_URL=${container_db_url}"
    } >> "$env_file"
    DB_PASSWORD_HARDENED=true
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
