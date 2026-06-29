#!/usr/bin/env bash

# ── 12. Alembic migrasyonları ────────────────────────────────────────────────
resolve_alembic_python() {
    local venv_python="$SCRIPT_DIR/.venv/bin/python"

    if [[ -x "$venv_python" ]]; then
        printf '%s\n' "$venv_python"
    elif command -v python3 &>/dev/null; then
        printf '%s\n' "python3"
    elif command -v python &>/dev/null; then
        printf '%s\n' "python"
    else
        return 1
    fi
}

run_migrations() {
    step "Veritabanı Migrasyonları"
    ALEMBIC_INI="$SCRIPT_DIR/alembic.ini"
    ENV_FILE="$SCRIPT_DIR/.env"

    if [[ ! -f "$ALEMBIC_INI" ]]; then
        warn "alembic.ini bulunamadı — migrasyon atlandı."
        MIGRATION_STATUS="alembic_yok"
        return
    fi

    DB_URL=""
    if [[ -f "$ENV_FILE" ]]; then
        DB_URL=$(read_env_value_from_file "DATABASE_URL" "$ENV_FILE")
    fi

    cd "$SCRIPT_DIR"

    ALEMBIC_PYTHON="$(resolve_alembic_python)" || \
        fail "Python yorumlayıcısı bulunamadı. python3 kurup yeniden deneyin (örn. sudo apt-get install -y python3)."
    ALEMBIC_CMD=("$ALEMBIC_PYTHON" -m alembic upgrade head)

    if [[ -z "$DB_URL" && -f "$ENV_FILE" ]]; then
        DB_URL=$("$ALEMBIC_PYTHON" - "$ENV_FILE" <<'PY'
from pathlib import Path
from urllib.parse import quote
import sys

env_path = Path(sys.argv[1])
values = {}
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    values[key.strip()] = value

password = values.get("POSTGRES_PASSWORD", "")
if password:
    user = values.get("POSTGRES_USER") or "sidar"
    host = values.get("POSTGRES_HOST") or "127.0.0.1"
    port = values.get("POSTGRES_PORT") or "5432"
    database = values.get("POSTGRES_DB") or "sidar"
    print(
        "postgresql+asyncpg://"
        f"{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}"
    )
PY
)
        if [[ -n "$DB_URL" ]]; then
            info "DATABASE_URL .env içinde kasıtlı olarak tek kaynak yaklaşımıyla tutulmuyor; migrasyon DSN'i POSTGRES_* parçalarından üretildi."
        fi
    fi

    if [[ -z "$DB_URL" ]]; then
        warn "DATABASE_URL bulunamadı — otomatik migrasyon atlandı."
        info "Veritabanını başlattıktan sonra manuel çalıştırın: ${ALEMBIC_PYTHON} -m alembic upgrade head"
        MIGRATION_STATUS="db_url_yok"
        return
    fi

    # Güvenlik: DB_URL içindeki parolayı loglarda maskele
    local masked_db_url="$DB_URL"
    if [[ "$DB_URL" =~ ^(postgresql(\+asyncpg)?://[^:/?#]+:)([^@]+)(@.+)$ ]]; then
        masked_db_url="${BASH_REMATCH[1]}***${BASH_REMATCH[4]}"
    fi
    info "DATABASE_URL: $masked_db_url"

    if [[ "$DOCKER_ONLY" == true ]]; then
        DOCKER_COMPOSE_CMD=()
        if command -v docker &>/dev/null && docker compose version &>/dev/null; then
            DOCKER_COMPOSE_CMD=(docker compose)
        elif command -v docker-compose &>/dev/null; then
            DOCKER_COMPOSE_CMD=(docker-compose)
        fi
        if [[ ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
            info "--docker-only: PostgreSQL/Redis Docker servisleri başlatılıyor..."
            start_docker_services_or_fail "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis
            DOCKER_DB_SERVICES_STARTED=true
            wait_for_compose_services_health "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis || warn "Compose healthcheck bekleme başarısız; klasik bağlantı kontrolleriyle devam edilecek."
            wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; sonraki adımlarda bağlantı hatası oluşabilir."
        else
            fail "--docker-only aktif ancak docker compose bulunamadı. Migrasyon öncesi servisler başlatılamıyor."
        fi
    fi

    if [[ "$DB_URL" == postgresql* ]]; then
        if ! command -v pg_isready &>/dev/null; then
            warn "pg_isready bulunamadı — veritabanı erişilebilirliği doğrulanamadı, migrasyon atlandı."
            info "Veritabanını başlattıktan sonra manuel çalıştırın: ${ALEMBIC_PYTHON} -m alembic upgrade head"
            MIGRATION_STATUS="pg_isready_yok"
            return
        fi

        DB_CONN_INFO=$("$ALEMBIC_PYTHON" - "$DB_URL" <<'PY'
from urllib.parse import urlparse, unquote
import sys

url = sys.argv[1]
url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
parsed = urlparse(url)

host = parsed.hostname or "127.0.0.1"
port = str(parsed.port or 5432)
user = unquote(parsed.username or "postgres")
password = unquote(parsed.password or "")
db = parsed.path.lstrip("/") or "postgres"

print(f"{host}|{port}|{user}|{db}|{password}")
PY
)

        DB_HOST=$(echo "$DB_CONN_INFO" | cut -d'|' -f1)
        DB_PORT=$(echo "$DB_CONN_INFO" | cut -d'|' -f2)
        DB_USER=$(echo "$DB_CONN_INFO" | cut -d'|' -f3)
        DB_NAME=$(echo "$DB_CONN_INFO" | cut -d'|' -f4)
        DB_PASSWORD=$(echo "$DB_CONN_INFO" | cut -d'|' -f5-)
        if [[ -n "${POSTGRES_PASSWORD:-}" ]]; then
            DB_PASSWORD="$POSTGRES_PASSWORD"
        fi
        ensure_postgres_databases_exist "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_PASSWORD" "$DB_NAME"

        if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
            DOCKER_COMPOSE_CMD=()
            if command -v docker &>/dev/null && docker compose version &>/dev/null; then
                DOCKER_COMPOSE_CMD=(docker compose)
            elif command -v docker-compose &>/dev/null; then
                DOCKER_COMPOSE_CMD=(docker-compose)
            fi

            if [[ ("$DB_HOST" == "localhost" || "$DB_HOST" == "127.0.0.1") && ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
                if [[ "$MIGRATION_DOCKER_POLICY" == "disabled" ]]; then
                    info "Kullanıcı tercihi nedeniyle migrasyon sırasında Docker servisleri otomatik başlatılmayacak."
                else
                    info "PostgreSQL erişilemedi ($DB_HOST:$DB_PORT/$DB_NAME). Docker servisleri otomatik başlatılıyor..."
                    start_docker_services_or_fail "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis
                    DOCKER_DB_SERVICES_STARTED=true
                    wait_for_compose_services_health "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis || warn "Compose healthcheck bekleme başarısız; klasik bağlantı kontrolleriyle devam edilecek."
                    wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; migrasyon sırasında cache/bağlantı hataları görülebilir."
                    wait_for_postgres_ready_after_docker_start "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || true
                fi
            fi

            if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
                warn "PostgreSQL erişilemedi ($DB_HOST:$DB_PORT/$DB_NAME) — migrasyon atlandı."
                if [[ ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
                    info "PostgreSQL log özeti (son 80 satır) alınıyor..."
                    "${DOCKER_COMPOSE_CMD[@]}" logs --tail 80 postgres || warn "PostgreSQL logları okunamadı."
                fi
                info "DB hazır olduktan sonra manuel çalıştırın: ${ALEMBIC_PYTHON} -m alembic upgrade head"
                MIGRATION_STATUS="db_erisilemez"
                if [[ "$MIGRATION_DOCKER_POLICY" == "disabled" ]]; then
                    warn "MIGRATION_DOCKER_POLICY=disabled olduğu için kurulum migrasyon olmadan devam ediyor."
                    return
                fi
                fail "Veritabanına erişilemediği için migrasyon tamamlanamadı. Kurulum güvenli şekilde durduruldu."
            fi
        fi

        local auth_check_rc=0
        verify_postgres_auth "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || auth_check_rc=$?
        if [[ "$auth_check_rc" -eq 2 ]]; then
            warn "PostgreSQL kimlik doğrulaması doğrulanamadı (psql/asyncpg denetimi kullanılamadı). Alembic denenecek."
        elif [[ "$auth_check_rc" -eq 10 ]]; then
            warn "PostgreSQL erişilebilir ancak parola doğrulaması başarısız. Eski volume kaynaklı şifre uyuşmazlığı giderilmeye çalışılıyor."
            local -a recovery_password_candidates=()
            if [[ -n "${PRE_HARDEN_DB_PASSWORD:-}" ]]; then
                recovery_password_candidates+=("$PRE_HARDEN_DB_PASSWORD")
            fi
            recovery_password_candidates+=("sidar" "postgres" "password" "admin" "changeme" "123456")
            if try_recover_postgres_password_with_alter_user \
                "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" "${recovery_password_candidates[@]}"; then
                auth_check_rc=0
                verify_postgres_auth "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || auth_check_rc=$?
                if [[ "$auth_check_rc" -eq 0 ]]; then
                    ok "ALTER USER kurtarma adımı sonrası PostgreSQL parola doğrulaması başarılı."
                fi
            fi

            if [[ "$auth_check_rc" -eq 10 ]]; then
                DOCKER_COMPOSE_CMD=()
                if command -v docker &>/dev/null && docker compose version &>/dev/null; then
                    DOCKER_COMPOSE_CMD=(docker compose)
                elif command -v docker-compose &>/dev/null; then
                    DOCKER_COMPOSE_CMD=(docker-compose)
                fi

                if [[ ("$DB_HOST" == "localhost" || "$DB_HOST" == "127.0.0.1") && ${#DOCKER_COMPOSE_CMD[@]} -gt 0 ]]; then
                    DB_PASSWORD_HARDENED=true
                    POSTGRES_VOLUME_RESET_DONE=false
                    if ! maybe_reset_postgres_volume_after_password_hardening "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis; then
                        MIGRATION_STATUS="db_auth_hatasi"
                        fail "PostgreSQL volume sıfırlanamadı; eski parola ile çalışan volume nedeniyle migrasyon güvenli şekilde durduruldu."
                    fi
                    start_docker_services_or_fail "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis
                    DOCKER_DB_SERVICES_STARTED=true
                    wait_for_compose_services_health "${DOCKER_COMPOSE_CMD[@]}" -- postgres redis || warn "Compose healthcheck bekleme başarısız; klasik bağlantı kontrolleriyle devam edilecek."
                    wait_for_redis_ready_after_docker_start || warn "Redis hazır kontrolü başarısız; migrasyon sırasında cache/bağlantı hataları görülebilir."

                    wait_for_postgres_ready_after_docker_start "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || true

                    auth_check_rc=0
                    verify_postgres_auth "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_NAME" "$DB_PASSWORD" || auth_check_rc=$?
                    if [[ "$auth_check_rc" -eq 0 ]]; then
                        ok "PostgreSQL parola doğrulaması SELECT 1 ile başarılı."
                    fi
                fi
            fi
        fi

        if [[ "$auth_check_rc" -ne 0 && "$auth_check_rc" -ne 2 ]]; then
            warn "PostgreSQL kimlik doğrulama kontrolü başarısız: ${POSTGRES_AUTH_CHECK_ERROR:-bilinmeyen_hata}"
            MIGRATION_STATUS="db_auth_hatasi"
            fail "PostgreSQL kimlik doğrulaması başarısız olduğu için migrasyon güvenli şekilde durduruldu."
        fi
    fi

    # Shell belleğinde kalmış eski değişkenlerin .env değerlerini ezmesini engelle.
    unset DATABASE_URL
    unset POSTGRES_PASSWORD
    if [[ -f "$ENV_FILE" ]]; then
        local refreshed_db_url=""
        local refreshed_postgres_password=""
        refreshed_db_url=$(read_env_value_from_file "DATABASE_URL" "$ENV_FILE")
        refreshed_postgres_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$ENV_FILE")

        if [[ -n "$refreshed_db_url" ]]; then
            DB_URL="$refreshed_db_url"
            export DATABASE_URL="$refreshed_db_url"
        fi
        if [[ -n "$refreshed_postgres_password" ]]; then
            export POSTGRES_PASSWORD="$refreshed_postgres_password"
        fi
    fi

    ALEMBIC_CMD=(env "DATABASE_URL=$DB_URL" "$ALEMBIC_PYTHON" -m alembic upgrade head)

    local alembic_output_file=""
    alembic_output_file=$(mktemp)
    if "${ALEMBIC_CMD[@]}" \
        > >(tee -a "$alembic_output_file") \
        2> >(tee -a "$alembic_output_file" >&2); then
        rm -f "$alembic_output_file"
        ok "Alembic migrasyonları DATABASE_URL ile tamamlandı."
        MIGRATION_STATUS="tamamlandi"
    else
        warn "Alembic migrasyonu başarısız oldu. Hata özeti (son 120 satır):"
        tail -n 120 "$alembic_output_file" || true
        rm -f "$alembic_output_file"
        MIGRATION_STATUS="hata"
        fail "Migrasyon başarısız. Log'ları kontrol edin ve hatayı düzeltmeden kuruluma devam etmeyin."
    fi
}

is_alembic_at_head() {
    local env_file="$SCRIPT_DIR/.env"
    local alembic_ini="$SCRIPT_DIR/alembic.ini"
    local py_bin=""
    local db_url=""
    local current_output=""
    local heads_output=""
    local current_rev=""
    local head_rev=""

    [[ -f "$alembic_ini" ]] || return 1
    py_bin="$(resolve_alembic_python)" || return 1

    if [[ -n "${DATABASE_URL:-}" ]]; then
        db_url="$DATABASE_URL"
    elif [[ -f "$env_file" ]]; then
        db_url="$(read_env_value_from_file "DATABASE_URL" "$env_file")"
    else
        debug "Alembic head kontrolü için DATABASE_URL bulunamadı: ortam değişkeni ve ${env_file} yok."
        return 1
    fi

    db_url="$(printf '%s' "$db_url" | tr -d '\n[:space:]')"
    if [[ -z "${db_url//[[:space:]]/}" ]]; then
        debug "Alembic head kontrolü için DATABASE_URL boş; current/head sorgusu atlandı."
        return 1
    fi

    current_output="$(env "DATABASE_URL=$db_url" "$py_bin" -m alembic current 2>&1)" || return 1
    heads_output="$(env "DATABASE_URL=$db_url" "$py_bin" -m alembic heads 2>&1)" || return 1
    current_rev="$(printf '%s\n' "$current_output" | awk '/^[[:space:]]*[0-9][[:alnum:]_]*/ {print $1}' | tail -n1)"
    head_rev="$(printf '%s\n' "$heads_output" | awk '/^[[:space:]]*[0-9][[:alnum:]_]*/ {print $1}' | tail -n1)"
    if [[ -z "$current_rev" || -z "$head_rev" ]]; then
        debug "Alembic current/head çıktısı ayrıştırılamadı. current=$(printf '%s' "$current_output" | tail -n 3 | tr '\n' ' ') heads=$(printf '%s' "$heads_output" | tail -n 3 | tr '\n' ' ')"
    fi
    [[ -n "$current_rev" && -n "$head_rev" && "$current_rev" == "$head_rev" ]]
}

ensure_postgres_databases_exist() (
    local db_host="$1"
    local db_port="$2"
    local db_user="$3"
    local db_password="$4"
    local primary_db="$5"
    local -a required_dbs=("$primary_db" "sidar" "sidar_development" "sidar_test")
    local db_name=""
    local unique_dbs=""
    local psql_bin=""
    local psql_err_file=""
    local select_output=""

    # PATH kurulum sırasında değişebilir; eski Bash command hash kayıtlarının
    # sistemdeki veya PATH üzerinden sağlanan güncel psql ikilisini gölgelemesini önle.
    hash -r
    psql_bin="$(command -v psql || true)"
    if [[ -z "$psql_bin" ]]; then
        warn "psql bulunamadı; veritabanı varlık kontrolü atlandı."
        return 0
    fi

    psql_err_file="$(mktemp)"
    trap 'rm -f "$psql_err_file"' EXIT

    unique_dbs=$(printf "%s\n" "${required_dbs[@]}" | awk 'NF && !seen[$0]++')
    while IFS= read -r db_name; do
        [[ -n "$db_name" ]] || continue
        : >"$psql_err_file"
        if ! select_output=$(PGPASSWORD="$db_password" "$psql_bin" -w \
            -h "$db_host" -p "$db_port" -U "$db_user" -d postgres \
            -tAc "SELECT 1 FROM pg_database WHERE datname = '${db_name}'" 2>"$psql_err_file"); then
            if grep -Eqi 'authentication|password' "$psql_err_file"; then
                fail "PostgreSQL auth başarısız: .env POSTGRES_PASSWORD ile container parolası uyumsuz. Çözüm: docker compose down -v && yeniden kurulum."
            fi
            warn "PostgreSQL veritabanı varlık sorgusu başarısız: ${db_name}"
            return 1
        fi
        if grep -qx '1' <<<"$select_output"; then
            continue
        fi

        info "Eksik PostgreSQL veritabanı oluşturuluyor: ${db_name}"
        if ! PGPASSWORD="$db_password" "$psql_bin" -w \
            -h "$db_host" -p "$db_port" -U "$db_user" -d postgres \
            -v ON_ERROR_STOP=1 \
            -c "CREATE DATABASE \"${db_name}\" OWNER \"${db_user}\";" >/dev/null 2>>"$psql_err_file"; then
            if grep -Eqi 'authentication|password' "$psql_err_file"; then
                fail "PostgreSQL auth başarısız: .env POSTGRES_PASSWORD ile container parolası uyumsuz. Çözüm: docker compose down -v && yeniden kurulum."
            fi
            return 1
        fi
        ok "Veritabanı hazır: ${db_name}"
    done <<<"$unique_dbs"
)
