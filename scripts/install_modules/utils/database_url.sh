#!/usr/bin/env bash
set -Eeuo pipefail
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

resolve_runtime_database_url_from_file() {
    local env_file="$1"
    local db_url=""
    local postgres_user=""
    local postgres_password=""
    local postgres_host=""
    local postgres_port=""
    local postgres_db=""
    local source_label=""

    [[ -f "$env_file" ]] || return 1
    source_label="$(basename "$env_file")"

    db_url="$(read_env_value_from_file "DATABASE_URL" "$env_file" | tr -d '\n[:space:]')"
    if [[ -n "$db_url" ]]; then
        printf '%s|%s\n' "$db_url" "${source_label}:DATABASE_URL"
        return 0
    fi

    postgres_password="$(read_env_value_from_file "POSTGRES_PASSWORD" "$env_file" | tr -d '\n')"
    [[ -n "${postgres_password//[[:space:]]/}" ]] || return 1
    postgres_user="$(read_env_value_from_file "POSTGRES_USER" "$env_file" | tr -d '\n')"
    postgres_host="$(read_env_value_from_file "POSTGRES_HOST" "$env_file" | tr -d '\n')"
    postgres_port="$(read_env_value_from_file "POSTGRES_PORT" "$env_file" | tr -d '\n')"
    postgres_db="$(read_env_value_from_file "POSTGRES_DB" "$env_file" | tr -d '\n')"

    postgres_user="${postgres_user:-sidar}"
    postgres_host="${postgres_host:-127.0.0.1}"
    postgres_port="${postgres_port:-5432}"
    postgres_db="${postgres_db:-sidar}"

    printf 'postgresql+asyncpg://%s:%s@%s:%s/%s|%s\n' \
        "$postgres_user" "$postgres_password" "$postgres_host" "$postgres_port" "$postgres_db" "-"
}

resolve_runtime_database_url() {
    local db_url=""
    local env_file=""
    local sidar_env=""
    local -a candidate_env_files=()
    local resolved=""
    local source=""

    db_url="${DATABASE_URL:-}"
    db_url="$(printf '%s' "$db_url" | tr -d '\n[:space:]')"
    if [[ -n "$db_url" ]]; then
        RUNTIME_DATABASE_URL="$db_url"
        RUNTIME_DATABASE_URL_SOURCE="process:DATABASE_URL"
        printf '%s\n' "$RUNTIME_DATABASE_URL"
        return 0
    fi

    candidate_env_files+=("${SCRIPT_DIR:-.}/.env")
    sidar_env="$(read_env_value_from_file "SIDAR_ENV" "${SCRIPT_DIR:-.}/.env" 2>/dev/null | tr -d '\n[:space:]' | tr '[:upper:]' '[:lower:]')"
    candidate_env_files+=("${SCRIPT_DIR:-.}/.env.advanced")
    [[ -n "$sidar_env" ]] && candidate_env_files+=("${SCRIPT_DIR:-.}/.env.${sidar_env}")
    if [[ -n "${DOTENV_FILE:-}" ]]; then
        if [[ "$DOTENV_FILE" = /* ]]; then
            candidate_env_files+=("$DOTENV_FILE")
        else
            candidate_env_files+=("${SCRIPT_DIR:-.}/$DOTENV_FILE")
        fi
    fi

    for env_file in "${candidate_env_files[@]}"; do
        [[ -n "$env_file" && -f "$env_file" ]] || continue
        if resolved="$(resolve_runtime_database_url_from_file "$env_file")"; then
            db_url="${resolved%%|*}"
            source="${resolved#*|}"
            if [[ "$source" == "-" ]]; then
                source="$(basename "$env_file"):POSTGRES_*"
            fi
            RUNTIME_DATABASE_URL="$db_url"
            RUNTIME_DATABASE_URL_SOURCE="$source"
            printf '%s\n' "$RUNTIME_DATABASE_URL"
            return 0
        fi
    done

    RUNTIME_DATABASE_URL=""
    # shellcheck disable=SC2034  # Read by later phase modules after sourcing.
    RUNTIME_DATABASE_URL_SOURCE=""
    return 1
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
    local postgres_user="sidar"
    local postgres_db="sidar"
    local postgres_password=""

    postgres_user=$(read_env_value_from_file "POSTGRES_USER" "$env_file" | tr -d '\n')
    postgres_db=$(read_env_value_from_file "POSTGRES_DB" "$env_file" | tr -d '\n')
    postgres_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$env_file" | tr -d '\n')

    [[ -n "${postgres_user//[[:space:]]/}" ]] || postgres_user="sidar"
    [[ -n "${postgres_db//[[:space:]]/}" ]] || postgres_db="sidar"

    if [[ -z "${postgres_password//[[:space:]]/}" ]] || is_weak_secret_value "$postgres_password"; then
        postgres_password=$(generate_secure_token 24)
        [[ -n "$postgres_password" ]] || fail "DATABASE_URL için güçlü parola üretilemedi."
        DB_PASSWORD_HARDENED=true
    fi

    local local_db_url="postgresql+asyncpg://${postgres_user}:${postgres_password}@127.0.0.1:5432/${postgres_db}"
    local container_db_url="postgresql+asyncpg://${postgres_user}:${postgres_password}@postgres:5432/${postgres_db}"

    sed_inplace '/^POSTGRES_USER=/d' "$env_file"
    sed_inplace '/^POSTGRES_PASSWORD=/d' "$env_file"
    sed_inplace '/^POSTGRES_DB=/d' "$env_file"
    sed_inplace '/^DATABASE_URL=/d' "$env_file"
    sed_inplace '/^SIDAR_CONTAINER_DATABASE_URL=/d' "$env_file"
    {
        echo "POSTGRES_USER=${postgres_user}"
        echo "POSTGRES_PASSWORD=${postgres_password}"
        echo "POSTGRES_DB=${postgres_db}"
        echo "DATABASE_URL=${local_db_url}"
        echo "SIDAR_CONTAINER_DATABASE_URL=${container_db_url}"
    } >> "$env_file"
}

database_name_from_postgresql_url() {
    local db_url="$1"
    local authority_and_path=""
    local db_path=""

    [[ "$db_url" == postgresql://* || "$db_url" == postgresql+asyncpg://* ]] || return 1
    authority_and_path="${db_url#*://}"
    [[ "$authority_and_path" == */* ]] || return 1
    db_path="${authority_and_path#*/}"
    db_path="${db_path%%\?*}"
    db_path="${db_path%%\#*}"
    [[ -n "$db_path" ]] || return 1
    printf '%s\n' "$db_path"
}

ensure_database_url_defaults() {
    local env_file="$1"
    local env_label="${env_file##*/}"
    local current_db_url=""
    local current_db_name=""
    local configured_db_name=""

    if [[ ! -f "$env_file" ]]; then
        return
    fi

    current_db_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")

    if [[ -z "$current_db_url" ]]; then
        DB_PASSWORD_HARDENED=false
        write_generated_default_database_url "$env_file"
        if [[ "${DB_PASSWORD_HARDENED:-false}" == "true" ]]; then
            ok "${env_label}: DATABASE_URL güçlü rastgele PostgreSQL parolasıyla eklendi."
        else
            ok "${env_label}: DATABASE_URL mevcut güçlü PostgreSQL parolası korunarak eklendi."
        fi
        # Keep fresh-create on the same validation path as pre-existing URLs.
        # Re-read the generated value instead of returning early so future changes
        # to DSN generation cannot silently bypass ssl/query and database-name checks.
        current_db_url=$(read_env_value_from_file "DATABASE_URL" "$env_file")
    fi

    if [[ "$current_db_url" == sqlite* ]] && [[ "${ALLOW_SQLITE_DATABASE_URL:-0}" != "1" ]]; then
        warn "${env_label} içinde SQLite DATABASE_URL tespit edildi: $current_db_url"
        DB_PASSWORD_HARDENED=false
        write_generated_default_database_url "$env_file"
        if [[ "${DB_PASSWORD_HARDENED:-false}" == "true" ]]; then
            ok "${env_label}: DATABASE_URL güçlü rastgele PostgreSQL parolasıyla güncellendi."
        else
            ok "${env_label}: DATABASE_URL mevcut güçlü PostgreSQL parolası korunarak güncellendi."
        fi
        return
    fi

    if [[ "$current_db_url" == *lotus* ]]; then
        warn "${env_label} içinde eski ürün adına ait DATABASE_URL tespit edildi; Sidar varsayılanına geçirilecek."
        DB_PASSWORD_HARDENED=false
        write_generated_default_database_url "$env_file"
        if [[ "${DB_PASSWORD_HARDENED:-false}" == "true" ]]; then
            ok "${env_label}: DATABASE_URL güçlü rastgele Sidar PostgreSQL DSN değerine güncellendi."
        else
            ok "${env_label}: DATABASE_URL mevcut güçlü PostgreSQL parolası korunarak Sidar DSN değerine güncellendi."
        fi
        return
    fi

    if [[ "${current_db_url,,}" =~ [\?\&]ssl= ]]; then
        warn "${env_label} içinde asyncpg ile uyumsuz ssl query parametresi içeren DATABASE_URL tespit edildi; güvenli PostgreSQL DSN yeniden üretilecek."
        DB_PASSWORD_HARDENED=false
        write_generated_default_database_url "$env_file"
        if [[ "${DB_PASSWORD_HARDENED:-false}" == "true" ]]; then
            ok "${env_label}: Uyumsuz ssl parametresi kaldırıldı ve DATABASE_URL güçlü rastgele PostgreSQL parolasıyla güncellendi."
        else
            ok "${env_label}: Uyumsuz ssl parametresi kaldırıldı ve DATABASE_URL mevcut güçlü PostgreSQL parolasıyla güncellendi."
        fi
        return
    fi

    configured_db_name=$(read_env_value_from_file "POSTGRES_DB" "$env_file" | tr -d '\n')
    if [[ -n "${configured_db_name//[[:space:]]/}" ]] && \
        current_db_name=$(database_name_from_postgresql_url "$current_db_url") && \
        [[ "$current_db_name" != "$configured_db_name" ]]; then
        warn "${env_label} içinde DATABASE_URL veritabanı (${current_db_name}) POSTGRES_DB (${configured_db_name}) ile eşleşmiyor; profile özgü PostgreSQL DSN yeniden üretilecek."
        DB_PASSWORD_HARDENED=false
        write_generated_default_database_url "$env_file"
        if [[ "${DB_PASSWORD_HARDENED:-false}" == "true" ]]; then
            ok "${env_label}: DATABASE_URL, POSTGRES_DB ile güçlü rastgele PostgreSQL parolası kullanılarak senkronize edildi."
        else
            ok "${env_label}: DATABASE_URL, POSTGRES_DB ile mevcut güçlü PostgreSQL parolası korunarak senkronize edildi."
        fi
    fi
}

ensure_database_url_defaults_for_variants() {
    local spec=""
    local variant_file=""
    local -a variant_specs=()

    mapfile -t variant_specs < <(sidar_default_db_env_variant_specs)
    for spec in "${variant_specs[@]}"; do
        variant_file="${spec%%:*}"
        [[ -n "$variant_file" && -f "$variant_file" ]] || continue
        ensure_database_url_defaults "$variant_file"
    done
}
