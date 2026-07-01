#!/usr/bin/env bash


seed_rag_in_docker_after_startup() {
    if [[ "${SIDAR_INSTALL_TEST_MODE:-}" == "1" ]]; then
        info "Test modu: RAG warmup seed atlandı."
        return 0
    fi

    local seed_mode="${AUTO_SEED_RAG_DOCKER_WARMUP:-true}"
    seed_mode="$(normalize_bool "$seed_mode")"
    [[ -z "$seed_mode" ]] && seed_mode="true"

    if [[ "$seed_mode" != "true" ]]; then
        info "AUTO_SEED_RAG_DOCKER_WARMUP=${AUTO_SEED_RAG_DOCKER_WARMUP:-false}; Docker RAG warmup seed atlandı."
        return 0
    fi

    local -a compose_cmd=()
    local compose_profiles="${COMPOSE_PROFILES:-}"
    local seed_service="sidar-web"
    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        compose_cmd=(docker-compose)
    else
        warn "Docker compose bulunamadı; RAG warmup seed atlandı. Manuel: docker compose run --rm --no-deps --entrypoint \"\" ${seed_service} uv run python -m scripts.seed_rag"
        return 0
    fi

    if [[ "$compose_profiles" == *"gpu"* ]]; then
        seed_service="sidar-web-gpu"
    fi

    info "RAG seed servisi aktif profillere göre seçildi: ${seed_service} (COMPOSE_PROFILES=${compose_profiles:-cpu})."
    info "Tam Docker modu: ilk açılış gecikmesini azaltmak için RAG/GraphRAG seed adımı çalıştırılıyor..."
    if (cd "$SCRIPT_DIR" && "${compose_cmd[@]}" run --rm --no-deps --entrypoint "" "$seed_service" uv run python -m scripts.seed_rag); then
        ok "Docker RAG/GraphRAG seed adımı tamamlandı."
    else
        warn "Docker RAG/GraphRAG seed adımı başarısız. Geçici container temizliği deneniyor..."
        (cd "$SCRIPT_DIR" && "${compose_cmd[@]}" rm -f -s "$seed_service" >/dev/null 2>&1) || true
        warn "Docker RAG/GraphRAG seed adımı başarısız. Manuel: ${compose_cmd[*]} run --rm --no-deps --entrypoint \"\" ${seed_service} uv run python -m scripts.seed_rag"
    fi
}

sidar_phase_local_migrations_and_models() {
    sidar_source_install_utils "ollama_models.sh"
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" == "local" ]]; then
        # DB migrasyonu öncesi servis hazırlığı: kullanıcı onayı bu aşamada alınır.
        prepare_docker_for_migrations
        local pg_pw="${POSTGRES_PASSWORD:-}"
        if [[ -z "${pg_pw//[[:space:]]/}" ]]; then
            pg_pw=$(read_env_value_from_file "POSTGRES_PASSWORD" "$SCRIPT_DIR/.env" | tr -d "\n")
        fi
        ensure_postgres_databases_exist "127.0.0.1" "${POSTGRES_PORT:-5432}" "${POSTGRES_USER:-sidar}" "$pg_pw" "${POSTGRES_DB:-sidar}"
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
        seed_rag_in_docker_after_startup
    fi
}


sidar_phase06_run_database_password_sync_all_envs() {
    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
        return 1
    fi

    if [[ ! -f "$SCRIPT_DIR/scripts/sync_database_passwords.py" ]]; then
        warn "scripts/sync_database_passwords.py bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
        return 1
    fi

    (cd "$SCRIPT_DIR" && uv run python scripts/sync_database_passwords.py --all-envs >/dev/null 2>&1)
}

sidar_phase06_cleanup_pre_service_smoke_log() {
    if [[ -n "${SIDAR_PHASE06_PRE_SERVICE_SMOKE_LOG:-}" ]]; then
        rm -f -- "$SIDAR_PHASE06_PRE_SERVICE_SMOKE_LOG"
        SIDAR_PHASE06_PRE_SERVICE_SMOKE_LOG=""
    fi
}

sidar_phase06_preserve_pre_service_smoke_log() {
    local log_path="$1"
    local dir=""
    local target=""

    [[ -f "$log_path" ]] || return 1
    if declare -F sidar_remediation_log_dir >/dev/null 2>&1; then
        dir="$(sidar_remediation_log_dir)"
    else
        dir="${SCRIPT_DIR}/artifacts/install/remediation"
        mkdir -p "$dir"
    fi

    target="${dir}/$(date +%Y%m%d_%H%M%S)_pre_service_smoke_gate.log"
    if cp "$log_path" "$target"; then
        printf '%s\n' "$target"
        return 0
    fi
    return 1
}

ensure_env_test_postgres_password_matches_base_before_smoke() {
    local base_env_file="$SCRIPT_DIR/.env"
    local test_env_file="$SCRIPT_DIR/.env.test"
    local test_example_file="$SCRIPT_DIR/.env.test.example"
    local base_password=""
    local test_password=""

    if [[ ! -f "$base_env_file" ]]; then
        warn ".env bulunamadı; .env.test PostgreSQL parola guard'ı atlandı."
        return 0
    fi

    base_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$base_env_file" | tr -d '\n')
    if [[ -z "${base_password//[[:space:]]/}" ]]; then
        warn ".env içinde POSTGRES_PASSWORD bulunamadı; .env.test PostgreSQL parola guard'ı atlandı."
        return 0
    fi

    if [[ ! -f "$test_env_file" && -f "$test_example_file" ]]; then
        cp "$test_example_file" "$test_env_file"
        ok ".env.test dosyası smoke guard için .env.test.example üzerinden oluşturuldu."
    fi

    if [[ ! -f "$test_env_file" ]]; then
        warn ".env.test bulunamadı; smoke guard otomatik düzeltme için --all-envs senkronizasyonunu tekrar deneyecek."
        sidar_phase06_run_database_password_sync_all_envs || true
    fi

    test_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$test_env_file" | tr -d '\n')
    if [[ "$test_password" == "$base_password" ]]; then
        ok ".env.test POSTGRES_PASSWORD değeri .env ile uyumlu."
        return 0
    fi

    warn ".env.test POSTGRES_PASSWORD değeri .env ile uyuşmuyor; smoke test öncesi otomatik düzeltiliyor."
    sidar_phase06_run_database_password_sync_all_envs || warn "--all-envs senkronizasyonu guard sırasında tamamlanamadı; dar kapsamlı .env.test düzeltmesi uygulanacak."

    test_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$test_env_file" | tr -d '\n')
    if [[ "$test_password" != "$base_password" ]]; then
        if [[ ! -f "$test_env_file" ]]; then
            : > "$test_env_file"
        fi
        sed_inplace '/^POSTGRES_PASSWORD=/d' "$test_env_file"
        echo "POSTGRES_PASSWORD=${base_password}" >> "$test_env_file"
        warn ".env.test POSTGRES_PASSWORD dar kapsamlı fallback ile .env değerine eşitlendi."
    fi

    test_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$test_env_file" | tr -d '\n')
    if [[ "$test_password" != "$base_password" ]]; then
        fail ".env.test POSTGRES_PASSWORD değeri .env ile eşitlenemedi; smoke testler güvenli şekilde durduruldu."
    fi

    ok ".env.test POSTGRES_PASSWORD değeri smoke test öncesi .env ile eşitlendi."
}

sidar_phase06_discover_postgres_volumes() {
    local -a compose_cmd=("$@")
    local env_file="$SCRIPT_DIR/.env"
    local compose_project_name="${COMPOSE_PROJECT_NAME:-}"
    local compose_arg=""
    local consume_next_as_project_name=false
    local -a candidate_volume_suffixes=()
    local volume_name=""

    for compose_arg in "${compose_cmd[@]}"; do
        if [[ "$consume_next_as_project_name" == true ]]; then
            compose_project_name="$compose_arg"
            consume_next_as_project_name=false
            continue
        fi
        case "$compose_arg" in
            -p|--project-name)
                consume_next_as_project_name=true
                ;;
            -p=*|--project-name=*)
                compose_project_name="${compose_arg#*=}"
                ;;
        esac
    done

    if [[ -z "$compose_project_name" && -f "$env_file" ]]; then
        compose_project_name=$(read_env_value_from_file "COMPOSE_PROJECT_NAME" "$env_file")
    fi
    compose_project_name=$(echo "${compose_project_name:-}" | tr -d "\"'[:space:]")

    if mapfile -t compose_volumes < <("${compose_cmd[@]}" config --volumes 2>/dev/null); then
        for volume_name in "${compose_volumes[@]}"; do
            if [[ "$volume_name" =~ (^|_)postgres_data$ ]]; then
                candidate_volume_suffixes+=("$volume_name")
            fi
        done
    fi
    if [[ ${#candidate_volume_suffixes[@]} -eq 0 ]]; then
        candidate_volume_suffixes+=("postgres_data")
    fi

    if declare -F sidar_discover_postgres_volumes >/dev/null 2>&1; then
        sidar_discover_postgres_volumes "$compose_project_name" "${candidate_volume_suffixes[@]}"
    else
        docker volume ls --format '{{.Name}}' 2>/dev/null | grep -Ei '(^|[_-])sidar([_-].*)?[_-](postgres|pg)[_-]?data$|(^|[_-])postgres_data$' || true
    fi
}

ensure_postgres_volume_reset_before_smoke_tests() {
    local -a docker_compose_cmd=()
    local -a volumes_before=()
    local -a volumes_after_down=()
    local -a volumes_after_rm=()
    local volume_name=""

    if [[ "${DB_PASSWORD_HARDENED:-false}" != true ]]; then
        info "DB parola hardening işaretlenmedi; smoke öncesi PostgreSQL volume reset gerekmiyor."
        return 0
    fi

    if [[ "${POSTGRES_VOLUME_RESET_DONE:-false}" == true ]]; then
        ok "PostgreSQL volume reset daha önce tamamlanmış olarak işaretli; smoke öncesi ek reset gerekmiyor."
        return 0
    fi

    if ! command -v docker &>/dev/null; then
        fail "DB parola hardening sonrası PostgreSQL volume reset doğrulaması için docker CLI gerekli."
    fi
    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        docker_compose_cmd=(docker compose)
    elif command -v docker-compose &>/dev/null; then
        docker_compose_cmd=(docker-compose)
    else
        fail "DB parola hardening sonrası PostgreSQL volume reset doğrulaması için docker compose gerekli."
    fi

    mapfile -t volumes_before < <(sidar_phase06_discover_postgres_volumes "${docker_compose_cmd[@]}")
    if [[ ${#volumes_before[@]} -gt 0 ]]; then
        warn "Smoke öncesi PostgreSQL volume reset doğrulaması: mevcut volume(ler): ${volumes_before[*]}"
    else
        info "Smoke öncesi PostgreSQL volume reset doğrulaması: mevcut PostgreSQL volume bulunamadı."
    fi

    warn "DB parola hardening sonrası volume reset tamamlanmamış; pg_isready/smoke öncesi docker compose down --volumes --remove-orphans çalıştırılıyor."
    if ! "${docker_compose_cmd[@]}" down --volumes --remove-orphans >/dev/null 2>&1; then
        fail "PostgreSQL volume reset için docker compose down --volumes --remove-orphans başarısız oldu."
    fi

    mapfile -t volumes_after_down < <(sidar_phase06_discover_postgres_volumes "${docker_compose_cmd[@]}")
    if [[ ${#volumes_after_down[@]} -gt 0 ]]; then
        warn "docker compose down -v sonrası kalan PostgreSQL volume(ler): ${volumes_after_down[*]} — zorla silinecek."
        for volume_name in "${volumes_after_down[@]}"; do
            if docker volume rm "$volume_name" -f >/dev/null 2>&1; then
                ok "PostgreSQL volume smoke öncesi zorla temizlendi: ${volume_name}"
            else
                warn "PostgreSQL volume smoke öncesi silinemedi: ${volume_name}"
            fi
        done
    else
        ok "docker compose down -v sonrası PostgreSQL volume kalmadı; reset doğrulandı."
    fi

    mapfile -t volumes_after_rm < <(sidar_phase06_discover_postgres_volumes "${docker_compose_cmd[@]}")
    if [[ ${#volumes_after_rm[@]} -gt 0 ]]; then
        fail "PostgreSQL volume reset doğrulanamadı; kalan volume(ler): ${volumes_after_rm[*]}"
    fi

    POSTGRES_VOLUME_RESET_DONE=true
    ok "PostgreSQL volume reset smoke test öncesi doğrulandı; yeni init için servisler tekrar başlatılıyor."
    start_docker_services_or_fail "${docker_compose_cmd[@]}" -- postgres redis
    wait_for_compose_services_health "${docker_compose_cmd[@]}" -- postgres redis || warn "PostgreSQL/Redis healthcheck reset sonrası beklenen sürede doğrulanamadı; smoke test kendi hazır kontrolleriyle devam edecek."
}

sync_database_passwords_before_smoke_tests() {
    if ! command -v uv &>/dev/null; then
        warn "uv bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
    elif [[ ! -f "$SCRIPT_DIR/scripts/sync_database_passwords.py" ]]; then
        warn "scripts/sync_database_passwords.py bulunamadı; smoke test öncesi PostgreSQL dotenv senkronizasyonu atlandı."
    else
        info "Smoke test öncesi PostgreSQL dotenv profilleri eşitleniyor (.env.test dahil)..."
        if sidar_phase06_run_database_password_sync_all_envs; then
            ok "Smoke test öncesi PostgreSQL dotenv profilleri eşitlendi."
        else
            warn "Smoke test öncesi PostgreSQL dotenv senkronizasyonu tamamlanamadı; guard dar kapsamlı düzeltmeyi deneyecek."
        fi
    fi

    ensure_env_test_postgres_password_matches_base_before_smoke
    ensure_postgres_volume_reset_before_smoke_tests

    if [[ ! -f "$SCRIPT_DIR/scripts/sync_postgres_password.py" ]]; then
        warn "scripts/sync_postgres_password.py bulunamadı; canlı PostgreSQL parola senkronizasyonu atlandı."
        return 0
    fi

    info "Smoke test öncesi canlı PostgreSQL kullanıcı parolası doğrulanıyor..."
    if (cd "$SCRIPT_DIR" && uv run python scripts/sync_postgres_password.py >/dev/null 2>&1); then
        ok "Canlı PostgreSQL kullanıcı parolası smoke test öncesi eşitlendi."
    else
        warn "Canlı PostgreSQL parola senkronizasyonu tamamlanamadı; smoke testler mevcut veritabanı durumu ile devam edecek."
        sidar_phase06_report_production_postgres_password_alignment || true
    fi
}

sidar_phase06_report_production_postgres_password_alignment() {
    local sidar_env=""
    sidar_env=$(read_env_value_from_file "SIDAR_ENV" "$SCRIPT_DIR/.env" | tr -d '\n' | tr '[:upper:]' '[:lower:]')
    sidar_env="${sidar_env:-development}"

    case "$sidar_env" in
        production|prod)
            ;;
        *)
            return 0
            ;;
    esac

    local pg_user pg_password pg_db pg_container
    pg_user=$(read_env_value_from_file "POSTGRES_USER" "$SCRIPT_DIR/.env" | tr -d '\n')
    pg_password=$(read_env_value_from_file "POSTGRES_PASSWORD" "$SCRIPT_DIR/.env" | tr -d '\n')
    pg_db=$(read_env_value_from_file "POSTGRES_DB" "$SCRIPT_DIR/.env" | tr -d '\n')
    pg_container=$(read_env_value_from_file "SIDAR_POSTGRES_CONTAINER" "$SCRIPT_DIR/.env" | tr -d '\n')

    pg_user="${pg_user:-sidar}"
    pg_db="${pg_db:-postgres}"
    pg_container="${pg_container:-sidar_postgres}"

    if [[ -z "${pg_password//[[:space:]]/}" ]]; then
        warn "Production profili: POSTGRES_PASSWORD boş görünüyor; mevcut volume parola uyumu doğrulanamadı."
        return 0
    fi

    if ! command -v docker &>/dev/null; then
        warn "Production profili: docker CLI bulunamadı; mevcut volume parola uyumu doğrulanamadı."
        return 0
    fi

    if env PGPASSWORD="$pg_password" docker exec "$pg_container" psql -U "$pg_user" -d "$pg_db" -c 'SELECT 1;' >/dev/null 2>&1; then
        ok "Production profili seçildi: mevcut PostgreSQL volume parolası .env ile uyumlu görünüyor."
    else
        warn "Production profili seçildi: mevcut PostgreSQL volume parolası .env ile doğrulanamadı. Gerekirse .env parolasını volume ile eşleştirin veya temiz kurulum için volume reset uygulayın."
    fi
}

run_pre_service_installer_smoke_gate() {
    local gate_enabled="${SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE:-1}"
    gate_enabled="$(normalize_bool "$gate_enabled")"
    [[ -z "$gate_enabled" ]] && gate_enabled="true"

    if [[ "$gate_enabled" != "true" ]]; then
        info "SIDAR_PRE_SERVICE_INSTALLER_SMOKE_GATE=0; servis öncesi installer smoke gate atlandı."
        return 0
    fi
    if [[ "${RUN_SMOKE_TESTS_MODE:-prompt}" == "never" ]]; then
        info "--skip-smoke-test/RUN_SMOKE_TESTS_MODE=never verildiği için servis öncesi installer smoke gate atlandı."
        return 0
    fi
    if [[ ! -f "$SCRIPT_DIR/tests/smoke/test_install_verification.py" ]]; then
        warn "Servis öncesi installer smoke gate atlandı: tests/smoke/test_install_verification.py bulunamadı."
        return 0
    fi
    if ! command -v uv >/dev/null 2>&1; then
        warn "Servis öncesi installer smoke gate atlandı: uv bulunamadı."
        return 0
    fi

    local expected_installer_version=""
    if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
        expected_installer_version="$(sed -nE 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' "$SCRIPT_DIR/pyproject.toml" | head -n1 || true)"
    fi
    if [[ -n "${expected_installer_version//[[:space:]]/}" ]]; then
        info "Installer sürüm sözleşmesi pyproject.toml üzerinden okunuyor: v${expected_installer_version}. Source/export doğrulaması CI smoke testi kapsamındadır."
    else
        warn "pyproject.toml içinde [project].version okunamadı; INSTALL_SIDAR_VERSION sözleşmesi CI smoke testi kapsamında doğrulanacak."
    fi

    local smoke_log
    smoke_log="$(mktemp "${TMPDIR:-/tmp}/sidar_pre_service_smoke.XXXXXX")" || fail "Servis öncesi installer smoke gate log dosyası oluşturulamadı."
    SIDAR_PHASE06_PRE_SERVICE_SMOKE_LOG="$smoke_log"
    sidar_phase06_fail_with_smoke_cleanup() {
        sidar_phase06_cleanup_pre_service_smoke_log
        fail "$@"
    }

    info "Servis öncesi installer smoke gate Python bağımlılıkları doğrulanıyor (pytest + pydantic)."
    if ! (
        cd "$SCRIPT_DIR" && \
            uv run python - <<'PY'
import importlib.util
import sys

missing = [
    module
    for module in ("pytest", "pydantic", "pydantic_settings")
    if importlib.util.find_spec(module) is None
]
if missing:
    print(", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
PY
    ); then
        warn "Servis öncesi installer smoke gate için pytest/pydantic bağımlılıkları eksik; dev-light profili uv ile senkronize ediliyor."
        if ! (cd "$SCRIPT_DIR" && uv sync --frozen --extra dev-light); then
            sidar_phase06_fail_with_smoke_cleanup "Servis öncesi installer smoke gate başlatılamadı; pytest/pydantic bağımlılıkları hazırlanamadı. Manuel doğrulama: uv sync --frozen --extra dev-light"
        fi
        ok "Servis öncesi installer smoke gate bağımlılıkları dev-light profiliyle hazırlandı."
    fi

    unset SIDAR_DATABASE_ENV_CHAIN_SYNCED || true
    info "Servis öncesi installer smoke gate başlamadan PostgreSQL dotenv profilleri eşitleniyor..."
    if sidar_phase06_run_database_password_sync_all_envs; then
        ok "Servis öncesi installer smoke gate dotenv profilleri eşitlendi."
    else
        sidar_phase06_fail_with_smoke_cleanup "Servis öncesi installer smoke gate başlatılamadı; PostgreSQL dotenv profilleri eşitlenemedi."
    fi

    info "Servis başlatmadan önce installer smoke gate çalıştırılıyor (-x, no-cov)."
    if (
        set -o pipefail
        (
            cd "$SCRIPT_DIR" && \
                SIDAR_INSTALL_TEST_MODE=1 \
                SIDAR_INSTALL_SMOKE_BASH_TIMEOUT="${SIDAR_INSTALL_SMOKE_BASH_TIMEOUT:-180}" \
                uv run pytest -q --no-cov -p no:xdist -x tests/smoke/test_install_verification.py \
                </dev/null
        ) 2>&1 | tee "$smoke_log"
    ); then
        ok "Servis öncesi installer smoke gate başarılı."
        sidar_phase06_cleanup_pre_service_smoke_log
    else
        local persisted_smoke_log=""
        persisted_smoke_log="$(sidar_phase06_preserve_pre_service_smoke_log "$smoke_log" || true)"
        warn "Smoke gate çıktısı: $smoke_log"
        if [[ -n "${persisted_smoke_log//[[:space:]]/}" ]]; then
            warn "Smoke gate kalıcı log kopyası: $persisted_smoke_log"
        else
            warn "Smoke gate kalıcı log kopyası artifacts/install/remediation altına yazılamadı."
        fi
        warn "Smoke gate hata önizleme (ilk 200 satır):"
        if command -v head >/dev/null 2>&1; then
            head -n 200 "$smoke_log" | sed 's/^/  | /' || true
        else
            sed -n '1,200p' "$smoke_log" | sed 's/^/  | /' || true
        fi
        warn "Smoke gate INSTALL_SIDAR_VERSION sözleşmesi başarısız olmuş olabilir; pyproject.toml içindeki [project].version satırını ve 'source install_sidar.sh' çıktısındaki INSTALL_SIDAR_VERSION değerini kontrol edin."
        warn "Probe-only sürüm kontrolü güncel install_sidar.sh içinde Bash fast-path ile saniyeler içinde bitmelidir; timeout alıyorsanız eski/farklı checkout, branch uyumsuzluğu veya WSL dosya sistemi yavaşlığını kontrol edin."
        warn "Ayrıntılı teşhis için docs/INSTALL_SMOKE_GATE_TROUBLESHOOTING.md içindeki hızlı 'SIDAR_INSTALL_VERSION_PROBE_ONLY=1' doğrulamasını çalıştırın."
        warn "Smoke gate probe timeout belirtisi varsa SIDAR_INSTALL_SMOKE_BASH_TIMEOUT=240 gibi daha yüksek bir değerle yeniden deneyin; kurulumun servis öncesi smoke gate'ini bilinçli atlamak için --skip-smoke-test veya RUN_SMOKE_TESTS_MODE=never kullanın."
        sidar_phase06_fail_with_smoke_cleanup "Servis öncesi installer smoke gate başarısız; Docker servisleri başlatılmadan kurulum durduruldu (detay: ${persisted_smoke_log:-$smoke_log})."
    fi
    sidar_phase06_cleanup_pre_service_smoke_log
}

sidar_phase_services_and_validation() {
    if declare -F phase06_docker_daemon_gate_or_fail >/dev/null 2>&1; then
        phase06_docker_daemon_gate_or_fail
    fi
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" == "local" ]]; then
        run_pre_service_installer_smoke_gate || return $?
    fi
    # Tüm altyapı (jaeger/prometheus/grafana dahil) smoke testlerden önce hazır olsun.
    launch_docker_services
    if [[ "${APP_RUNTIME_MODE_SELECTED:-local}" == "local" ]]; then
        sync_database_passwords_before_smoke_tests
        run_smoke_tests
        run_install_integration_api_tests
        run_test_artifact_audit
    else
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        SMOKE_TEST_STATUS="tam_docker_modu_nedeniyle_atlandi"
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        INTEGRATION_TEST_STATUS="tam_docker_modu_nedeniyle_atlandi"
        # shellcheck disable=SC2034  # summarized by print_summary in the finish phase.
        AUDIT_STATUS="tam_docker_modu_nedeniyle_atlandi"
        info "Tam Docker modu: lokal smoke-test/integration/audit adımları atlanıyor."
    fi
}
